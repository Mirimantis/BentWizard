"""BentWizard model linter — the rev-2 workflow's §6 as executable rules.

Runs on FCStd files directly (pure Python, no FreeCAD) via the fcstd
reader. Strict rules protect the mechanism — datums placed from the face
table, joinery bound only to its own datum and joint VarSet, pairings
that resolve — and the model; advisory rules report style and drift.

What this layer cannot see is geometry: solid count, growth direction
and the parameter sweep need FreeCAD and live in ``template_check``'s
geometry half, ``apply``'s post-conditions and the audit command.

Usage:
    python -m freecad.bentwizard.linter <file.FCStd> [file2.FCStd ...]

Exit code 1 if any strict finding, else 0.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from . import facetable, naming
from .fcstd import Constraint, FcstdDocument, expression_refs

STRICT = "strict"
ADVISORY = "advisory"

DATUM_TYPE = "Part::LocalCoordinateSystem"
MAPMODE_DEACTIVATED = 0          # the static enumeration's first entry


@dataclass
class Finding:
    rule: str
    severity: str
    obj: str          # internal object name
    label: str        # user-facing label
    message: str

    def __str__(self):
        return f"[{self.rule}] {self.label} ({self.obj}): {self.message}"


# --------------------------------------------------------------------------
# Semantic model
# --------------------------------------------------------------------------

class Model:
    """Semantic view of one document, shared by all rules."""

    def __init__(self, doc: FcstdDocument):
        self.doc = doc
        self.bodies = doc.of_type("PartDesign::Body")
        self.owner = {}                      # member name -> body
        for body in self.bodies:
            group = body.prop("Group")
            for link in (group.links if group else []):
                self.owner[link.obj] = body
        self.varsets = doc.of_type("App::VarSet")

        # Every expression reference in the document, to any object.
        self.all_refs = []                   # (obj, expr, target, propname)
        for obj in doc.objects.values():
            for e in obj.expressions:
                for target, prop in expression_refs(e.expression, doc):
                    self.all_refs.append((obj, e, target, prop))
        self.refs = [r for r in self.all_refs if r[2].is_type("App::VarSet")]

        self.datums = [o for o in doc.of_type(DATUM_TYPE)
                       if o.prop(naming.PROP_FACE) is not None
                       and o.prop(naming.PROP_STATION) is not None]
        self.datum_names = {d.name for d in self.datums}
        self.components = [b for b in self.bodies
                           if b.prop(naming.PROP_COMPONENT_ROLE) is not None]
        self.component_names = {c.name for c in self.components}
        self._classify_varsets()

    # -- VarSet classification --------------------------------------------

    def _classify_varsets(self):
        self.dims_of = {}        # body name -> dims varset
        self.kind = {}           # varset name -> "dims" | "joint" | "group"
        # Structural: the base Pad's Length binding names the body's Dims.
        for body in self.bodies:
            group = body.prop("Group")
            for link in (group.links if group else []):
                feat = self.doc.objects.get(link.obj)
                if feat is None or not feat.is_type("PartDesign::Pad"):
                    continue
                for e in feat.expressions:
                    if e.path.lstrip(".") != "Length":
                        continue
                    refs = expression_refs(e.expression, self.doc)
                    # the stick pad reads '<<TDim_...>>.LengthZ'; a component's
                    # pad reads a joint parameter, which must not be mistaken
                    # for a Dims binding
                    if (len(refs) == 1 and refs[0][0].is_type("App::VarSet")
                            and refs[0][1] == "LengthZ"):
                        vs = refs[0][0]
                        self.dims_of[body.name] = vs
                        self.kind[vs.name] = "dims"
                break   # the first Pad is the base feature
        joint_names = {d.prop(naming.PROP_JOINT).value
                       for d in self.datums
                       if d.prop(naming.PROP_JOINT) is not None
                       and d.prop(naming.PROP_JOINT).value}
        # accessor VarSets, by the internal Name their joint records — a
        # label test alone misses one whose joint (or itself) was renamed
        accessor_names = {v.prop(naming.PROP_ACCESSORS).value
                          for v in self.varsets
                          if v.prop(naming.PROP_ACCESSORS) is not None
                          and v.prop(naming.PROP_ACCESSORS).value}
        for vs in self.varsets:
            if vs.name in self.kind:
                continue
            # an accessor VarSet carries the same Host*/Mate* properties as
            # a template's joint VarSet, so it is tested first
            if vs.name in accessor_names or naming.is_accessors_label(vs.label):
                self.kind[vs.name] = "accessors"
            elif (naming.is_joint_varset_label(vs.label)
                    or vs.name in joint_names
                    or any(vs.prop(s + a) is not None
                           for s in naming.SIDES for a in naming.ACCESSORS)):
                self.kind[vs.name] = "joint"
            else:
                self.kind[vs.name] = "group"

    # -- helpers ------------------------------------------------------------

    def joint_varsets(self):
        return [v for v in self.varsets if self.kind.get(v.name) == "joint"]

    def dims_varsets(self):
        return [v for v in self.varsets if self.kind.get(v.name) == "dims"]

    def timbers(self):
        return [b for b in self.bodies if b.name in self.dims_of]

    def body_dims(self, body):
        return self.dims_of.get(body.name)

    def datum_owner(self, datum):
        return self.owner.get(datum.name)

    def datum_face(self, datum):
        p = datum.prop(naming.PROP_FACE)
        return p.value if p is not None else None

    def datum_by_name(self, name):
        return self.doc.objects.get(name) if name in self.datum_names else None

    def datum_mate(self, datum):
        p = datum.prop(naming.PROP_MATE_DATUM)
        return self.datum_by_name(p.value) if p and p.value else None

    def datum_joint(self, datum):
        p = datum.prop(naming.PROP_JOINT)
        obj = self.doc.objects.get(p.value) if p and p.value else None
        return obj if obj is not None and obj.is_type("App::VarSet") else None

    def joint_datums(self, vs):
        return [d for d in self.datums if self.datum_joint(d) is vs]

    def accessors_of(self, vs):
        """Where a joint's accessors live: its accessor VarSet when it has
        one, else the joint VarSet itself (a template, or a document from
        before the split). By the recorded internal Name first, as
        `datums.accessors_varset` does; the label is only a fallback."""
        p = vs.prop(naming.PROP_ACCESSORS)
        if p is not None and p.value:
            obj = self.doc.objects.get(p.value)
            if obj is not None and self.kind.get(obj.name) == "accessors":
                return obj
        want = naming.accessors_label(vs.label)
        for obj in self.varsets:
            if obj.label == want and self.kind.get(obj.name) == "accessors":
                return obj
        return vs

    def joint_of_accessors(self, obj):
        """The joint VarSet an accessor VarSet belongs to, or None — the
        joint that records its Name, else the one its label names."""
        if self.kind.get(obj.name) != "accessors":
            return None
        for vs in self.varsets:
            p = vs.prop(naming.PROP_ACCESSORS)
            if p is not None and p.value == obj.name \
                    and self.kind.get(vs.name) == "joint":
                return vs
        if naming.is_accessors_label(obj.label):
            stem = obj.label[len(naming.ACCESSORS_PREFIX):]
            for vs in self.varsets:
                if vs.label == stem and self.kind.get(vs.name) == "joint":
                    return vs
        return None

    def accessor_datum(self, vs, side):
        """The datum a joint's <side>WidthU accessor reads, or None —
        looked up wherever that joint's accessors live."""
        for e in self.accessors_of(vs).expressions:
            if e.path.lstrip(".") == side + "WidthU":
                for target, _p in expression_refs(e.expression, self.doc):
                    if target.name in self.datum_names:
                        return target
        return None

    def mirrorings_of(self, body):
        return [m for m in self.doc.of_type("Part::Mirroring")
                if any(l.obj == body.name for l in (m.prop("Source").links
                                                   if m.prop("Source") else []))]

    def component_placement_holder(self, comp):
        """The object whose Placement carries a component to its datum:
        the component body itself, or its mirroring."""
        holders = [comp] + self.mirrorings_of(comp)
        for h in holders:
            for e in h.expressions:
                if e.path.lstrip(".") == "Placement":
                    return h
        return None

    def component_placement_ref(self, comp):
        """What the component's Placement holder reads: ('varset', vs,
        side) for the joint VarSet's Host/MatePlacement accessor, ('datum',
        d, None) for a datum read directly, or None."""
        holder = self.component_placement_holder(comp)
        if holder is None:
            return None
        for e in holder.expressions:
            if e.path.lstrip(".") == "Placement":
                for target, prop in expression_refs(e.expression, self.doc):
                    # an applied joint's components read the accessor
                    # VarSet; report the JOINT either way, so nothing
                    # downstream needs to know which shape this is
                    vs = (self.joint_of_accessors(target)
                          if self.kind.get(target.name) == "accessors"
                          else target if self.kind.get(target.name) == "joint"
                          else None)
                    if vs is not None:
                        for side in naming.SIDES:
                            if prop == naming.placement_accessor(side):
                                return ("varset", vs, side)
                    if target.name in self.datum_names:
                        return ("datum", target, None)
        return None

    def component_datum(self, comp):
        """The datum a component is placed on — through its joint
        VarSet's HostPlacement / MatePlacement accessor, or (a defect the
        'component-placement-direct' rule reports) read directly."""
        ref = self.component_placement_ref(comp)
        if ref is None:
            return None
        kind, target, side = ref
        if kind == "varset":
            return self.accessor_datum(target, side)
        return target

    def component_members(self, comp):
        """The component body and everything inside it."""
        group = comp.prop("Group")
        members = [comp]
        for link in (group.links if group else []):
            obj = self.doc.objects.get(link.obj)
            if obj is not None:
                members.append(obj)
        return members

    def joint_members(self, vs):
        """Objects belonging to a joint: everything referencing its
        VarSet, closed over profile sketches, attachment supports,
        Booleans holding a member, and mirrorings of a member. The
        VarSet itself and the datums are excluded."""
        members = {}
        for (obj, _e, target, _p) in self.refs:
            if target is vs and obj is not vs and obj.name not in self.datum_names:
                members[obj.name] = obj
        changed = True
        while changed:
            changed = False
            for obj in self.doc.objects.values():
                if obj.name in members or obj is vs or obj.name in self.datum_names:
                    continue
                hit = False
                for pname in ("Profile", "Source"):
                    p = obj.prop(pname)
                    if p and any(l.obj in members for l in p.links):
                        hit = True
                sup = obj.prop("AttachmentSupport") or obj.prop("Support")
                if obj.is_type("PartDesign::Boolean"):
                    g = obj.prop("Group")
                    if g and any(l.obj in members for l in g.links):
                        hit = True
                if hit:
                    members[obj.name] = obj
                    changed = True
            # attachment supports of members (datums excluded)
            for obj in list(members.values()):
                sup = obj.prop("AttachmentSupport") or obj.prop("Support")
                for link in (sup.links if sup else []):
                    t = self.doc.objects.get(link.obj)
                    if t is not None and t.name not in members \
                            and t.name not in self.datum_names \
                            and not t.is_type("App::Origin"):
                        own = self.owner.get(t.name)
                        if own is not None and own.name in self.component_names:
                            members[t.name] = t
                            changed = True
        return members

    def constraint_expression(self, sketch, index):
        for e in sketch.expressions:
            if e.path in (f"Constraints[{index}]", f".Constraints[{index}]"):
                return e.expression
        return None


