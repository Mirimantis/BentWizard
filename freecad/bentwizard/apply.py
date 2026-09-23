"""Apply and remove a timber joint — the rev-2 mechanism.

Applying a joint is a copy, not a rebuild:

1. **Copy.** The template's joint VarSet and each component Body — the
   body with its own features and Origin, and nothing else — are copied
   into the document with ``copyObject(objs, False)``. FreeCAD remaps
   every link and expression *among the copied set* (the VarSet
   included), while expressions naming the template's datums keep
   naming them by label, which is exactly the handle we need.
2. **Pair.** The two target datums are paired under the copied VarSet,
   which binds its ``Host*``/``Mate*`` accessors through them.
3. **Re-point.** Every ``<<template datum>>`` token in the copied set
   becomes the target datum — one substitution over the component's
   ``Placement`` and its accessor references (Part H1b).
4. **Mirror when parity differs.** A component keeps its timber-local
   x/y offsets at either end and on opposite faces (Part H2/H3): when
   the target datum's parity is not the authoring datum's, a
   ``Part::Mirroring`` across the component's local X carries the
   Placement instead of the body. Only for a template that is handed
   (or predates the ``Handed`` flag): one declared ``Handed = False``
   looks the same from either side and is never mirrored — a mirroring
   links a component body outside the timber, which FreeCAD's GUI
   reports as an out-of-scope link on every recompute (2026-09-19).
5. **Boolean**, in declared order, ``Cut`` for a cutter and ``Fuse`` for
   an adder, into the timber that owns the datum. The Boolean seats its
   operand in the timber Body's LOCAL frame (round 3), which is why the
   binding is the datum's local Placement. FreeCAD 26.3 resolves the
   operand globally instead, so every Boolean created here is pinned
   with ``UseLegacyBodyPlacement`` — see
   ``component.set_legacy_placement``.
6. **Assert one solid** after every Boolean. Three different errors
   produced exactly the expected volume with wrong geometry; only the
   solid count told a joint from a severed timber.

Removing a joint deletes the Booleans, mirrorings, component bodies,
handle, seat and VarSet, and unpairs the datums — which stay, because
they belong to the timber. The timber returns to its bare
stick; nothing about it moved.
"""

from __future__ import annotations

import re
from collections import namedtuple

import FreeCAD as App

from . import (component, datums, facetable, measure, naming,
               template_library)
from .datums import DatumError
from .template import JointError, TemplateSpec
from .timber import dim_input, dims_varset

Applied = namedtuple("Applied", "varset components booleans warnings")

_COPY_FAILED = "copyObject returned an unexpected set"


# --------------------------------------------------------------------------
# Structural queries
# --------------------------------------------------------------------------

def joint_datums(varset):
    """The datums paired under a joint VarSet, host first."""
    return datums.datums_of_joint(varset)


def joint_bodies(varset):
    """The timbers a joint connects (host first)."""
    return [datums.owner(d) for d in joint_datums(varset)]


def joint_members(varset):
    """Everything a joint is made of, apart from its VarSet and datums:
    its component bodies (with their features and Origins), their
    mirrorings, and the Booleans that apply them.

    Structural, and anchored on COMPONENT bodies — a body declaring a
    ComponentRole whose own features carry the ``<<J-Kind-serial>>``
    token. Never a timber: a timber holds the Boolean that references
    the joint, and widening the closure through it once deleted a
    timber's section, pad and datums along with the joint.
    """
    doc = varset.Document
    token = f"<<{varset.Label}>>"

    def mentions(obj):
        return any(token in e for _p, e in obj.ExpressionEngine)

    comps = [b for b in doc.Objects
             if b.TypeId == "PartDesign::Body"
             and hasattr(b, naming.PROP_COMPONENT_ROLE)
             and (mentions(b) or any(mentions(f) for f in b.Group))]
    members = {}
    for body in comps:
        members[body.Name] = body
        for f in body.Group:
            members[f.Name] = f
        origin = body.Origin
        if origin is not None:
            members[origin.Name] = origin
            for f in origin.OriginFeatures:
                members[f.Name] = f
    comp_names = {b.Name for b in comps}
    holders = set(comp_names)
    for obj in doc.Objects:
        if obj.TypeId == "Part::Mirroring":
            src = getattr(obj, "Source", None)
            if src is not None and src.Name in comp_names:
                members[obj.Name] = obj
                holders.add(obj.Name)
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Boolean"                 and any(o.Name in holders for o in obj.Group):
            members[obj.Name] = obj
    return list(members.values())


