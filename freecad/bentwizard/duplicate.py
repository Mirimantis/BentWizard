"""Duplicate Timbers — copy a set of timbers with their timber joints.

Rebuild, not copy (the phantom-feature / stale-expression trap of
findings #2/#12 cannot occur when nothing is copy-remapped): each timber
is re-created with new_timber (Dims values AND expressions preserved, so
project bindings stay pointed at the SAME project VarSets), each of its
face datums is placed again (Station literal or expression carried
over), and each joint whose two timbers both lie inside the set is
re-applied from its recorded template onto the copied datums with its
CURRENT parameter state — literals, user overrides, and expression
bindings, rewritten to the copies. Joints reaching outside the set are
skipped and reported.
"""

from __future__ import annotations

import FreeCAD as App

from . import datums, naming, template_library
from .apply import JointError, apply_joint, bent_joints, joint_datums
from .template import TemplateSpec
from .timber import dims_varset, new_timber


def find_template(kind, library_dirs, source_name=None):
    """TemplateSpec for a joint: by its recorded TemplateSource if that
    file exists, else the library's single template of this kind."""
    if source_name:
        path = template_library.find(source_name, library_dirs)
        if path is not None:
            return TemplateSpec(path)
    matches = []
    for _stem, path in template_library.templates(library_dirs):
        try:
            spec = TemplateSpec(path)
        except JointError:
            continue
        if spec.kind == kind:
            matches.append(spec)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise JointError(f"no library template of kind {kind!r}")
    raise JointError(f"several templates of kind {kind!r} and the joint "
                     f"records no TemplateSource — cannot choose")


def suggest_member_labels(doc, bodies):
    """{body -> suggested copy label}: same base, next free serial."""
    labels = [o.Label for o in doc.Objects]
    taken, out = [], {}
    for body in bodies:
        label = naming.successor_label(labels, body.Label, taken=taken)
        out[body] = label
        taken.append(label)
    return out


def suggest_joint_serials(doc, joints):
    """{joint VarSet -> next free serial in its J-<Kind>-NNN family}."""
    labels = [o.Label for o in doc.Objects]
    taken, out = [], {}
    for joint in joints:
        parsed = naming.parse_joint_label(joint.Label)
        kind = parsed[0] if parsed else "Joint"
        label = naming.next_serial(labels, naming.JOINT_PREFIX + kind,
                                   taken=taken, sep="-")
        taken.append(label)
        out[joint] = naming.split_serial(label)[1]
    return out


def _rewrite(expr, renames):
    for old, new in renames.items():
        expr = expr.replace(old, new)
    return expr


def _copy_datums(src, copy, renames):
    """Place the source's face datums on the copy; map every source
    datum (ends included) to its counterpart."""
    mapping = {}
    for d in datums.datums_of(src):
        face = datums.face_of(d)
        if face in naming.END_SUFFIX:
            mapping[d.Name] = datums.end_datum(copy, face)
            continue
        expr = next((e for p, e in d.ExpressionEngine
                     if p.lstrip(".") == naming.PROP_STATION), None)
        station = ("=" + _rewrite(expr, renames)) if expr else \
            App.Units.Quantity(f"{float(getattr(d, naming.PROP_STATION))} mm")
        mapping[d.Name] = datums.add_datum(copy, face, station)
    return mapping


