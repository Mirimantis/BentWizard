"""Dovetail — a dovetail-shaped tenon in a matching socket.

The trapezoidal dovetail shape provides withdrawal resistance, making
this joint ideal for beam-to-post or joist-to-beam connections where
the secondary member must resist pulling away from the primary.

This module must work headless — no FreeCADGui / Qt imports.
"""

import math

import FreeCAD
import Part

from joints.base import (
    JointCoordinateSystem,
    JointParameter,
    JointStructuralProperties,
    ParameterSet,
    SecondaryProfile,
    TimberJointDefinition,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _member_local_cs(obj):
    """Return the member local coordinate system (origin, x, y, z)."""
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


def _make_trapezoid_wire(origin, width_dir, height_dir, depth_dir,
                         narrow_width, wide_width, height, depth):
    """Create a trapezoidal prism solid for a dovetail shape.

    The trapezoid is narrower at the entry face and wider at the back.

    Parameters
    ----------
    origin : FreeCAD.Vector
        Centre of the entry face.
    width_dir : FreeCAD.Vector
        Unit vector in the width direction of the trapezoid.
    height_dir : FreeCAD.Vector
        Unit vector in the height direction.
    depth_dir : FreeCAD.Vector
        Unit vector pointing from entry face toward the wider back face.
    narrow_width : float
        Width at the entry face (narrow end).
    wide_width : float
        Width at the back face (wide end).
    height : float
        Height of the dovetail.
    depth : float
        Depth from entry to back.

    Returns
    -------
    Part.Shape
        The trapezoidal prism solid.
    """
    # Entry face (narrow).
    e1 = origin - width_dir * (narrow_width / 2.0) - height_dir * (height / 2.0)
    e2 = origin + width_dir * (narrow_width / 2.0) - height_dir * (height / 2.0)
    e3 = origin + width_dir * (narrow_width / 2.0) + height_dir * (height / 2.0)
    e4 = origin - width_dir * (narrow_width / 2.0) + height_dir * (height / 2.0)

    # Back face (wide).
    back_origin = origin + depth_dir * depth
    b1 = back_origin - width_dir * (wide_width / 2.0) - height_dir * (height / 2.0)
    b2 = back_origin + width_dir * (wide_width / 2.0) - height_dir * (height / 2.0)
    b3 = back_origin + width_dir * (wide_width / 2.0) + height_dir * (height / 2.0)
    b4 = back_origin - width_dir * (wide_width / 2.0) + height_dir * (height / 2.0)

    # Build faces and sew into a shell, then make solid.
    entry_wire = Part.makePolygon([e1, e2, e3, e4, e1])
    back_wire = Part.makePolygon([b1, b2, b3, b4, b1])

    # Side faces.
    bottom_wire = Part.makePolygon([e1, e2, b2, b1, e1])
    top_wire = Part.makePolygon([e4, e3, b3, b4, e4])
    left_wire = Part.makePolygon([e1, e4, b4, b1, e1])
    right_wire = Part.makePolygon([e2, e3, b3, b2, e2])

    faces = []
    for w in [entry_wire, back_wire, bottom_wire, top_wire, left_wire, right_wire]:
        faces.append(Part.Face(w))

    shell = Part.makeShell(faces)
    solid = Part.makeSolid(shell)
    return solid


def _approach_depth_dir(primary, secondary, joint_cs):
    """Return ``depth_dir`` pointing from the approach face INTO the primary.

    ``sec_x`` points from secondary start toward secondary end.  When the
    joint is at the *start* end, ``sec_x`` points **away** from the primary,
    so we need to negate the projected direction.  When the joint is at the
    *end* end, ``sec_x`` already points toward the primary.
    """
    _pri_o, pri_x, pri_y, _pri_z = _member_local_cs(primary)
    _sec_o, sec_x, _sec_y, _sec_z = _member_local_cs(secondary)

    sec_start = FreeCAD.Vector(secondary.A_StartPoint)
    sec_end = FreeCAD.Vector(secondary.B_EndPoint)
    dist_start = (joint_cs.origin - sec_start).Length
    dist_end = (joint_cs.origin - sec_end).Length

    # Project secondary datum into primary cross-section plane.
    sec_in_plane = sec_x - pri_x * sec_x.dot(pri_x)
    if sec_in_plane.Length < 1e-6:
        sec_in_plane = pri_y
    else:
        sec_in_plane.normalize()

    # When joint is at the start end sec_x (and its projection) points
    # away from the primary — flip to get the INTO direction.
    if dist_start <= dist_end:
        return sec_in_plane * -1.0
    return FreeCAD.Vector(sec_in_plane)


# Channel mode constants
CHANNEL_THROUGH = "Through"
CHANNEL_HALF = "Half"


# ---------------------------------------------------------------------------
# Joint Definition
# ---------------------------------------------------------------------------

class DovetailDefinition(TimberJointDefinition):
    """Dovetail joint definition."""

    NAME = "Dovetail"
    ID = "dovetail"
    CATEGORY = "Dovetail"
    DESCRIPTION = (
        "A dovetail-shaped tenon fits into a matching trapezoidal socket. "
        "Provides withdrawal resistance for beam-to-post or joist-to-beam "
        "connections."
    )
    ICON = ""
    DIAGRAM = ""

    PRIMARY_ROLES = [
        "Beam", "Girt", "SummerBeam", "Plate", "Post",
    ]
    SECONDARY_ROLES = [
        "FloorJoist", "Rafter", "Purlin", "Girt",
    ]
    MIN_ANGLE = 75.0
    MAX_ANGLE = 105.0

    # -- parameters ---------------------------------------------------------

    def get_parameters(self, primary, secondary, joint_cs):
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)
        pri_w = float(primary.Width)

        # Dovetail geometry.
        dovetail_angle = 14.0      # degrees — standard 1:4 slope
        tail_width = sec_w          # full timber width for Through mode

        # Socket depth: half the primary member width.
        socket_depth = pri_w * 0.5

        # Taper widths along the primary axis.  The spread is driven by
        # socket depth and dovetail angle.
        tail_base_width = sec_w * 0.6
        spread = 2.0 * socket_depth * math.tan(math.radians(dovetail_angle))
        tail_end_width = tail_base_width + spread

        # Shoulder: material to the sides of the dovetail on the secondary.
        # Zero when tail_width fills the full timber width (Through mode).
        shoulder_depth = max(0.0, (sec_w - tail_width) / 2.0)

        clearance = 1.6  # 1/16 inch

        params = [
            JointParameter("dovetail_angle", "angle",
                           dovetail_angle, dovetail_angle,
                           min_value=8.0, max_value=20.0,
                           group="Dovetail",
                           description="Dovetail slope angle in degrees"),
            JointParameter("tail_base_width", "length",
                           tail_base_width, tail_base_width,
                           min_value=20.0, max_value=sec_w * 0.9,
                           group="Dovetail",
                           description="Tail width at the entry (narrow) end. "
                                       "Socket base width = this + 2 \u00d7 clearance."),
            JointParameter("tail_end_width", "length",
                           tail_end_width, tail_end_width,
                           min_value=tail_base_width,
                           group="Dovetail",
                           description="Tail width at the back (wide) end. "
                                       "Socket end width = this + 2 \u00d7 clearance."),
            JointParameter("tail_width", "length",
                           tail_width, tail_width,
                           min_value=20.0, max_value=sec_w,
                           group="Dovetail",
                           description="Width of the dovetail along the "
                                       "timber width"),
            JointParameter("socket_depth", "length",
                           socket_depth, socket_depth,
                           min_value=pri_w * 0.25, max_value=pri_w * 0.75,
                           group="Socket",
                           description="Depth of dovetail socket in primary "
                                       "member (into the face)"),
            JointParameter("housing_depth", "length",
                           shoulder_depth, shoulder_depth,
                           min_value=0.0,
                           group="Dovetail",
                           description="Housing depth around the dovetail "
                                       "(0 = no housing)"),
            JointParameter("clearance", "length",
                           clearance, clearance,
                           min_value=0.0, max_value=3.0,
                           group="Socket",
                           description="Clearance per side in socket "
                                       "(socket width = tail width + "
                                       "2 \u00d7 this value)"),
            JointParameter("channel_mode", "enumeration",
                           CHANNEL_THROUGH, CHANNEL_THROUGH,
                           group="Socket",
                           description="Through = open both sides; "
                                       "Half = open toward nearer edge",
                           enum_options=[CHANNEL_THROUGH, CHANNEL_HALF]),
            JointParameter("flip_channel", "boolean",
                           False, False,
                           group="Socket",
                           description="Reverse which side the half-channel "
                                       "opens toward"),
        ]
        return ParameterSet(params)

    # -- dependent defaults -------------------------------------------------

    def update_dependent_defaults(self, params):
        """Keep tail_end_width in sync with base_width, angle, and socket_depth.

        The end width is derived from the base width plus the taper spread
        over the socket depth at the dovetail angle.
        """
        base_w = params.get("tail_base_width")
        socket_d = params.get("socket_depth")
        angle = params.get("dovetail_angle")
        spread = 2.0 * socket_d * math.tan(math.radians(angle))
        new_end_w = base_w + spread

        end_param = params.get_param("tail_end_width")
        if not end_param.is_overridden:
            end_param.default_value = new_end_w
            end_param.value = new_end_w
        # Update min bound: end width should never be less than base width.
        end_param.min_value = base_w

    # -- primary cut (dovetail socket) -------------------------------------

    def build_primary_tool(self, params, primary, secondary, joint_cs):
        """Build the dovetail socket to subtract from the primary member.

        The socket is on the face of the primary where the secondary
        approaches.  The dovetail cross-section (narrow at the approach
        face, wide at the back) prevents the secondary from being
        pulled straight out.

        The socket runs perpendicular to the approach face.  ``Through``
        mode opens both sides; ``Half`` opens toward one edge.
        """
        clearance = params.get("clearance")
        narrow_w = params.get("tail_base_width") + 2 * clearance
        wide_w = params.get("tail_end_width") + 2 * clearance
        socket_depth = params.get("socket_depth")
        channel_mode = params.get("channel_mode")
        flip = params.get("flip_channel")

        _pri_o, pri_x, pri_y, pri_z = _member_local_cs(primary)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)

        # depth_dir: from the approach face INTO the primary.
        depth_dir = _approach_depth_dir(primary, secondary, joint_cs)

        # Taper direction: perpendicular to both primary axis and depth.
        # The dovetail taper (narrow->wide) is measured along pri_x.
        # The socket runs along taper_dir through the primary cross-section.
        taper_dir = depth_dir.cross(pri_x)
        taper_dir.normalize()

        # Through extent to locate the approach face.
        through_extent = (abs(depth_dir.dot(pri_y)) * pri_w
                          + abs(depth_dir.dot(pri_z)) * pri_h)

        # Approach face: the face of the primary nearest the secondary.
        approach_face = joint_cs.origin - depth_dir * (through_extent / 2.0)

        # Socket extent along taper_dir.
        taper_extent = (abs(taper_dir.dot(pri_y)) * pri_w
                        + abs(taper_dir.dot(pri_z)) * pri_h)

        extra = 2.0  # mm overshoot for boolean reliability

        if channel_mode == CHANNEL_THROUGH:
            socket_length = taper_extent + 2 * extra
            socket_center = approach_face
        else:
            # Half: open toward the nearer edge in taper_dir.
            # Check which edge of the primary is closer to the joint
            # in the taper_dir direction.
            socket_half = taper_extent / 2.0 + extra
            # Default: open in +taper_dir if joint is above centre,
            # otherwise -taper_dir.  flip reverses this.
            open_sign = 1.0
            if flip:
                open_sign = -1.0
            open_dir = taper_dir * open_sign
            socket_length = socket_half
            socket_center = approach_face + open_dir * (socket_half / 2.0)

        # The socket runs along taper_dir, so taper_dir is the "height"
        # parameter in _make_trapezoid_wire.  The dovetail taper
        # (narrow at approach face, wide at back) is along pri_x.
        socket = _make_trapezoid_wire(
            socket_center,
            pri_x,           # width param: dovetail taper
            taper_dir,       # height param: socket runs this way
            depth_dir,       # depth param: into the primary
            narrow_w,        # narrow at approach face
            wide_w,          # wide at back
            socket_length,   # socket extent
            socket_depth,    # depth into primary
        )

        return socket

    # -- secondary extension ------------------------------------------------

    def secondary_extension(self, params, primary, secondary, joint_cs):
        """Extension past the datum endpoint for the dovetail tenon.

        Unlike the through mortise & tenon, the dovetail socket starts at
        the primary's approach face and goes ``socket_depth`` inward — it
        does NOT pass all the way through.  The extension is only the
        portion of the socket that reaches past the primary's centerline
        (where the datum endpoint snaps).
        """
        socket_depth = params.get("socket_depth")
        approach_dist = self._approach_face_distance(
            primary, secondary, joint_cs
        )
        return max(0.0, socket_depth - approach_dist)

    @staticmethod
    def _approach_face_distance(primary, secondary, joint_cs):
        """Distance from the primary centerline to its approach face.

        This is the distance along the secondary's approach direction
        from the intersection point (centerline) to the near surface
        of the primary member.
        """
        _pri_o, pri_x, pri_y, pri_z = _member_local_cs(primary)
        depth_dir = _approach_depth_dir(primary, secondary, joint_cs)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)
        through_extent = (abs(depth_dir.dot(pri_y)) * pri_w
                          + abs(depth_dir.dot(pri_z)) * pri_h)
        return through_extent / 2.0

    # -- secondary profile (dovetail tenon + shoulder) ----------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the dovetail tenon shape and shoulder cut.

        The tenon taper matches the socket: narrow at the entry (shoulder
        face), wide at the back, so it locks against the dovetail profile
        and cannot be withdrawn.

        The shoulder face is at the primary's approach surface — not at
        the datum endpoint (centerline).  The shoulder cut runs a single
        dovetail trapezoid from the approach face inward by ``socket_depth``.

        In Half channel mode, the tenon is offset to one side to match
        the half-socket position in the primary.
        """
        narrow_w = params.get("tail_base_width")
        wide_w = params.get("tail_end_width")
        tail_w = params.get("tail_width")
        socket_depth = params.get("socket_depth")
        channel_mode = params.get("channel_mode")
        flip = params.get("flip_channel")

        sec_origin, sec_x, sec_y, sec_z = _member_local_cs(secondary)
        _pri_o, pri_x, pri_y, pri_z = _member_local_cs(primary)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        sec_start = FreeCAD.Vector(secondary.A_StartPoint)
        sec_end = FreeCAD.Vector(secondary.B_EndPoint)

        # Which end of the secondary is at the joint?
        dist_start = (joint_cs.origin - sec_start).Length
        dist_end = (joint_cs.origin - sec_end).Length

        if dist_start <= dist_end:
            tenon_direction = sec_x * -1.0
            shoulder_origin = sec_start
        else:
            tenon_direction = sec_x
            shoulder_origin = sec_end

        inward_dir = tenon_direction * -1.0

        # Taper direction: matches the socket (perpendicular to both
        # the primary axis and the approach direction).
        depth_dir = _approach_depth_dir(primary, secondary, joint_cs)
        taper_dir = depth_dir.cross(pri_x)
        taper_dir.normalize()

        # The shoulder face is at the primary's approach surface,
        # NOT at the datum endpoint (which is the primary centerline).
        approach_dist = self._approach_face_distance(
            primary, secondary, joint_cs
        )
        shoulder_face = shoulder_origin + inward_dir * approach_dist

        # In Half mode, offset the tenon center to match the socket.
        if channel_mode == CHANNEL_HALF:
            open_sign = -1.0 if flip else 1.0
            open_dir = taper_dir * open_sign
            tenon_center = shoulder_face + open_dir * (tail_w / 4.0)
        else:
            tenon_center = shoulder_face

        # Build tenon: starts at shoulder face, extends socket_depth
        # into the primary.  Narrow at entry (shoulder face, matching the
        # socket mouth), wide at back (deep in primary, matching socket back).
        tenon = _make_trapezoid_wire(
            tenon_center,
            pri_x,               # dovetail taper along primary axis
            taper_dir,           # constant dimension
            tenon_direction,     # extends toward primary
            narrow_w, wide_w, tail_w, socket_depth,
        )

        # Shoulder cut — must extend at least to the datum endpoint so
        # that shallow sockets don't leave a full-section stub past the
        # dovetail tip.
        #   approach_dist = distance from shoulder_face to datum endpoint
        #   socket_depth  = dovetail depth (may be shorter)
        cut_depth = max(socket_depth, approach_dist + 2.0)  # 2mm overshoot

        full_corner = (shoulder_face
                       - sec_y * (sec_w / 2.0)
                       - sec_z * (sec_h / 2.0))
        fp1 = full_corner
        fp2 = full_corner + sec_y * sec_w
        fp3 = full_corner + sec_y * sec_w + sec_z * sec_h
        fp4 = full_corner + sec_z * sec_h

        full_wire = Part.makePolygon([fp1, fp2, fp3, fp4, fp1])
        full_face = Part.Face(full_wire)
        full_box = full_face.extrude(tenon_direction * cut_depth)

        # Dovetail-shaped keep zone: only extends socket_depth (the
        # actual dovetail).  Material past the dovetail tip is fully
        # removed by the cut.
        dovetail_keep = _make_trapezoid_wire(
            tenon_center,
            pri_x, taper_dir, tenon_direction,
            narrow_w, wide_w, tail_w, socket_depth,
        )

        try:
            shoulder_cut = full_box.cut(dovetail_keep)
        except Exception:
            shoulder_cut = full_box

        return SecondaryProfile(
            tenon_shape=tenon,
            shoulder_cut=shoulder_cut,
        )

    # -- validation ---------------------------------------------------------

    def validate(self, params, primary, secondary, joint_cs):
        results = []
        sec_h = float(secondary.Height)
        sec_w = float(secondary.Width)
        pri_w = float(primary.Width)
        tail_w = params.get("tail_width")
        narrow_w = params.get("tail_base_width")
        socket_d = params.get("socket_depth")

        if tail_w > sec_w:
            results.append(ValidationResult(
                "warning",
                f"Dovetail width ({tail_w:.1f}mm) exceeds secondary "
                f"member width ({sec_w:.1f}mm).",
                "DOVETAIL_TOO_WIDE_TAIL",
            ))

        if narrow_w > sec_w * 0.8:
            results.append(ValidationResult(
                "warning",
                f"Dovetail base width ({narrow_w:.1f}mm) exceeds 80% of "
                f"secondary member width ({sec_w:.1f}mm).",
                "DOVETAIL_TOO_WIDE",
            ))

        if socket_d > pri_w * 0.6:
            results.append(ValidationResult(
                "warning",
                f"Socket depth ({socket_d:.1f}mm) exceeds 60% of primary "
                f"member width ({pri_w:.1f}mm). May weaken the primary.",
                "SOCKET_TOO_DEEP",
            ))

        if joint_cs.angle < self.MIN_ANGLE or joint_cs.angle > self.MAX_ANGLE:
            results.append(ValidationResult(
                "error",
                f"Intersection angle ({joint_cs.angle:.1f} deg) is outside "
                f"the valid range ({self.MIN_ANGLE}\u2013{self.MAX_ANGLE} deg).",
                "ANGLE_OUT_OF_RANGE",
            ))

        return results

    # -- fabrication signature ----------------------------------------------

    def fabrication_signature(self, params, primary, secondary, joint_cs):
        return {
            "joint_type": self.ID,
            "tail_base_width": params.get("tail_base_width"),
            "tail_end_width": params.get("tail_end_width"),
            "tail_width": params.get("tail_width"),
            "socket_depth": params.get("socket_depth"),
            "dovetail_angle": params.get("dovetail_angle"),
            "angle": round(joint_cs.angle, 1),
        }

    # -- structural properties (placeholder) --------------------------------

    def structural_properties(self, params, primary, secondary):
        return JointStructuralProperties()
