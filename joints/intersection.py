"""Datum line intersection detection and joint coordinate system construction.

Pure geometry utilities — no FreeCAD object creation.  Used by the AddJoint
command and by auto-detection after member placement.

This module must work headless — no FreeCADGui / Qt imports.
"""

import math
from dataclasses import dataclass
from typing import Any, Optional

import FreeCAD

from joints.base import JointCoordinateSystem

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTERSECTION_TOLERANCE = 12.7     # mm (0.5 inches)
ENDPOINT_THRESHOLD = 0.02         # fraction — within 2 % of segment end
MIN_ANGLE_DEGREES = 5.0           # reject near-parallel datums


# ---------------------------------------------------------------------------
# Intersection Result
# ---------------------------------------------------------------------------

@dataclass
class IntersectionResult:
    """Result of detecting an intersection between two member datum lines.

    Attributes
    ----------
    primary_obj : FreeCAD document object
        The primary (housing) member.
    secondary_obj : FreeCAD document object
        The secondary (tenoned) member.
    point : FreeCAD.Vector
        Midpoint of closest approach in world space.
    distance : float
        Closest approach distance in mm.
    intersection_type : str
        ``"EndpointToMidpoint"``, ``"MidpointToMidpoint"``, or
        ``"EndpointToEndpoint"``.
    joint_cs : JointCoordinateSystem
        Local coordinate system at the intersection.
    """

    primary_obj: Any
    secondary_obj: Any
    point: Any                  # FreeCAD.Vector
    distance: float
    intersection_type: str
    joint_cs: JointCoordinateSystem


# ---------------------------------------------------------------------------
# Segment-to-Segment Closest Approach
# ---------------------------------------------------------------------------

def closest_approach_segments(p1, d1, p2, d2):
    """Compute the closest approach between two 3-D line segments.

    Each segment is defined by its start and end points.

    Parameters
    ----------
    p1, d1 : FreeCAD.Vector
        Start and end of segment 1.
    p2, d2 : FreeCAD.Vector
        Start and end of segment 2.

    Returns
    -------
    pt_on_1 : FreeCAD.Vector
        Closest point on segment 1.
    pt_on_2 : FreeCAD.Vector
        Closest point on segment 2.
    distance : float
        Distance between the two closest points.
    t1 : float
        Fractional parameter along segment 1 (0.0 = p1, 1.0 = d1).
    t2 : float
        Fractional parameter along segment 2 (0.0 = p2, 1.0 = d2).
    """
    u = d1 - p1       # direction of segment 1
    v = d2 - p2       # direction of segment 2
    w = p1 - p2

    a = u.dot(u)      # |u|^2
    b = u.dot(v)
    c = v.dot(v)      # |v|^2
    d_val = u.dot(w)
    e = v.dot(w)

    denom = a * c - b * b   # always >= 0

    # If segments are nearly parallel, use midpoint of overlap or endpoints
    if denom < 1e-10:
        s = 0.0
        t = e / c if c > 1e-10 else 0.0
    else:
        s = (b * e - c * d_val) / denom
        t = (a * e - b * d_val) / denom

    # Clamp s to [0, 1] and recompute t
    s = max(0.0, min(1.0, s))
    # Recompute t for clamped s
    t_num = b * s + e
    t = t_num / c if c > 1e-10 else 0.0
    t = max(0.0, min(1.0, t))

    # Recompute s for clamped t
    s_num = b * t - d_val
    s = s_num / a if a > 1e-10 else 0.0
    s = max(0.0, min(1.0, s))

    pt1 = p1 + u * s
    pt2 = p2 + v * t
    dist = (pt1 - pt2).Length

    return pt1, pt2, dist, s, t


# ---------------------------------------------------------------------------
# Intersection Classification
# ---------------------------------------------------------------------------