def duplicate_bent(doc, member_map, joint_serial_map, library_dirs,
                   position_tag="", group_label="", assembly_label="",
                   offset=None):
    """Duplicate the timbers in member_map ({source body -> new label})
    plus every joint fully inside the set (joint_serial_map: {source
    joint VarSet label -> new serial}).

    Copies reproduce the sources' relative placements. With
    `assembly_label` the copies are assembled into a new bent
    sub-assembly of that name, `offset` (App.Vector, mm) placing it
    relative to the source — a provisional position, overridden once
    connecting timber joints are applied. Without it, `offset` shifts
    the loose copies directly; `group_label` files them in a Std Group.

    Returns (new_bodies: {source -> copy}, new_joints: [VarSet],
    skipped: [joint label]). Caller owns the transaction.
    """
    for label in member_map.values():
        if not label or not label.strip():
            raise JointError("every duplicated timber needs a new label")
    if len(set(member_map.values())) != len(member_map):
        raise JointError("duplicate labels in the new-timber names")

    inside, outside = bent_joints(doc, list(member_map))

    # --- timbers: rebuild, carry Dims expressions, place datums --------
    new_bodies, renames, datum_map = {}, {}, {}
    for src, new_label in member_map.items():
        dims = dims_varset(src)
        if dims is None:
            raise JointError(f"{src.Label!r} has no Dims VarSet")
        body, new_dims = new_timber(
            doc, new_label.strip(),
            *(App.Units.Quantity(f"{float(getattr(dims, n))} mm") for n in naming.DIMS),
            position_tag=position_tag)
        new_bodies[src] = body
        renames[f"<<{src.Label}>>"] = f"<<{body.Label}>>"
        renames[f"<<{dims.Label}>>"] = f"<<{new_dims.Label}>>"
        for path, expr in dims.ExpressionEngine:
            new_dims.setExpression(path.lstrip("."), _rewrite(expr, renames))
    doc.recompute()
    for src, copy in new_bodies.items():
        for old_name, new_datum in _copy_datums(src, copy, renames).items():
            datum_map[old_name] = new_datum
            renames[f"<<{doc.getObject(old_name).Label}>>"] = f"<<{new_datum.Label}>>"
    doc.recompute()

    # --- joints -----------------------------------------------------------
    new_joints = []
    for varset in inside:
        if varset.Label not in joint_serial_map:
            raise JointError(f"no new serial given for {varset.Label}")
        parsed = naming.parse_joint_label(varset.Label)
        spec = find_template(parsed[0] if parsed else "", library_dirs,
                             getattr(varset, naming.PROP_TEMPLATE_SOURCE, None))
        pair = joint_datums(varset)
        if len(pair) != 2:
            raise JointError(f"{varset.Label}: not paired")
        host, mate = pair
        targets = {
            spec.host_role: {"body": new_bodies[datums.owner(host)],
                             "datum": datum_map[host.Name]},
            spec.mate_role: {"body": new_bodies[datums.owner(mate)],
                             "datum": datum_map[mate.Name]},
        }
        exprs = {p.lstrip("."): e for p, e in varset.ExpressionEngine}
        values = {}
        for p in spec.parameters:
            name = p["name"]
            if not hasattr(varset, name):
                continue            # the template gained a parameter this joint predates
            if name in exprs:
                values[name] = "=" + _rewrite(exprs[name], renames)
            else:
                current = getattr(varset, name)
                if isinstance(current, (int, bool, str)):
                    values[name] = current
                else:
                    values[name] = App.Units.Quantity(f"{float(current)} mm") \
                        if p["type"] != "App::PropertyAngle" \
                        else App.Units.Quantity(f"{float(current)} deg")
        applied = apply_joint(doc, spec, joint_serial_map[varset.Label], targets,
                              values=values,
                              position_tag=getattr(varset, naming.PROP_POSITION_TAG, ""))
        new_joints.append(applied.varset)

    # --- placement: copies reproduce the sources' relative layout -------
    from .assemble import (assemble_timbers, container_assembly,
                           refresh_joint_display)
    source_asms = {container_assembly(src) for src in member_map}
    base = (source_asms.pop().getGlobalPlacement()
            if len(source_asms) == 1 and None not in source_asms
            else App.Placement())
    shift = App.Placement(offset or App.Vector(), App.Rotation())
    for src, copy in new_bodies.items():
        rel = base.inverse().multiply(src.getGlobalPlacement())
        copy.Placement = rel if assembly_label else shift.multiply(base).multiply(rel)
    doc.recompute()

    assembly_label = (assembly_label or "").strip()
    if assembly_label:
        principal_src = next((src for src in member_map if grounded_by(src, inside)),
                             None) or next(iter(member_map))
        asm, _skipped, _misfits, _adopted = assemble_timbers(
            doc, list(new_bodies.values()), label=assembly_label,
            grounded=new_bodies[principal_src])
        asm.Placement = shift.multiply(base)
        doc.recompute()
        refresh_joint_display(asm)

    group_label = (group_label or "").strip()
    if group_label and not assembly_label:
        group = next((o for o in doc.getObjectsByLabel(group_label)
                      if o.TypeId == "App::DocumentObjectGroup"), None)
        if group is None:
            group = doc.addObject("App::DocumentObjectGroup", "BentGroup")
            group.Label = group_label
        group.addObjects(list(new_bodies.values()))

    return new_bodies, new_joints, [v.Label for v in outside]


def grounded_by(body, joints):
    """True when `body` hosts a joint in `joints` without ever being the
    entering half — the principal-timber heuristic."""
    from .assemble import _engagement_datums
    movers, anchors = set(), set()
    for varset in joints:
        pair = _engagement_datums(varset)
        if pair is None:
            continue
        movers.add(pair[0][0])
        anchors.add(pair[1][0])
    return body in anchors and body not in movers
