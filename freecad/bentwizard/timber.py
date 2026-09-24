"""New Timber — core logic (no GUI imports).

A timber is the **design solid**: one ``PartDesign::Body`` labeled with
the timber's permanent name (free-form; ``T-Post-Level1-003`` style
recommended — see naming.py), a ``TDim_``-prefixed Dims VarSet nested
inside it, a section sketch on the XY origin plane **centred on the
origin** (half-width constraints measured from the origin, never a
Symmetric constraint), a Pad to ``LengthZ``, and the two end datums
(``D_<timber>_A`` at Station 0, ``D_<timber>_B`` at ``LengthZ``) that
every joint at an end pairs against.

Dimensions are ``WidthX``, ``WidthY``, ``LengthZ`` — timber-local, free
of orientation connotation ("width horizontal, depth vertical" is a
drawing matter, not a modelling one). ``LengthZ`` is the frame
dimension, bearing face to bearing face; it does not change when
joinery is applied or swapped. The ordered stick is measured off the
finished solid (measure.py), never typed.

Built fresh instead of copied-and-remapped: duplicating a body is the
phantom-feature / stale-expression trap (findings #2, #12).
"""

from __future__ import annotations

import re

import FreeCAD as App
import Part
import Sketcher

from . import naming

TOOLTIPS = {
    "WidthX": "Section extent along the timber's local X, centred on "
              "the axis. Timber-local: which way it faces in the "
              "building is a drawing matter.",
    "WidthY": "Section extent along the timber's local Y, centred on "
              "the axis.",
    "LengthZ": "Design length along local Z, end A (Z = 0) to end B: "
               "the frame dimension, bearing face to bearing face. "
               "Joinery grows past it; the ordered stick is measured "
               "off the finished solid.",
    naming.PROP_POSITION_TAG:
        "Where this stick lands in the structure (e.g. 'Bent 2, north "
        "post') — display-only label for layout drawings and lists. "
        "Nothing binds to it; set, change, or clear it freely.",
}

_DIMS_BINDING = re.compile(naming.LABEL_REF.pattern + r"\.LengthZ\b")


class TimberError(ValueError):
    """A new-timber request that cannot be honored."""


def _origin_plane(body, role):
    for f in body.Origin.OriginFeatures:
        if f.Role == role:
            return f
    raise TimberError(f"body has no origin plane {role!r}")


def dim_input(raw):
    """(quantity, expression) — exactly one is None. A string starting
    with '=' is an expression (spreadsheet convention); anything else
    must parse as a quantity."""
    if isinstance(raw, str) and raw.lstrip().startswith("="):
        expr = raw.lstrip()[1:].strip()
        if not expr:
            raise TimberError("empty expression (nothing after '=')")
        return None, expr
    try:
        return App.Units.Quantity(raw), None
    except Exception:
        raise TimberError(f"cannot parse quantity {raw!r} (prefix with "
                          f"'=' for an expression)")


def dims_varset(body):
    """The Dims VarSet driving a timber body's base pad, or None.

    Resolved structurally (whatever the pad's Length expression binds
    to), never by label convention: a renamed body whose VarSet kept
    the old label must still resolve.
    """
    doc = body.Document
    for obj in body.Group:
        if obj.TypeId != "PartDesign::Pad":
            continue
        for path, expr in obj.ExpressionEngine:
            if path.lstrip(".") == "Length":
                # the stick pad reads '<<TDim_...>>.LengthZ'; a component's
                # pad reads a joint parameter and is not a timber
                m = _DIMS_BINDING.search(expr)
                if m:
                    hits = doc.getObjectsByLabel(naming.unquote_label(m.group(1)))
                    if hits and hits[0].TypeId == "App::VarSet":
                        return hits[0]
        break   # the first Pad is the base feature
    return None


def is_timber(obj):
    return obj.TypeId == "PartDesign::Body" and dims_varset(obj) is not None


def timber_bodies(doc):
    """Bodies with a Dims VarSet driving their base pad — resolved
    structurally so renamed timbers still qualify."""
    return [o for o in doc.Objects if is_timber(o)]


