"""Apply-Joint — clone a joint template's stacks into project timbers.

The template FCStd is read as a *specification* (pure fcstd reader +
the linter's semantic model), then rebuilt natively in the target
document: one fresh joint VarSet (schema, values, tooltips, junction
bindings rewritten to the target timbers' Dims), and per template role
the full feature stack — landing frame, sketches with geometry and
named constraints, pockets/holes — with every label and expression
written in target terms. Rebuild-not-copy is the same decision as
new_timber: there is nothing to remap afterward (findings #2, #12),
and the tool writes every expression (finding #1) and label (#6).

v1 placement: the template's landing face and end. Face/end/hand
selection is a frame re-placement by design (landing-frame
architecture) and layers on next.
"""

from __future__ import annotations

import re

import FreeCAD as App
import Part
import Sketcher

from . import joint_handle, naming
from .fcstd import FcstdDocument
from .linter import Model, footprint_violations

DIMENSIONAL = {6, 7, 8, 9, 11, 18, 19}   # constraint types carrying a value
Constraint_DISTANCE_X = 7
Constraint_DISTANCE_Y = 8

# Reference faces (workflow doc §2): Face 1 = XZ reference face (y=0),
# Face 2 = YZ reference face (x=0), Faces 3/4 opposite them. Side-
# landing templates are authored on Face 4 (canonical FlatFace on
# YZ_Plane; validated at apply time). Each target face is a transform
# of the template frame, derived from the canonical FlatFace axes
# probed in 1.1.1 (YZ: Z->+X, XZ: Z->-Y; frame Y -> +Z on both, so
# station semantics never change):
#   plane   — origin plane the frame re-attaches to
#   swap    — swap Width<->Depth tokens in the frame offset expressions
#             (the family normal changes axis)
#   z_mode  — Base.z from the template's expression T:
#             identity: T | negate: -(T) | complement: ddim - (T)
#             (complement turns "far-face bearing" into "near-face")
#   flip_z  — canonical frame Z points INTO the wood on this face: flip
#             end-plane-profile cuts and mirror along-frame-Z sketch
#             coordinates (the same transform end B uses)
TEMPLATE_FACE = 4
FACES = {
    1: {"plane": "XZ_Plane", "swap": True, "z_mode": "negate_complement",
        "flip_z": False, "ddim": "Depth"},
    2: {"plane": "YZ_Plane", "swap": False, "z_mode": "complement",
        "flip_z": True, "ddim": "Width"},
    3: {"plane": "XZ_Plane", "swap": True, "z_mode": "negate",
        "flip_z": True, "ddim": "Depth"},
    4: {"plane": "YZ_Plane", "swap": False, "z_mode": "identity",
        "flip_z": False, "ddim": "Width"},
}

# geometry the rebuilder understands; extend alongside new templates
_SUPPORTED_GEOMETRY = ("line", "circle")


class JointError(ValueError):
    """An apply-joint request that cannot be honored."""


_LABEL_IN_EXPR = re.compile(r"<<([^<>]+)>>")


def dims_varset(body):
    """The Dims VarSet driving a timber body's base pad, or None.

    Resolved structurally (whatever the pad's Length expression binds
    to), never by label convention: a renamed body whose VarSet kept
    the old label must still resolve — the live bug was such a timber
    being silently excluded and another body substituted for it.
    """
    doc = body.Document
    for obj in body.Group:
        if obj.TypeId != "PartDesign::Pad":
            continue
        for path, expr in obj.ExpressionEngine:
            if path.lstrip(".") == "Length":
                m = _LABEL_IN_EXPR.search(expr)
                if m:
                    hits = doc.getObjectsByLabel(m.group(1))
                    if hits and hits[0].TypeId == "App::VarSet":
                        return hits[0]
        break   # the first Pad is the base feature
    return None


def joints_group(doc):
    """The document root's timber-joints Std Group (created on first
    use), where a joint's handle waits until assimilation files it in
    the bent it belongs to. Named apart from "Joints" because every
    FreeCAD Assembly carries its own Assembly::JointGroup labeled
    "Joints" — two same-name tree nodes once a bent is assembled;
    legacy groups (that one, and 'TimberJointVars' from before handles)
    are renamed in place. Pure organization — an
    App::DocumentObjectGroup has no geometric effect."""
    return joint_handle.handle_group(doc)


# --------------------------------------------------------------------------
# Template specification (pure reading, no FreeCAD document mutation)
# --------------------------------------------------------------------------