# --------------------------------------------------------------------------
# Strict rules
# --------------------------------------------------------------------------

_TOPO_SUB = re.compile(r"(Face|Edge|Vertex)\d+")


def rule_solid_face_references(model):
    """§6 strict: no solid-face references. Sketch supports, datum
    attachments and assembly joint references point at origin planes and
    datums, never at solid topology, which renumbers on any edit."""
    findings = []
    checked = ("AttachmentSupport", "Support", "Reference1", "Reference2",
               "ExternalGeometry", "MirrorPlane")
    for obj in model.doc.objects.values():
        for pname in checked:
            p = obj.prop(pname)
            if p is None:
                continue
            for link in p.links:
                if _TOPO_SUB.search(link.sub or ""):
                    findings.append(Finding(
                        "solid-face-reference", STRICT, obj.name, obj.label,
                        f"{pname} references solid topology "
                        f"'{link.obj}.{link.sub}' — attach to origin planes "
                        f"or datums selected from the tree instead"))
    return findings


def rule_label_reserved_characters(model):
    """§3 strict: Body, VarSet and datum labels avoid the reserved
    characters — they are embedded verbatim in <<Label>> expressions."""
    findings = []
    for obj in list(model.bodies) + list(model.varsets) + list(model.datums):
        bad = naming.reserved_in_label(obj.label)
        if bad:
            findings.append(Finding(
                "label-reserved-characters", STRICT, obj.name, obj.label,
                f"label contains reserved character(s) {bad!r} — '>', "
                f"'\\', ';' and line breaks break <<Label>> expression "
                f"references; any other characters are fine"))
    return findings


