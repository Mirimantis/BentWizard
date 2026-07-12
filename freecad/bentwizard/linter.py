"""BentWizard model linter — workflow document §6 as executable rules.

Runs on FCStd files directly (pure Python, no FreeCAD) via the fcstd
reader. Strict rules protect the clone mechanism and the model; advisory
rules report style and drift. Each rule cites the workflow document /
findings log item it implements.

Usage:
    python -m freecad.bentwizard.linter <file.FCStd> [file2.FCStd ...]

Exit code 1 if any strict finding, else 0.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from .fcstd import (
    Constraint,
    FcstdDocument,
    expression_refs,
    point_in_polygon,
    point_segment_distance,
    sketch_profile_loops,
)

STRICT = "strict"
ADVISORY = "advisory"

# Severing limits (roadmap Phase 1): strict at the limit, advisory at 35 %.
MORTISE_LIMIT = 0.75
HOUSING_LIMIT = 0.50
CAUTION_LIMIT = 0.35


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
# Semantic model: bodies, ownership, VarSet classification
# --------------------------------------------------------------------------

class Model:
    """Semantic view of one document, shared by all rules."""

    def __init__(self, doc: FcstdDocument):
        self.doc = doc

        # Bodies and feature ownership (Body.Group lists every member).
        self.bodies = doc.of_type("PartDesign::Body")
        self.owner = {}                      # member name -> body
        for body in self.bodies:
            group = body.prop("Group")
            for link in (group.links if group else []):
                self.owner[link.obj] = body

        self.varsets = doc.of_type("App::VarSet")

        # Every (object, varset, prop) expression reference in the document.
        self.refs = []                       # (obj, path, varset, propname)
        for obj in doc.objects.values():
            for e in obj.expressions:
                for target, prop in expression_refs(e.expression, doc):
                    if target.is_type("App::VarSet"):
                        self.refs.append((obj, e, target, prop))

        self._classify_varsets()

    # -- VarSet classification --------------------------------------------
    #
    # Production files are classified by the Kind_Owner label convention
    # (TimberDims_/Joint_/Group_/Project_/Order_). Prototype files predate
    # the convention, so fall back to structure: a Dims VarSet drives its
    # body's base Pad length; a group VarSet is referenced only from other
    # VarSets; everything else referenced from body features is a joint
    # VarSet.

    def _classify_varsets(self):
        self.dims_of = {}        # body name -> dims varset
        self.kind = {}           # varset name -> "dims" | "joint" | "group"

        for vs in self.varsets:
            label = vs.label
            if label.startswith("TimberDims_"):
                self.kind[vs.name] = "dims"
            elif label.startswith("Joint_"):
                self.kind[vs.name] = "joint"
            elif label.startswith(("Group_", "Project_", "Order_")):
                self.kind[vs.name] = "group"

        # Structural: the base Pad's Length binding names the body's Dims.
        for body in self.bodies:
            group = body.prop("Group")
            members = [l.obj for l in (group.links if group else [])]
            for m in members:
                feat = self.doc.objects.get(m)
                if feat is None or not feat.is_type("PartDesign::Pad"):
                    continue
                for e in feat.expressions:
                    if e.path != "Length":
                        continue
                    refs = expression_refs(e.expression, self.doc)
                    if len(refs) == 1 and refs[0][0].is_type("App::VarSet"):
                        vs = refs[0][0]
                        self.dims_of[body.name] = vs
                        self.kind.setdefault(vs.name, "dims")
                break   # base feature is the first Pad

        # Anything referenced only from other VarSets is a group VarSet;
        # remaining VarSets referenced from body features are joint VarSets.
        for vs in self.varsets:
            if vs.name in self.kind:
                continue
            sources = [o for (o, _, t, _) in self.refs if t is vs]
            if sources and all(s.is_type("App::VarSet") for s in sources):
                self.kind[vs.name] = "group"
            elif any(s.name in self.owner for s in sources):
                self.kind[vs.name] = "joint"
            else:
                self.kind[vs.name] = "group"

    # -- helpers ------------------------------------------------------------

    def joint_varsets(self):
        return [v for v in self.varsets if self.kind.get(v.name) == "joint"]

    def dims_varsets(self):
        return [v for v in self.varsets if self.kind.get(v.name) == "dims"]

    def body_dims(self, body):
        return self.dims_of.get(body.name)

    def own_dims_label(self, obj):
        body = self.owner.get(obj.name)
        if body is None:
            return None
        dims = self.body_dims(body)
        return dims.label if dims else None

    def section_extents(self, body):
        """(Width, Depth) values in mm of a body's Dims VarSet, or None."""
        dims = self.body_dims(body)
        if dims is None:
            return None
        w = dims.prop("Width")
        d = dims.prop("Depth")
        if w is None or d is None:
            return None
        return (w.value, d.value)

    def sketch_station(self, sketch):
        """'A' or 'B': which stick end frame a sketch is positioned in.

        End B = the sketch sits on a datum whose offset expression involves
        the owning timber's Dims.Length; everything else is end A.
        """
        own_dims = self.own_dims_label(sketch)
        support = sketch.prop("AttachmentSupport") or sketch.prop("Support")
        if support is None or not support.links or own_dims is None:
            return "A"
        target = self.doc.objects.get(support.links[0].obj)
        if target is None or not target.is_type("Part::Datum"):
            return "A"
        for e in target.expressions:
            for ref_obj, prop in expression_refs(e.expression, self.doc):
                if ref_obj.label == own_dims and prop == "Length":
                    return "B"
        return "A"

    def profile_sketch(self, feature):
        """The sketch a Pad/Pocket/Hole feature's Profile links to."""
        p = feature.prop("Profile")
        if p and p.links:
            return self.doc.objects.get(p.links[0].obj)
        return None

    def constraint_expression(self, sketch, index):
        """The expression string bound to Constraints[index], if any."""
        for e in sketch.expressions:
            if e.path in (f"Constraints[{index}]", f".Constraints[{index}]"):
                return e.expression
        return None

    def single_ref_value(self, expression):
        """Value + (varset, prop) when an expression is one property
        reference, optionally scaled (`X.P`, `X.P / 2`, `X.P * n`).
        Returns (value_mm, varset, propname) or None."""
        refs = expression_refs(expression, self.doc)
        if len(refs) != 1:
            return None
        varset, propname = refs[0]
        prop = varset.prop(propname)
        if prop is None or not isinstance(prop.value, float):
            return None
        stripped = re.sub(r"<<[^<>]+>>\.[A-Za-z_][A-Za-z0-9_]*", "", expression)
        stripped = stripped.strip()
        value = prop.value
        m = re.fullmatch(r"/\s*([0-9.]+)", stripped)
        if m:
            value /= float(m.group(1))
        elif re.fullmatch(r"\*\s*([0-9.]+)", stripped):
            value *= float(re.fullmatch(r"\*\s*([0-9.]+)", stripped).group(1))
        elif stripped:
            return None   # more arithmetic than a simple scale — skip
        return (value, varset, propname)