class TemplateSpec:
    """Everything needed to re-execute a template in a target document."""

    def __init__(self, path):
        self.path = str(path)
        doc = FcstdDocument.from_file(path)
        model = Model(doc)

        joints = model.joint_varsets()
        if len(joints) != 1:
            raise JointError(
                f"template must contain exactly one joint VarSet, "
                f"found {len(joints)}")
        self.joint = joints[0]
        self.joint_label = self.joint.label            # e.g. Joint_MT_0a
        parsed = naming.parse_joint_label(self.joint_label)
        if parsed is None:
            raise JointError(
                f"joint VarSet label {self.joint_label!r} is not "
                f"J-<Kind>-<ID> or legacy Joint_<Kind>_<ID>")
        self.kind, self.template_jid = parsed          # e.g. ("MT", "0a")
        import os
        self.source_name = os.path.splitext(os.path.basename(self.path))[0]
        # descriptive kind token for new joint labels (J-<token>-<serial>):
        # the library file stem carries the readable name (Joint_HousedMT
        # -> HousedMT), which beats a terse internal kind like "MT"
        self.kind_token = naming.kind_token_from_source(self.source_name)

        # Companion layout VarSet (optional; roadmap: Parametric layout).
        # Resolved through the VarSet_Role marker, never by label — the
        # Frame_Role discipline. A template without one behaves exactly
        # as before, so every existing template stays valid.
        self.layout = None
        self.layout_label = None
        for vs in doc.of_type("App::VarSet"):
            if vs is self.joint:
                continue
            role = vs.prop(naming.VARSET_ROLE_PROP)
            if role is not None and role.value == naming.VARSET_ROLE_LAYOUT:
                if self.layout is not None:
                    raise JointError(
                        f"template declares more than one companion "
                        f"layout VarSet ({self.layout.label!r}, "
                        f"{vs.label!r}) — a joint may have at most one")
                self.layout = vs
                self.layout_label = vs.label

        # Parameter schema: (name, type_id, value, tooltip, expression).
        # The two VarSets present ONE merged schema to the dialog, each
        # row tagged with the VarSet it lands on: a parameter moved to
        # the companion must still be editable where the user expects
        # it, without the dialog knowing the split exists.
        exprs = {e.path.lstrip("."): e.expression
                 for e in self.joint.expressions}
        layout_exprs = ({e.path.lstrip("."): e.expression
                         for e in self.layout.expressions}
                        if self.layout is not None else {})
        # A joint parameter bound to the companion is CONSUMED from it.
        # It still has to EXIST on the joint VarSet — the template's own
        # geometry references it — so it is tagged, never dropped; only
        # the dialog hides it, because the companion's row is the
        # editable one and a read-only echo beside it just confuses.
        consumed = set()
        if self.layout_label:
            token = f"<<{self.layout_label}>>"
            consumed = {name for name, e in exprs.items() if token in e}

        self.parameters = []
        for p in sorted(self.joint.properties.values(), key=lambda p: p.name):
            if p.group is None:
                continue
            self.parameters.append({
                "name": p.name, "type_id": p.type_id, "value": p.value,
                "tooltip": p.doc or "", "group": p.group,
                "expression": exprs.get(p.name),
                "metadata": naming.is_template_metadata(p.name, p.group),
                "varset": "joint", "consumed": p.name in consumed,
            })
        for p in sorted((self.layout.properties.values()
                         if self.layout is not None else []),
                        key=lambda p: p.name):
            if p.group is None or p.name == naming.VARSET_ROLE_PROP:
                continue
            self.parameters.append({
                "name": p.name, "type_id": p.type_id, "value": p.value,
                "tooltip": p.doc or "", "group": p.group,
                "expression": layout_exprs.get(p.name),
                "metadata": naming.is_template_metadata(p.name, p.group),
                "varset": "layout", "consumed": False,
            })

        # Template metadata (Tier 2, 'Template_' name prefix — adopted
        # July 2026): the Handed flag and the declared angle range. The
        # dialog and apply read them (hand option hidden/refused when
        # not handed; angle parameters clamped/checked against the
        # range). Legacy templates carry neither: handed defaults True
        # (hand offered, today's behavior), bounds default None
        # (unchecked).
        meta = {p.name: p.value for p in self.joint.properties.values()
                if naming.is_template_metadata(p.name, p.group)}
        handed = meta.get("Template_Handed")
        if handed is None:
            handed = meta.get("Handed")        # the roadmap's short name
        self.handed = True if handed is None else bool(handed)
        self.angle_min = meta.get("Template_Angle_Min")   # degrees or None
        self.angle_max = meta.get("Template_Angle_Max")
        # Short kind token for feature labels ('WHD'). Templates predating
        # Template_Abbrev fall back to the long '_J-<Kind>-<serial>' suffix,
        # so they still apply correctly — just verbosely.
        self.abbrev = meta.get(naming.TEMPLATE_ABBREV) or None
        # the suffix template feature labels carry
        self.member_suffix = naming.joint_suffix_for(self.joint_label,
                                                     self.abbrev)

        # Per-role stacks: body label -> ordered member specs, skipping
        # the pristine-timber base (section sketch + stick pad).
        self.roles = {}
        self.dims_labels = {}                          # role -> TimberDims label
        self.end_landing_roles = set()                 # roles whose frame sits on a stick end
        self.side_landing_roles = {}                   # role -> template frame plane (YZ/XZ)
        for body in model.bodies:
            dims = model.body_dims(body)
            if dims is None:
                raise JointError(f"template body {body.label!r} has no Dims")
            self.dims_labels[body.label] = dims.label
            base = self._base_members(doc, body)
            stack = []
            group = body.prop("Group")
            for link in (group.links if group else []):
                if link.obj in base:
                    continue
                member = doc.objects[link.obj]
                if member.is_type("App::VarSet"):
                    # a body-nested VarSet is the timber's own Dims (New
                    # Timber nests it inside the Body — §3 tree
                    # organization), never joint geometry. Cloning it
                    # would drop an empty near-duplicate Dims VarSet
                    # into every target timber, which Remove Joint then
                    # cannot clean up (nothing ties it to the joint).
                    continue
                stack.append(self._member_spec(doc, member))
            # Datums (landing frame, mate frame, shoulder datums) must be
            # rebuilt before the sketches/features that attach to them,
            # whatever order they were authored in — a mate frame is
            # commonly authored AFTER the cheek sketch that lands on it,
            # and the rebuilder would then miss it in `local` and resolve
            # the mate-frame sub to a body origin plane by name (silent:
            # the cut lands at the body origin, uncut cheeks). Hoist all
            # datums to the front, preserving their relative order (so a
            # mate frame stays after the joint frame it attaches to); the
            # solid-feature chain keeps its order after them, since
            # pockets chain on one another and datums never do.
            def _is_datum(s):
                return s["type_id"].startswith(
                    ("Part::LocalCoordinateSystem", "Part::Datum"))
            stack = ([s for s in stack if _is_datum(s)]
                     + [s for s in stack if not _is_datum(s)])
            self.roles[body.label] = stack
            # a role lands on a stick end when its frame attaches to the
            # XY origin plane (end A/B selection applies), and on a long
            # face when it attaches to YZ/XZ (face selection applies)
            for spec in stack:
                if spec["type_id"] != "Part::LocalCoordinateSystem":
                    continue
                sub = spec.get("support", {}).get("sub", "")
                if "XY_Plane" in sub:
                    self.end_landing_roles.add(body.label)
                elif "YZ_Plane" in sub:
                    self.side_landing_roles[body.label] = "YZ_Plane"
                elif "XZ_Plane" in sub:
                    self.side_landing_roles[body.label] = "XZ_Plane"
                break

        # The anchor role — the timber the joint LANDS ON. Same test
        # assemble._engagement_frames uses to pick the seat's fixed side:
        # a landing frame and no mate frame. Named here because the
        # companion layout VarSet's expressions measure the anchor's
        # section (Grid_Setback = ddim/2) and so have to follow the face
        # the anchor is applied to. None for a template that declares no
        # Frame_Role, which then behaves exactly as before.
        self.anchor_role = None
        for label, stack in self.roles.items():
            frame_roles = {s.get("frame_role") for s in stack}
            if (naming.FRAME_ROLE_LANDING in frame_roles
                    and naming.FRAME_ROLE_MATE not in frame_roles):
                self.anchor_role = label
                break

    @staticmethod
    def _base_members(doc, body):
        """Internal names of the base section sketch + stick pad."""
        base = set()
        group = body.prop("Group")
        for link in (group.links if group else []):
            obj = doc.objects[link.obj]
            if obj.is_type("PartDesign::Pad"):
                base.add(obj.name)
                profile = obj.prop("Profile")
                if profile and profile.links:
                    base.add(profile.links[0].obj)
                break   # the first Pad is the base feature
        return base

    def _member_spec(self, doc, obj):
        spec = {"name": obj.name, "type_id": obj.type_id, "label": obj.label,
                "expressions": [(e.path, e.expression)
                                for e in obj.expressions]}
        sup = obj.prop("AttachmentSupport")
        if sup and sup.links:
            link = sup.links[0]
            target = doc.objects.get(link.obj)
            sub = link.sub.rstrip(".")
            # normalize LCS child-object references to the child's role
            sub_obj = doc.objects.get(sub)
            if sub_obj is not None and target is not None \
                    and target.is_type("Part::LocalCoordinateSystem"):
                role_prop = sub_obj.prop("Role")
                if role_prop and role_prop.value:
                    sub = role_prop.value
            spec["support"] = {
                "target": target.name if target else link.obj,
                "target_label": target.label if target else link.obj,
                "target_type": target.type_id if target else "",
                "sub": sub,
            }
            mm = obj.prop("MapMode")
            spec["map_mode"] = mm.value if mm else None
            mr = obj.prop("MapReversed")
            spec["map_reversed"] = bool(mr.value) if mr else False
            ao = obj.prop("AttachmentOffset")
            spec["offset"] = ao.placement if ao else None
        # Tier-2 frame role, carried through to the applied model — without
        # it Preview, Assemble, Duplicate and the end-B seat flip cannot
        # tell a landing frame from a mate frame. Legacy templates predate
        # the property; fall back to the retired label substrings.
        if obj.is_type("Part::LocalCoordinateSystem", "Part::Datum"):
            role = obj.prop(naming.FRAME_ROLE_PROP)
            spec["frame_role"] = (role.value if role and role.value
                                  else naming.legacy_frame_role(obj.label))
        if obj.is_type("Sketcher::SketchObject"):
            g = obj.prop("Geometry")
            spec["geometry"] = g.geometry if g else []
            for geo in spec["geometry"]:
                if geo.kind not in _SUPPORTED_GEOMETRY:
                    raise JointError(
                        f"{obj.label}: unsupported geometry {geo.type_id} "
                        f"(rebuilder handles lines and circles)")
            c = obj.prop("Constraints")
            spec["constraints"] = c.constraints if c else []
        if obj.is_type("PartDesign::"):
            for pname in ("Type", "SideType", "Reversed", "DepthType",
                          "DrillPoint", "Tapered", "ThreadType"):
                p = obj.prop(pname)
                if p is not None and p.value is not None:
                    spec.setdefault("feature_props", {})[pname] = p.value
            profile = obj.prop("Profile")
            if profile and profile.links:
                spec["profile"] = profile.links[0].obj
            length = obj.prop("Length")
            if length is not None:
                spec["length_mm"] = length.value
            dia = obj.prop("Diameter")
            if dia is not None:
                spec["diameter_mm"] = dia.value
        return spec