def rule_lcs_child_plane_reference(model):
    """§6 strict: attach to an LCS by its sub-element, never to the LCS's
    child plane object directly — that resolves to identity placement
    and the sketch silently detaches (roadmap caveat, verified 1.1.1)."""
    child_of = {}
    for lcs in model.doc.of_type(DATUM_TYPE):
        feats = lcs.prop("OriginFeatures")
        for link in (feats.links if feats else []):
            child_of[link.obj] = lcs
    findings = []
    for obj in model.doc.objects.values():
        sup = obj.prop("AttachmentSupport") or obj.prop("Support")
        if sup is None:
            continue
        for link in sup.links:
            lcs = child_of.get(link.obj)
            if lcs is None:
                continue
            target = model.doc.objects.get(link.obj)
            findings.append(Finding(
                "lcs-child-plane-reference", STRICT, obj.name, obj.label,
                f"attaches to '{target.label if target else link.obj}' "
                f"directly, a child plane of '{lcs.label}' — reference the "
                f"LCS with the plane as a sub-element instead; a direct "
                f"child reference resolves to identity placement"))
    return findings


def rule_datum_not_attached(model):
    """§4.2 strict: datums are positioned by direct placement with
    MapMode Deactivated — never by attachment (three separate axis bugs
    came from attached-datum mapping)."""
    findings = []
    for d in model.datums:
        mode = d.prop("MapMode")
        sup = d.prop("AttachmentSupport") or d.prop("Support")
        attached = (mode is not None and mode.value not in (None, MAPMODE_DEACTIVATED)) \
            or bool(sup and sup.links)
        if attached:
            findings.append(Finding(
                "datum-not-attached", STRICT, d.name, d.label,
                "datum is positioned by attachment — datums are placed "
                "directly from the face table (MapMode Deactivated, no "
                "support); re-create it with Add Datum"))
    return findings


