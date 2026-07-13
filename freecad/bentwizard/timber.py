"""New Timber from template — core logic (no GUI imports).

Constructs a pristine parametric timber per workflow doc §4.1: one Body
labeled with the MemberID, a TimberDims VarSet, a section sketch on the
XY origin plane (rectangle in the first quadrant, corner pinned to the
origin), and a Pad to Dims.Length. The origin planes become the square-
rule reference faces (Face 1 = XZ, Face 2 = YZ).

Built fresh instead of copied-and-remapped: duplication of existing
bodies is the phantom-feature / stale-expression trap (findings #2,
#12); programmatic construction has nothing to remap, and the tool
writes every expression (finding #1) and every label (finding #6).
"""

from __future__ import annotations

import re

import FreeCAD as App
import Part
import Sketcher

MEMBER_ID = re.compile(r"^[A-Z]{1,3}\d*-\d+$|^[A-Z]{1,3}-B\d+-\d+$")

TOOLTIPS = {
    "Width": "Section extent along local X, measured from reference "
             "Face 2 (the YZ origin plane).",
    "Depth": "Section extent along local Y, measured from reference "
             "Face 1 (the XZ origin plane).",
    "Length": "Stick length from end A (Z=0) to end B, including "
              "tenons, etc.",
}


class TimberError(ValueError):
    """A new-timber request that cannot be honored."""


def _origin_plane(body, role):
    for f in body.Origin.OriginFeatures:
        if f.Role == role:
            return f
    raise TimberError(f"body has no origin plane {role!r}")


def new_timber(doc, member_id, width, depth, length):
    """Create one pristine timber; returns (body, dims_varset).

    `width`/`depth`/`length` are App.Units.Quantity (or anything its
    constructor accepts, e.g. "8 in"). Raises TimberError on a bad
    MemberID, duplicate labels, or failed verification. The caller owns
    the transaction.
    """
    # Any unique label is accepted (custom roles are legitimate; the
    # naming-convention linter rule is advisory, and Role/Bent/Position
    # auto-numbering arrives with Phase 2). Only reject what breaks
    # expression references.
    member_id = (member_id or "").strip()
    if not member_id:
        raise TimberError("the timber needs a label (MemberID like P2-1 "
                          "recommended)")
    if "<" in member_id or ">" in member_id:
        raise TimberError(f"{member_id!r}: '<' and '>' would break "
                          f"expression references")
    dims_label = f"TimberDims_{member_id}"
    for label in (member_id, dims_label):
        if doc.getObjectsByLabel(label):
            raise TimberError(f"label {label!r} already exists in this document")

    qty = App.Units.Quantity
    width, depth, length = qty(width), qty(depth), qty(length)
    for name, q in (("Width", width), ("Depth", depth), ("Length", length)):
        if q.Value <= 0:
            raise TimberError(f"{name} must be positive, got {q.UserString}")

    # Dims VarSet
    dims = doc.addObject("App::VarSet", "TimberDims")
    dims.Label = dims_label
    for prop, value in (("Width", width), ("Depth", depth), ("Length", length)):
        dims.addProperty("App::PropertyLength", prop, "Dims", TOOLTIPS[prop])
        setattr(dims, prop, value)

    # Body
    body = doc.addObject("PartDesign::Body", "Body")
    body.Label = member_id

    # Section sketch: first-quadrant rectangle, corner pinned to origin.
    sketch = body.newObject("Sketcher::SketchObject", "SectionSketch")
    sketch.Label = f"{member_id}_SectionSketch"
    sketch.AttachmentSupport = [(_origin_plane(body, "XY_Plane"), "")]
    sketch.MapMode = "FlatFace"

    w, d = width.Value, depth.Value
    V = App.Vector
    sketch.addGeometry([
        Part.LineSegment(V(0, 0, 0), V(w, 0, 0)),
        Part.LineSegment(V(w, 0, 0), V(w, d, 0)),
        Part.LineSegment(V(w, d, 0), V(0, d, 0)),
        Part.LineSegment(V(0, d, 0), V(0, 0, 0)),
    ], False)
    sketch.addConstraint([
        Sketcher.Constraint("Coincident", 0, 2, 1, 1),
        Sketcher.Constraint("Coincident", 1, 2, 2, 1),
        Sketcher.Constraint("Coincident", 2, 2, 3, 1),
        Sketcher.Constraint("Coincident", 3, 2, 0, 1),
        Sketcher.Constraint("Horizontal", 0),
        Sketcher.Constraint("Horizontal", 2),
        Sketcher.Constraint("Vertical", 1),
        Sketcher.Constraint("Vertical", 3),
        Sketcher.Constraint("Coincident", 0, 1, -1, 1),   # corner -> origin
        Sketcher.Constraint("DistanceX", 0, 1, 0, 2, w),
        Sketcher.Constraint("DistanceY", 1, 1, 1, 2, d),
    ])
    sketch.renameConstraint(9, "Width")
    sketch.renameConstraint(10, "Depth")
    sketch.setExpression("Constraints.Width", f"<<{dims_label}>>.Width")
    sketch.setExpression("Constraints.Depth", f"<<{dims_label}>>.Depth")

    # Pad to the full stick length.
    pad = body.newObject("PartDesign::Pad", "Stick")
    pad.Label = f"{member_id}_Stick"
    pad.Profile = sketch
    pad.setExpression("Length", f"<<{dims_label}>>.Length")

    doc.recompute()
    _verify(body, sketch, pad, width, depth, length)
    return body, dims


def _verify(body, sketch, pad, width, depth, length):
    """The 'verified' in verified construction: recompute succeeded and
    the solid is exactly the requested stick."""
    for obj in (sketch, pad, body):
        if "Invalid" in obj.State or "Error" in obj.State:
            raise TimberError(f"{obj.Label}: recompute failed ({obj.State})")
    if sketch.solve() != 0:
        raise TimberError(f"{sketch.Label}: section sketch did not solve")
    expect = width.Value * depth.Value * length.Value
    got = body.Shape.Volume
    if abs(got - expect) > 1e-6 * max(expect, 1.0):
        raise TimberError(
            f"stick volume {got:.3f} mm^3 != expected {expect:.3f} mm^3")
    bound = {e[0].lstrip(".") for e in sketch.ExpressionEngine}
    if not {"Constraints.Width", "Constraints.Depth"} <= bound:
        raise TimberError("section sketch lost its Dims bindings")
    if not any(e[0].lstrip(".") == "Length" for e in pad.ExpressionEngine):
        raise TimberError("pad lost its Dims.Length binding")