# --------------------------------------------------------------------------
# Strict rules
# --------------------------------------------------------------------------

def rule_joint_varset_single_instance(model):
    """§6 strict: one VarSet per joint instance.

    (a) A joint VarSet referenced from more than two bodies drives more
        than one mated pair.
    (b) A joint VarSet whose profile sketches within one body sit at both
        stick ends (end-A frame and end-B frame) drives two joint
        locations on that timber.
    Both are §7 debt 1 (MT1 drives both beam ends and both posts).
    """
    findings = []
    for vs in model.joint_varsets():
        bodies = {}
        for (obj, _, target, _) in model.refs:
            if target is not vs:
                continue
            body = model.owner.get(obj.name)
            if body is not None:
                bodies.setdefault(body.name, body)
        if len(bodies) > 2:
            names = ", ".join(sorted(b.label for b in bodies.values()))
            findings.append(Finding(
                "joint-varset-single-instance", STRICT, vs.name, vs.label,
                f"joint VarSet is referenced from {len(bodies)} bodies "
                f"({names}); a joint instance mates exactly two timbers — "
                f"split into one VarSet per joint instance"))
        for body in bodies.values():
            stations = set()
            for (obj, _, target, _) in model.refs:
                if target is vs and model.owner.get(obj.name) is body \
                        and obj.is_type("Sketcher::"):
                    stations.add(model.sketch_station(obj))
            if stations == {"A", "B"}:
                findings.append(Finding(
                    "joint-varset-single-instance", STRICT, vs.name, vs.label,
                    f"joint VarSet drives features at both ends of "
                    f"'{body.label}' — two joint locations, one VarSet; "
                    f"split into one VarSet per joint instance"))
    return findings