def new_timber(doc, member_id, width_x, width_y, length_z, position_tag=""):
    """Create one pristine timber with its end datums; returns
    (body, dims_varset).

    `member_id` is the permanent label (T-Post-001 style recommended);
    `position_tag` optionally pre-fills the display-only PositionTag.
    Each dimension is an App.Units.Quantity (or anything its constructor
    accepts, e.g. "8 in"), or a string starting with '=' to bind the
    Dims property by expression instead (the front door to project
    VarSets, e.g. "=<<ProjectVars>>.PostHeight"). Raises TimberError on
    a bad label, duplicate labels, a bad expression, or failed
    verification. The caller owns the transaction.
    """
    member_id = (member_id or "").strip()
    if not member_id:
        raise TimberError("the timber needs a label (T-Post-001 style "
                          "recommended)")
    bad = naming.reserved_in_label(member_id)
    if bad:
        raise TimberError(f"{member_id!r}: reserved character(s) {bad!r} — "
                          f"'>', '\\', ';' and line breaks break <<Label>> "
                          f"expression references; any other characters "
                          f"are fine")
    dims_label = naming.dims_label(member_id)
    for label in (member_id, dims_label):
        if doc.getObjectsByLabel(label):
            raise TimberError(f"label {label!r} already exists in this document")

    dims_in = {name: dim_input(raw) for name, raw in
               zip(naming.DIMS, (width_x, width_y, length_z))}
    for name, (q, _expr) in dims_in.items():
        if q is not None and q.Value <= 0:
            raise TimberError(f"{name} must be positive, got {q.UserString}")

    # Dims VarSet — literals set directly, expression inputs bound and
    # resolved (recompute) before any geometry exists, so a bad binding
    # leaves nothing behind but the VarSet, which is removed.
    dims = doc.addObject("App::VarSet", "TDim")
    dims.Label = dims_label
    try:
        for prop, (q, expr) in dims_in.items():
            dims.addProperty("App::PropertyLength", prop, "Dims",
                             TOOLTIPS[prop])
            if expr is None:
                setattr(dims, prop, q)
            else:
                try:
                    dims.setExpression(prop, expr)
                except Exception as err:
                    raise TimberError(f"{prop}: bad expression {expr!r} "
                                      f"({err})")
        if any(expr for _q, expr in dims_in.values()):
            doc.recompute([dims])
            for prop, (_q, expr) in dims_in.items():
                if expr is None:
                    continue
                if "Invalid" in dims.State or "Error" in dims.State:
                    raise TimberError(f"{prop}: expression {expr!r} did "
                                      f"not evaluate — check the "
                                      f"referenced VarSet and property")
                if getattr(dims, prop).Value <= 0:
                    raise TimberError(
                        f"{prop}: expression {expr!r} resolves to "
                        f"{getattr(dims, prop).UserString}; must be "
                        f"positive")
    except TimberError:
        doc.removeObject(dims.Name)
        raise
    dims.addProperty("App::PropertyString", naming.PROP_POSITION_TAG, "Tag",
                     TOOLTIPS[naming.PROP_POSITION_TAG])
    setattr(dims, naming.PROP_POSITION_TAG, (position_tag or "").strip())
    wx, wy, lz = dims.WidthX, dims.WidthY, dims.LengthZ

    # Body — with the Dims VarSet nested inside it, so the tree keeps a
    # timber and its data together (pure organization; the binding is by
    # expression, not by membership)
    body = doc.addObject("PartDesign::Body", "Body")
    body.Label = member_id
    body.addObject(dims)

    # Section sketch: rectangle centred on the origin. The four half-width
    # constraints measure from the origin root point to the corners — the
    # origin axes are the centrelines — so nothing uses the Symmetric
    # constraint (finding #13) and each half is bound to Dims by name.
    sketch = body.newObject("Sketcher::SketchObject", "Section")
    sketch.Label = naming.section_sketch_label(member_id)
    sketch.AttachmentSupport = [(_origin_plane(body, "XY_Plane"), "")]
    sketch.MapMode = "FlatFace"

    hx, hy = wx.Value / 2, wy.Value / 2
    V = App.Vector
    sketch.addGeometry([
        Part.LineSegment(V(-hx, -hy, 0), V(hx, -hy, 0)),    # 0 bottom
        Part.LineSegment(V(hx, -hy, 0), V(hx, hy, 0)),      # 1 right
        Part.LineSegment(V(hx, hy, 0), V(-hx, hy, 0)),      # 2 top
        Part.LineSegment(V(-hx, hy, 0), V(-hx, -hy, 0)),    # 3 left
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
        # signed distances from the origin (-1, 1) to a corner on each side
        Sketcher.Constraint("DistanceX", -1, 1, 1, 1, hx),   # 8  origin -> right
        Sketcher.Constraint("DistanceX", 3, 1, -1, 1, hx),   # 9  left -> origin
        Sketcher.Constraint("DistanceY", -1, 1, 2, 1, hy),   # 10 origin -> top
        Sketcher.Constraint("DistanceY", 0, 1, -1, 1, hy),   # 11 bottom -> origin
    ])
    names = {8: "HalfWidthXPos", 9: "HalfWidthXNeg",
             10: "HalfWidthYPos", 11: "HalfWidthYNeg"}
    for index, name in names.items():
        sketch.renameConstraint(index, name)
    for name in ("HalfWidthXPos", "HalfWidthXNeg"):
        sketch.setExpression(f"Constraints.{name}", f"<<{dims_label}>>.WidthX / 2")
    for name in ("HalfWidthYPos", "HalfWidthYNeg"):
        sketch.setExpression(f"Constraints.{name}", f"<<{dims_label}>>.WidthY / 2")

    # Pad to the design length.
    pad = body.newObject("PartDesign::Pad", "Stick")
    pad.Label = naming.stick_label(member_id)
    pad.Profile = sketch
    pad.setExpression("Length", f"<<{dims_label}>>.LengthZ")

    doc.recompute()
    _verify(body, sketch, pad, wx, wy, lz)

    # End datums: every timber has them from birth, so a joint at an end
    # has something to pair against and layout can read Station 0 / LengthZ.
    from . import datums
    datums.add_end_datums(body)
    return body, dims


