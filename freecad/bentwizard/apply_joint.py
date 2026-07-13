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

import FreeCAD as App
import Part
import Sketcher

from .fcstd import FcstdDocument
from .linter import Model

DIMENSIONAL = {6, 7, 8, 9, 11, 18, 19}   # constraint types carrying a value

# geometry the rebuilder understands; extend alongside new templates
_SUPPORTED_GEOMETRY = ("line", "circle")


class JointError(ValueError):
    """An apply-joint request that cannot be honored."""


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
        parts = self.joint_label.split("_")
        if len(parts) < 3 or parts[0] != "Joint":
            raise JointError(
                f"joint VarSet label {self.joint_label!r} is not "
                f"Joint_<Kind>_<ID>")
        self.kind = "_".join(parts[1:-1])              # e.g. MT
        self.template_jid = parts[-1]                  # e.g. 0a

        # Parameter schema: (name, type_id, value, tooltip, expression)
        exprs = {e.path.lstrip("."): e.expression
                 for e in self.joint.expressions}
        self.parameters = []
        for p in sorted(self.joint.properties.values(), key=lambda p: p.name):
            if p.group is None:
                continue
            self.parameters.append({
                "name": p.name, "type_id": p.type_id, "value": p.value,
                "tooltip": p.doc or "", "group": p.group,
                "expression": exprs.get(p.name),
            })

        # Per-role stacks: body label -> ordered member specs, skipping
        # the pristine-timber base (section sketch + stick pad).
        self.roles = {}
        self.dims_labels = {}                          # role -> TimberDims label
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
                stack.append(self._member_spec(doc, doc.objects[link.obj]))
            self.roles[body.label] = stack

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


def apply_joint(doc, template, joint_id, body_map, values=None):
    """Apply `template` (TemplateSpec) into `doc`.

    body_map: {template body label -> target PartDesign body object},
    e.g. {"P0-1": post, "B0-1": beam}. values: optional {property name ->
    value} overrides applied to the new joint VarSet (literal override
    of a junction binding replaces the expression, per §4.9).
    Returns the new joint VarSet. Caller owns the transaction.
    """
    values = values or {}
    joint_id = (joint_id or "").strip()
    if not joint_id or "<" in joint_id or ">" in joint_id:
        raise JointError("joint ID must be a non-empty string without <>")
    new_joint_label = f"Joint_{template.kind}_{joint_id}"
    if doc.getObjectsByLabel(new_joint_label):
        raise JointError(f"label {new_joint_label!r} already exists")
    if set(body_map) != set(template.roles):
        raise JointError(
            f"body_map roles {sorted(body_map)} != template roles "
            f"{sorted(template.roles)}")

    # Label/expression rewrite table: template joint + each role's
    # MemberID and Dims label -> target equivalents.
    renames = {template.joint_label: new_joint_label,
               # feature labels carry the joint ID as a suffix
               f"_{template.kind}_{template.template_jid}":
               f"_{template.kind}_{joint_id}"}
    for tmpl_label, body in body_map.items():
        renames[template.dims_labels[tmpl_label]] = f"TimberDims_{body.Label}"
        renames[tmpl_label] = body.Label
    expr_renames = {f"<<{k}>>": f"<<{v}>>" for k, v in renames.items()}

    # Target Dims sanity: each mapped body must have its Dims VarSet.
    for tmpl_label, body in body_map.items():
        if not doc.getObjectsByLabel(f"TimberDims_{body.Label}"):
            raise JointError(
                f"{body.Label!r} has no TimberDims_{body.Label} VarSet — "
                f"is it a BentWizard timber?")

    # --- joint VarSet -----------------------------------------------------
    varset = doc.addObject("App::VarSet", "JointVarSet")
    varset.Label = new_joint_label
    for p in template.parameters:
        varset.addProperty(p["type_id"], p["name"], p["group"], p["tooltip"])
        setattr(varset, p["name"], p["value"])
    for p in template.parameters:
        if p["name"] in values:
            setattr(varset, p["name"], values[p["name"]])   # literal override
        elif p["expression"]:
            varset.setExpression(p["name"],
                                 _rewrite(p["expression"], expr_renames))

    # --- per-role stacks ----------------------------------------------------
    made = []
    for tmpl_label, stack in template.roles.items():
        body = body_map[tmpl_label]
        local = {}          # template internal name -> new object
        for spec in stack:
            obj = _rebuild_member(doc, body, spec, local, renames, expr_renames)
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
    return varset


def _rebuild_member(doc, body, spec, local, renames, expr_renames):
    type_id = spec["type_id"]
    obj = body.newObject(type_id, type_id.split(":")[-1])
    obj.Label = _rewrite(spec["label"], renames)

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
            # a body origin plane, recorded in any of FreeCAD's forms
            obj.AttachmentSupport = [(_origin_plane(body, spec["support"]), "")]
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
        _rebuild_sketch(obj, spec)
    elif type_id.startswith("PartDesign::"):
        _rebuild_feature(obj, spec, local)

    for path, expression in spec["expressions"]:
        obj.setExpression(path.lstrip("."),
                          _rewrite(expression, expr_renames))
    return obj


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


def _rebuild_sketch(sketch, spec):
    V = App.Vector
    for geo in spec["geometry"]:
        if geo.kind == "line":
            g = Part.LineSegment(V(geo.start[0], geo.start[1], 0),
                                 V(geo.end[0], geo.end[1], 0))
        else:
            circle = Part.Circle()
            circle.Center = V(geo.center[0], geo.center[1], 0)
            circle.Radius = geo.radius
            g = circle
        sketch.addGeometry(g, geo.construction)
    cons = []
    for con in spec["constraints"]:
        cname = _CONSTRAINT_NAMES.get(con.type_id)
        if cname is None:
            raise JointError(
                f"{spec['label']}: unsupported constraint type {con.type_id}")
        cons.append(Sketcher.Constraint(cname, *_constraint_args(con)))
    if cons:
        sketch.addConstraint(cons)
    for i, con in enumerate(spec["constraints"]):
        if con.name:
            sketch.renameConstraint(i, con.name)


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