def joint_components(varset):
    """The joint's component bodies (cutters and adders), in ComponentOrder."""
    comps = [o for o in joint_members(varset)
             if o.TypeId == "PartDesign::Body"
             and hasattr(o, naming.PROP_COMPONENT_ROLE)]
    return sorted(comps, key=lambda c: (getattr(c, naming.PROP_COMPONENT_ORDER, 0),
                                        c.Label))


def joint_varsets(doc):
    return [o for o in doc.Objects
            if o.TypeId == "App::VarSet" and naming.is_joint_varset_label(o.Label)]


def bent_joints(doc, bodies):
    """(inside, outside): joints whose two timbers are both in `bodies`,
    and joints touching the set with one timber outside it."""
    names = {b.Name for b in bodies}
    inside, outside = [], []
    for vs in joint_varsets(doc):
        owners = {b.Name for b in joint_bodies(vs) if b is not None}
        if not owners:
            continue
        if owners <= names:
            inside.append(vs)
        elif owners & names:
            outside.append(vs)
    return inside, outside


def next_serial(doc, kind):
    """The next free serial for J-<kind>-NNN in `doc`."""
    label = naming.next_serial([o.Label for o in doc.Objects],
                               naming.JOINT_PREFIX + kind, sep="-")
    return naming.split_serial(label)[1]


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------

def _resolve_target(doc, role, target):
    """(body, datum, created) for one role's target — an existing datum
    or a new one placed for the occasion."""
    body = target.get("body")
    if body is None or dims_varset(body) is None:
        raise JointError(f"role {role!r}: pick a timber")
    datum = target.get("datum")
    if datum is not None:
        if not datums.is_datum(datum):
            raise JointError(f"role {role!r}: {datum.Label!r} is not a datum")
        if datums.owner(datum) is not body:
            raise JointError(f"role {role!r}: datum {datum.Label!r} is not on "
                             f"{body.Label!r}")
        if datums.is_paired(datum):
            raise JointError(f"role {role!r}: datum {datum.Label!r} is already "
                             f"paired under "
                             f"{getattr(datum, naming.PROP_JOINT, '')!r}; remove "
                             f"that timber joint first")
        # A free datum can be moved as it is reused: the dialog passes a
        # station only when the framer changed it. Safe because it is
        # free — nothing else reads an unpaired datum.
        if target.get("station") is not None:
            try:
                datums.set_station(datum, target["station"])
            except DatumError as err:
                raise JointError(f"role {role!r}: {err}")
        return body, datum, False
    face = target.get("face")
    if face is None:
        raise JointError(f"role {role!r}: choose an existing datum or a face")
    if facetable.is_end(face):
        datum = datums.end_datum(body, face)
        if datum is not None:
            if datums.is_paired(datum):
                raise JointError(f"role {role!r}: {body.Label}'s "
                                 f"{facetable.display(face)} datum is already "
                                 f"paired; remove that timber joint first")
            return body, datum, False
    datum = datums.add_datum(body, face, target.get("station"))
    return body, datum, True


def _set_value(varset, name, value):
    if isinstance(value, str) and value.lstrip().startswith("="):
        _q, expr = dim_input(value)
        try:
            varset.evalExpression(expr)
        except Exception as err:
            raise JointError(f"{name}: bad expression {expr!r} ({err})")
        varset.setExpression(name, expr)
        return
    varset.setExpression(name, None)
    type_id = varset.getTypeIdOfProperty(name)
    if type_id == "App::PropertyInteger":
        setattr(varset, name, int(value))
    elif type_id == "App::PropertyBool":
        setattr(varset, name, bool(value))
    elif type_id == "App::PropertyString":
        setattr(varset, name, str(value))
    elif type_id in ("App::PropertyLength", "App::PropertyDistance",
                     "App::PropertyAngle", "App::PropertyQuantity"):
        setattr(varset, name, App.Units.Quantity(value)
                if isinstance(value, str) else value)
    else:
        setattr(varset, name, value)


def _substitute(objs, old_label, new_label):
    """Re-point every reference to `old_label` in the expressions of
    `objs` at `new_label`. A cross-document copy rewrites a
    ``<<Label>>`` it cannot resolve into the bare ``Label.Prop`` form,
    so both spellings are matched."""
    pattern = re.compile(r"(<<" + re.escape(old_label) + r">>|(?<![\w.])"
                         + re.escape(old_label) + r"(?=\.))")
    for obj in objs:
        for path, expr in list(obj.ExpressionEngine):
            new = pattern.sub(f"<<{new_label}>>", expr)
            if new != expr:
                obj.setExpression(path, new)


