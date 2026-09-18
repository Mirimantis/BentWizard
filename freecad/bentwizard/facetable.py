"""The face table — where a timber's datums sit and how they are oriented.

Pure data, no FreeCAD import, so the pure-Python linter and the
FreeCAD-side ``datums`` module read the SAME rows: a datum the tool
writes and a datum the linter accepts are defined once, here.

A **datum** (never "frame" — to a framer a frame is a structure made of
wood) is a ``Part::LocalCoordinateSystem`` owned by a timber, placed
directly (never by attachment) from one row of this table. One rule
governs every row, verified empirically on all four faces and both ends
(docs/session-frame-accessors.md, Part G; the rev-2 Step 0 probe):

    local Z points OUT of the material; local Y runs along the timber
    toward end A; local X = Y x Z.

So a cutter modelled in -Z eats into the timber on every face and an
adder modelled in +Z grows out of it, with no parity correction
anywhere. Rotation and position must always come from the same row —
a datum carrying the -X rotation at the +X position looks plausible and
cuts into open air.

Accessors: ``WidthU``/``WidthV`` are the host's extents along the
datum's local X and Y, ``DepthW`` its extent behind the datum along -Z.
On an end datum both in-plane axes are section directions and DepthW
is the stick length; on a face datum one in-plane axis runs along the
timber and DepthW is the through-section dimension. XYZ is always
timber-local, UVW always datum-local.

**Parity** is what the mirror rule keys on. Any rigid Z -> -Z flip
preserves exactly one in-plane axis and swaps the other, so "the same
timber-local offsets at both ends" is a MIRROR, not a rotation
(Part H2/H3). A component authored on a datum of one parity is
mirrored across its local X when applied to a datum of the other. The
-X face equals the +X face reflected through the timber's YZ plane
composed with that local-X mirror (likewise -Y/+Y and A/B), which is
why one parity bit covers ends and opposite faces alike.
"""

from __future__ import annotations

from collections import namedtuple

Row = namedtuple("Row", (
    "x",            # expression for Placement.Base.x, '{dims}' = Dims label; None = 0
    "y",            # expression for Placement.Base.y
    "station",      # default Station expression (ends only); None = user supplied
    "axis",         # rotation axis (unnormalised) and angle in degrees
    "angle",
    "quaternion",   # the same rotation as (x, y, z, w); -q is the same rotation
    "u",            # Dims property behind WidthU
    "v",            # ... WidthV
    "w",            # ... DepthW
    "outward",      # unit outward normal in timber coordinates
    "parity",       # +1 / -1, see the mirror rule
    "display",      # what the framer reads: '+X', 'End A'
))

_H = 0.7071067811865476

FACE_TABLE = {
    "XPos": Row("<<{dims}>>.WidthX / 2", None, None, (-1, 1, -1), 120,
                (-0.5, 0.5, -0.5, 0.5), "WidthY", "LengthZ", "WidthX",
                (1, 0, 0), +1, "+X"),
    "XNeg": Row("-<<{dims}>>.WidthX / 2", None, None, (-1, -1, 1), 120,
                (-0.5, -0.5, 0.5, 0.5), "WidthY", "LengthZ", "WidthX",
                (-1, 0, 0), -1, "-X"),
    "YPos": Row(None, "<<{dims}>>.WidthY / 2", None, (1, 0, 0), -90,
                (-_H, 0, 0, _H), "WidthX", "LengthZ", "WidthY",
                (0, 1, 0), +1, "+Y"),
    "YNeg": Row(None, "-<<{dims}>>.WidthY / 2", None, (0, 1, -1), 180,
                (0, _H, -_H, 0), "WidthX", "LengthZ", "WidthY",
                (0, -1, 0), -1, "-Y"),
    "EndA": Row(None, None, "0", (0, 1, 0), 180,
                (0, 1, 0, 0), "WidthX", "WidthY", "LengthZ",
                (0, 0, -1), -1, "End A"),
    "EndB": Row(None, None, "<<{dims}>>.LengthZ", (0, 0, 1), 0,
                (0, 0, 0, 1), "WidthX", "WidthY", "LengthZ",
                (0, 0, 1), +1, "End B"),
}

FACES = ("XPos", "XNeg", "YPos", "YNeg")     # side faces
ENDS = ("EndA", "EndB")
PLACES = FACES + ENDS                        # every value `Face` may take

ACCESSORS = ("WidthU", "WidthV", "DepthW")
DIMS = ("WidthX", "WidthY", "LengthZ")


def is_end(face):
    return face in ENDS


def parity(face):
    return FACE_TABLE[face].parity


def display(face):
    return FACE_TABLE[face].display


def accessor_expressions(face, dims_label):
    """{accessor: expression} a datum on `face` carries for its own
    timber's Dims VarSet — the row's U/V/W bindings."""
    row = FACE_TABLE[face]
    return {"WidthU": f"<<{dims_label}>>.{row.u}",
            "WidthV": f"<<{dims_label}>>.{row.v}",
            "DepthW": f"<<{dims_label}>>.{row.w}"}


def position_expressions(face, dims_label):
    """{'.Placement.Base.x'|'.Placement.Base.y': expression} for the
    components the row drives from Dims (z is always 'Station')."""
    row = FACE_TABLE[face]
    out = {}
    if row.x:
        out[".Placement.Base.x"] = row.x.format(dims=dims_label)
    if row.y:
        out[".Placement.Base.y"] = row.y.format(dims=dims_label)
    return out


def same_rotation(q1, q2, tol=1e-6):
    """True when two (x, y, z, w) quaternions are the same rotation
    (q and -q are)."""
    return (all(abs(a - b) < tol for a, b in zip(q1, q2))
            or all(abs(a + b) < tol for a, b in zip(q1, q2)))