def rule_datum_declaration(model):
    """§4.2 strict: every datum declares a valid Face and is exactly what
    the face table writes for it — Placement.z bound to Station, x/y
    bound to the row's half-widths, accessors bound to the row's Dims
    properties, the row's rotation. Rotation and position must come from
    the same row: a mismatched pair looks plausible and cuts into air."""
    findings = []
    for d in model.datums:
        face = model.datum_face(d)
        if face not in facetable.PLACES:
            findings.append(Finding(
                "datum-declaration", STRICT, d.name, d.label,
                f"Face is {face!r}; expected one of {', '.join(facetable.PLACES)}"))
            continue
        body = model.datum_owner(d)
        dims = model.body_dims(body) if body is not None else None
        if dims is None:
            findings.append(Finding(
                "datum-declaration", STRICT, d.name, d.label,
                "datum is not inside a timber Body (no Dims VarSet drives "
                "the owning body's base pad)"))
            continue
        exprs = {e.path.lstrip("."): e.expression for e in d.expressions}
        problems = []
        if exprs.get("Placement.Base.z") != naming.PROP_STATION:
            problems.append("Placement.z is not bound to Station")
        want = facetable.position_expressions(face, dims.label)
        for path, expr in want.items():
            if exprs.get(path.lstrip(".")) != expr:
                problems.append(f"{path.lstrip('.')} should be '{expr}'")
        for path in ("Placement.Base.x", "Placement.Base.y"):
            if path in exprs and "." + path not in want:
                problems.append(f"{path} is bound but the "
                                f"{facetable.display(face)} row leaves it at 0")
        for acc, expr in facetable.accessor_expressions(face, dims.label).items():
            if exprs.get(acc) != expr:
                problems.append(f"{acc} should be '{expr}'")
        pl = d.prop("Placement")
        row = facetable.FACE_TABLE[face]
        if pl is not None and pl.placement is not None \
                and not facetable.same_rotation(pl.placement.q, row.quaternion):
            problems.append(f"rotation is not the {facetable.display(face)} "
                            f"row's (quaternion {row.quaternion})")
        if problems:
            findings.append(Finding(
                "datum-declaration", STRICT, d.name, d.label,
                f"datum on {facetable.display(face)} does not match its "
                f"face-table row: " + "; ".join(problems)))
    return findings


def rule_datum_link_scope(model):
    """§4.2 strict: pairing is recorded as strings. A link property on a
    datum cannot reach the mate (another Body) without a scope violation
    on the next recompute, and links are never needed here."""
    findings = []
    for d in model.datums:
        bad = [p.name for p in d.properties.values()
               if p.group is not None
               and p.type_id.startswith(("App::PropertyLink", "App::PropertyXLink"))]
        if bad:
            findings.append(Finding(
                "datum-link-scope", STRICT, d.name, d.label,
                f"link property(ies) {', '.join(bad)} on a datum — a link "
                f"cannot cross a Body boundary; pairing uses the MateDatum "
                f"and Joint strings, mate dimensions the joint VarSet's "
                f"accessors"))
    return findings