def rule_multi_instance_sketch(model):
    """§6 strict: no multi-instance sketches.

    A sketch whose circles are positioned in different stick-end frames
    (some center positions plain, some measured via Dims.Length) serves
    two joint stations and cannot survive the per-instance VarSet split.
    §7 debt 2 (combined two-circle peg sketch on the beam).
    """
    findings = []
    for sketch in model.doc.of_type("Sketcher::SketchObject"):
        own_dims = model.own_dims_label(sketch)
        geom_prop = sketch.prop("Geometry")
        cons_prop = sketch.prop("Constraints")
        if own_dims is None or geom_prop is None or cons_prop is None:
            continue
        circles = [i for i, g in enumerate(geom_prop.geometry)
                   if g.kind == "circle" and not g.construction]
        if len(circles) < 2:
            continue
        frames = {}
        for geo_id in circles:
            frame = "A"
            for ci, con in enumerate(cons_prop.constraints):
                if con.type_id not in (Constraint.DISTANCE,
                                       Constraint.DISTANCE_X,
                                       Constraint.DISTANCE_Y):
                    continue
                if geo_id not in con.geo_ids():
                    continue
                expr = model.constraint_expression(sketch, ci)
                if expr is None:
                    continue
                for ref_obj, prop in expression_refs(expr, model.doc):
                    if ref_obj.label == own_dims and prop == "Length":
                        frame = "B"
            frames.setdefault(frame, []).append(geo_id)
        if len(frames) > 1:
            findings.append(Finding(
                "multi-instance-sketch", STRICT, sketch.name, sketch.label,
                f"circles in this sketch are positioned from both stick "
                f"ends (frames A and B) — it serves two joint instances; "
                f"use one sketch per instance"))
    return findings


def rule_cross_timber_dims(model):
    """§6 strict: no cross-timber Dims references.

    Any object inside body X binding to body Y's Dims VarSet couples the
    timbers and breaks the clone mechanism (and is the recurring silent
    bug after duplication — §4.2's expression audit). Layout values that
    must match the mating timber belong in the joint VarSet.
    §7 debt 3 (PegHole_MT1_sketch2 on Post2 references PostDims).
    """
    findings = []
    for (obj, expr, target, prop) in model.refs:
        if model.kind.get(target.name) != "dims":
            continue
        body = model.owner.get(obj.name)
        if body is None:
            continue   # objects outside bodies (assembly, spreadsheet) exempt
        own = model.body_dims(body)
        if own is not None and target is not own:
            findings.append(Finding(
                "cross-timber-dims-reference", STRICT, obj.name, obj.label,
                f"expression '{expr.path}' in body '{body.label}' references "
                f"'{target.label}.{prop}', another timber's Dims (own Dims is "
                f"'{own.label}') — bind via the joint VarSet instead"))
    return findings


_TOPO_SUB = re.compile(r"(Face|Edge|Vertex)\d+")


def rule_solid_face_references(model):
    """§6 strict: no solid-face references.

    Sketch supports, datum attachments, and assembly joint references must
    point at origin planes and datums, never at solid topology (Face/Edge/
    Vertex), which renumbers on any feature edit. Findings log #8/#10.
    """
    findings = []
    checked = ("AttachmentSupport", "Support", "Reference1", "Reference2",
               "ExternalGeometry")
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


def rule_island_interior(model):
    """§6 strict: islands strictly interior or removal regions used.

    In an island-pocket sketch the kept profile must not touch the outer
    removal loop — coincident edges break face generation (finding #14).
    Checked for polygon loops; sketches with unsupported geometry are
    skipped rather than guessed at.
    """
    findings = []
    tol = 1e-6
    for feature in model.doc.of_type("PartDesign::Pocket"):
        sketch = model.profile_sketch(feature)
        if sketch is None:
            continue
        geom_prop = sketch.prop("Geometry")
        if geom_prop is None:
            continue
        loops, complete = sketch_profile_loops(geom_prop.geometry)
        if not complete or len(loops) < 2:
            continue
        polygons = [l for l in loops if l[0] == "polygon"]
        for i, outer in enumerate(polygons):
            for j, inner in enumerate(polygons):
                if i == j:
                    continue
                overts, iverts = outer[1], inner[1]
                if not all(point_in_polygon(v, overts) for v in iverts):
                    continue   # not nested — separate removal regions, fine
                touch = min(
                    point_segment_distance(v, overts[k], overts[(k + 1) % len(overts)])
                    for v in iverts for k in range(len(overts)))
                if touch <= tol:
                    findings.append(Finding(
                        "island-not-interior", STRICT, sketch.name, sketch.label,
                        f"island profile touches the outer removal loop in "
                        f"pocket '{feature.label}' — keep the island strictly "
                        f"interior or sketch removal regions directly"))
    return findings


