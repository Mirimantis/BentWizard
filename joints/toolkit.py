"""Joint geometry toolkit --- face-referenced helpers for building joint cuts.

Every function in this module models one step a timber framer performs:
identify the approach face, mark the pocket layout, cut straight into the
timber, shape the tenon, fit the shoulder against the face.

All geometry is referenced to the actual member face, not to centerline
vectors.  This produces correct results at any intersection angle.

The toolkit is optional --- joint definitions can import and compose these
helpers, or build raw ``Part.Shape`` objects directly.

This module must work headless --- no FreeCADGui / Qt imports.
"""

import math
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import FreeCAD
import Part

from joints.base import JointCoordinateSystem


# ---------------------------------------------------------------------------
# Member Face Context
# ---------------------------------------------------------------------------

@dataclass
class MemberFaceContext:
    """Everything a joint definition needs about one member at an intersection.

    Built by :func:`build_face_context`.  Passed to toolkit functions.

    Attributes
    ----------
    origin : FreeCAD.Vector
        Datum start point.
    axis : FreeCAD.Vector
        Unit vector along datum (start -> end).
    y_dir : FreeCAD.Vector
        Unit width direction of the member cross-section.
    z_dir : FreeCAD.Vector
        Unit height direction of the member cross-section.
    width : float
        Member width (extent along y_dir).
    height : float
        Member height (extent along z_dir).
    face_normal : FreeCAD.Vector
        Inward normal of the approach face (points into the member).
    face_point : FreeCAD.Vector
        Where the other member's datum pierces this member's approach face.
    raw_solid : Part.Shape
        The member's un-cut rectangular solid (for ``common()`` clipping).
    at_start : bool
        True if the joint is at this member's start endpoint.
    toward_other : FreeCAD.Vector
        Unit vector from this member's datum point toward the other member.
    datum_point : FreeCAD.Vector
        Point on this member's datum line closest to the intersection.
    """

    origin: Any
    axis: Any
    y_dir: Any
    z_dir: Any
    width: float
    height: float
    face_normal: Any
    face_point: Any
    raw_solid: Any
    at_start: bool
    toward_other: Any
    datum_point: Any


# ---------------------------------------------------------------------------
# Local coordinate system (single source of truth)
# ---------------------------------------------------------------------------

def member_local_cs(obj):
    """Return ``(origin, x_axis, y_axis, z_axis)`` for a TimberMember.

    X runs along the datum, Y is the width direction, Z is the height
    direction.  Matches the logic in ``TimberMember._build_solid``.
    """
    start = FreeCAD.Vector(obj.A_StartPoint)
    end = FreeCAD.Vector(obj.B_EndPoint)
    direction = end - start
    length = direction.Length

    if length < 1e-6:
        return (start,
                FreeCAD.Vector(1, 0, 0),
                FreeCAD.Vector(0, 1, 0),
                FreeCAD.Vector(0, 0, 1))

    x_axis = FreeCAD.Vector(direction)
    x_axis.normalize()

    world_z = FreeCAD.Vector(0, 0, 1)
    if abs(x_axis.dot(world_z)) > 0.999:
        up_hint = FreeCAD.Vector(0, 1, 0)
    else:
        up_hint = world_z

    y_axis = x_axis.cross(up_hint)
    y_axis.normalize()
    z_axis = y_axis.cross(x_axis)
    z_axis.normalize()

    return start, x_axis, y_axis, z_axis


# ---------------------------------------------------------------------------
# Raw (un-cut) member solid
# ---------------------------------------------------------------------------

def _build_raw_solid(obj):
    """Build the member's rectangular solid without joint boolean cuts.

    Includes joint-driven extensions at each end so the raw solid
    envelope matches what ``TimberMember.execute()`` starts with.
    """
    start = FreeCAD.Vector(obj.A_StartPoint)
    end = FreeCAD.Vector(obj.B_EndPoint)
    direction = end - start
    length = direction.Length

    if length < 1e-6:
        return Part.makeBox(1, 1, 1)

    w = float(obj.Width)
    h = float(obj.Height)
    if w < 1e-6 or h < 1e-6:
        return Part.makeBox(1, 1, 1)

    origin_pt, x_axis, y_axis, z_axis = member_local_cs(obj)

    # Query extensions from connected joints.
    start_ext = 0.0
    end_ext = 0.0
    doc = obj.Document
    if doc is not None:
        for doc_obj in doc.Objects:
            if getattr(doc_obj, "SecondaryMember", None) != obj:
                continue
            se = getattr(doc_obj, "SecondaryStartExtension", 0.0)
            ee = getattr(doc_obj, "SecondaryEndExtension", 0.0)
            start_ext = max(start_ext, se)
            end_ext = max(end_ext, ee)

    effective_start = start - x_axis * start_ext
    effective_length = length + start_ext + end_ext

    corner = effective_start + z_axis * (-h / 2.0) + y_axis * (-w / 2.0)

    p1 = corner
    p2 = corner + y_axis * w
    p3 = corner + y_axis * w + z_axis * h
    p4 = corner + z_axis * h

    wire = Part.makePolygon([p1, p2, p3, p4, p1])
    face = Part.Face(wire)
    solid = face.extrude(x_axis * effective_length)

    return solid


