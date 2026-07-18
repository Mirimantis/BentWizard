"""Duplicate Bent — copy a set of timbers with their joints.

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

import re
from pathlib import Path

import FreeCAD as App

from .apply_joint import (JointError, TemplateSpec, apply_joint,
                          dims_varset, joint_role_frames)
from .timber import new_timber

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


def find_template(kind, library_dir, source_name=None):
    """TemplateSpec for a joint: by recorded source name if available,
    else the library's single template of this kind."""
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
        if spec.kind == kind:
            matches.append(spec)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise JointError(f"no library template of kind {kind!r}")
    raise JointError(
        f"multiple library templates of kind {kind!r} and the joint does "
        f"not record its Template_Source — cannot choose")


def bent_joints(doc, bodies):
    """(inside, outside): joint VarSets whose role bodies are all within
    `bodies`, and those that reach outside the set (skipped)."""
    body_set = set(bodies)
    inside, outside = [], []
    for obj in doc.Objects:
        if obj.TypeId != "App::VarSet" or not obj.Label.startswith("Joint_"):
            continue
        joint_bodies = set(joint_role_frames(obj))
        if not joint_bodies:
            continue
        if joint_bodies & body_set:
            (inside if joint_bodies <= body_set else outside).append(obj)
    return inside, outside


def _role_body_map(varset, template):
    """{role label -> body} for a joint, from its placement record,
    with a structural fallback (mate-frame carrier -> the template role
    whose stack carries the MateFrame)."""
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
         if any("MateFrame" in s["label"] for s in stack)), None)
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


def duplicate_bent(doc, member_map, joint_id_map, library_dir):
    """Duplicate the timbers in member_map ({source body -> new label})
    plus every joint fully inside the set (joint_id_map: {source joint
    VarSet label -> new joint ID}). Returns (new_bodies: {source ->
    copy}, new_joints: [VarSet], skipped: [VarSet label]). Caller owns
    the transaction.
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
            App.Units.Quantity(f"{dims.Length.Value} mm"))
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
        template = find_template(
            "_".join(varset.Label.split("_")[1:-1]), library_dir,
            getattr(varset, "Template_Source", None))
        role_bodies = _role_body_map(varset, template)
        body_map = {role: new_bodies[body]
                    for role, body in role_bodies.items()}
        record = getattr(varset, "Placement_Record", "")
        placement = parse_placement_record(record)[1] if record else {}

        # current parameter state: expressions (rewritten to the copies)
        # win over literals, so user overrides AND group bindings carry
        exprs = {p.lstrip("."): e for p, e in varset.ExpressionEngine}
        values = {}
        for p in template.parameters:
            if p["name"] in exprs:
                expr = exprs[p["name"]]
                for old, new in label_renames.items():
                    expr = expr.replace(old, new)
                values[p["name"]] = expr
            else:
                current = getattr(varset, p["name"])
                values[p["name"]] = (int(current) if isinstance(current, int)
                                     else App.Units.Quantity(
                                         f"{current.Value} mm"))
        new_joints.append(apply_joint(
            doc, template, joint_id_map[varset.Label], body_map,
            values=values, placement=placement))

    return new_bodies, new_joints, [v.Label for v in outside]