def rule_datum_pairing(model):
    """§4.2 strict: a recorded pairing resolves both ways — the mate
    exists, points back, both name the same joint VarSet, and that
    VarSet's Host*/Mate* accessors read exactly these two datums."""
    findings = []
    for d in model.datums:
        mate_p = d.prop(naming.PROP_MATE_DATUM)
        joint_p = d.prop(naming.PROP_JOINT)
        mate_name = mate_p.value if mate_p else ""
        joint_name = joint_p.value if joint_p else ""
        if not mate_name and not joint_name:
            continue
        problems = []
        mate = model.datum_by_name(mate_name) if mate_name else None
        if mate is None:
            problems.append(f"MateDatum {mate_name!r} is not a datum in this document")
        else:
            back = mate.prop(naming.PROP_MATE_DATUM)
            if not back or back.value != d.name:
                problems.append(f"mate '{mate.label}' does not point back")
            if model.datum_owner(mate) is model.datum_owner(d):
                problems.append("mate is on the same timber")
        vs = model.datum_joint(d)
        if vs is None:
            problems.append(f"Joint {joint_name!r} is not a VarSet in this document")
        else:
            if mate is not None:
                mj = mate.prop(naming.PROP_JOINT)
                if not mj or mj.value != vs.name:
                    problems.append(f"mate '{mate.label}' names a different joint")
            host = model.accessor_datum(vs, "Host")
            mate_acc = model.accessor_datum(vs, "Mate")
            if {o.name for o in (host, mate_acc) if o is not None} \
                    != {o.name for o in (d, mate) if o is not None}:
                problems.append(f"'{vs.label}' Host*/Mate* accessors do not "
                                f"read this pair of datums")
            acc_vs = model.accessors_of(vs)
            missing = [s + a for s in naming.SIDES for a in naming.ALL_ACCESSORS
                       if acc_vs.prop(s + a) is None]
            if missing:
                problems.append(f"'{acc_vs.label}' lacks accessor(s) "
                                f"{', '.join(missing)}")
        if problems:
            findings.append(Finding(
                "datum-pairing", STRICT, d.name, d.label,
                "pairing does not resolve: " + "; ".join(problems)))
    return findings


def rule_component_declaration(model):
    """§4.3 strict: a component body declares a valid ComponentRole and a
    ComponentOrder, and its Placement (or its mirroring's) is bound to a
    datum — that binding is what seats it and what makes it a joint's."""
    findings = []
    for comp in model.components:
        problems = []
        role = comp.prop(naming.PROP_COMPONENT_ROLE).value
        if role not in naming.COMPONENT_ROLES:
            problems.append(f"ComponentRole {role!r}; expected "
                            f"{' or '.join(naming.COMPONENT_ROLES)}")
        order = comp.prop(naming.PROP_COMPONENT_ORDER)
        if order is None or not isinstance(order.value, int):
            problems.append("no integer ComponentOrder (cutters before adders)")
        if model.component_datum(comp) is None:
            problems.append("Placement is not bound to a datum through the "
                            "joint VarSet ('<<J-...>>.HostPlacement' or "
                            "'.MatePlacement' on the body, or on its mirroring)")
        if problems:
            findings.append(Finding(
                "component-declaration", STRICT, comp.name, comp.label,
                "; ".join(problems)))
    return findings


def rule_component_placement_direct(model):
    """Strict: a component Body must not read a datum's Placement
    directly. FreeCAD files a datum's child axes and planes under the
    FIRST GeoFeatureGroup in the datum's in-list without checking
    membership; a component Body that links the datum can come before
    the owning timber, and the datum then fails its scope check on the
    next recompute ('Link(s) to object(s) ... go out of the allowed
    scope'). Bind to the joint VarSet's HostPlacement / MatePlacement
    instead. Advisory on a mirroring (not a GeoFeatureGroup, harmless),
    for uniformity."""
    findings = []
    for comp in model.components:
        ref = model.component_placement_ref(comp)
        if ref is None or ref[0] != "datum":
            continue
        holder = model.component_placement_holder(comp)
        direct_body = holder is comp
        findings.append(Finding(
            "component-placement-direct", STRICT if direct_body else ADVISORY,
            holder.name, holder.label,
            f"Placement reads datum '{ref[1].label}' directly; bind it to the "
            f"joint VarSet's HostPlacement / MatePlacement accessor instead"
            + (" — a Body reading a datum makes FreeCAD file the datum's "
               "axes under that Body, and the datum fails its scope check "
               "on recompute" if direct_body else "")))
    return findings