def _is_island_sketch(sketch):
    """True when the sketch's profile loops are nested (island pocket)."""
    geom_prop = sketch.prop("Geometry")
    if geom_prop is None:
        return False
    loops, complete = sketch_profile_loops(geom_prop.geometry)
    if not complete:
        return False
    polygons = [l[1] for l in loops if l[0] == "polygon"]
    for i, outer in enumerate(polygons):
        for j, inner in enumerate(polygons):
            if i != j and all(point_in_polygon(v, outer) for v in inner):
                return True
    return False


def _severing_ratios(model):
    """Shared scan for severing/caution checks.

    Yields (feature, sketch, body, varset, propname, value, extent, limit)
    for every joint-VarSet-bound dimensional parameter that removes wood
    from a timber: profile widths/thicknesses vs. the section extent
    (mortise rule) and housing depths vs. the through-dimension.

    Island-pocket sketches (nested loops) are excluded from the profile
    checks: there the inner profile is the *kept* tenon, and its width is
    already checked on the receiving timber's mortise.
    """
    for feature in model.doc.of_type("PartDesign::Pocket"):
        body = model.owner.get(feature.name)
        if body is None:
            continue
        extents = model.section_extents(body)
        if extents is None:
            continue
        min_extent = min(extents)
        sketch = model.profile_sketch(feature)

        # Housing depth: the pocket's own Length parameter.
        for e in feature.expressions:
            if e.path != "Length":
                continue
            hit = model.single_ref_value(e.expression)
            if hit is None:
                continue
            value, varset, propname = hit
            if model.kind.get(varset.name) != "joint":
                continue
            if "housing" in propname.replace("_", "").lower():
                yield (feature, sketch, body, varset, propname,
                       value, min_extent, HOUSING_LIMIT)

        # Mortise/profile widths: dimensional constraints in the sketch.
        if sketch is None:
            continue
        if _is_island_sketch(sketch):
            continue
        for ci in range(len(sketch.prop("Constraints").constraints
                            if sketch.prop("Constraints") else [])):
            expr = model.constraint_expression(sketch, ci)
            if expr is None:
                continue
            hit = model.single_ref_value(expr)
            if hit is None:
                continue
            value, varset, propname = hit
            if model.kind.get(varset.name) != "joint":
                continue
            flat = propname.replace("_", "").lower()
            # Housing_* parameters legitimately span the mating timber's
            # full section; their severing exposure is depth, checked above.
            if flat.startswith("housing"):
                continue
            if flat.endswith(("width", "thickness")):
                yield (feature, sketch, body, varset, propname,
                       value, min_extent, MORTISE_LIMIT)


def rule_severing_limits(model):
    """§6 strict: parameter values within severing limits.

    Mortise/profile widths ≤ 75 % of the receiving section extent,
    housing depths ≤ 50 % of the through-dimension (roadmap Phase 1).
    """
    findings = []
    seen = set()
    for (feature, sketch, body, varset, propname,
         value, extent, limit) in _severing_ratios(model):
        ratio = value / extent
        key = (feature.name, varset.name, propname)
        if ratio > limit + 1e-9 and key not in seen:
            seen.add(key)
            findings.append(Finding(
                "severing-limit", STRICT, feature.name, feature.label,
                f"'{varset.label}.{propname}' = {value:.1f} mm is "
                f"{ratio:.0%} of '{body.label}' section extent "
                f"({extent:.1f} mm); limit is {limit:.0%}"))
    return findings


def rule_joint_fits_footprint(model):
    """Roadmap parameter sanity: the joint must fit inside its landing
    footprint. A setback + extent past the housing opening describes an
    impossible joint (tenon taller/wider than the beam); sketch
    dimensions invert and stick when parameters cross that line (live
    Part E finding). Name-keyed on the template property conventions.
    """
    findings = []
    pairs = (("Tenon_Setback_Face1", "Tenon_Height", "Housing_Height"),
             ("Tenon_Setback_Face2", "Tenon_Width", "Housing_Width"))
    for vs in model.joint_varsets():
        for setback_n, extent_n, opening_n in pairs:
            props = [vs.prop(n) for n in (setback_n, extent_n, opening_n)]
            if any(p is None or not isinstance(p.value, float) for p in props):
                continue
            setback, extent, opening = (p.value for p in props)
            if setback + extent > opening + 1e-6:
                findings.append(Finding(
                    "joint-exceeds-footprint", STRICT, vs.name, vs.label,
                    f"{setback_n} + {extent_n} = {setback + extent:.1f} mm "
                    f"exceeds {opening_n} = {opening:.1f} mm — the joint "
                    f"does not fit its landing footprint and sketch "
                    f"dimensions will invert"))
    return findings


