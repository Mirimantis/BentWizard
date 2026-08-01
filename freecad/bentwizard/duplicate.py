"""Duplicate Timbers — copy a set of timbers with their timber joints.

Rebuild, not copy (the phantom-feature / stale-expression trap of
findings #2/#12 cannot occur when nothing is copy-remapped): each
timber is re-created with new_timber (Dims values AND expressions
preserved, so group bindings stay pointed at the SAME group VarSets —
workflow §4.2's layer boundary), and each joint whose roles both lie
inside the set is re-applied with apply_joint using its recorded
placement (face/end/hand from Placement_Record) and its CURRENT
parameter state — literals, user overrides, and expression bindings,
rewritten to the copies. Joints reaching outside the set are skipped
and reported.
"""

from __future__ import annotations

from pathlib import Path

import FreeCAD as App

from . import naming
from .apply_joint import (JointError, TemplateSpec, apply_joint,
                          bent_joints, dims_varset, joint_role_frames,
                          parse_placement_record)
from .timber import new_timber


def find_template(kind, library_dir, source_name=None):
    """TemplateSpec for a joint: by recorded source name if available,
    else the library's single template of this kind (matching either the
    template's internal kind or its descriptive kind token — joint
    labels of the two schemes carry one or the other)."""
    library = Path(library_dir)
    if source_name:
        path = library / f"{source_name}.FCStd"
        if path.exists():
            return TemplateSpec(path)
    matches = []
    for path in sorted(library.glob("*.FCStd")):
        try:
            spec = TemplateSpec(path)
        except JointError:
            continue
        if kind in (spec.kind, spec.kind_token):
            matches.append(spec)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise JointError(f"no library template of kind {kind!r}")
    raise JointError(
        f"multiple library templates of kind {kind!r} and the joint does "
        f"not record its Template_Source — cannot choose")


def _role_body_map(varset, template):
    """{role label -> body} for a joint, from its placement record,
    with a structural fallback (mate-frame carrier -> the template role
    whose stack carries the Frame_Role='Mate' frame)."""
    doc = varset.Document
    frames = joint_role_frames(varset)
    record = getattr(varset, "Placement_Record", "")
    if record:
        role_bodies, _ = parse_placement_record(record)
        by_label = {b.Label: b for b in frames}
        if set(role_bodies.values()) <= set(by_label):
            return {role: by_label[label]
                    for role, label in role_bodies.items()}
    # structural fallback (e.g. a body renamed after apply)
    mate_role = next(
        (role for role, stack in template.roles.items()
         if any(s.get("frame_role") == naming.FRAME_ROLE_MATE
                for s in stack)), None)
    roles = list(template.roles)
    if mate_role is None or len(roles) != 2 or len(frames) != 2:
        raise JointError(
            f"{varset.Label}: cannot match bodies to template roles")
    other_role = next(r for r in roles if r != mate_role)
    mate_body = next((b for b, f in frames.items() if f["mate"]), None)
    other_body = next((b for b in frames if b is not mate_body), None)
    if mate_body is None or other_body is None:
        raise JointError(
            f"{varset.Label}: cannot match bodies to template roles")
    return {mate_role: mate_body, other_role: other_body}


def suggest_member_labels(doc, bodies):
    """{body -> suggested copy label}: same base, next free serial (only
    the trailing serial segment is ever touched — descriptive middles
    keep their digits). Suggestions in one batch never collide."""
    labels = [o.Label for o in doc.Objects]
    taken, out = [], {}
    for body in bodies:
        label = naming.successor_label(labels, body.Label, taken=taken)
        out[body] = label
        taken.append(label)
    return out