# --------------------------------------------------------------------------
# Joint instance membership and removal
# --------------------------------------------------------------------------

def joint_members(varset):
    """Every object belonging to a joint instance (the VarSet excluded).

    Structural, not label-based: anything whose expressions reference
    the joint VarSet, closed over attachment supports (the landing
    frames, which may carry no expressions of their own) and the
    frames' child datum features.
    """
    doc = varset.Document
    token = f"<<{varset.Label}>>"
    members = set()
    for obj in doc.Objects:
        if obj is varset:
            continue
        engine = getattr(obj, "ExpressionEngine", None) or []
        if any(token in expr for _path, expr in engine):
            members.add(obj)
    # profile-consumer closure: a Through-All pocket may carry no
    # expressions of its own (depth implicit, diameter in the sketch) —
    # it belongs to the joint through its profile sketch
    for obj in doc.Objects:
        profile = getattr(obj, "Profile", None)
        if profile:
            target = profile[0] if isinstance(profile, tuple) else profile
            if target in members:
                members.add(obj)
    # attachment-support closure: landing frames and datums the members
    # hang off (only within the members' own bodies)
    for obj in list(members):
        for link in (getattr(obj, "AttachmentSupport", None) or []):
            target = link[0]
            if target.TypeId.startswith(("Part::LocalCoordinateSystem",
                                         "Part::Datum")):
                members.add(target)
    # LCS child features (axes/planes/origin) die with their frame
    for obj in list(members):
        if obj.TypeId == "Part::LocalCoordinateSystem":
            members.update(getattr(obj, "OriginFeatures", []))
    return members


def _expression_input(value):
    """The expression in an apply-time `values` entry, or None when it
    is a literal.

    Same spreadsheet convention as new_timber: a string starting with
    '=' is an expression, anything else is a value. apply_joint used to
    treat EVERY string as an expression, which silently turned a plain
    '3 in' into the expression `3 in` — resolving to the same number,
    so it looked right, while quietly making the property
    expression-bound and unwritable. It cost two debugging rounds
    during the grid-span work before the inconsistency was named.
    """
    if isinstance(value, str) and value.lstrip().startswith("="):
        expr = value.lstrip()[1:].strip()
        if not expr:
            raise JointError("empty expression (nothing after '=')")
        return expr
    return None


def layout_varset(varset):
    """A joint's companion layout VarSet, or None.

    Structural: whichever VarSet this joint's own expressions consume
    from carries the VarSet_Role marker. Never label-matched — a
    renamed companion must still resolve (Frame_Role's lesson) — with
    the label kept only as a fallback for a companion nothing happens
    to reference yet.
    """
    doc = varset.Document
    for _path, expr in (getattr(varset, "ExpressionEngine", None) or []):
        for label in _LABEL_IN_EXPR.findall(expr):
            for obj in doc.getObjectsByLabel(label):
                if obj.TypeId == "App::VarSet" and getattr(
                        obj, naming.VARSET_ROLE_PROP,
                        None) == naming.VARSET_ROLE_LAYOUT:
                    return obj
    for obj in doc.getObjectsByLabel(naming.layout_label(varset.Label)):
        if obj.TypeId == "App::VarSet":
            return obj
    return None


def remove_joint(varset):
    """Remove a joint instance: all members from both timbers, the
    companion layout VarSet if the template declared one, then the
    VarSet. Returns the number of objects removed. Caller owns the
    transaction."""
    doc = varset.Document
    companion = layout_varset(varset)
    if companion is not None:
        # a timber whose Length is driven from a span consumes this
        # joint's allowance; freeze that one term at its resolved value
        # so the stick stays put instead of shrinking by the tenon it is
        # losing (and dragging the far post with it) mid-delete
        from .span import freeze_allowance_term
        freeze_allowance_term(companion)
    # clear any live preview first — its ghost link and group are not
    # joint members (no expression ties them to the VarSet), so removing
    # the joint would orphan the ghost and leave the secondary hidden
    # with no VarSet left for the Preview tool to find
    preview = find_preview(varset)
    if preview is not None:
        remove_preview(preview)
    # the handle is not a joint member either (it holds the VarSet, it
    # does not reference it by expression) — it would outlive its joint
    joint_handle.remove_handle(varset)
    members = joint_members(varset)
    # the joint's Fixed assembly joint (if assembled) references the
    # landing/mate frames — remove it with the frames it points at
    frame_names = {o.Name for o in members
                   if o.TypeId == "Part::LocalCoordinateSystem"}
    for obj in list(doc.Objects):
        if getattr(obj, "JointType", None) is None:
            continue
        refs = [getattr(obj, "Reference1", None),
                getattr(obj, "Reference2", None)]
        for ref in refs:
            subs = ref[1] if ref and len(ref) == 2 else []
            # dotted-path segment match: "LocalCoordinateSystem" must
            # not swallow another joint's "LocalCoordinateSystem002"
            if any(name in ("." + sub).replace(".", " ").split()
                   for name in frame_names for sub in subs if sub):
                doc.removeObject(obj.Name)
                break
    member_names = {o.Name for o in members}
    ordered = []
    for obj in doc.Objects:
        if obj.TypeId != "PartDesign::Body":
            continue
        # later features chain on earlier ones: remove dependents first
        ordered.extend(child.Name for child in reversed(list(obj.Group))
                       if child.Name in member_names)
    ordered.extend(member_names.difference(ordered))   # LCS children etc.
    removed = 0
    affected_bodies = set()
    for name in ordered:
        obj = doc.getObject(name)
        if obj is None:                        # may cascade with a parent
            continue
        parent = obj.getParentGeoFeatureGroup()
        if parent is not None:
            affected_bodies.add(parent)
        # the API does not relink the solid chain on removal: point any
        # dependent feature (and the body Tip) past the leaving feature
        base = getattr(obj, "BaseFeature", None)
        if base is not None or hasattr(obj, "BaseFeature"):
            for other in doc.Objects:
                if getattr(other, "BaseFeature", None) is obj:
                    other.BaseFeature = base
            body = obj.getParentGeoFeatureGroup()
            if body is not None and body.Tip is obj:
                body.Tip = base
        doc.removeObject(name)
        removed += 1
    doc.removeObject(varset.Name)
    if companion is not None:
        # goes with its joint: nothing else may consume from it, since
        # a pure source is by definition only read downstream
        doc.removeObject(companion.Name)
        removed += 1
    joint_handle.prune_root_group(doc)
    doc.recompute()
    # deleting a body's visible tip leaves the relinked tip hidden (the
    # GUI restores it on delete; the API does not) — the timber would
    # look deleted
    for body in affected_bodies:
        if body.Tip is not None:
            body.Tip.Visibility = True
    return removed + 1