# --------------------------------------------------------------------------
# Advisory rules
# --------------------------------------------------------------------------

_VARSET_LABEL = re.compile(r"^(TimberDims|Joint|Group|Project|Order)_\S+$")
_MEMBER_ID = re.compile(r"^[A-Z]{1,3}\d*-\d+$|^[A-Z]{1,3}-B\d+-\d+$")
_PROPERTY_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*(_[A-Z0-9][A-Za-z0-9]*)+$")
_DIMS_BASE_PROPS = {"Width", "Depth", "Length"}


def rule_naming_conventions(model):
    """§3 advisory: labels and property names follow the decided scheme.

    VarSets are Kind_Owner; timber bodies carry MemberIDs; template
    properties are Part_Attribute[_Qualifier]. §7 debts 5/6 (prototype
    names predate the convention; ProjectVars et al.).
    """
    findings = []
    for vs in model.varsets:
        if not _VARSET_LABEL.match(vs.label):
            findings.append(Finding(
                "naming-convention", ADVISORY, vs.name, vs.label,
                f"VarSet label does not follow Kind_Owner "
                f"(TimberDims_/Joint_/Group_/Project_/Order_)"))
        is_dims = model.kind.get(vs.name) == "dims"
        bad_props = []
        for p in vs.properties.values():
            if p.group is None:        # framework property, not user-defined
                continue
            if is_dims and p.name in _DIMS_BASE_PROPS:
                continue
            if not _PROPERTY_NAME.match(p.name):
                bad_props.append(p.name)
        if bad_props:
            findings.append(Finding(
                "naming-convention", ADVISORY, vs.name, vs.label,
                f"{len(bad_props)} property name(s) do not follow "
                f"Part_Attribute[_Qualifier]: {', '.join(sorted(bad_props))}"))
    for body in model.bodies:
        if not _MEMBER_ID.match(body.label):
            findings.append(Finding(
                "naming-convention", ADVISORY, body.name, body.label,
                f"body label is not a MemberID "
                f"([RolePrefix][Bent]-[Position], e.g. P2-1)"))
    return findings


def rule_symmetry_constraint(model):
    """§6 advisory: centerline + half-width in place of Symmetry.

    The Symmetry constraint is order- and target-sensitive (finding #13);
    the adopted method is a centerline construction line with half-width
    distance constraints.
    """
    findings = []
    for sketch in model.doc.of_type("Sketcher::SketchObject"):
        cons = sketch.prop("Constraints")
        if cons is None:
            continue
        count = sum(1 for c in cons.constraints
                    if c.type_id == Constraint.SYMMETRIC)
        if count:
            findings.append(Finding(
                "symmetry-constraint", ADVISORY, sketch.name, sketch.label,
                f"uses {count} Symmetric constraint(s); replace with "
                f"centerline construction line + half-width constraints"))
    return findings


def rule_caution_threshold(model):
    """§6 advisory: parameter values past the 35 % caution threshold."""
    findings = []
    seen = set()
    for (feature, sketch, body, varset, propname,
         value, extent, limit) in _severing_ratios(model):
        ratio = value / extent
        key = (feature.name, varset.name, propname)
        if CAUTION_LIMIT + 1e-9 < ratio <= limit + 1e-9 and key not in seen:
            seen.add(key)
            findings.append(Finding(
                "caution-threshold", ADVISORY, feature.name, feature.label,
                f"'{varset.label}.{propname}' = {value:.1f} mm is "
                f"{ratio:.0%} of '{body.label}' section extent "
                f"({extent:.1f} mm); past the 35% caution threshold"))
    return findings