def suggest_joint_ids(doc, joints):
    """{joint VarSet -> suggested new joint ID (serial)} for the copies.
    The kind token is read from the joint's label (new scheme) or its
    Template_Source (legacy labels), so the serial is allocated against
    the right J-<Kind>-NNN family."""
    labels = [o.Label for o in doc.Objects]
    taken, out = [], {}
    for joint in joints:
        parsed = naming.parse_joint_label(joint.Label)
        if joint.Label.startswith(naming.JOINT_PREFIX) and parsed:
            token = parsed[0]
        else:
            source = getattr(joint, "Template_Source", "")
            token = (naming.kind_token_from_source(source) if source
                     else (parsed[0] if parsed else "Joint"))
        label = naming.next_serial(labels, naming.JOINT_PREFIX + token,
                                   taken=taken)
        taken.append(label)
        out[joint] = naming.split_serial(label)[1]
    return out


def duplicate_bent(doc, member_map, joint_id_map, library_dir,
                   position_tag="", group_label="", assembly_label="",
                   offset=None):
    """Duplicate the timbers in member_map ({source body -> new label})
    plus every joint fully inside the set (joint_id_map: {source joint
    VarSet label -> new joint ID}). `position_tag` pre-fills the copies'
    display-only Position_Tag; `group_label` puts the new bodies in a
    Std Group of that label (created if absent).

    Copies reproduce the sources' relative placements. When
    `assembly_label` is given the copies are assembled into a new bent
    sub-assembly of that name (their joints become Fixed assembly
    joints; the copy of the sources' principal timber is grounded) and
    `offset` (App.Vector, mm) places the new bent relative to the
    source — a provisional position, overridden parametrically once the
    connecting timber joints (tie beams) are applied. Without
    `assembly_label`, `offset` shifts the loose copies directly.

    Returns (new_bodies: {source -> copy}, new_joints: [VarSet],
    skipped: [VarSet label]). Caller owns the transaction.
    """
    for label in member_map.values():
        if not label or not label.strip():
            raise JointError("every duplicated timber needs a new label")
    if len(set(member_map.values())) != len(member_map):
        raise JointError("duplicate labels in the new-timber names")

    inside, outside = bent_joints(doc, member_map)

    # --- timbers: rebuild, then mirror the Dims expressions ------------
    new_bodies = {}
    label_renames = {}
    for src, new_label in member_map.items():
        dims = dims_varset(src)
        if dims is None:
            raise JointError(f"{src.Label!r} has no Dims VarSet")
        body, new_dims = new_timber(
            doc, new_label.strip(),
            App.Units.Quantity(f"{dims.Width.Value} mm"),
            App.Units.Quantity(f"{dims.Depth.Value} mm"),
            App.Units.Quantity(f"{dims.Length.Value} mm"),
            position_tag=position_tag)
        new_bodies[src] = body
        label_renames[f"<<{src.Label}>>"] = f"<<{body.Label}>>"
        label_renames[f"<<{dims.Label}>>"] = f"<<{new_dims.Label}>>"
        # group bindings and other Dims expressions carry over verbatim
        # (same group VarSets — sharing IS the binding, §4.9)
        for path, expr in dims.ExpressionEngine:
            for old, new in label_renames.items():
                expr = expr.replace(old, new)
            new_dims.setExpression(path.lstrip("."), expr)
    doc.recompute()

    # --- joints ---------------------------------------------------------
    new_joints = []
    for varset in inside:
        if varset.Label not in joint_id_map:
            raise JointError(f"no new joint ID given for {varset.Label}")
        parsed = naming.parse_joint_label(varset.Label)
        template = find_template(
            parsed[0] if parsed else "", library_dir,
            getattr(varset, "Template_Source", None))
        role_bodies = _role_body_map(varset, template)
        body_map = {role: new_bodies[body]
                    for role, body in role_bodies.items()}
        record = getattr(varset, "Placement_Record", "")
        placement = parse_placement_record(record)[1] if record else {}

        # current parameter state: expressions (rewritten to the copies)
        # win over literals, so user overrides AND group bindings carry
        # A parameter may live on the joint VarSet or on its companion
        # layout VarSet (the template declares the split); read each
        # from wherever it actually is, so a copy carries both halves.
        from .apply_joint import layout_varset
        companion = layout_varset(varset)
        # kept per owner, never merged: a consumed name (Tenon_Length)
        # exists on BOTH VarSets, and the joint's binding would shadow
        # the companion's actual value
        joint_exprs = {p.lstrip("."): e for p, e in varset.ExpressionEngine}
        layout_exprs = ({p.lstrip("."): e
                         for p, e in companion.ExpressionEngine}
                        if companion is not None else {})
        values = {}
        for p in template.parameters:
            if p["metadata"]:
                # Template_* metadata describes the TEMPLATE, not this
                # joint — apply_joint takes it from the template itself.
                # (It is not a dimension either: Template_Abbrev is a
                # string, which the Quantity branch below cannot carry.)
                continue
            owner = companion if p.get("varset") == "layout" else varset
            if owner is None or not hasattr(owner, p["name"]):
                continue        # template gained a parameter this joint predates
            if p.get("consumed"):
                # rebuilt from the companion by apply_joint; carrying the
                # stale binding would point the copy at the ORIGINAL's
                # companion (finding #2: audit, never blind-clone)
                continue
            exprs = (layout_exprs if p.get("varset") == "layout"
                     else joint_exprs)
            if p["name"] in exprs:
                expr = exprs[p["name"]]
                for old, new in label_renames.items():
                    expr = expr.replace(old, new)
                values[p["name"]] = expr
            else:
                current = getattr(owner, p["name"])
                values[p["name"]] = (int(current) if isinstance(current, int)
                                     else App.Units.Quantity(
                                         f"{current.Value} mm"))
        new_joints.append(apply_joint(
            doc, template, joint_id_map[varset.Label], body_map,
            values=values, placement=placement))

    # --- placement: copies reproduce the sources' relative layout -------
    # (poses relative to the sources' shared bent, when they have one)
    from .assemble import (assemble_timbers, container_assembly,
                           refresh_joint_display)
    source_asms = {container_assembly(src) for src in member_map}
    base = (source_asms.pop().getGlobalPlacement()
            if len(source_asms) == 1 and None not in source_asms
            else App.Placement())
    shift = App.Placement(offset or App.Vector(), App.Rotation())
    for src, copy in new_bodies.items():
        rel = base.inverse().multiply(src.getGlobalPlacement())
        copy.Placement = rel if assembly_label else \
            shift.multiply(base).multiply(rel)
    doc.recompute()

    # --- assembly: copies become a new bent sub-assembly ----------------
    assembly_label = (assembly_label or "").strip()
    if assembly_label:
        principal_src = next(
            (src for src in member_map
             if grounded_by(src, inside)), None) or next(iter(member_map))
        asm, _skipped, _misfits, _adopted = assemble_timbers(
            doc, list(new_bodies.values()), label=assembly_label,
            grounded=new_bodies[principal_src])
        asm.Placement = shift.multiply(base)
        doc.recompute()
        refresh_joint_display(asm)      # icons follow the offset bent

    # --- tree organization: optional Std Group for the copies -----------
    group_label = (group_label or "").strip()
    if group_label and not assembly_label:
        group = next(
            (o for o in doc.getObjectsByLabel(group_label)
             if o.TypeId == "App::DocumentObjectGroup"), None)
        if group is None:
            group = doc.addObject("App::DocumentObjectGroup", "BentGroup")
            group.Label = group_label
        group.addObjects(list(new_bodies.values()))

    return new_bodies, new_joints, [v.Label for v in outside]


def grounded_by(body, joints):
    """True when `body` anchors a joint in `joints` without ever being
    the entering half — the principal-timber heuristic, matching
    assemble.pick_grounded."""
    from .assemble import _engagement_frames
    movers, anchors = set(), set()
    for varset in joints:
        pair = _engagement_frames(varset)
        if pair is None:
            continue
        movers.add(pair[0][0])
        anchors.add(pair[1][0])
    return body in anchors and body not in movers