# --------------------------------------------------------------------------
# Mated-joint engagement (Preview, assembly)
# --------------------------------------------------------------------------

_SEGMENT = re.compile(
    r"(?P<role>[^;]+?) -> (?P<body>.+?): "
    r"(?:face (?P<face>\d), hand (?P<hand>\w+)|end (?P<end>[AB]))")


def parse_placement_record(record):
    """(role -> body label, placement dict) from a Placement_Record."""
    role_bodies, placement = {}, {}
    for seg in record.split(";"):
        m = _SEGMENT.match(seg.strip())
        if not m:
            raise JointError(f"cannot parse placement record segment "
                             f"{seg.strip()!r}")
        role = m.group("role").strip()
        role_bodies[role] = m.group("body").strip()
        if m.group("end"):
            placement[role] = {"end": m.group("end")}
        else:
            placement[role] = {"face": int(m.group("face")),
                               "hand": m.group("hand")}
    return role_bodies, placement


def anchor_face(varset, anchor_body):
    """The face the anchor role was applied on, from the joint's
    Placement_Record; TEMPLATE_FACE when unrecorded (legacy joints and
    end-landing anchors)."""
    record = getattr(varset, "Placement_Record", "")
    if not record:
        return TEMPLATE_FACE
    try:
        role_bodies, placement = parse_placement_record(record)
    except JointError:
        return TEMPLATE_FACE
    for role, label in role_bodies.items():
        if label == anchor_body.Label and "face" in placement[role]:
            return placement[role]["face"]
    # body renamed after apply: if exactly one role carries a face
    # choice, it is the anchor (side-landing) role
    faces = [p["face"] for p in placement.values() if "face" in p]
    return faces[0] if len(faces) == 1 else TEMPLATE_FACE


def mate_parity(varset, anchor_body):
    """The engaged-pose correction between a joint's landing and mate
    frames: identity on faces whose frame Z points out of the wood
    (template face 4, face 1), a 180° turn about the frame's local Y
    (the depth axis — "end for end, keep it upright") on the flip_z
    faces (2 and 3), where plain frame coincidence would seat the
    mating timber mirrored through the bearing plane — the inverted
    end-B bent of the first GUI shakedown."""
    if FACES[anchor_face(varset, anchor_body)]["flip_z"]:
        return App.Placement(App.Vector(),
                             App.Rotation(App.Vector(0, 1, 0), 180))
    return App.Placement()


def joint_role_frames(varset):
    """{body: {'landing': LCS|None, 'mate': LCS|None}} for a joint's roles.

    The landing frame is where the joint sits on its timber; the mate
    frame is on the role that enters its mate (the tenon side), declaring
    the pose that seats the joint.

    Roles come from the Tier-2 `Frame_Role` property, never the label —
    the retired 'JointFrame'/'MateFrame' substring match silently
    disabled Preview, Assemble and Duplicate whenever a template author
    renamed a frame. Documents built before the property fall back to
    those substrings.
    """
    frames = {}
    for obj in joint_members(varset):
        if obj.TypeId != "Part::LocalCoordinateSystem":
            continue
        body = obj.getParentGeoFeatureGroup()
        if body is None:
            continue
        # every joint LCS registers its body, role or not: bent_joints
        # reads the body set to decide which joints a bent spans
        slot = frames.setdefault(body, {"landing": None, "mate": None})
        role = (getattr(obj, naming.FRAME_ROLE_PROP, None)
                or naming.legacy_frame_role(obj.Label))
        if role == naming.FRAME_ROLE_MATE:
            slot["mate"] = obj
        elif role == naming.FRAME_ROLE_LANDING:
            slot["landing"] = obj
    return frames


def bent_joints(doc, bodies):
    """(inside, outside): timber-joint VarSets whose role bodies are all
    within `bodies`, and those that reach outside the set."""
    body_set = set(bodies)
    inside, outside = [], []
    for obj in doc.Objects:
        if obj.TypeId != "App::VarSet" \
                or not naming.is_joint_varset_label(obj.Label):
            continue
        joint_bodies = set(joint_role_frames(obj))
        if not joint_bodies:
            continue
        if joint_bodies & body_set:
            (inside if joint_bodies <= body_set else outside).append(obj)
    return inside, outside


def engagement_placement(varset):
    """Seated pose for the mating half of a joint.

    The role carrying a mate frame (the tenon side) is the mover; the
    other role (the mortise side) is the anchor. Returns
    (mover_body, anchor_body, placement) where `placement` set on the
    mover body seats its mate frame on the anchor's landing frame
    (frame coincidence composed with mate_parity for the anchor's
    face) — independent of either body's current placement. Returns
    None when the joint predates mate frames or is missing a frame.
    """
    frames = joint_role_frames(varset)
    mover = next(((b, f) for b, f in frames.items() if f["mate"]), None)
    anchor = next(((b, f) for b, f in frames.items()
                   if f["landing"] and not f["mate"]), None)
    if mover is None or anchor is None:
        return None
    mover_body, mover_f = mover
    anchor_body, anchor_f = anchor
    landing_g = anchor_f["landing"].getGlobalPlacement()
    mate_g = mover_f["mate"].getGlobalPlacement()
    target = landing_g.multiply(mate_parity(varset, anchor_body))
    # the mate frame expressed in the mover body's own frame (constant);
    # global chains, not body.Placement, so bodies inside a placed
    # container (a bent sub-assembly) resolve correctly
    mate_local = mover_body.getGlobalPlacement().inverse().multiply(mate_g)
    seated_global = target.multiply(mate_local.inverse())
    # returned in the mover's container frame — what body.Placement takes
    parent = mover_body.getGlobalPlacement().multiply(
        mover_body.Placement.inverse())
    return mover_body, anchor_body, parent.inverse().multiply(seated_global)


def preview_group_label(varset):
    return f"Preview_{varset.Label}"


def find_preview(varset):
    """The existing preview group for this joint, or None."""
    groups = varset.Document.getObjectsByLabel(preview_group_label(varset))
    return groups[0] if groups else None


def remove_preview(group):
    """Delete a preview group and its link, restoring the hidden
    secondary body's visibility. Caller owns the transaction."""
    doc = group.Document
    hidden = getattr(group, "HiddenBody", "")
    for link in list(group.Group):
        doc.removeObject(link.Name)
    body = doc.getObject(hidden) if hidden else None
    if body is not None:
        body.Visibility = True
    doc.removeObject(group.Name)
    doc.recompute()