# ---------------------------------------------------------------------------
# Approach face identification
# ---------------------------------------------------------------------------

def _find_approach_face(solid, ray_origin, ray_dir):
    """Find which face of *solid* the ray hits first.

    Returns ``(inward_normal, pierce_point)`` or ``(None, None)`` if
    no face is hit.

    The inward normal points INTO the solid (opposite of the face's
    outward normal).
    """
    best_dist = float("inf")
    best_normal = None
    best_point = None

    for face in solid.Faces:
        # Get face surface and check if it's a plane.
        surf = face.Surface
        if not hasattr(surf, "Axis"):
            continue  # skip non-planar faces (shouldn't happen for a box)

        face_normal_out = FreeCAD.Vector(surf.Axis)
        face_pos = FreeCAD.Vector(surf.Position)

        # Ray-plane intersection: t = (face_pos - ray_origin) . face_normal / (ray_dir . face_normal)
        denom = ray_dir.dot(face_normal_out)
        if abs(denom) < 1e-9:
            continue  # ray parallel to face

        t = (face_pos - ray_origin).dot(face_normal_out) / denom
        if t < -1e-3:
            continue  # face is behind the ray origin

        hit = ray_origin + ray_dir * t

        # Check if hit point is within the face boundary.
        # Use a small tolerance for the containment check.
        try:
            # Project hit point onto face and check UV bounds.
            uv = face.Surface.parameter(hit)
            if face.isPartOfDomain(uv[0], uv[1]):
                if t < best_dist:
                    best_dist = t
                    best_normal = face_normal_out * -1.0  # inward
                    best_point = hit
        except Exception:
            # Fallback: check distance from hit point to face.
            try:
                dist = face.distToShape(Part.Vertex(hit))[0]
                if dist < 1.0:  # 1mm tolerance
                    if t < best_dist:
                        best_dist = t
                        best_normal = face_normal_out * -1.0
                        best_point = hit
            except Exception:
                continue

    return best_normal, best_point


# ---------------------------------------------------------------------------
# MemberFaceContext factory
# ---------------------------------------------------------------------------