def _redirect_accessors(objs, joint_label, holder_label):
    """Move accessor references from the joint VarSet onto its accessor
    VarSet, leaving parameter references alone.

    A template holds its accessors on its own joint VarSet, so a copied
    component asks `<<J-Kind-001>>.MateWidthU` for them and
    `<<J-Kind-001>>.TenonLength` for a parameter. Apply expands the
    accessors onto `Accessors_J-Kind-001`; only the first kind moves.
    Both the ``<<Label>>`` and the bare ``Label.Prop`` spellings are
    matched, as in `_substitute`."""
    head = (r"(?:<<" + re.escape(joint_label) + r">>|(?<![\w.])"
            + re.escape(joint_label) + r")")
    accessors = [side + acc for side in naming.SIDES
                 for acc in naming.ALL_ACCESSORS]
    # longest first: MateWidthU must not be matched as a prefix of a
    # longer accessor name should one ever be added
    pattern = re.compile(head + r"\.(" + "|".join(
        sorted((re.escape(a) for a in accessors), key=len, reverse=True))
        + r")(?![\w])")
    for obj in objs:
        for path, expr in list(obj.ExpressionEngine):
            new = pattern.sub(rf"<<{holder_label}>>.\1", expr)
            if new != expr:
                obj.setExpression(path, new)


def _copy_set(body):
    """A component body with its own features and Origin — the set that
    copies cleanly with `with_dependencies=False` (Part H finding 10)."""
    return [body] + list(body.Group) + [body.Origin] + list(body.Origin.OriginFeatures)