def rule_component_reference_scope(model):
    """§4.3 strict: joinery references only the datum it is placed on,
    its joint VarSet, and that joint's accessor VarSet — host data
    through the datum's own accessors, mate data through the Mate*
    accessors, never a timber's Dims, another datum, or another timber's
    objects. Referencing the mate's datum directly gives the right
    numbers today and the wrong ones after a re-pair, and makes the
    template non-portable."""
    findings = []
    for comp in model.components:
        datum = model.component_datum(comp)
        vs = model.datum_joint(datum) if datum is not None else None
        # the accessors are the joint's own object; a component reading
        # them is reading its joint, one indirection out
        acc = model.accessors_of(vs) if vs is not None else None
        allowed = {o.name for o in (datum, vs, acc) if o is not None}
        members = model.component_members(comp) + model.mirrorings_of(comp)
        own = {m.name for m in members}
        for obj in members:
            for e in obj.expressions:
                for target, prop in expression_refs(e.expression, model.doc):
                    if target.name in own or target.name in allowed:
                        continue
                    if target.is_type("App::Origin", "App::Plane", "App::Line"):
                        continue
                    if vs is None and model.kind.get(target.name) in (
                            "joint", "accessors"):
                        continue        # unpaired template geometry: the joint VarSet is fine
                    what = ("its own timber's Dims"
                            if model.kind.get(target.name) == "dims" else
                            "another datum" if target.name in model.datum_names else
                            f"'{target.label}'")
                    findings.append(Finding(
                        "component-reference-scope", STRICT, obj.name, obj.label,
                        f"'{e.path}' references {what} ('{target.label}."
                        f"{prop}') — a component reads only the datum it "
                        f"is placed on ('{datum.label if datum else '?'}') "
                        f"and its joint VarSet"))
    return findings


def rule_boolean_operand(model):
    """§4.3 strict: a PartDesign::Boolean applies exactly one operand,
    and never an App::Part container — a container operand fails in the
    GUI with 'Tool shape is null' while passing every headless check."""
    findings = []
    for bo in model.doc.of_type("PartDesign::Boolean"):
        g = bo.prop("Group")
        links = g.links if g else []
        if len(links) != 1:
            findings.append(Finding(
                "boolean-operand", STRICT, bo.name, bo.label,
                f"Boolean holds {len(links)} operand(s); one component per "
                f"Boolean"))
            continue
        target = model.doc.objects.get(links[0].obj)
        if target is not None and target.is_type("App::Part"):
            findings.append(Finding(
                "boolean-operand", STRICT, bo.name, bo.label,
                f"operand '{target.label}' is an App::Part container — "
                f"Booleans take a Body (or a Part::Mirroring of one)"))
    return findings


# --------------------------------------------------------------------------
# Advisory rules
# --------------------------------------------------------------------------

_KIND_OWNER = re.compile(r"^(TDim|Group|Project|Order)_.+$")


def rule_naming_conventions(model):
    """§3 advisory: joint VarSets are J-<Kind>-<serial>; a Dims VarSet is
    'TDim_<its timber>'; timber bodies end in a separator + serial; datum
    labels start with 'D_'; component labels are <Descriptive>.<Kind>.
    <serial> carrying their joint's kind and serial."""
    findings = []
    for vs in model.joint_varsets():
        if not naming.is_joint_varset_label(vs.label):
            findings.append(Finding(
                "naming-convention", ADVISORY, vs.name, vs.label,
                "joint VarSet label should read 'J-<Kind>-<serial>' "
                "('J-HousedMT-001'; a template's own is '...-000')"))
    for body in model.timbers():
        if naming.split_serial(body.label)[1] is None:
            findings.append(Finding(
                "naming-convention", ADVISORY, body.name, body.label,
                "body label has no trailing serial (separator + digits, e.g. "
                "'T-Post-003' or 'T-Post.Balcony.001') — copy tools bump "
                "the serial and will append one"))
        dims = model.body_dims(body)
        if dims is not None and naming.dims_owner(dims.label) != body.label:
            findings.append(Finding(
                "naming-convention", ADVISORY, dims.name, dims.label,
                f"Dims VarSet label should be '{naming.dims_label(body.label)}' "
                f"to match its timber — tools resolve the binding "
                f"structurally, but drifted labels invite mistakes"))
    for d in model.datums:
        if not d.label.startswith("D_"):
            findings.append(Finding(
                "naming-convention", ADVISORY, d.name, d.label,
                "datum label should start with 'D_' "
                "('D_T-Post-001_YPos_001', 'D_T-Post-001_A')"))
    for comp in model.components:
        parsed = naming.parse_component_label(comp.label)
        datum = model.component_datum(comp)
        vs = model.datum_joint(datum) if datum is not None else None
        want = naming.parse_joint_label(vs.label) if vs is not None else None
        if parsed is None:
            findings.append(Finding(
                "naming-convention", ADVISORY, comp.name, comp.label,
                "component label should read '<Descriptive>.<Kind>.<serial>' "
                "('Mortise.HousedMT.001')"))
        elif want is not None and (parsed[1], parsed[2]) != want:
            findings.append(Finding(
                "naming-convention", ADVISORY, comp.name, comp.label,
                f"component label carries '{parsed[1]}.{parsed[2]}' but its "
                f"joint is '{vs.label}' — expected "
                f"'{naming.component_label(parsed[0], *want)}'"))
    return findings