def create_preview(varset):
    """Non-destructive engaged view: a ghost (App::Link) of the joint's
    secondary half — the mate-frame carrier, the piece that enters —
    seated in the real primary half at its actual location. The real
    secondary body is hidden so it doesn't overlap its ghost; the
    primary stays as the visible reference. No placement is ever touched
    (finding #11). Replaces any prior preview of this joint. Returns the
    group, or None if not previewable. Caller owns the transaction.

    The ghost is *attached* to the primary's landing frame, so it tracks
    parameter edits live: the landing frame moves with Joint_Station and
    the primary section, and the linked body reshapes for every joint
    parameter. It seats correctly wherever the primary body currently
    sits. What is NOT tracked (needs a refresh — toggle off/on): edits
    that move the mate frame WITHIN the secondary, i.e. the secondary's
    Width or Depth (mate frame at Width/2, Depth/2) or Tenon_Length (its
    Z) — the attachment offset to that frame is fixed at creation — and
    moving a body with the transform tool while the preview is up. The
    complete fix is a recompute-driven ghost placement (see roadmap)."""
    eng = engagement_placement(varset)
    if eng is None:
        return None
    mover_body, anchor_body, seated = eng
    doc = varset.Document
    existing = find_preview(varset)
    if existing is not None:
        remove_preview(existing)
    group = doc.addObject("App::DocumentObjectGroup", "JointPreview")
    group.Label = preview_group_label(varset)
    group.addProperty("App::PropertyString", "HiddenBody", "Preview",
                      "Real body hidden while its ghost is displayed")
    group.HiddenBody = mover_body.Name
    link = doc.addObject("App::Link", "PreviewLink")
    link.Label = f"Preview_{mover_body.Label}_{varset.Label}"
    link.setLink(mover_body)
    link.LinkTransform = False
    # attach to the landing frame so the ghost follows it on recompute.
    # The attach engine resolves the support in its BODY-LOCAL frame, so
    # the offset must be built from the frame's local placement too
    # (using the global placement lands the ghost at the origin-relative
    # spot when the primary body has been moved). link_local = landing *
    # offset = seated at creation; station edits then track live.
    landing = joint_role_frames(varset)[anchor_body]["landing"]
    link.addExtension("Part::AttachExtensionPython")
    link.AttachmentSupport = [(landing, "")]
    link.MapMode = "ObjectXY"
    link.AttachmentOffset = landing.Placement.inverse().multiply(seated)
    group.addObject(link)
    mover_body.Visibility = False
    doc.recompute()
    return group


# --------------------------------------------------------------------------
# Rebuilding in the target document
# --------------------------------------------------------------------------

def _constraint_args(con):
    """Sketcher.Constraint positional args from a parsed constraint."""
    args = []
    for geo, pos in ((con.first, con.first_pos),
                     (con.second, con.second_pos),
                     (con.third, 0)):
        if geo == -2000:
            break
        args.append(geo)
        if pos:
            args.append(pos)
    if con.type_id in DIMENSIONAL:
        args.append(con.value)
    return args


_CONSTRAINT_NAMES = {
    1: "Coincident", 2: "Horizontal", 3: "Vertical", 4: "Parallel",
    5: "Tangent", 6: "Distance", 7: "DistanceX", 8: "DistanceY",
    9: "Angle", 10: "Perpendicular", 11: "Radius", 12: "Equal",
    13: "PointOnObject", 14: "Symmetric", 17: "Block", 18: "Diameter",
}