def apply_joint(doc, spec, serial, targets, values=None, position_tag=""):
    """Apply template `spec` as joint J-<Kind>-<serial>.

    `targets[role]` is ``{"body": Body, "datum": LCS}`` for an existing
    unpaired datum, or ``{"body": Body, "face": <facetable place>,
    "station": value-or-'=expr'}`` to place one. `values` maps parameter
    names to literals or ``'=<expression>'`` strings. Returns an
    ``Applied`` (varset, component bodies, Booleans, warnings). Raises
    JointError/DatumError with the document possibly half-changed — the
    caller owns the transaction and aborts it on failure.
    """
    if not isinstance(spec, TemplateSpec):
        spec = TemplateSpec(spec)
    # a document whose joinery predates the operand flag opens on 26.3
    # with its components detached; bring it up to the contract first,
    # so the joint being added is not the only sound one in the file
    component.ensure_legacy_placement(doc)
    serial = str(serial).strip()
    if not serial.isdigit():
        raise JointError(f"serial must be digits, got {serial!r}")
    label = naming.joint_label(spec.kind, serial)
    if doc.getObjectsByLabel(label):
        raise JointError(f"{label} already exists in this document")
    missing = [r for r in spec.roles if r not in targets]
    if missing:
        raise JointError(f"no target for role(s) {', '.join(missing)}")

    resolved = {}
    for role in spec.roles:
        resolved[role] = _resolve_target(doc, role, targets[role])
    bodies = [resolved[r][0] for r in spec.roles]
    if bodies[0] is bodies[1]:
        raise JointError("a timber joint connects two different timbers")
    host_datum = resolved[spec.host_role][1]
    mate_datum = resolved[spec.mate_role][1]

    # --- copy the VarSet and the components out of the template -------
    with template_library.open_hidden(spec.path) as tdoc:
        t_varset = tdoc.getObjectsByLabel(spec.varset_label)
        if not t_varset:
            raise JointError(f"{spec.stem}: joint VarSet "
                             f"{spec.varset_label!r} not found")
        t_varset = t_varset[0]
        objs = [t_varset]
        comp_slices = []
        for c in spec.components:
            t_body = tdoc.getObject(c["name"])
            if t_body is None:
                raise JointError(f"{spec.stem}: component {c['label']!r} not found")
            block = _copy_set(t_body)
            comp_slices.append((c, len(objs), len(block)))
            objs.extend(block)
        copies = doc.copyObject(objs, False)
    if len(copies) != len(objs) or copies[0].TypeId != "App::VarSet":
        raise JointError(_COPY_FAILED)
    varset = copies[0]
    components = []
    for c, start, n in comp_slices:
        body = copies[start]
        if body.TypeId != "PartDesign::Body":
            raise JointError(_COPY_FAILED)
        components.append((c, body, copies[start:start + n]))

    # --- relabel and parameterize --------------------------------------
    varset.Label = label
    for c, body, _block in components:
        body.Label = naming.retag_component_label(c["label"], spec.kind, serial)
    # the template's accessor bindings name template datums; pair() rewrites them
    for side in naming.SIDES:
        for acc in naming.ALL_ACCESSORS:
            if hasattr(varset, side + acc):
                varset.setExpression(side + acc, None)

    for name, value in (values or {}).items():
        if not hasattr(varset, name):
            raise JointError(f"{label} has no parameter {name!r}")
        param = spec.parameter(name)
        if param is not None and param.get("read_only"):
            # ReadOnly greys the property editor but does not stop a
            # Python write, so it is honoured here or nowhere
            raise JointError(f"{label}: {name} is fixed by the template "
                             f"{spec.stem} and cannot be set")
        _set_value(varset, name, value)
    if not hasattr(varset, naming.PROP_TEMPLATE_SOURCE):
        varset.addProperty("App::PropertyString", naming.PROP_TEMPLATE_SOURCE,
                           naming.TEMPLATE_META_GROUP,
                           "The library template this joint was applied from.")
    setattr(varset, naming.PROP_TEMPLATE_SOURCE, spec.stem)
    if not hasattr(varset, naming.PROP_POSITION_TAG):
        varset.addProperty("App::PropertyString", naming.PROP_POSITION_TAG, "Tag",
                           "Where this joint sits in the structure — display-"
                           "only, for drawings and schedules.")
    setattr(varset, naming.PROP_POSITION_TAG, (position_tag or "").strip())

    # --- pair ---------------------------------------------------------------
    # expands the accessors onto Accessors_<joint>; the copied components
    # still name the joint VarSet for them, so redirect those references
    datums.pair(host_datum, mate_datum, varset)
    holder = datums.accessors_varset(varset)
    if holder is not varset:
        for _c, _body, block in components:
            _redirect_accessors(block, varset.Label, holder.Label)
        # the copy inherited the TEMPLATE's accessor properties; drop them
        # now that nothing reads them there, so the joint VarSet a framer
        # opens holds only parameters. After the redirect, never before:
        # removing a property the components still name breaks them.
        for side in naming.SIDES:
            for acc in naming.ALL_ACCESSORS:
                name = side + acc
                if hasattr(varset, name):
                    varset.removeProperty(name)

    # --- re-point and place each component ------------------------------
    target_datum = {spec.host_datum_label: host_datum,
                    spec.mate_datum_label: mate_datum}
    placed = []
    for c, body, block in components:
        t_datum_label = c["datum"]
        target = target_datum[t_datum_label]
        _substitute(block, t_datum_label, target.Label)
        # a template authored with a mirroring in it is unusual; the
        # authoring parity is the datum's the component was bound to
        authored_parity = facetable.parity(spec.datum_face[t_datum_label])
        mirror = spec.mirrors and authored_parity != datums.parity(target)
        holder = body
        if mirror:
            body.setExpression("Placement", None)
            body.Placement = App.Placement()
            m = doc.addObject("Part::Mirroring", "Mirror")
            m.Label = naming.mirror_label(body.Label)
            m.Source = body
            m.Base = App.Vector(0, 0, 0)
            m.Normal = App.Vector(1, 0, 0)
            m.setExpression("Placement", datums.placement_binding(varset, target))
            holder = m
        placed.append((c, body, holder, target))
    doc.recompute()
    for c, body, holder, _t in placed:
        if not measure.is_whole(body):
            raise JointError(f"{body.Label}: the component is not one valid "
                             f"solid at these parameters "
                             f"({measure.solid_count(body)} solids)")

    # --- booleans, in declared order ----------------------------------------
    warnings = []
    booleans = []
    for c, body, holder, target in placed:
        timber = datums.owner(target)
        before = timber.Shape.Volume
        op = naming.BOOLEAN_OP[c["role"]]
        bo = timber.newObject("PartDesign::Boolean", "Boolean")
        bo.Label = naming.boolean_label(c["role"], body.Label)
        bo.Group = [holder]          # direct assignment: addObjects would
        bo.Type = op                 # drag a mirroring's Source in too
        bo.Refine = True
        component.set_legacy_placement(bo)   # operand frame: see there
        doc.recompute()
        if "Invalid" in bo.State or "Error" in bo.State:
            raise JointError(f"{bo.Label}: recompute failed ({bo.State})")
        if not measure.is_whole(timber):
            raise JointError(
                f"{bo.Label} leaves {timber.Label} as "
                f"{measure.solid_count(timber)} solids — the {c['role'].lower()} "
                f"does not land inside the stick (severed, or missed it)")
        after = timber.Shape.Volume
        if op == "Cut" and abs(after - before) < 1e-6:
            warnings.append(f"{bo.Label} removed no material from "
                            f"{timber.Label} — check the datum's face and station")
        if op == "Fuse" and abs(after - before) < 1e-6:
            warnings.append(f"{bo.Label} added no material to {timber.Label}")
        booleans.append(bo)
        show_tip(timber)

    from . import joint_handle
    joint_handle.ensure_handle(varset, host_datum)
    for w in warnings:
        App.Console.PrintWarning(f"BentWizard: {w}\n")
    return Applied(varset, [b for _c, b, _h, _t in placed], booleans, warnings)