def build_face_context(member_obj, other_obj, joint_cs, role="primary"):
    """Build a :class:`MemberFaceContext` for one member at a joint.

    Parameters
    ----------
    member_obj : FreeCAD document object
        The member to build context for.
    other_obj : FreeCAD document object
        The other member at the joint.
    joint_cs : JointCoordinateSystem
        The joint coordinate system.
    role : str
        ``"primary"`` or ``"secondary"`` --- determines which axis from
        the JCS is "this" member's axis.
    """
    origin, x_axis, y_axis, z_axis = member_local_cs(member_obj)
    w = float(member_obj.Width)
    h = float(member_obj.Height)

    raw_solid = _build_raw_solid(member_obj)

    # Determine which end of this member is at the joint.
    mem_start = FreeCAD.Vector(member_obj.A_StartPoint)
    mem_end = FreeCAD.Vector(member_obj.B_EndPoint)
    dist_start = (joint_cs.origin - mem_start).Length
    dist_end = (joint_cs.origin - mem_end).Length
    at_start = dist_start <= dist_end

    # The datum point on this member closest to the intersection.
    datum_point = mem_start if at_start else mem_end

    # Direction from this member toward the other at the joint.
    other_start = FreeCAD.Vector(other_obj.A_StartPoint)
    other_end = FreeCAD.Vector(other_obj.B_EndPoint)
    other_origin, other_x, _other_y, _other_z = member_local_cs(other_obj)

    # Ray from the intersection point along the other member's axis,
    # directed toward this member.  We try both directions and pick the
    # one that hits a face of this member's solid.
    # First, project the other's axis into this member's cross-section
    # plane to get the approach direction.
    other_in_plane = other_x - x_axis * other_x.dot(x_axis)
    if other_in_plane.Length < 1e-6:
        # Other member is parallel to this member's axis (degenerate).
        other_in_plane = y_axis
    else:
        other_in_plane.normalize()

    # Determine which direction points from the other toward this member.
    # The other member's datum point at the joint tells us the direction.
    other_dist_start = (joint_cs.origin - other_start).Length
    other_dist_end = (joint_cs.origin - other_end).Length
    other_at_start = other_dist_start <= other_dist_end
    if other_at_start:
        # Other member's start is at the joint; its axis points away
        # from the joint, so the approach direction is -other_x projected.
        approach_dir = other_in_plane * -1.0
    else:
        approach_dir = FreeCAD.Vector(other_in_plane)

    # The approach direction should point INTO this member (from the
    # other member toward this member's center).  Verify by checking
    # that it points from the joint origin roughly toward this member's
    # datum center.
    mid = (mem_start + mem_end) * 0.5
    to_center = mid - joint_cs.origin
    # Project to_center into cross-section plane.
    to_center_plane = to_center - x_axis * to_center.dot(x_axis)
    if to_center_plane.Length > 1e-6 and approach_dir.dot(to_center_plane) < 0:
        approach_dir = approach_dir * -1.0

    # Cast ray to find the approach face.
    # Start the ray from outside the member along the approach direction.
    ray_start = joint_cs.origin - approach_dir * (w + h)
    face_normal, face_point = _find_approach_face(raw_solid, ray_start, approach_dir)

    if face_normal is None:
        # Fallback: use the approach direction as the face normal
        # and compute face point analytically.
        face_normal = FreeCAD.Vector(approach_dir)
        # Distance from datum center to face along approach_dir.
        half_extent = (abs(approach_dir.dot(y_axis)) * w
                       + abs(approach_dir.dot(z_axis)) * h) / 2.0
        face_point = joint_cs.origin - approach_dir * half_extent

    toward_other = approach_dir * -1.0

    return MemberFaceContext(
        origin=origin,
        axis=x_axis,
        y_dir=y_axis,
        z_dir=z_axis,
        width=w,
        height=h,
        face_normal=face_normal,
        face_point=face_point,
        raw_solid=raw_solid,
        at_start=at_start,
        toward_other=toward_other,
        datum_point=datum_point,
    )


# ---------------------------------------------------------------------------
# Mortise / dovetail axes
# ---------------------------------------------------------------------------

def mortise_axes(pri_ctx):
    """Compute ``(width_dir, height_dir)`` for a mortise or dovetail rectangle.

    Height direction runs along the primary member's grain (datum axis),
    projected perpendicular to the approach face normal.  Width direction
    is perpendicular to both.

    This ensures the long dimension of the mortise runs with the grain.
    """
    # Project primary grain into the plane perpendicular to face_normal.
    h_dir = pri_ctx.axis - pri_ctx.face_normal * pri_ctx.axis.dot(pri_ctx.face_normal)
    if h_dir.Length < 1e-6:
        # Primary grain is parallel to face normal (degenerate).
        return pri_ctx.y_dir, pri_ctx.z_dir

    h_dir.normalize()
    w_dir = pri_ctx.face_normal.cross(h_dir)
    w_dir.normalize()

    return w_dir, h_dir


# ---------------------------------------------------------------------------
# Shoulder plane
# ---------------------------------------------------------------------------

def shoulder_plane(pri_ctx, housing_depth=0.0):
    """Compute the shoulder plane position and normal.

    The shoulder sits against the primary's approach face.  When
    ``housing_depth > 0``, it is recessed into the primary by that amount.

    Returns ``(plane_origin, plane_inward_normal)`` where the normal
    points into the primary (same direction as ``face_normal``).
    """
    # The shoulder origin is on the approach face, offset inward by
    # housing_depth along the face normal.
    sh_origin = pri_ctx.face_point + pri_ctx.face_normal * housing_depth
    return sh_origin, FreeCAD.Vector(pri_ctx.face_normal)


# ---------------------------------------------------------------------------
# Face pocket (mortise)
# ---------------------------------------------------------------------------