def rule_property_naming(model):
    """§3 advisory: user-defined properties on VarSets and datums are
    UpperCamelCase with no separators (FreeCAD's own convention; the
    Property View inserts display spaces itself)."""
    findings = []
    for obj in list(model.varsets) + list(model.datums):
        bad = sorted(p.name for p in obj.properties.values()
                     if p.group is not None and not naming.is_camel_case(p.name))
        if bad:
            findings.append(Finding(
                "property-naming", ADVISORY, obj.name, obj.label,
                f"property name(s) not UpperCamelCase: {', '.join(bad)} "
                f"('TenonLength', not 'Tenon_Length')"))
    return findings


def rule_duplicate_labels(model):
    """§3 advisory: two expression-targetable objects share a Label —
    '<<Label>>' resolves to only one of them."""
    findings = []
    seen = {}
    for obj in list(model.varsets) + list(model.datums) + list(model.components):
        seen.setdefault(obj.label, []).append(obj)
    for label, objs in seen.items():
        names = sorted({o.name for o in objs})
        if len(names) > 1:
            findings.append(Finding(
                "duplicate-label", ADVISORY, names[1], label,
                f"{len(names)} objects share this label ({', '.join(names)}) "
                f"— '<<{label}>>' expression references resolve to only one"))
    return findings


def rule_symmetry_constraint(model):
    """§6 advisory: centreline + half-width in place of Symmetric
    (finding #13)."""
    findings = []
    for sketch in model.doc.of_type("Sketcher::SketchObject"):
        cons = sketch.prop("Constraints")
        if cons is None:
            continue
        count = sum(1 for c in cons.constraints if c.type_id == Constraint.SYMMETRIC)
        if count:
            findings.append(Finding(
                "symmetry-constraint", ADVISORY, sketch.name, sketch.label,
                f"uses {count} Symmetric constraint(s); replace with "
                f"half-width constraints measured from the origin"))
    return findings


def rule_group_binding_deviation(model):
    """§4.7 advisory: sibling joint VarSets bind a same-named property to
    a group VarSet and this one holds a literal — deliberate override?"""
    findings = []
    bound = {}
    for (obj, e, target, _prop) in model.refs:
        if obj.is_type("App::VarSet") and model.kind.get(target.name) == "group":
            bound.setdefault(e.path.lstrip("."), set()).add(obj.name)
    for propname, binders in bound.items():
        for vs in model.joint_varsets():
            if vs.name in binders or vs.prop(propname) is None:
                continue
            findings.append(Finding(
                "group-binding-deviation", ADVISORY, vs.name, vs.label,
                f"property '{propname}' is a literal here but bound to a "
                f"group VarSet on sibling(s) {', '.join(sorted(binders))} — "
                f"deliberate override?"))
    return findings


def rule_stale_attachment_offset(model):
    """§5 advisory: nonzero AttachmentOffset translations no expression
    drives hide in unexamined components (finding #10)."""
    findings = []
    for obj in model.doc.objects.values():
        p = obj.prop("AttachmentOffset")
        if p is None or p.placement is None:
            continue
        pl = p.placement
        driven = {e.path.split(".")[-1].lower()
                  for e in obj.expressions if "AttachmentOffset" in e.path}
        stray = [f"Base.{comp}={val:.3f}"
                 for comp, val in (("x", pl.px), ("y", pl.py), ("z", pl.pz))
                 if abs(val) > 1e-9 and comp not in driven]
        if stray:
            findings.append(Finding(
                "stale-attachment-offset", ADVISORY, obj.name, obj.label,
                f"attachment offset has expression-free nonzero "
                f"translation(s): {', '.join(stray)} — verify they are "
                f"intended, not stale"))
    return findings


_AUTO_LABEL = re.compile(
    r"^(Sketch|Pad|Pocket|Hole|Body|VarSet|DatumPlane|DatumLine|DatumPoint|"
    r"Local_CS|LocalCoordinateSystem|Boolean|Mirroring|Revolution|Groove|"
    r"Chamfer|Fillet)\d*$")
_NAMEABLE = ("PartDesign::", "Sketcher::", "Part::Datum", "Part::Local",
             "Part::Mirroring", "App::VarSet")