def classify_intersection(t1: float, t2: float,
                          threshold: float = ENDPOINT_THRESHOLD) -> str:
    """Classify the intersection type from fractional parameters.

    A parameter within *threshold* of 0.0 or 1.0 is considered an endpoint.

    Returns
    -------
    str
        ``"EndpointToEndpoint"``, ``"EndpointToMidpoint"``, or
        ``"MidpointToMidpoint"``.
    """
    ep1 = (t1 <= threshold) or (t1 >= 1.0 - threshold)
    ep2 = (t2 <= threshold) or (t2 >= 1.0 - threshold)

    if ep1 and ep2:
        return "EndpointToEndpoint"
    elif ep1 or ep2:
        return "EndpointToMidpoint"
    else:
        return "MidpointToMidpoint"


# ---------------------------------------------------------------------------
# Joint Coordinate System
# ---------------------------------------------------------------------------

def compute_joint_cs(primary_obj, secondary_obj,
                     intersection_point) -> Optional[JointCoordinateSystem]:
    """Build a :class:`JointCoordinateSystem` from two members.

    Parameters
    ----------
    primary_obj, secondary_obj : FreeCAD document object
        TimberMember objects.
    intersection_point : FreeCAD.Vector
        World-space intersection point.

    Returns
    -------
    JointCoordinateSystem or None
        ``None`` if the datums are near-parallel (angle < 5 degrees).
    """
    p_start = FreeCAD.Vector(primary_obj.A_StartPoint)
    p_end = FreeCAD.Vector(primary_obj.B_EndPoint)
    s_start = FreeCAD.Vector(secondary_obj.A_StartPoint)
    s_end = FreeCAD.Vector(secondary_obj.B_EndPoint)

    p_dir = p_end - p_start
    s_dir = s_end - s_start

    p_len = p_dir.Length
    s_len = s_dir.Length

    if p_len < 1e-6 or s_len < 1e-6:
        return None

    p_axis = FreeCAD.Vector(p_dir)
    p_axis.normalize()
    s_axis = FreeCAD.Vector(s_dir)
    s_axis.normalize()

    # Compute angle between the two datum directions.
    cos_angle = p_axis.dot(s_axis)
    cos_angle = max(-1.0, min(1.0, cos_angle))
    angle_rad = math.acos(abs(cos_angle))
    angle_deg = math.degrees(angle_rad)

    if angle_deg < MIN_ANGLE_DEGREES:
        return None

    # Normal = cross product of the two datum directions.
    normal = p_axis.cross(s_axis)
    norm_len = normal.Length

    if norm_len < 1e-6:
        # Fallback for nearly collinear datums (scarf joint case):
        # use the primary member's local Z axis.
        world_z = FreeCAD.Vector(0, 0, 1)
        if abs(p_axis.dot(world_z)) > 0.999:
            up_hint = FreeCAD.Vector(0, 1, 0)
        else:
            up_hint = world_z
        y_tmp = p_axis.cross(up_hint)
        y_tmp.normalize()
        normal = y_tmp.cross(p_axis)
        normal.normalize()
    else:
        normal.normalize()

    return JointCoordinateSystem(
        origin=FreeCAD.Vector(intersection_point),
        primary_axis=p_axis,
        secondary_axis=s_axis,
        normal=normal,
        angle=angle_deg,
    )


# ---------------------------------------------------------------------------
# Primary / Secondary Assignment
# ---------------------------------------------------------------------------

def assign_primary_secondary(obj_a, obj_b, intersection_type: str, t_a: float,
                             t_b: float):
    """Determine which member is primary (housing) and which is secondary.

    Rules
    -----
    - **EndpointToMidpoint**: the midpoint member is primary (it receives
      the mortise).
    - **MidpointToMidpoint**: the larger cross-section member is primary.
    - **EndpointToEndpoint**: the larger cross-section member is primary.

    Parameters
    ----------
    obj_a, obj_b : FreeCAD document object
        The two TimberMember objects.
    intersection_type : str
        As returned by :func:`classify_intersection`.
    t_a, t_b : float
        Fractional parameters along each member's datum.

    Returns
    -------
    primary, secondary : FreeCAD document object
        The ordered pair.
    """
    if intersection_type == "EndpointToMidpoint":
        ep_a = (t_a <= ENDPOINT_THRESHOLD) or (t_a >= 1.0 - ENDPOINT_THRESHOLD)
        if ep_a:
            # A is at endpoint, B is at midpoint → B is primary
            return obj_b, obj_a
        else:
            return obj_a, obj_b

    # For MidpointToMidpoint and EndpointToEndpoint, use cross-section area.
    area_a = float(obj_a.Width) * float(obj_a.Height)
    area_b = float(obj_b.Width) * float(obj_b.Height)
    if area_a >= area_b:
        return obj_a, obj_b
    else:
        return obj_b, obj_a