def _rewrite(text, replacements):
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def apply_joint(doc, template, joint_id, body_map, values=None,
                placement=None):
    """Apply `template` (TemplateSpec) into `doc`.

    body_map: {template body label -> target PartDesign body object},
    e.g. {"P0-1": post, "B0-1": beam}. values: optional {property name ->
    value} overrides applied to the new joint VarSet, or to its
    companion layout VarSet for parameters the template declares there
    (literal override of a junction binding replaces the expression,
    per §4.9). A value is a Quantity/number, or a string starting with
    '=' for an expression — the spreadsheet convention new_timber uses.
    A plain string is a literal, NOT an expression.
    placement: optional {template body label -> options}:
      {"end": "A"|"B"} for end-landing roles — end B keeps the frame
      orientation (reference-face rule: setbacks keep measuring from the same
      reference faces), translates it to Dims.Length, flips along-axis
      cut directions, and negates along-axis positions, including the
      drawbore sign flip (§4.7);
      {"face": 1..4} for side-landing roles — re-attaches the landing
      frame per the FACES table.
    Returns the new joint VarSet. Caller owns the transaction.
    """
    values = values or {}
    placement = placement or {}
    for role, opts in placement.items():
        end = str(opts.get("end", "A")).upper()
        if end not in ("A", "B"):
            raise JointError(f"placement end for {role!r} must be A or B")
        if end == "B" and role not in template.end_landing_roles:
            raise JointError(
                f"role {role!r} does not land on a stick end; end B "
                f"placement does not apply")
        face = opts.get("face", TEMPLATE_FACE)
        if face not in FACES:
            raise JointError(f"placement face for {role!r} must be 1-4")
        hand = str(opts.get("hand", "template")).lower()
        if hand not in ("template", "mirrored"):
            raise JointError(
                f"placement hand for {role!r} must be 'template' or "
                f"'mirrored'")
        if hand == "mirrored" and not template.handed:
            raise JointError(
                f"role {role!r}: this template is symmetrical "
                f"(Template_Handed false) — mirrored hand does not apply")
        if face != TEMPLATE_FACE or hand == "mirrored":
            if role not in template.side_landing_roles:
                raise JointError(
                    f"role {role!r} does not land on a long face; "
                    f"face/hand placement does not apply")
            if template.side_landing_roles[role] != "YZ_Plane":
                raise JointError(
                    f"template role {role!r} is not authored on the "
                    f"canonical face (Face 4 / YZ plane); face/hand "
                    f"selection needs a Face-4 template")
    joint_id = (joint_id or "").strip()
    if not joint_id or "<" in joint_id or ">" in joint_id:
        raise JointError("joint ID must be a non-empty string without <>")
    new_joint_label = naming.joint_label(template.kind_token, joint_id)
    if doc.getObjectsByLabel(new_joint_label):
        raise JointError(f"label {new_joint_label!r} already exists")
    if set(body_map) != set(template.roles):
        raise JointError(
            f"body_map roles {sorted(body_map)} != template roles "
            f"{sorted(template.roles)}")

    # Label/expression rewrite table: template joint + each role's
    # MemberID and Dims label -> target equivalents. The target Dims
    # label is resolved structurally from the body's base pad, so a
    # renamed body binds its ACTUAL VarSet, whatever it is called.
    renames = {template.joint_label: new_joint_label,
               # feature labels carry the joint token as a suffix
               # ('.WHD.000' -> '.WHD.007')
               template.member_suffix:
                   naming.joint_suffix_for(new_joint_label, template.abbrev)}
    role_dims = {}
    for tmpl_label, body in body_map.items():
        dims = dims_varset(body)
        if dims is None:
            raise JointError(
                f"{body.Label!r} has no Dims VarSet driving its base pad — "
                f"is it a BentWizard timber?")
        role_dims[tmpl_label] = dims.Label
        renames[template.dims_labels[tmpl_label]] = dims.Label
        # descriptive-first feature labels no longer embed the timber name,
        # so this entry is a no-op for them; it stays for expressions that
        # reference a body directly, and to scrub the timber token out of
        # legacy templates whose features still carry it
        renames[tmpl_label] = body.Label
    new_layout_label = None
    if template.layout is not None:
        new_layout_label = naming.layout_label(new_joint_label)
        renames[template.layout_label] = new_layout_label
    expr_renames = {f"<<{k}>>": f"<<{v}>>" for k, v in renames.items()}

    def _fill(target, params):
        """Create `params` on `target` and apply values/expressions."""
        for p in params:
            target.addProperty(p["type_id"], p["name"], p["group"],
                               p["tooltip"])
            setattr(target, p["name"], p["value"])
        for p in params:
            if p.get("consumed"):
                # Consumed from the companion — the binding always wins.
                # `values` is keyed by NAME and both VarSets share these
                # names, so without this the companion's own value lands
                # on the joint VarSet too and silently replaces the
                # binding: the allowance would then track an edit the
                # actual cut ignored.
                if p["expression"]:
                    target.setExpression(
                        p["name"], _rewrite(p["expression"], expr_renames))
                continue
            if p["name"] in values:
                v = values[p["name"]]
                expr = _expression_input(v)
                if expr is not None:
                    try:
                        target.setExpression(p["name"], expr)
                    except Exception as exc:
                        raise JointError(
                            f"{p['name']}: invalid expression {expr!r} "
                            f"— {exc}")
                elif isinstance(v, str):
                    # a plain string is a literal: parse it the way the
                    # property's own type would
                    try:
                        setattr(target, p["name"], v)
                    except Exception as exc:
                        raise JointError(
                            f"{p['name']}: cannot use {v!r} as a value "
                            f"(prefix with '=' for an expression) — {exc}")
                else:
                    setattr(target, p["name"], v)   # literal override
            elif p["expression"]:
                target.setExpression(p["name"],
                                     _rewrite(p["expression"], expr_renames))

    # The companion's expressions measure the ANCHOR timber's section
    # (Grid_Setback = ddim/2), but nothing was face-correcting them:
    # _face_transform is applied only to landing-frame specs, and _fill
    # rewrites labels alone. On faces 1/3 — where FACES[n]['ddim'] is
    # Depth — Grid_Setback kept reading Width, so on-center layout came
    # out wrong by half the section difference, silently. Swap the
    # anchor's section tokens here, before _fill renames them.
    anchor = template.anchor_role
    swap_dims = None
    if (anchor is not None and anchor in template.side_landing_roles
            and FACES[placement.get(anchor, {}).get("face",
                                                    TEMPLATE_FACE)]["swap"]):
        swap_dims = template.dims_labels[anchor]

    def _params(kind):
        rows = [p for p in template.parameters if p["varset"] == kind]
        if kind != "layout" or swap_dims is None:
            return rows
        return [dict(p, expression=_swap_section_tokens(p["expression"],
                                                        swap_dims))
                if p["expression"] else p
                for p in rows]

    # --- companion layout VarSet ------------------------------------------
    # Created FIRST: it is the pure source the joint VarSet consumes
    # from, and that direction is what keeps a grid-driven Dims.Length
    # out of a dependency cycle (roadmap: Parametric layout).
    layout = None
    if template.layout is not None:
        layout = doc.addObject("App::VarSet", "JointLayoutVarSet")
        layout.Label = new_layout_label
        joints_group(doc).addObject(layout)
        layout.addProperty("App::PropertyString", naming.VARSET_ROLE_PROP,
                           naming.TEMPLATE_META_GROUP,
                           "Marks this as a joint's companion layout "
                           "VarSet: the pure source holding the "
                           "length-consuming parameters. Tools resolve "
                           "the companion through this, never by label.")
        setattr(layout, naming.VARSET_ROLE_PROP, naming.VARSET_ROLE_LAYOUT)
        _fill(layout, _params("layout"))

    # --- joint VarSet -----------------------------------------------------
    varset = doc.addObject("App::VarSet", "JointVarSet")
    varset.Label = new_joint_label
    joints_group(doc).addObject(varset)
    _fill(varset, _params("joint"))

    # Pre-flight parameter sanity against the RESOLVED values — junction
    # bindings have now evaluated against the actual chosen timbers, so
    # this is where template defaults meet a too-small stick. Refuse
    # before cutting anything (roadmap: apply-dialog sanity bounds).
    doc.recompute()
    for vs in (v for v in (varset, layout) if v is not None):
        if "Invalid" in vs.State or "Error" in vs.State:
            # an expression that parsed but cannot evaluate (e.g. a
            # VarSet or property that does not exist) surfaces here
            raise JointError(
                f"{vs.Label} failed to compute — check the expression "
                f"values entered for this joint")

    def lookup(name):
        # parameters may live on either VarSet: a length-consuming one
        # (Tenon_Length) moves to the companion, and the sanity checks
        # must still see it. The joint VarSet wins when both carry the
        # name, since that is the value the geometry actually reads.
        p = getattr(varset, name, None)
        if p is None and layout is not None:
            p = getattr(layout, name, None)
        return p.Value if hasattr(p, "Value") else p

    problems = footprint_violations(lookup)
    if problems:
        raise JointError(
        "the joint does not fit these timbers:\n  "
        + "\n  ".join(problems)
        + "\nreduce the tenon/setback values or use larger timbers")

    # Declared angle range (Template_Angle_Min/Max): every angle-typed
    # joint parameter must resolve inside it — the template author's
    # statement of where the cut profiles stay valid.
    if template.angle_min is not None or template.angle_max is not None:
        lo, hi = template.angle_min, template.angle_max
        for p in template.parameters:
            if p["type_id"] != "App::PropertyAngle" or p["metadata"]:
                continue
            v = lookup(p["name"])
            if v is None:
                continue
            if (lo is not None and v < lo - 1e-9) \
                    or (hi is not None and v > hi + 1e-9):
                raise JointError(
                    f"{p['name']} = {v:g}° is outside this template's "
                    f"declared angle range [{lo:g}°, {hi:g}°] "
                    f"(Template_Angle_Min/Max) — its cut profiles are "
                    f"not valid there")

    # Placement provenance (Tier 2): which face/end/hand each role was
    # applied with — the input for Preview Mated Joint and future
    # re-place operations (e.g. rotating a mortise onto another face).
    record = "; ".join(
        f"{role} -> {body_map[role].Label}: "
        + (f"end {str(placement.get(role, {}).get('end', 'A')).upper()}"
           if role in template.end_landing_roles else
           f"face {placement.get(role, {}).get('face', TEMPLATE_FACE)}, "
           f"hand {str(placement.get(role, {}).get('hand', 'template')).lower()}")
        for role in template.roles)
    varset.addProperty(
        "App::PropertyString", "Placement_Record", "Placement",
        "How each template role was placed (timber, face/end, hand) — "
        "written by Apply Joint; used by preview and re-place tools.")
    varset.Placement_Record = record
    varset.addProperty(
        "App::PropertyString", "Template_Source", "Placement",
        "Library template this joint was applied from — used by "
        "Duplicate Timbers to re-apply the joint on the copies.")
    varset.Template_Source = template.source_name
    varset.addProperty(
        "App::PropertyString", "Position_Tag", "Tag",
        "Where this joint sits in the structure (e.g. 'Bent 2, north "
        "girt') — display-only label for drawings and lists. Nothing "
        "binds to it; set, change, or clear it freely.")

    # --- per-role stacks ----------------------------------------------------
    made = []
    for tmpl_label, stack in template.roles.items():
        body = body_map[tmpl_label]
        opts = placement.get(tmpl_label, {})
        end_b = str(opts.get("end", "A")).upper() == "B"
        face = FACES[opts.get("face", TEMPLATE_FACE)]
        ctx = {
            "end_b": end_b,
            "face": face,
            "flip_z": end_b or face["flip_z"],
            # hand: mirror the across-face axis (frame X). The frame
            # origin sits at the footprint center, so the §4.6 handed-
            # mate setback complement is a pure coordinate mirror.
            "flip_x": str(opts.get("hand", "template")).lower() == "mirrored",
            "dims_label": role_dims[tmpl_label],
            "frame_name": next((s["name"] for s in stack
                                if s["type_id"] == "Part::LocalCoordinateSystem"),
                               None),
            "sketch_subs": {},   # template sketch name -> frame-child role
            # side-landing roles may re-attach the frame to another face
            "frame_plane": (face["plane"]
                            if tmpl_label in template.side_landing_roles
                            else None),
            "side_landing": tmpl_label in template.side_landing_roles,
        }
        local = {}          # template internal name -> new object
        for spec in stack:
            obj = _rebuild_member(doc, body, spec, local, renames,
                                  expr_renames, ctx)
            local[spec["name"]] = obj
            made.append(obj)
            # each solid feature probes its BaseFeature's shape as soon
            # as its parameters are set — keep the chain computed
            doc.recompute()

    doc.recompute()
    bad = [o.Label for o in made + [varset]
           if "Invalid" in o.State or "Error" in o.State]
    if bad:
        raise JointError(f"recompute failed for: {', '.join(bad)}")
    # the joint's handle: one clickable thing standing for a joint that
    # is otherwise scattered across two bodies. Assimilation re-files it
    # once the joint has an assembly to belong to.
    joint_handle.ensure_handle(varset)
    return varset