def face_pocket(ctx, pocket_w, pocket_h, pocket_depth, w_dir, h_dir,
                offset=None, overshoot=2.0):
    """Cut a rectangular pocket from the approach face straight into the member.

    Creates an oversized box centered on ``ctx.face_point`` (plus optional
    *offset*), oriented along (*w_dir*, *h_dir*, face_normal), extending
    from outside the face to *pocket_depth* inside.  Clips to the member
    solid via ``common()`` so the pocket respects the actual face boundary
    at any intersection angle.

    Parameters
    ----------
    ctx : MemberFaceContext
    pocket_w : float
        Pocket width along *w_dir*.
    pocket_h : float
        Pocket height along *h_dir*.
    pocket_depth : float
        Depth from face surface into the member.
    w_dir, h_dir : FreeCAD.Vector
        Orientation of the pocket rectangle in the face plane.
    offset : FreeCAD.Vector or None
        Optional offset from *ctx.face_point*.
    overshoot : float
        Extra depth outside the face for boolean reliability.
    """
    center = FreeCAD.Vector(ctx.face_point)
    if offset is not None:
        center = center + offset

    # Start the pocket well outside the face for boolean reliability.
    start = center - ctx.face_normal * overshoot

    # Corner of the pocket box.
    corner = start - w_dir * (pocket_w / 2.0) - h_dir * (pocket_h / 2.0)

    p1 = corner
    p2 = corner + w_dir * pocket_w
    p3 = corner + w_dir * pocket_w + h_dir * pocket_h
    p4 = corner + h_dir * pocket_h

    wire = Part.makePolygon([p1, p2, p3, p4, p1])
    face = Part.Face(wire)
    pocket = face.extrude(ctx.face_normal * (pocket_depth + overshoot))

    # Clip to member solid so pocket starts exactly at the face.
    try:
        clipped = pocket.common(ctx.raw_solid)
        if clipped.Volume > 0.01:
            return clipped
    except Exception:
        pass

    # Fallback: return unclipped pocket.
    return pocket


# ---------------------------------------------------------------------------
# Tapered face pocket (dovetail socket)
# ---------------------------------------------------------------------------

def face_tapered_pocket(ctx, narrow_w, wide_w, pocket_h, pocket_depth,
                        taper_dir, channel_dir, channel_extent=None,
                        overshoot=2.0):
    """Cut a trapezoidal pocket from the approach face into the member.

    The pocket narrows at the entry (face) and widens toward the back.
    ``taper_dir`` is the direction along which the taper runs (primary grain).
    ``channel_dir`` is perpendicular to the taper (constant extent).

    Parameters
    ----------
    ctx : MemberFaceContext
    narrow_w : float
        Width along *taper_dir* at the entry (face).
    wide_w : float
        Width along *taper_dir* at the back.
    pocket_h : float
        Extent along *channel_dir* (constant).
    pocket_depth : float
        Depth from face into the member.
    taper_dir : FreeCAD.Vector
    channel_dir : FreeCAD.Vector
    channel_extent : float or None
        If provided, overrides pocket_h for the channel dimension.
    overshoot : float
    """
    if channel_extent is not None:
        pocket_h = channel_extent

    center = FreeCAD.Vector(ctx.face_point)
    start = center - ctx.face_normal * overshoot

    hw_n = narrow_w / 2.0
    hw_w = wide_w / 2.0
    hc = pocket_h / 2.0

    # Entry face (narrow, at the approach face).
    e1 = start - taper_dir * hw_n - channel_dir * hc
    e2 = start + taper_dir * hw_n - channel_dir * hc
    e3 = start + taper_dir * hw_n + channel_dir * hc
    e4 = start - taper_dir * hw_n + channel_dir * hc

    # Back face (wide, deeper into the member).
    depth_vec = ctx.face_normal * (pocket_depth + overshoot)
    b1 = start + depth_vec - taper_dir * hw_w - channel_dir * hc
    b2 = start + depth_vec + taper_dir * hw_w - channel_dir * hc
    b3 = start + depth_vec + taper_dir * hw_w + channel_dir * hc
    b4 = start + depth_vec - taper_dir * hw_w + channel_dir * hc

    # Build 6 faces of the trapezoidal prism.
    entry_wire = Part.makePolygon([e1, e2, e3, e4, e1])
    back_wire = Part.makePolygon([b1, b2, b3, b4, b1])
    bottom_wire = Part.makePolygon([e1, e2, b2, b1, e1])
    top_wire = Part.makePolygon([e4, e3, b3, b4, e4])
    left_wire = Part.makePolygon([e1, e4, b4, b1, e1])
    right_wire = Part.makePolygon([e2, e3, b3, b2, e2])

    faces = [Part.Face(w) for w in
             [entry_wire, back_wire, bottom_wire, top_wire,
              left_wire, right_wire]]

    shell = Part.makeShell(faces)
    pocket = Part.makeSolid(shell)

    # Clip to member solid.
    try:
        clipped = pocket.common(ctx.raw_solid)
        if clipped.Volume > 0.01:
            return clipped
    except Exception:
        pass

    return pocket