def _verify(body, sketch, pad, wx, wy, lz):
    """The 'verified' in verified construction: recompute succeeded and
    the solid is exactly the requested stick, centred on the axis."""
    for obj in (sketch, pad, body):
        if "Invalid" in obj.State or "Error" in obj.State:
            raise TimberError(f"{obj.Label}: recompute failed ({obj.State})")
    if sketch.solve() != 0:
        raise TimberError(f"{sketch.Label}: section sketch did not solve")
    expect = wx.Value * wy.Value * lz.Value
    got = body.Shape.Volume
    if abs(got - expect) > 1e-6 * max(expect, 1.0):
        raise TimberError(
            f"stick volume {got:.3f} mm^3 != expected {expect:.3f} mm^3")
    bb = body.Shape.BoundBox
    tol = 1e-6 * max(wx.Value, wy.Value, 1.0)
    if (abs(bb.XMin + wx.Value / 2) > tol or abs(bb.XMax - wx.Value / 2) > tol
            or abs(bb.YMin + wy.Value / 2) > tol
            or abs(bb.YMax - wy.Value / 2) > tol
            or abs(bb.ZMin) > tol or abs(bb.ZMax - lz.Value) > tol):
        raise TimberError("stick is not centred on the origin")
    bound = {e[0].lstrip(".") for e in sketch.ExpressionEngine}
    want = {"Constraints.HalfWidthXPos", "Constraints.HalfWidthXNeg",
            "Constraints.HalfWidthYPos", "Constraints.HalfWidthYNeg"}
    if not want <= bound:
        raise TimberError("section sketch lost its Dims bindings")
    if not any(e[0].lstrip(".") == "Length" for e in pad.ExpressionEngine):
        raise TimberError("pad lost its Dims.LengthZ binding")