# --------------------------------------------------------------------------
# Remove
# --------------------------------------------------------------------------

def show_tip(body):
    """In the GUI, show a Body's Tip and hide its other solid features —
    what PartDesign's own commands do after adding a feature. Features
    added from Python leave the previous Tip visible (the stick hides the
    Boolean's cut) and a removed Tip leaves nothing visible."""
    if not App.GuiUp:
        return
    tip = body.Tip
    for f in body.Group:
        vo = getattr(f, "ViewObject", None)
        if vo is None or not hasattr(f, "BaseFeature"):
            continue                    # only the solid feature chain
        vo.Visibility = f is tip
    if body.ViewObject is not None:
        body.ViewObject.Visibility = True


def _unlink_feature(body, feat):
    """Take a solid feature out of a Body's chain, relinking what
    followed it, before deleting it."""
    base = getattr(feat, "BaseFeature", None)
    for other in body.Group:
        if getattr(other, "BaseFeature", None) is feat:
            other.BaseFeature = base
    if body.Tip is feat:
        body.Tip = base
    body.removeObject(feat)


def remove_joint(varset):
    """Remove a timber joint: Booleans, mirrorings, components, handle,
    seat and VarSet; the datums stay, unpaired. A timber this joint
    placed keeps the position it had — the seat goes, nothing moves.
    Asserts each timber returns to one solid. Caller owns the
    transaction."""
    doc = varset.Document
    pair = joint_datums(varset)
    timber_names = [datums.owner(d).Name for d in pair if datums.owner(d) is not None]
    # snapshot everything by NAME before deleting anything: a deleted
    # object's proxy raises on any attribute, and removing a feature can
    # cascade
    members = joint_members(varset)
    booleans = [(o.Name, o.getParentGeoFeatureGroup())
                for o in members if o.TypeId == "PartDesign::Boolean"]
    mirrorings = [o.Name for o in members if o.TypeId == "Part::Mirroring"]
    components = []
    for o in members:
        if o.TypeId == "PartDesign::Body":
            origin = o.Origin
            components.append(([f.Name for f in o.Group],
                               [f.Name for f in origin.OriginFeatures] if origin else [],
                               origin.Name if origin else None, o.Name))

    from . import frame, joint_handle
    frame.unseat(varset)
    joint_handle.remove_handle(varset)

    for name, body in booleans:
        bo = doc.getObject(name)
        if bo is None:
            continue
        if body is not None and doc.getObject(body.Name) is not None:
            _unlink_feature(body, bo)
        doc.removeObject(name)
    for name in mirrorings:
        if doc.getObject(name) is not None:
            doc.removeObject(name)
    for features, origin_features, origin, body_name in components:
        for name in list(reversed(features)) + origin_features + [origin, body_name]:
            if name and doc.getObject(name) is not None:
                doc.removeObject(name)
    for d in pair:
        datums.unpair(d)
    # the accessor VarSet belongs to the joint, not the timbers — resolve
    # it before the joint VarSet goes, since that is what names it
    accessors = datums.accessors_varset(varset)
    accessors_name = accessors.Name if accessors is not varset else None
    doc.removeObject(varset.Name)
    if accessors_name and doc.getObject(accessors_name) is not None:
        doc.removeObject(accessors_name)
    joint_handle.prune_root_group(doc)
    doc.recompute()
    timbers = [doc.getObject(n) for n in timber_names]
    for t in timbers:
        if t is None:
            continue
        show_tip(t)
        if "Invalid" in t.State or "Error" in t.State:
            raise JointError(f"{t.Label}: recompute failed after removal ({t.State})")
        if not measure.is_whole(t):
            raise JointError(f"{t.Label} is {measure.solid_count(t)} solids after removal")
    return timbers