# ---------------------------------------------------------------------------
# Tenon block
# ---------------------------------------------------------------------------

def tenon_block(sec_ctx, sh_origin, sh_normal, tenon_w, tenon_h, tenon_length,
                w_dir, h_dir, tenon_dir=None):
    """Build a rectangular tenon extending from the shoulder plane.

    The tenon cross-section (``tenon_w`` x ``tenon_h``) is laid out in
    the shoulder plane using *w_dir* and *h_dir* (typically the mortise
    axes).  The tenon then extends along *tenon_dir* for *tenon_length*.

    By default ``tenon_dir`` equals ``sh_normal`` (perpendicular to the
    primary face).  For angled joints, pass the secondary member's axis
    direction so the tenon follows the brace/rafter naturally.  The
    shoulder face of the tenon sits in the shoulder plane regardless of
    the extrusion direction.

    Parameters
    ----------
    sec_ctx : MemberFaceContext
        The secondary member context.
    sh_origin : FreeCAD.Vector
        Origin on the shoulder plane (where secondary datum pierces it).
    sh_normal : FreeCAD.Vector
        Inward normal of the shoulder plane (into the primary).
    tenon_w, tenon_h : float
        Tenon cross-section dimensions.
    tenon_length : float
        How far the tenon extends past the shoulder.
    w_dir, h_dir : FreeCAD.Vector
        Orientation of the tenon rectangle (should match mortise axes).
    tenon_dir : FreeCAD.Vector or None
        Direction the tenon extends.  Defaults to ``sh_normal``.
        For angled joints, pass the secondary's axis toward the primary.
    """
    if tenon_dir is None:
        tenon_dir = sh_normal

    # The tenon face is laid out in the shoulder plane at sh_origin.
    corner = (sh_origin
              - w_dir * (tenon_w / 2.0)
              - h_dir * (tenon_h / 2.0))

    p1 = corner
    p2 = corner + w_dir * tenon_w
    p3 = corner + w_dir * tenon_w + h_dir * tenon_h
    p4 = corner + h_dir * tenon_h

    wire = Part.makePolygon([p1, p2, p3, p4, p1])
    face = Part.Face(wire)
    # Extrude along tenon_dir.  When tenon_dir differs from sh_normal,
    # this creates a sheared prism --- the tenon follows the secondary's
    # axis but its shoulder face stays in the shoulder plane.
    tenon = face.extrude(tenon_dir * tenon_length)

    return tenon


# ---------------------------------------------------------------------------
# Tapered tenon (dovetail tail)
# ---------------------------------------------------------------------------

def tapered_tenon(sec_ctx, sh_origin, sh_normal, narrow_w, wide_w,
                  tenon_length, taper_dir, channel_dir, channel_extent):
    """Build a trapezoidal tenon (dovetail tail) from the shoulder plane.

    Narrow at the shoulder (entry), wide at the back.

    Parameters
    ----------
    sec_ctx : MemberFaceContext
    sh_origin, sh_normal : FreeCAD.Vector
    narrow_w : float
        Width along taper_dir at the shoulder (neck).
    wide_w : float
        Width along taper_dir at the back (flare).
    tenon_length : float
    taper_dir, channel_dir : FreeCAD.Vector
    channel_extent : float
        Constant extent along channel_dir.
    """
    hw_n = narrow_w / 2.0
    hw_w = wide_w / 2.0
    hc = channel_extent / 2.0

    # Entry face (narrow, at shoulder).
    e1 = sh_origin - taper_dir * hw_n - channel_dir * hc
    e2 = sh_origin + taper_dir * hw_n - channel_dir * hc
    e3 = sh_origin + taper_dir * hw_n + channel_dir * hc
    e4 = sh_origin - taper_dir * hw_n + channel_dir * hc

    # Back face (wide, deep into primary).
    back = sh_origin + sh_normal * tenon_length
    b1 = back - taper_dir * hw_w - channel_dir * hc
    b2 = back + taper_dir * hw_w - channel_dir * hc
    b3 = back + taper_dir * hw_w + channel_dir * hc
    b4 = back - taper_dir * hw_w + channel_dir * hc

    entry_wire = Part.makePolygon([e1, e2, e3, e4, e1])
    back_wire = Part.makePolygon([b1, b2, b3, b4, b1])
    bottom_wire = Part.makePolygon([e1, e2, b2, b1, e1])
    top_wire = Part.makePolygon([e4, e3, b3, b4, e4])
    left_wire = Part.makePolygon([e1, e4, b4, b1, e1])
    right_wire = Part.makePolygon([e2, e3, b3, b2, e2])

    faces = [Part.Face(w) for w in
             [entry_wire, back_wire, bottom_wire, top_wire,
              left_wire, right_wire]]

    shell = Part.makeShell(faces)
    return Part.makeSolid(shell)