def rule_auto_labels(model):
    """§3 advisory: a label identical to FreeCAD's auto-generated name
    means the object was never named."""
    findings = []
    for obj in model.doc.objects.values():
        if not obj.is_type(*_NAMEABLE):
            continue
        if _AUTO_LABEL.match(obj.label):
            findings.append(Finding(
                "auto-generated-label", ADVISORY, obj.name, obj.label,
                "label is FreeCAD's auto-generated name — rename it "
                "('Mortise.HousedMT.001', 'D_T-Post-001_YPos_001')"))
    return findings


def rule_duplicate_tooltips(model):
    """§3 advisory: identical tooltip text on two properties of one
    VarSet is almost always a copy-paste error."""
    findings = []
    for vs in model.varsets:
        by_text = {}
        for p in vs.properties.values():
            if p.group is None:
                continue
            text = (p.doc or "").strip()
            if text:
                by_text.setdefault(text, []).append(p.name)
        for text, names in by_text.items():
            if len(names) > 1:
                findings.append(Finding(
                    "duplicate-tooltip", ADVISORY, vs.name, vs.label,
                    f"properties {', '.join(sorted(names))} share identical "
                    f"tooltip text — copy-paste error?"))
    return findings


def rule_missing_tooltips(model):
    """§3 advisory: tooltips are mandatory on every template-defined
    property (which face/end it measures from, in framing terms)."""
    findings = []
    for vs in model.varsets:
        missing = sorted(p.name for p in vs.properties.values()
                         if p.group is not None and not (p.doc or "").strip())
        if missing:
            findings.append(Finding(
                "missing-tooltip", ADVISORY, vs.name, vs.label,
                f"{len(missing)} property(ies) missing tooltips: "
                f"{', '.join(missing)}"))
    return findings


def rule_component_order(model):
    """§4.4 advisory: within one timber, a joint's cutters apply before
    its adders (the two orders do not commute — round 3 T5: applied
    second, a shoulder cutter saws the tenon off)."""
    findings = []
    by_joint = {}
    for comp in model.components:
        datum = model.component_datum(comp)
        vs = model.datum_joint(datum) if datum is not None else None
        if datum is None:
            continue
        key = (vs.name if vs else "", model.datum_owner(datum).name
               if model.datum_owner(datum) else "")
        by_joint.setdefault(key, []).append(comp)
    for comps in by_joint.values():
        ordered = sorted(comps, key=lambda c: (c.prop(naming.PROP_COMPONENT_ORDER).value
                                               if c.prop(naming.PROP_COMPONENT_ORDER)
                                               and isinstance(c.prop(naming.PROP_COMPONENT_ORDER).value, int)
                                               else 0))
        seen_adder = False
        for c in ordered:
            role = c.prop(naming.PROP_COMPONENT_ROLE).value
            if role == naming.COMPONENT_ADDER:
                seen_adder = True
            elif role == naming.COMPONENT_CUTTER and seen_adder:
                findings.append(Finding(
                    "component-order", ADVISORY, c.name, c.label,
                    "cutter ordered after an adder on the same timber — "
                    "unless the cutter deliberately trims the adder, give "
                    "cutters the lower ComponentOrder"))
    return findings


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

STRICT_RULES = [
    rule_solid_face_references,
    rule_label_reserved_characters,
    rule_lcs_child_plane_reference,
    rule_datum_not_attached,
    rule_datum_declaration,
    rule_datum_link_scope,
    rule_datum_pairing,
    rule_component_declaration,
    rule_component_placement_direct,
    rule_component_reference_scope,
    rule_boolean_operand,
]

ADVISORY_RULES = [
    rule_naming_conventions,
    rule_property_naming,
    rule_duplicate_labels,
    rule_symmetry_constraint,
    rule_group_binding_deviation,
    rule_stale_attachment_offset,
    rule_auto_labels,
    rule_duplicate_tooltips,
    rule_missing_tooltips,
    rule_component_order,
]


def lint(path):
    """Lint one FCStd file; returns a list of Findings."""
    return lint_document(FcstdDocument.from_file(path))


def lint_document(doc):
    model = Model(doc)
    findings = []
    for rule in STRICT_RULES + ADVISORY_RULES:
        findings.extend(rule(model))
    return findings


def format_report(path, findings):
    lines = [f"== {path} =="]
    for severity, title in ((STRICT, "STRICT"), (ADVISORY, "ADVISORY")):
        group = [f for f in findings if f.severity == severity]
        lines.append(f"{title}: {len(group)} finding(s)")
        for f in group:
            lines.append(f"  {f}")
    return "\n".join(lines)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    exit_code = 0
    for path in argv:
        findings = lint(path)
        print(format_report(path, findings))
        if any(f.severity == STRICT for f in findings):
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