def rule_group_binding_deviation(model):
    """§6 advisory: instances deviating from their group bindings.

    When sibling VarSets bind a same-named property to a group VarSet and
    one holds a literal instead, that instance silently deviates from its
    group. (Full group membership arrives with Phase 1 tooling; this
    detects the expression-visible case.)
    """
    findings = []
    bound = {}     # propname -> set of varset names binding it to a group
    for (obj, e, target, prop) in model.refs:
        if obj.is_type("App::VarSet") and model.kind.get(target.name) == "group":
            bound.setdefault(e.path, set()).add(obj.name)
    for propname, binders in bound.items():
        for vs in model.joint_varsets():
            if vs.name in binders or vs.prop(propname) is None:
                continue
            findings.append(Finding(
                "group-binding-deviation", ADVISORY, vs.name, vs.label,
                f"property '{propname}' is a literal here but bound to a "
                f"group VarSet on sibling(s) "
                f"{', '.join(sorted(binders))} — deliberate override?"))
    return findings


def rule_stale_attachment_offset(model):
    """§5/§6 advisory: stale attachment-offset components.

    Attachment offsets must be read in full — stray values hide in
    unexamined components (finding #10). Flag nonzero offset components
    that no expression drives.
    """
    findings = []
    for obj in model.doc.objects.values():
        p = obj.prop("AttachmentOffset")
        if p is None or p.placement is None:
            continue
        pl = p.placement
        driven = {e.path.split(".")[-1].lower()
                  for e in obj.expressions
                  if "AttachmentOffset" in e.path}
        stray = []
        for comp, val in (("x", pl.px), ("y", pl.py), ("z", pl.pz)):
            if abs(val) > 1e-9 and comp not in driven:
                stray.append(f"Base.{comp}={val:.3f}")
        if abs(pl.angle) > 1e-9 and "angle" not in driven:
            stray.append(f"Angle={pl.angle:.3f}")
        if stray:
            findings.append(Finding(
                "stale-attachment-offset", ADVISORY, obj.name, obj.label,
                f"attachment offset has expression-free nonzero "
                f"component(s): {', '.join(stray)} — verify they are "
                f"intended, not stale"))
    return findings


_AUTO_LABEL = re.compile(
    r"^(Sketch|Pad|Pocket|Hole|Body|VarSet|DatumPlane|DatumLine|DatumPoint|"
    r"Fixed|Revolution|Groove|Chamfer|Fillet|Local_CS)\d*$")
_NAMEABLE = ("PartDesign::", "Sketcher::", "Part::Datum", "App::VarSet")


def rule_auto_labels(model):
    """§6 advisory: unrenamed auto-labeled features.

    A label identical to FreeCAD's auto-generated name means the object
    was never named per convention. §7 debt 4 (Hole001 on Post2).
    """
    findings = []
    for obj in model.doc.objects.values():
        if not obj.is_type(*_NAMEABLE) and not (
                obj.is_type("App::FeaturePython") and obj.name.startswith("Joint")):
            continue
        if _AUTO_LABEL.match(obj.label):
            findings.append(Finding(
                "auto-generated-label", ADVISORY, obj.name, obj.label,
                f"label is FreeCAD's auto-generated name — rename per "
                f"convention (MemberID_Feature_JointID)"))
    return findings


def rule_duplicate_tooltips(model):
    """§3 advisory: identical tooltip text on two properties of one
    VarSet is almost always a copy-paste error (caught live during the
    first template build: Tenon_Thickness carrying Housing_Depth's
    tooltip). Tooltips are written per property."""
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
    """§3 advisory: tooltips mandatory on every template-defined property.

    Full-sentence context, including which face/end the value measures
    from, written by the template author.
    """
    findings = []
    for vs in model.varsets:
        missing = sorted(
            p.name for p in vs.properties.values()
            if p.group is not None and not (p.doc or "").strip())
        if missing:
            findings.append(Finding(
                "missing-tooltip", ADVISORY, vs.name, vs.label,
                f"{len(missing)} property(ies) missing tooltips: "
                f"{', '.join(missing)}"))
    return findings


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

STRICT_RULES = [
    rule_joint_varset_single_instance,
    rule_multi_instance_sketch,
    rule_cross_timber_dims,
    rule_solid_face_references,
    rule_island_interior,
    rule_severing_limits,
    rule_joint_fits_footprint,
]

ADVISORY_RULES = [
    rule_naming_conventions,
    rule_symmetry_constraint,
    rule_caution_threshold,
    rule_group_binding_deviation,
    rule_stale_attachment_offset,
    rule_auto_labels,
    rule_duplicate_tooltips,
    rule_missing_tooltips,
]


def lint(path):
    """Lint one FCStd file; returns a list of Findings."""
    doc = FcstdDocument.from_file(path)
    return lint_document(doc)


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