# ---------------------------------------------------------------------------
# Shoulder cut
# ---------------------------------------------------------------------------

def shoulder_cut(sec_ctx, sh_origin, sh_normal, keep_shape=None, overshoot=2.0):
    """Remove material from the secondary member beyond the shoulder plane.

    The shoulder plane is defined by ``sh_origin`` and ``sh_normal``
    (which follows the primary's approach face).  The slab face is built
    **in the shoulder plane** (perpendicular to ``sh_normal``), so the
    cut on the secondary follows the primary's face angle --- producing
    an angled shoulder on braces and rafters that sits flat against the
    primary's face.

    If *keep_shape* is provided (the tenon), it is subtracted from the
    slab so only the waste material is removed.

    Parameters
    ----------
    sec_ctx : MemberFaceContext
        Secondary member context.
    sh_origin : FreeCAD.Vector
        Origin on the shoulder plane.
    sh_normal : FreeCAD.Vector
        Inward normal of the shoulder plane (toward primary center).
    keep_shape : Part.Shape or None
        Tenon/tail to preserve (subtracted from the cut slab).
    overshoot : float
        Extra extent for boolean reliability.
    """
    w = sec_ctx.width
    h = sec_ctx.height

    # Oversized extent to cover the secondary's cross-section at any angle.
    full_extent = (w + h) * 2.0

    # Two orthogonal directions in the shoulder plane (perpendicular to
    # sh_normal).  These define the slab face orientation.  Any two
    # orthogonal directions in the plane work --- the slab is oversized.
    up = FreeCAD.Vector(0, 0, 1)
    if abs(sh_normal.dot(up)) > 0.999:
        up = FreeCAD.Vector(0, 1, 0)
    sh_u = sh_normal.cross(up)
    sh_u.normalize()
    sh_v = sh_normal.cross(sh_u)
    sh_v.normalize()

    # The slab starts slightly behind the shoulder plane (on the
    # secondary body side) and extends past the member end on the
    # tenon/primary side.
    slab_start = sh_origin - sh_normal * overshoot
    slab_depth = full_extent

    corner = (slab_start
              - sh_u * (full_extent / 2.0)
              - sh_v * (full_extent / 2.0))

    p1 = corner
    p2 = corner + sh_u * full_extent
    p3 = corner + sh_u * full_extent + sh_v * full_extent
    p4 = corner + sh_v * full_extent

    wire = Part.makePolygon([p1, p2, p3, p4, p1])
    face = Part.Face(wire)
    slab = face.extrude(sh_normal * slab_depth)

    if keep_shape is not None:
        try:
            slab = slab.cut(keep_shape)
        except Exception:
            pass  # fallback: slab without tenon subtraction

    return slab


# ---------------------------------------------------------------------------
# Lap notch
# ---------------------------------------------------------------------------

