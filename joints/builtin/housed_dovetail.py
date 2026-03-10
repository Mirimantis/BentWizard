"""Dovetail --- a trapezoidal tenon in a matching socket.

The dovetail shape (narrow at the mouth, wider at the back) provides
withdrawal resistance, making this joint ideal for joist-to-beam or
beam-to-post connections.

The dovetail taper runs along the primary member's grain direction.
The socket channel runs perpendicular to both the grain and the
approach direction, allowing the secondary to slide in from the side.

Optional housing adds a shallow rectangular pocket around the socket
opening, providing bearing surface and rotation resistance.

This module must work headless --- no FreeCADGui / Qt imports.
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


def _approach_depth_dir(primary, secondary, joint_cs):
    """Return a unit vector pointing from the approach face INTO the primary."""
    _pri_o, pri_x, pri_y, _pri_z = _member_local_cs(primary)
    _sec_o, sec_x, _sec_y, _sec_z = _member_local_cs(secondary)

    sec_start = FreeCAD.Vector(secondary.A_StartPoint)
    sec_end = FreeCAD.Vector(secondary.B_EndPoint)
    dist_start = (joint_cs.origin - sec_start).Length
    dist_end = (joint_cs.origin - sec_end).Length

    sec_in_plane = sec_x - pri_x * sec_x.dot(pri_x)
    if sec_in_plane.Length < 1e-6:
        sec_in_plane = pri_y
    else:
        sec_in_plane.normalize()

    if dist_start <= dist_end:
        return sec_in_plane * -1.0
    return FreeCAD.Vector(sec_in_plane)


def _dovetail_axes(primary, secondary, joint_cs):
    """Return (w_dir, h_dir) for the dovetail geometry.

    h_dir runs along the primary grain (projected perpendicular to
    the approach direction) --- this is the dovetail taper direction.
    w_dir is perpendicular --- the channel direction.

    Same computation as ``_mortise_axes()`` in mortise_tenon.py.
    """
    _pri_o, pri_x, pri_y, pri_z = _member_local_cs(primary)
    depth_dir = _approach_depth_dir(primary, secondary, joint_cs)

    h_dir = pri_x - depth_dir * pri_x.dot(depth_dir)
    if h_dir.Length < 1e-6:
        _sec_o, _sec_x, sec_y, sec_z = _member_local_cs(secondary)
        return sec_y, sec_z

    h_dir.normalize()
    w_dir = depth_dir.cross(h_dir)
    w_dir.normalize()

    return w_dir, h_dir


def _make_trapezoid_solid(origin, taper_dir, channel_dir, depth_dir,
                          narrow_w, wide_w, channel_extent, depth):
    """Create a trapezoidal prism solid for a dovetail shape.

    The trapezoid tapers along ``taper_dir`` (narrow at entry, wide
    at back) and has constant extent along ``channel_dir``.

    Parameters
    ----------
    origin : FreeCAD.Vector
        Centre of the entry face.
    taper_dir : FreeCAD.Vector
        Unit vector along the taper (dovetail profile direction).
    channel_dir : FreeCAD.Vector
        Unit vector along the constant channel extent.
    depth_dir : FreeCAD.Vector
        Unit vector from entry face toward the wider back face.
    narrow_w : float
        Width along ``taper_dir`` at the entry face.
    wide_w : float
        Width along ``taper_dir`` at the back face.
    channel_extent : float
        Extent along ``channel_dir`` (constant).
    depth : float
        Depth from entry to back along ``depth_dir``.
    """
    hw_n = narrow_w / 2.0
    hw_w = wide_w / 2.0
    hc = channel_extent / 2.0

    # Entry face (narrow).
    e1 = origin - taper_dir * hw_n - channel_dir * hc
    e2 = origin + taper_dir * hw_n - channel_dir * hc
    e3 = origin + taper_dir * hw_n + channel_dir * hc
    e4 = origin - taper_dir * hw_n + channel_dir * hc

    # Back face (wide).
    back = origin + depth_dir * depth
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
        "connections.  Optional housing adds a bearing pocket."
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

    # -- approach face helpers ----------------------------------------------

    @staticmethod
    def _approach_face_distance(primary, secondary, joint_cs):
        """Distance from primary centerline to its approach face."""
        _pri_o, pri_x, pri_y, pri_z = _member_local_cs(primary)
        depth_dir = _approach_depth_dir(primary, secondary, joint_cs)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)
        through_extent = (abs(depth_dir.dot(pri_y)) * pri_w
                          + abs(depth_dir.dot(pri_z)) * pri_h)
        return through_extent / 2.0

    # -- parameters ---------------------------------------------------------

    def get_parameters(self, primary, secondary, joint_cs):
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)

        # Dovetail axes.
        w_dir, h_dir = _dovetail_axes(primary, secondary, joint_cs)
        _pri_o, _pri_x, pri_y, pri_z = _member_local_cs(primary)
        _sec_o, _sec_x, sec_y, sec_z = _member_local_cs(secondary)

        # Secondary extent along the dovetail height direction (primary grain).
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)
        sec_extent_h = (abs(h_dir.dot(sec_y)) * sec_w
                        + abs(h_dir.dot(sec_z)) * sec_h)

        # Approach face distance and through extent.
        afd = self._approach_face_distance(primary, secondary, joint_cs)
        through_extent = afd * 2.0

        # Socket depth: half the primary through-extent.
        socket_depth = through_extent * 0.5

        # Dovetail angle (standard 1:4 slope).
        dovetail_angle = 14.0

        # Dovetail height at the narrow end (neck), along primary grain.
        dovetail_height = sec_extent_h * 0.5

        # Housing depth (default: none).
        housing_depth = 0.0

        # Clearance per side.
        clearance = 1.6

        # Flare height (derived).
        effective_depth = socket_depth - housing_depth
        spread = 2.0 * effective_depth * math.tan(math.radians(dovetail_angle))
        flare_height = dovetail_height + spread

        # Primary cross-section extent in the dovetail height direction
        # (for max-value clamping).
        pri_extent_h = (abs(h_dir.dot(pri_y)) * pri_w
                        + abs(h_dir.dot(pri_z)) * pri_h)

        params = [
            # -- Dovetail --
            JointParameter("dovetail_height", "length",
                           dovetail_height, dovetail_height,
                           min_value=20.0, max_value=sec_extent_h,
                           group="Dovetail",
                           description="Height at the narrow end (neck), "
                                       "along primary grain"),
            JointParameter("dovetail_angle", "angle",
                           dovetail_angle, dovetail_angle,
                           min_value=8.0, max_value=20.0,
                           group="Dovetail",
                           description="Taper angle (standard 1:4 = 14\u00b0)"),
            JointParameter("flare_height", "length",
                           flare_height, flare_height,
                           min_value=dovetail_height,
                           group="Dovetail",
                           description="Height at the wide end (flare), "
                                       "derived from neck + angle + depth",
                           read_only=True),
            JointParameter("sec_extent_h", "length",
                           sec_extent_h, sec_extent_h,
                           group="Dovetail",
                           description="Secondary member extent along "
                                       "primary grain (reference)",
                           read_only=True),
            # -- Socket --
            JointParameter("socket_depth", "length",
                           socket_depth, socket_depth,
                           min_value=through_extent * 0.25,
                           max_value=through_extent * 0.50,
                           group="Socket",
                           description="Total depth of socket from "
                                       "approach face into primary"),
            JointParameter("primary_depth", "length",
                           through_extent, through_extent,
                           group="Socket",
                           description="Primary member depth in the "
                                       "approach direction (reference)",
                           read_only=True),
            JointParameter("housing_depth", "length",
                           housing_depth, housing_depth,
                           min_value=0.0, max_value=socket_depth * 0.5,
                           group="Socket",
                           description="Housing pocket depth "
                                       "(0 = no housing)"),
            JointParameter("clearance", "length",
                           clearance, clearance,
                           min_value=0.0, max_value=3.0,
                           group="Socket",
                           description="Clearance per side "
                                       "(socket = tail + 2\u00d7 clearance)"),
            JointParameter("channel_mode", "enumeration",
                           CHANNEL_THROUGH, CHANNEL_THROUGH,
                           group="Socket",
                           description="Through = open both sides; "
                                       "Half = open toward one edge",
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
        """Keep flare_height in sync and clamp height/angle so the flare
        never exceeds the secondary member's extent along primary grain.

        Order matters: socket_depth and housing_depth are clamped first
        because they feed effective_depth which drives all the dovetail
        height/angle limits.
        """
        # -- Socket depth max depends on channel mode ----------------------
        # Through mode: max 50% of primary depth (preserves structural
        # integrity when the socket passes through the full width).
        # Half mode: max 75% (the remaining half maintains structure).
        primary_depth = params.get("primary_depth")
        channel_mode = params.get("channel_mode")
        sd_param = params.get_param("socket_depth")
        if channel_mode == CHANNEL_THROUGH:
            sd_param.max_value = primary_depth * 0.50
        else:
            sd_param.max_value = primary_depth * 0.75
        if sd_param.value > sd_param.max_value:
            sd_param.value = sd_param.max_value

        # Keep housing_depth max at half of socket_depth.
        hd_param = params.get_param("housing_depth")
        hd_param.max_value = sd_param.value * 0.5
        if hd_param.value > hd_param.max_value:
            hd_param.value = hd_param.max_value

        # -- Now read clamped values for downstream calculations -----------
        sd = sd_param.value
        hd = hd_param.value
        angle = params.get("dovetail_angle")
        sec_ext_h = params.get("sec_extent_h")

        effective_depth = max(0.0, sd - hd)

        # -- Clamp dovetail_height so flare stays within secondary --------
        # flare = dh + 2 * effective_depth * tan(angle)  <=  sec_ext_h
        # => max dh = sec_ext_h - 2 * effective_depth * tan(angle)
        dh_param = params.get_param("dovetail_height")
        spread = 2.0 * effective_depth * math.tan(math.radians(angle))
        max_dh = sec_ext_h - spread
        max_dh = max(max_dh, dh_param.min_value)
        dh_param.max_value = max_dh
        if dh_param.value > max_dh:
            dh_param.value = max_dh

        # -- Clamp dovetail_angle so flare stays within secondary ---------
        # flare = dh + 2 * effective_depth * tan(angle)  <=  sec_ext_h
        # => max angle = atan((sec_ext_h - dh) / (2 * effective_depth))
        angle_param = params.get_param("dovetail_angle")
        if effective_depth > 0.1:
            remaining = max(0.0, sec_ext_h - dh_param.value)
            max_angle = math.degrees(
                math.atan(remaining / (2.0 * effective_depth)))
            max_angle = min(max_angle, 20.0)
            max_angle = max(max_angle, angle_param.min_value)
        else:
            max_angle = 20.0
        angle_param.max_value = max_angle
        if angle_param.value > max_angle:
            angle_param.value = max_angle

        # -- Recompute flare from (potentially clamped) values ------------
        final_spread = (2.0 * effective_depth
                        * math.tan(math.radians(angle_param.value)))
        new_flare = dh_param.value + final_spread

        flare_param = params.get_param("flare_height")
        if not flare_param.is_overridden:
            flare_param.default_value = new_flare
            flare_param.value = new_flare
        flare_param.min_value = dh_param.value

    # -- primary cut (dovetail socket + housing) ----------------------------

    def build_primary_tool(self, params, primary, secondary, joint_cs):
        """Build the dovetail socket to subtract from the primary member.

        The socket channel runs along ``w_dir`` (perpendicular to primary
        grain).  The dovetail taper (narrow at mouth, wide at back) runs
        along ``h_dir`` (primary grain direction).

        When ``housing_depth > 0``, a wider rectangular pocket is cut
        from the approach face to the housing depth, then the dovetail
        socket continues from the housing bottom to ``socket_depth``.
        """
        clearance = params.get("clearance")
        dh = params.get("dovetail_height")
        flare_h = params.get("flare_height")
        socket_depth = params.get("socket_depth")
        housing_depth = params.get("housing_depth")
        channel_mode = params.get("channel_mode")
        flip = params.get("flip_channel")

        w_dir, h_dir = _dovetail_axes(primary, secondary, joint_cs)
        _pri_o, _pri_x, pri_y, pri_z = _member_local_cs(primary)
        _sec_o, _sec_x, sec_y, sec_z = _member_local_cs(secondary)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        depth_dir = _approach_depth_dir(primary, secondary, joint_cs)
        afd = self._approach_face_distance(primary, secondary, joint_cs)
        approach_face = joint_cs.origin - depth_dir * afd

        # Channel extent along w_dir (perpendicular to primary grain).
        channel_extent = (abs(w_dir.dot(pri_y)) * pri_w
                          + abs(w_dir.dot(pri_z)) * pri_h)

        extra = 2.0  # mm overshoot for boolean reliability

        if channel_mode == CHANNEL_THROUGH:
            chan_length = channel_extent + 2 * extra
            chan_center = approach_face
        else:
            chan_half = channel_extent / 2.0 + extra
            open_sign = -1.0 if flip else 1.0
            open_dir = w_dir * open_sign
            chan_length = chan_half
            chan_center = approach_face + open_dir * (chan_half / 2.0)

        # Dovetail socket: trapezoidal, from approach face (or housing
        # bottom) to socket_depth.
        if housing_depth > 0.1:
            # Housing bottom is the start of the dovetail taper.
            dovetail_start = approach_face + depth_dir * housing_depth
            dovetail_depth = socket_depth - housing_depth
        else:
            dovetail_start = approach_face
            dovetail_depth = socket_depth

        # Adjust center for half-channel offset (relative to approach_face).
        if channel_mode == CHANNEL_THROUGH:
            dt_center = dovetail_start
        else:
            dt_center = dovetail_start + (chan_center - approach_face)

        # Overshoot: extend socket slightly past approach face for booleans.
        dt_origin = dt_center - depth_dir * extra
        dt_total_depth = dovetail_depth + extra

        narrow_sock = dh + 2 * clearance
        wide_sock = flare_h + 2 * clearance

        socket = _make_trapezoid_solid(
            dt_origin,
            h_dir,           # taper direction (primary grain)
            w_dir,           # channel direction
            depth_dir,       # into primary
            narrow_sock,     # narrow at mouth
            wide_sock,       # wide at back
            chan_length,     # channel extent
            dt_total_depth,  # depth
        )

        # Housing pocket: full secondary cross-section + clearance,
        # from approach face to housing_depth.
        if housing_depth > 0.1:
            sec_extent_w = (abs(w_dir.dot(sec_y)) * sec_w
                            + abs(w_dir.dot(sec_z)) * sec_h)
            sec_extent_h = (abs(h_dir.dot(sec_y)) * sec_w
                            + abs(h_dir.dot(sec_z)) * sec_h)
            hw = sec_extent_w + 2 * clearance
            hh = sec_extent_h + 2 * clearance

            if channel_mode == CHANNEL_THROUGH:
                hous_center = approach_face
                hous_chan = max(chan_length, hw)
            else:
                hous_center = chan_center
                hous_chan = max(chan_length, hw)

            hous_origin = hous_center - depth_dir * extra

            hous_corner = (hous_origin
                           - h_dir * (hh / 2.0)
                           - w_dir * (hous_chan / 2.0))
            hp1 = hous_corner
            hp2 = hous_corner + h_dir * hh
            hp3 = hous_corner + h_dir * hh + w_dir * hous_chan
            hp4 = hous_corner + w_dir * hous_chan

            hous_wire = Part.makePolygon([hp1, hp2, hp3, hp4, hp1])
            hous_face = Part.Face(hous_wire)
            housing = hous_face.extrude(depth_dir * (housing_depth + extra))

            try:
                socket = socket.fuse(housing)
            except Exception:
                pass  # fall back to socket alone

        return socket

    # -- secondary extension ------------------------------------------------

    def secondary_extension(self, params, primary, secondary, joint_cs):
        """Extension past the datum endpoint for the dovetail tenon."""
        socket_depth = params.get("socket_depth")
        afd = self._approach_face_distance(primary, secondary, joint_cs)
        return max(0.0, socket_depth - afd)

    # -- secondary profile (dovetail tenon + shoulder) ----------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the dovetail tenon and shoulder cut.

        The shoulder face is at ``approach_face + housing_depth`` into
        the primary (same pattern as M&T housing).  The dovetail tenon
        extends from the shoulder face for ``socket_depth - housing_depth``.

        In Through mode the tenon spans the full secondary width along
        ``w_dir``.  In Half mode the tenon is reduced to half-width and
        offset to match the half-channel socket.
        """
        dh = params.get("dovetail_height")
        flare_h = params.get("flare_height")
        socket_depth = params.get("socket_depth")
        housing_depth = params.get("housing_depth")
        channel_mode = params.get("channel_mode")
        flip = params.get("flip_channel")

        w_dir, h_dir = _dovetail_axes(primary, secondary, joint_cs)
        _sec_o, sec_x, sec_y, sec_z = _member_local_cs(secondary)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        # Secondary extent along channel direction (full width).
        sec_extent_w = (abs(w_dir.dot(sec_y)) * sec_w
                        + abs(w_dir.dot(sec_z)) * sec_h)

        sec_start = FreeCAD.Vector(secondary.A_StartPoint)
        sec_end = FreeCAD.Vector(secondary.B_EndPoint)

        dist_start = (joint_cs.origin - sec_start).Length
        dist_end = (joint_cs.origin - sec_end).Length

        if dist_start <= dist_end:
            tenon_direction = sec_x * -1.0
            shoulder_origin = sec_start
        else:
            tenon_direction = sec_x
            shoulder_origin = sec_end

        inward_dir = tenon_direction * -1.0

        depth_dir = _approach_depth_dir(primary, secondary, joint_cs)
        afd = self._approach_face_distance(primary, secondary, joint_cs)
        approach_face_pt = shoulder_origin + inward_dir * afd

        # Shoulder face: approach face + housing_depth into primary.
        shoulder_face = approach_face_pt + tenon_direction * housing_depth

        # Effective dovetail depth (from shoulder face).
        dovetail_depth = socket_depth - housing_depth

        # Tail extent and center offset for half-channel mode.
        if channel_mode == CHANNEL_HALF:
            tail_extent_w = sec_extent_w / 2.0
            open_sign = -1.0 if flip else 1.0
            tail_offset = w_dir * (open_sign * sec_extent_w / 4.0)
        else:
            tail_extent_w = sec_extent_w
            tail_offset = FreeCAD.Vector(0, 0, 0)

        tail_center = shoulder_face + tail_offset

        # Build tenon: trapezoidal, from shoulder face into primary.
        tenon = _make_trapezoid_solid(
            tail_center,
            h_dir,                # taper direction (primary grain)
            w_dir,                # channel direction
            tenon_direction,      # extends toward primary
            dh,                   # narrow at shoulder (neck)
            flare_h,              # wide at back (flare)
            tail_extent_w,        # half or full secondary width
            dovetail_depth,       # depth from shoulder to socket bottom
        )

        # Shoulder cut: removes full cross-section from shoulder face
        # outward, keeping only the dovetail tenon.
        datum_reach = afd - housing_depth
        cut_depth = max(dovetail_depth, datum_reach + 2.0)

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

        # Dovetail keep zone: same shape as tenon.
        dovetail_keep = _make_trapezoid_solid(
            tail_center,
            h_dir, w_dir, tenon_direction,
            dh, flare_h, tail_extent_w, dovetail_depth,
        )

        try:
            shoulder_cut = full_box.cut(dovetail_keep)
        except Exception:
            shoulder_cut = full_box

        # In half-channel mode with housing, the non-tail half of the
        # secondary must not extend past the approach face.  The main
        # shoulder cut starts at shoulder_face (= approach + housing_depth),
        # so material outside the housing footprint has housing_depth of
        # extra stock that seats into a pocket that doesn't exist.
        #
        # The housing pocket in the primary is wider than the half-tail
        # (it accommodates the full secondary cross-section + clearance)
        # and offset toward the open side.  The trim slab boundary must
        # match the housing's non-tail edge, not the secondary centerline.
        if channel_mode == CHANNEL_HALF and housing_depth > 0.1:
            open_sign = -1.0 if flip else 1.0
            open_dir = w_dir * open_sign
            clearance = params.get("clearance")

            # Replicate the housing boundary from build_primary_tool().
            _pri_o, _pri_x, pri_y, pri_z = _member_local_cs(primary)
            pri_w = float(primary.Width)
            pri_h = float(primary.Height)
            channel_extent = (abs(w_dir.dot(pri_y)) * pri_w
                              + abs(w_dir.dot(pri_z)) * pri_h)
            extra = 2.0
            chan_half = channel_extent / 2.0 + extra
            hous_w = sec_extent_w + 2 * clearance
            hous_chan = max(chan_half, hous_w)

            # Housing center is offset by chan_half/2 in open_dir.
            # Non-tail edge of housing in open_dir from approach_face_pt:
            housing_non_tail = chan_half / 2.0 - hous_chan / 2.0

            # Only trim if the secondary extends past the housing edge.
            sec_non_tail = -sec_extent_w / 2.0
            if housing_non_tail > sec_non_tail + 0.1:
                overshoot = max(sec_w, sec_h)

                # Trim boundary in world space.
                trim_edge = approach_face_pt + open_dir * housing_non_tail

                # Far edge: past the secondary's non-tail extent.
                far_w = abs(sec_non_tail - housing_non_tail) + 2.0

                tc1 = (trim_edge
                       - open_dir * far_w - h_dir * overshoot)
                tc2 = (trim_edge
                       - h_dir * overshoot)
                tc3 = (trim_edge
                       + h_dir * overshoot)
                tc4 = (trim_edge
                       - open_dir * far_w + h_dir * overshoot)

                trim_wire = Part.makePolygon([tc1, tc2, tc3, tc4, tc1])
                trim_face = Part.Face(trim_wire)
                trim_slab = trim_face.extrude(
                    tenon_direction * housing_depth)

                try:
                    shoulder_cut = shoulder_cut.fuse(trim_slab)
                except Exception:
                    pass  # fall back to shoulder_cut alone

        return SecondaryProfile(
            tenon_shape=tenon,
            shoulder_cut=shoulder_cut,
        )

    # -- validation ---------------------------------------------------------

    def validate(self, params, primary, secondary, joint_cs):
        results = []
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)

        dh = params.get("dovetail_height")
        flare_h = params.get("flare_height")
        socket_depth = params.get("socket_depth")
        housing_depth = params.get("housing_depth")

        w_dir, h_dir = _dovetail_axes(primary, secondary, joint_cs)
        _pri_o, _pri_x, pri_y, pri_z = _member_local_cs(primary)

        afd = self._approach_face_distance(primary, secondary, joint_cs)
        through_extent = afd * 2.0

        # Primary extent in the dovetail height direction.
        pri_extent_h = (abs(h_dir.dot(pri_y)) * pri_w
                        + abs(h_dir.dot(pri_z)) * pri_h)

        # Flare exceeds primary cross-section.
        if pri_extent_h > 1.0 and flare_h > pri_extent_h * 0.75:
            results.append(ValidationResult(
                "error",
                f"Flare height ({flare_h:.1f}mm) exceeds 75% of primary "
                f"cross-section ({pri_extent_h:.1f}mm) along grain. "
                f"Reduce dovetail_height or dovetail_angle.",
                "FLARE_EXCEEDS_PRIMARY",
            ))

        # Socket too deep.
        if socket_depth > through_extent * 0.60:
            results.append(ValidationResult(
                "warning",
                f"Socket depth ({socket_depth:.1f}mm) exceeds 60% of "
                f"primary through-dimension ({through_extent:.1f}mm). "
                f"May weaken the primary.",
                "SOCKET_TOO_DEEP",
            ))

        # Housing deeper than socket.
        if housing_depth >= socket_depth:
            results.append(ValidationResult(
                "error",
                f"Housing depth ({housing_depth:.1f}mm) must be less "
                f"than socket depth ({socket_depth:.1f}mm).",
                "HOUSING_EXCEEDS_SOCKET",
            ))

        # Angle range.
        if joint_cs.angle < self.MIN_ANGLE or joint_cs.angle > self.MAX_ANGLE:
            results.append(ValidationResult(
                "error",
                f"Intersection angle ({joint_cs.angle:.1f}\u00b0) is outside "
                f"the valid range ({self.MIN_ANGLE}\u2013{self.MAX_ANGLE}\u00b0).",
                "ANGLE_OUT_OF_RANGE",
            ))

        return results

    # -- fabrication signature ----------------------------------------------

    def fabrication_signature(self, params, primary, secondary, joint_cs):
        return {
            "joint_type": self.ID,
            "dovetail_height": params.get("dovetail_height"),
            "dovetail_angle": params.get("dovetail_angle"),
            "socket_depth": params.get("socket_depth"),
            "housing_depth": params.get("housing_depth"),
            "angle": round(joint_cs.angle, 1),
        }

    # -- structural properties (placeholder) --------------------------------

    def structural_properties(self, params, primary, secondary):
        return JointStructuralProperties()