def _aligned_axis(sketch, direction):
    """Which sketch-local axis (0=x, 1=y) runs along `direction` (a
    frame axis, in body coordinates), or None when the direction is
    perpendicular to the sketch plane (nothing to mirror there).
    Placements inside a body are body-local, so this is pose-independent.
    """
    rot = sketch.Placement.Rotation
    for axis, vec in ((0, App.Vector(1, 0, 0)), (1, App.Vector(0, 1, 0))):
        if abs(rot.multVec(vec).dot(direction)) > 0.99:
            return axis
    if abs(rot.multVec(App.Vector(0, 0, 1)).dot(direction)) > 0.99:
        return None
    raise JointError(
        f"{sketch.Label}: cannot identify the frame axis in this sketch "
        f"plane (end/face/hand placement needs an axis-aligned frame)")


def _rebuild_member(doc, body, spec, local, renames, expr_renames, ctx):
    type_id = spec["type_id"]
    obj = body.newObject(type_id, type_id.split(":")[-1])
    obj.Label = _rewrite(spec["label"], renames)
    if spec.get("frame_role"):
        # Tier-2: re-declare the role on the clone (see naming.FRAME_ROLE_PROP)
        obj.addProperty("App::PropertyString", naming.FRAME_ROLE_PROP,
                        "TimberJoint",
                        "This frame's role in the timber joint: 'Landing' "
                        "(where the joint sits on this timber) or 'Mate' "
                        "(the pose this timber takes when seated).")
        setattr(obj, naming.FRAME_ROLE_PROP, spec["frame_role"])
    on_frame = ("support" in spec
                and spec["support"]["target"] == ctx["frame_name"])
    is_frame = spec["name"] == ctx["frame_name"]
    if on_frame and type_id == "Sketcher::SketchObject":
        ctx["sketch_subs"][spec["name"]] = spec["support"]["sub"]

    if "support" in spec:
        target_type = spec["support"]["target_type"]
        sub = spec["support"]["sub"].rstrip(".")
        if spec["support"]["target"] in local:
            # anchored to an earlier member of this cloned stack (the
            # landing frame). Reference the frame's child plane BY NAME,
            # exactly like the template does: resolving by role takes a
            # different AttachEngine path with a different in-plane
            # orientation, which flips one-directional cuts.
            anchor = local[spec["support"]["target"]]
            if sub and anchor.TypeId == "Part::LocalCoordinateSystem":
                for child in anchor.OutList:
                    if getattr(child, "Role", "") == sub:
                        sub = child.Name + "."
                        break
                else:
                    raise JointError(
                        f"{spec['label']}: frame has no child with role "
                        f"{sub!r}")
            obj.AttachmentSupport = [(anchor, sub)]
        elif target_type.startswith("App::Plane") or target_type == "App::Origin" \
                or "Plane" in sub:
            # a body origin plane, recorded in any of FreeCAD's forms;
            # the landing frame of a side-landing role re-attaches to
            # the chosen face's plane
            if is_frame and ctx["frame_plane"]:
                anchor = next(f for f in body.Origin.OriginFeatures
                              if f.Role == ctx["frame_plane"])
            else:
                anchor = _origin_plane(body, spec["support"])
            obj.AttachmentSupport = [(anchor, "")]
        else:
            raise JointError(
                f"{spec['label']}: unsupported attachment target "
                f"{spec['support']}")
        mm = spec.get("map_mode")
        if mm is not None:
            if isinstance(mm, int):
                mm = obj.getEnumerationsOfProperty("MapMode")[mm]
            obj.MapMode = mm
        if spec.get("map_reversed"):
            obj.MapReversed = True
        off = spec.get("offset")
        if off is not None:
            # App.Rotation's 4-float form is (x, y, z, w) — same order
            # as the file's Q0..Q3
            obj.AttachmentOffset = App.Placement(
                App.Vector(off.px, off.py, off.pz),
                App.Rotation(off.q[0], off.q[1], off.q[2], off.q[3]))

    if type_id == "Sketcher::SketchObject":
        negate_axes = set()
        if (ctx["flip_z"] or ctx["flip_x"]) and on_frame:
            # mirror every in-plane sketch axis aligned with a flipped
            # frame direction: flip_z reaches perpendicular sketches
            # (the drawbore), flip_x reaches frame-plane sketches (the
            # handed mortise) — each automatically, per plane
            doc.recompute()          # resolve the attachment placements
            frot = local[ctx["frame_name"]].Placement.Rotation
            for active, frame_vec in ((ctx["flip_z"], App.Vector(0, 0, 1)),
                                      (ctx["flip_x"], App.Vector(1, 0, 0))):
                if active:
                    axis = _aligned_axis(obj, frot.multVec(frame_vec))
                    if axis is not None:
                        negate_axes.add(axis)
        _rebuild_sketch(obj, spec, negate_axes)
        obj.Visibility = False       # consumed by a cut; declutter the view
    elif type_id.startswith("PartDesign::"):
        _rebuild_feature(obj, spec, local)
        if ctx["flip_z"] and hasattr(obj, "Reversed") \
                and ctx["sketch_subs"].get(spec.get("profile")) == "XY_Plane":
            # frame-plane profile: the cut runs along frame Z — flip it
            obj.Reversed = not obj.Reversed

    negate_paths = spec.pop("_negate_paths", set())
    for path, expression in spec["expressions"]:
        expression = _rewrite(expression, expr_renames)
        clean = path.lstrip(".")
        if is_frame and ctx["side_landing"]:
            expression = _face_transform(clean, expression, ctx)
        if clean in negate_paths:
            expression = f"-({expression})"
        elif on_frame and not is_frame \
                and spec["support"]["sub"] == "XY_Plane" \
                and ((ctx["flip_z"] and clean == "AttachmentOffset.Base.z")
                     or (ctx["flip_x"] and clean == "AttachmentOffset.Base.x")):
            # frame-child datum offsets along a flipped frame axis
            # measure backward (e.g. the shoulder under end B)
            expression = f"-({expression})"
        obj.setExpression(clean, expression)

    if ctx["end_b"] and is_frame:
        # the landing frame itself: same orientation (the reference
        # faces don't change), translated to the far end
        obj.setExpression("AttachmentOffset.Base.z",
                          f"<<{ctx['dims_label']}>>.Length")

    if ctx["flip_z"] and spec.get("frame_role") == naming.FRAME_ROLE_MATE:
        # the mate frame declares the engaged pose; end B translates its
        # position (the shoulder moves to the far end) but must also
        # REVERSE its orientation so its Z points back toward the beam
        # body, not off the tenon end — otherwise engagement seats the
        # joint backwards (tenon out, body through the timber). Rotate
        # 180° about the SUPPORT frame's Y (the landing frame's depth
        # axis): keeps Depth on the same reference face, flips Width —
        # the "turn the stick end-for-end, keep it upright" motion.
        if any(path.lstrip(".").startswith("AttachmentOffset.Rotation")
               for path, _ in spec["expressions"]):
            # an expression-driven mate-frame tilt (angled template)
            # cannot be statically composed with the flip — refuse
            # rather than mis-seat silently
            raise JointError(
                f"{spec['label']}: this placement needs the end-for-end "
                f"seat flip, which cannot compose with the mate frame's "
                f"expression-driven rotation — apply this template at "
                f"its authored placement until angled placement lands")
        off = obj.AttachmentOffset
        off.Rotation = mate_flip_rotation(off.Rotation)
        obj.AttachmentOffset = off
    return obj