def lap_notch(ctx, notch_width, notch_depth, face_dir, overshoot=2.0):
    """Cut a notch from a specific face of the member.

    Identifies the face of the member solid whose outward normal is
    closest to ``face_dir``, then cuts inward by ``notch_depth`` over
    ``notch_width`` along the member's datum axis.

    Parameters
    ----------
    ctx : MemberFaceContext
        Member context.
    notch_width : float
        Extent of the notch along the member's datum axis.
    notch_depth : float
        How deep to cut from the face inward.
    face_dir : FreeCAD.Vector
        Which face to notch from (the face with outward normal closest
        to this direction is selected).
    overshoot : float
        Extra extent for boolean reliability.
    """
    # Find which face of the member to notch from by checking which
    # cross-section direction (y or z) aligns best with face_dir.
    # The four candidate face normals are: +y, -y, +z, -z.
    candidates = [
        (ctx.y_dir, ctx.y_dir),
        (ctx.y_dir * -1.0, ctx.y_dir * -1.0),
        (ctx.z_dir, ctx.z_dir),
        (ctx.z_dir * -1.0, ctx.z_dir * -1.0),
    ]

    best_dot = -2.0
    notch_face_normal = ctx.z_dir  # default: top face
    for outward_normal, _ in candidates:
        d = face_dir.dot(outward_normal)
        if d > best_dot:
            best_dot = d
            notch_face_normal = outward_normal

    # Inward direction (from face into member).
    inward = notch_face_normal * -1.0

    # Distance from datum center to the face in the notch direction.
    half_extent = (abs(notch_face_normal.dot(ctx.y_dir)) * ctx.width
                   + abs(notch_face_normal.dot(ctx.z_dir)) * ctx.height) / 2.0

    # The face position: datum_point + outward * half_extent.
    face_pos = ctx.datum_point + notch_face_normal * half_extent

    # Notch box: along datum for notch_width, through full member
    # perpendicular to both datum and notch direction, inward by notch_depth.
    #
    # The "through" direction is perpendicular to both the datum axis
    # and the notch direction.
    through_dir = ctx.axis.cross(notch_face_normal)
    if through_dir.Length < 1e-6:
        # Datum parallel to notch direction (degenerate).
        through_dir = ctx.y_dir
    else:
        through_dir.normalize()

    through_extent = (abs(through_dir.dot(ctx.y_dir)) * ctx.width
                      + abs(through_dir.dot(ctx.z_dir)) * ctx.height)

    # Corner of the notch box, starting at the face, extending inward.
    corner = (face_pos
              - ctx.axis * (notch_width / 2.0)
              - through_dir * ((through_extent + 2 * overshoot) / 2.0))

    p1 = corner
    p2 = corner + ctx.axis * notch_width
    p3 = corner + ctx.axis * notch_width + inward * notch_depth
    p4 = corner + inward * notch_depth

    wire = Part.makePolygon([p1, p2, p3, p4, p1])
    face_shape = Part.Face(wire)
    notch = face_shape.extrude(through_dir * (through_extent + 2 * overshoot))

    return notch


# ---------------------------------------------------------------------------
# Extension calculation
# ---------------------------------------------------------------------------

def approach_face_distance(pri_ctx):
    """Distance from the primary datum line to the approach face.

    For a rectangular cross-section, this is half the member's extent
    in the face_normal direction.
    """
    return (abs(pri_ctx.face_normal.dot(pri_ctx.y_dir)) * pri_ctx.width
            + abs(pri_ctx.face_normal.dot(pri_ctx.z_dir)) * pri_ctx.height) / 2.0


def secondary_extension_for_tenon(pri_ctx, tenon_length, housing_depth=0.0,
                                  cos_alpha=1.0):
    """How far the secondary must extend past its datum endpoint.

    The datum endpoint is at the primary's centerline.  *tenon_length*
    is the perpendicular depth of the tenon from the shoulder into the
    primary.  The shoulder is at ``afd - housing_depth`` from the
    centerline (perpendicular to face).

    If the tenon passes the centerline, the perpendicular overshoot is
    ``tenon_length - (afd - housing_depth)``.  This perpendicular
    distance maps to ``overshoot / cos_alpha`` along the secondary
    axis, since the secondary approaches at angle α to the face normal.
    """
    afd = approach_face_distance(pri_ctx)
    ca = max(cos_alpha, 0.01)
    return max(0.0, (tenon_length - (afd - housing_depth)) / ca)


# ---------------------------------------------------------------------------
# Cross-section extent helpers
# ---------------------------------------------------------------------------

def extent_along(ctx, direction):
    """Extent of a member's cross-section along an arbitrary direction.

    Returns the width of the member's rectangular cross-section projected
    onto *direction*.
    """
    return (abs(direction.dot(ctx.y_dir)) * ctx.width
            + abs(direction.dot(ctx.z_dir)) * ctx.height)
