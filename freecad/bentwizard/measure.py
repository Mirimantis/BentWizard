"""Measurements off the finished solid — what the cut list orders.

A timber's ``LengthZ`` is the design length, bearing face to bearing
face. Joinery (tenons, tongues) grows past it, so the stick a sawyer
must supply is read off the finished solid, **in the timber's own
frame** — a rotated timber's global bounding box is meaningless
(spike round 3, R2: 2069 mm read against a true 2438 mm).

For an angled end the cut list orders the **long point**: a sawyer
cannot cut an angled end onto a stick already cut to the short point.
The local bounding box IS the long point; the short point needs the
sawn face, found as the one whose normal is not axis-aligned.

Solid count is the assertion that matters (round 3): a 1 mm gap in a
fusion, a cutter spanning the whole section, an operand seated in the
wrong frame — each produced exactly the expected volume, passed
``isValid()`` and ``isClosed()``, and left everything Up-to-date. Only
``len(Solids) == 1`` told a joint from a severed timber.
"""

from __future__ import annotations

from .timber import dims_varset


def local_shape(body):
    """`body`'s shape expressed in the body's own frame."""
    shape = body.Shape.copy()
    shape.Placement = body.Placement.inverse().multiply(shape.Placement)
    return shape


def solid_count(body):
    return len(body.Shape.Solids)


def is_whole(body):
    """One valid, closed solid — the post-condition of every Boolean."""
    s = body.Shape
    return len(s.Solids) == 1 and s.isValid() and s.isClosed()


def design_length(body):
    """`LengthZ` from the Dims VarSet, in mm (None for a non-timber)."""
    dims = dims_varset(body)
    return float(dims.LengthZ) if dims is not None else None


def order_length(body):
    """The stick to order, in mm: the finished solid's extent along the
    timber's own Z (its long point when an end is angled)."""
    return local_shape(body).BoundBox.ZLength


def end_projection(body):
    """(past_A, past_B) in mm — how far the finished solid reaches past
    the design length at each end (0 for a plain end, the tenon length
    for a tenoned one). Negative means the solid stops short."""
    bb = local_shape(body).BoundBox
    lz = design_length(body)
    if lz is None:
        return None
    # OCC bounding boxes carry ~1e-14 noise; a micron is well below any
    # framing tolerance and keeps a plain end reading exactly 0
    return (round(-bb.ZMin, 6), round(bb.ZMax - lz, 6))


def angled_end_points(body, tol=1e-6):
    """(short_point_mm, long_point_mm) of a non-square end, found from
    the one face whose normal is not axis-aligned, in the body's own
    frame; (None, None) when every face is square."""
    shape = local_shape(body)
    for face in shape.Faces:
        normal = face.normalAt(0, 0)
        axis_aligned = min(abs(abs(normal.x) - 1.0),
                           abs(abs(normal.y) - 1.0),
                           abs(abs(normal.z) - 1.0))
        if axis_aligned > tol:
            box = face.BoundBox
            return box.ZMin, box.ZMax
    return None, None


def topology(shape):
    """The facts a geometry assertion reads, as a dict."""
    return {"volume": shape.Volume,
            "solids": len(shape.Solids),
            "valid": bool(shape.isValid()),
            "closed": bool(shape.isClosed()),
            "faces": len(shape.Faces),
            "edges": len(shape.Edges),
            "vertexes": len(shape.Vertexes)}


def unhealthy(doc):
    """Objects left Touched or Invalid after a recompute."""
    return [o for o in doc.Objects
            if "Invalid" in o.State or "Touched" in o.State]


def report(body):
    """One timber's numbers for the audit: design and order length, end
    projections, solid count."""
    lz = design_length(body)
    proj = end_projection(body)
    return {"label": body.Label,
            "design_mm": lz,
            "order_mm": order_length(body),
            "past_A_mm": proj[0] if proj else None,
            "past_B_mm": proj[1] if proj else None,
            "solids": solid_count(body),
            "whole": is_whole(body)}