# ---------------------------------------------------------------------------
# Document-Level Intersection Detection
# ---------------------------------------------------------------------------

def _is_timber_member(obj) -> bool:
    """Return True if *obj* is a TimberMember document object."""
    if not hasattr(obj, "Proxy"):
        return False
    proxy = obj.Proxy
    if proxy is None:
        return False
    return type(proxy).__name__ == "TimberMember"


def _is_timber_joint(obj) -> bool:
    """Return True if *obj* is a TimberJoint document object."""
    if not hasattr(obj, "Proxy"):
        return False
    proxy = obj.Proxy
    if proxy is None:
        return False
    return type(proxy).__name__ == "TimberJoint"


def _joint_exists_for_pair(doc, obj_a, obj_b) -> bool:
    """Return True if a TimberJoint already links *obj_a* and *obj_b*."""
    for obj in doc.Objects:
        if not _is_timber_joint(obj):
            continue
        pm = getattr(obj, "PrimaryMember", None)
        sm = getattr(obj, "SecondaryMember", None)
        if (pm == obj_a and sm == obj_b) or (pm == obj_b and sm == obj_a):
            return True
    return False


def detect_intersections(doc, tolerance: float = INTERSECTION_TOLERANCE):
    """Scan all TimberMember objects for pairwise intersections.

    Skips pairs that already have a TimberJoint linking them.

    Parameters
    ----------
    doc : FreeCAD.Document
        The active document.
    tolerance : float
        Maximum closest-approach distance in mm.

    Returns
    -------
    list[IntersectionResult]
    """
    members = [o for o in doc.Objects if _is_timber_member(o)]
    results = []

    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            a = members[i]
            b = members[j]
            if _joint_exists_for_pair(doc, a, b):
                continue
            result = _test_pair(a, b, tolerance)
            if result is not None:
                results.append(result)

    return results


def detect_intersections_for_member(doc, member_obj,
                                    tolerance: float = INTERSECTION_TOLERANCE):
    """Detect intersections between *member_obj* and all other members.

    Faster than a full scan — use after placing a single new member.

    Parameters
    ----------
    doc : FreeCAD.Document
    member_obj : FreeCAD document object
        The newly placed TimberMember.
    tolerance : float

    Returns
    -------
    list[IntersectionResult]
    """
    results = []
    for obj in doc.Objects:
        if obj == member_obj:
            continue
        if not _is_timber_member(obj):
            continue
        if _joint_exists_for_pair(doc, member_obj, obj):
            continue
        result = _test_pair(member_obj, obj, tolerance)
        if result is not None:
            results.append(result)
    return results


def _test_pair(obj_a, obj_b,
               tolerance: float) -> Optional[IntersectionResult]:
    """Test whether two members intersect within tolerance.

    Returns an :class:`IntersectionResult` or ``None``.
    """
    p1 = FreeCAD.Vector(obj_a.A_StartPoint)
    d1 = FreeCAD.Vector(obj_a.B_EndPoint)
    p2 = FreeCAD.Vector(obj_b.A_StartPoint)
    d2 = FreeCAD.Vector(obj_b.B_EndPoint)

    pt1, pt2, dist, t1, t2 = closest_approach_segments(p1, d1, p2, d2)

    if dist > tolerance:
        return None

    # Midpoint of closest approach as the intersection point.
    midpt = (pt1 + pt2) * 0.5

    itype = classify_intersection(t1, t2)
    primary, secondary = assign_primary_secondary(obj_a, obj_b, itype, t1, t2)

    joint_cs = compute_joint_cs(primary, secondary, midpt)
    if joint_cs is None:
        return None   # near-parallel datums — not a valid joint

    return IntersectionResult(
        primary_obj=primary,
        secondary_obj=secondary,
        point=midpt,
        distance=dist,
        intersection_type=itype,
        joint_cs=joint_cs,
    )