def mate_flip_rotation(authored):
    """The end-for-end mate-frame seat flip: 180° about the landing
    frame's Y (depth) axis, LEFT-composed so an authored mate-frame
    rotation survives. The flip acts in the support frame's axes, after
    the authored turn — right-composing (about the mate frame's own Y)
    would tip a turned mate frame upside down, e.g. the housed
    dovetail's 90°-about-Z frame, whose seated X must stay the up axis."""
    return App.Rotation(App.Vector(0, 1, 0), 180).multiply(authored)


def _swap_section_tokens(expression, dims_label):
    """Exchange Width and Depth on `dims_label` — the substitution a face
    change makes when the joint normal moves to the other section axis
    (FACES[n]['swap'])."""
    w, d = f"<<{dims_label}>>.Width", f"<<{dims_label}>>.Depth"
    return expression.replace(w, "\x00").replace(d, w).replace("\x00", d)


def _face_transform(path, expression, ctx):
    """Rewrite a landing-frame offset expression for the chosen face."""
    face = ctx["face"]
    dims = ctx["dims_label"]
    if face["swap"]:
        expression = _swap_section_tokens(expression, dims)
    if path == "AttachmentOffset.Base.z":
        mode = face["z_mode"]
        if mode == "negate":
            expression = f"-({expression})"
        elif mode == "complement":
            expression = f"<<{dims}>>.{face['ddim']} - ({expression})"
        elif mode == "negate_complement":
            expression = f"-(<<{dims}>>.{face['ddim']} - ({expression}))"
    return expression


def _origin_plane(body, support):
    want = support["sub"].rstrip(".") or support["target_label"]
    for f in body.Origin.OriginFeatures:
        if f.Role == want.split(".")[-1] or f.Role == want:
            return f
    # support recorded as ('Origin002', 'XY_Plane001.') — match by prefix
    role = "".join(c for c in want if not c.isdigit()).rstrip(".")
    for f in body.Origin.OriginFeatures:
        if f.Role == role:
            return f
    raise JointError(f"no origin plane matching {want!r} in {body.Label!r}")


def _rebuild_sketch(sketch, spec, negate_axes=frozenset()):
    V = App.Vector

    def pt(xy):
        flipped = list(xy)
        for axis in negate_axes:
            flipped[axis] = -flipped[axis]
        return V(flipped[0], flipped[1], 0)

    for geo in spec["geometry"]:
        if geo.kind == "line":
            g = Part.LineSegment(pt(geo.start), pt(geo.end))
        else:
            circle = Part.Circle()
            circle.Center = pt(geo.center)
            circle.Radius = geo.radius
            g = circle
        sketch.addGeometry(g, geo.construction)

    # signed position constraints on a mirrored axis negate their
    # values (and, via _negate_paths, their expressions)
    negate_types = {Constraint_DISTANCE_X for a in negate_axes if a == 0} \
        | {Constraint_DISTANCE_Y for a in negate_axes if a == 1}
    negate_paths = set()
    cons = []
    for i, con in enumerate(spec["constraints"]):
        cname = _CONSTRAINT_NAMES.get(con.type_id)
        if cname is None:
            raise JointError(
                f"{spec['label']}: unsupported constraint type {con.type_id}")
        args = _constraint_args(con)
        if con.type_id in negate_types:
            args[-1] = -args[-1]
            negate_paths.add(f"Constraints[{i}]")
            if con.name:
                negate_paths.add(f"Constraints.{con.name}")
        cons.append(Sketcher.Constraint(cname, *args))
    if cons:
        sketch.addConstraint(cons)
    for i, con in enumerate(spec["constraints"]):
        if con.name:
            sketch.renameConstraint(i, con.name)
    spec["_negate_paths"] = negate_paths


def _rebuild_feature(feature, spec, local):
    if "profile" in spec:
        profile = local.get(spec["profile"])
        if profile is None:
            raise JointError(
                f"{spec['label']}: profile sketch was not part of the "
                f"cloned stack")
        feature.Profile = profile
    for pname, value in spec.get("feature_props", {}).items():
        if not hasattr(feature, pname):
            continue
        if isinstance(value, bool):
            setattr(feature, pname, value)
        elif isinstance(value, int):
            # enums serialize as index; translate through the enum list
            enums = feature.getEnumerationsOfProperty(pname)
            if not enums:
                raise JointError(
                    f"{spec['label']}: {pname} index {value} but property "
                    f"is not an enumeration")
            setattr(feature, pname, enums[value])
        else:
            setattr(feature, pname, value)
    if "length_mm" in spec and hasattr(feature, "Length"):
        feature.Length = spec["length_mm"]
    if "diameter_mm" in spec and hasattr(feature, "Diameter"):
        feature.Diameter = spec["diameter_mm"]
