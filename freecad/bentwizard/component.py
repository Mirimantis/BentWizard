"""Authoring helpers for joint components — cutters and adders.

A component is a ``PartDesign::Body`` at the document root carrying two
Tier-2 markers (``ComponentRole`` = Cutter/Adder, ``ComponentOrder``)
and a ``Placement`` bound to the datum it sits on. Its geometry is
modelled from its own origin: a **cutter in -Z** (into the material
behind the datum), an **adder in +Z** (out of it). It reads only its
own datum's accessors and its joint VarSet — never a timber's Dims,
never another datum.

These helpers are what the library build script and the tests author
with; a template author in the GUI does the same by hand (New Component
is a natural future command built on ``new_component``).
"""

from __future__ import annotations

import FreeCAD as App
import Part
import Sketcher

from . import naming

TOOLTIPS = {
    naming.PROP_COMPONENT_ROLE:
        "Cutter (modelled in -Z, cut from the timber behind the datum) or "
        "Adder (modelled in +Z, fused onto it).",
    naming.PROP_COMPONENT_ORDER:
        "Order this component is applied in on its timber: cutters "
        "before adders unless the cutter deliberately trims the adder.",
}


def new_component(doc, label, role, order, varset, datum):
    """An empty component body placed on `datum`, which must be paired
    under joint `varset`: the body's Placement binds to the VarSet's
    HostPlacement / MatePlacement accessor, never to the datum itself
    (see naming.PLACEMENT_ACCESSOR for why)."""
    from . import datums
    if role not in naming.COMPONENT_ROLES:
        raise ValueError(f"role must be Cutter or Adder, got {role!r}")
    body = doc.addObject("PartDesign::Body", "Component")
    body.Label = label
    body.addProperty("App::PropertyEnumeration", naming.PROP_COMPONENT_ROLE,
                     naming.COMPONENT_GROUP, TOOLTIPS[naming.PROP_COMPONENT_ROLE])
    setattr(body, naming.PROP_COMPONENT_ROLE, list(naming.COMPONENT_ROLES))
    setattr(body, naming.PROP_COMPONENT_ROLE, role)
    body.addProperty("App::PropertyInteger", naming.PROP_COMPONENT_ORDER,
                     naming.COMPONENT_GROUP, TOOLTIPS[naming.PROP_COMPONENT_ORDER])
    setattr(body, naming.PROP_COMPONENT_ORDER, int(order))
    body.setExpression("Placement", datums.placement_binding(varset, datum))
    return body


def _xy_plane(body):
    for f in body.Origin.OriginFeatures:
        if f.Role == "XY_Plane":
            return f
    raise ValueError("body has no XY plane")


def add_prism(body, label, width_x, width_y, length_z, direction=+1,
              offset=(0.0, 0.0)):
    """A rectangular prism padded from the body's XY plane, centred on
    its Z axis (plus `offset` in mm), of section `width_x` x `width_y`
    and length `length_z` — each an expression string such as
    ``'<<J-HousedMT-000>>.TenonThickness'`` or ``'2 in'`` — grown in +Z
    (`direction` 1, an adder) or -Z (-1, a cutter). Returns the pad.

    Half-width constraints from the origin, never Symmetric (finding
    #13); the sketch sits on the origin plane, depth is the pad's own
    length (datum strategy)."""
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    sk.Label = naming.feature_label(label, "Sketcher::SketchObject", "")
    sk.AttachmentSupport = [(_xy_plane(body), "")]
    sk.MapMode = "FlatFace"
    if offset != (0.0, 0.0):
        sk.AttachmentOffset = App.Placement(App.Vector(offset[0], offset[1], 0),
                                            App.Rotation())
    hx, hy = 25.0, 25.0
    V = App.Vector
    sk.addGeometry([
        Part.LineSegment(V(-hx, -hy, 0), V(hx, -hy, 0)),
        Part.LineSegment(V(hx, -hy, 0), V(hx, hy, 0)),
        Part.LineSegment(V(hx, hy, 0), V(-hx, hy, 0)),
        Part.LineSegment(V(-hx, hy, 0), V(-hx, -hy, 0)),
    ], False)
    sk.addConstraint([
        Sketcher.Constraint("Coincident", 0, 2, 1, 1),
        Sketcher.Constraint("Coincident", 1, 2, 2, 1),
        Sketcher.Constraint("Coincident", 2, 2, 3, 1),
        Sketcher.Constraint("Coincident", 3, 2, 0, 1),
        Sketcher.Constraint("Horizontal", 0),
        Sketcher.Constraint("Horizontal", 2),
        Sketcher.Constraint("Vertical", 1),
        Sketcher.Constraint("Vertical", 3),
        Sketcher.Constraint("DistanceX", -1, 1, 1, 1, hx),   # 8
        Sketcher.Constraint("DistanceX", 3, 1, -1, 1, hx),   # 9
        Sketcher.Constraint("DistanceY", -1, 1, 2, 1, hy),   # 10
        Sketcher.Constraint("DistanceY", 0, 1, -1, 1, hy),   # 11
    ])
    for index, name in ((8, "HalfXPos"), (9, "HalfXNeg"),
                        (10, "HalfYPos"), (11, "HalfYNeg")):
        sk.renameConstraint(index, name)
    for name in ("HalfXPos", "HalfXNeg"):
        sk.setExpression(f"Constraints.{name}", f"({width_x}) / 2")
    for name in ("HalfYPos", "HalfYNeg"):
        sk.setExpression(f"Constraints.{name}", f"({width_y}) / 2")
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Label = label
    pad.Profile = sk
    pad.setExpression("Length", length_z)
    pad.Reversed = direction < 0
    return pad


def apply_boolean(timber, component_or_mirroring, role, label=None):
    """The Boolean that applies a component to a timber — direct Group
    assignment, because addObjects would drag a mirroring's Source in
    as a second operand."""
    bo = timber.newObject("PartDesign::Boolean", "Boolean")
    bo.Group = [component_or_mirroring]
    bo.Type = naming.BOOLEAN_OP[role]
    bo.Refine = True
    if label:
        bo.Label = label
    return bo
