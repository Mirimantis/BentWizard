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
from joints.toolkit import (
    MemberFaceContext,
    build_face_context,
    member_local_cs,
    mortise_axes,
    shoulder_plane,
    face_pocket,
    face_tapered_pocket,
    tapered_tenon,
    shoulder_cut,
    approach_face_distance,
    secondary_extension_for_tenon,
    extent_along,
)


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

    # -- parameters ---------------------------------------------------------

    def get_parameters(self, primary, secondary, joint_cs):
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)

        # Build face context for correct approach geometry.
        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")

        # Dovetail axes (same computation as mortise_axes).
        w_dir, h_dir = mortise_axes(pri_ctx)

        _sec_o, _sec_x, sec_y, sec_z = member_local_cs(secondary)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        # Secondary extent along the dovetail height direction (primary grain).
        sec_extent_h = (abs(h_dir.dot(sec_y)) * sec_w
                        + abs(h_dir.dot(sec_z)) * sec_h)

        # Approach face distance and through extent.
        afd = approach_face_distance(pri_ctx)
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
        """
        # -- Socket depth max depends on channel mode ----------------------
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
        dh_param = params.get_param("dovetail_height")
        spread = 2.0 * effective_depth * math.tan(math.radians(angle))
        max_dh = sec_ext_h - spread
        max_dh = max(max_dh, dh_param.min_value)
        dh_param.max_value = max_dh
        if dh_param.value > max_dh:
            dh_param.value = max_dh

        # -- Clamp dovetail_angle so flare stays within secondary ---------
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

        Uses the toolkit's ``face_tapered_pocket()`` for the dovetail
        socket and ``face_pocket()`` for the optional housing.
        """
        clearance = params.get("clearance")
        dh = params.get("dovetail_height")
        flare_h = params.get("flare_height")
        socket_depth = params.get("socket_depth")
        housing_depth = params.get("housing_depth")
        channel_mode = params.get("channel_mode")
        flip = params.get("flip_channel")

        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        w_dir, h_dir = mortise_axes(pri_ctx)

        _sec_o, _sec_x, sec_y, sec_z = member_local_cs(secondary)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        # Channel extent along w_dir (perpendicular to primary grain).
        channel_extent = extent_along(pri_ctx, w_dir)

        extra = 2.0  # overshoot

        # Socket dimensions with clearance.
        narrow_sock = dh + 2 * clearance
        wide_sock = flare_h + 2 * clearance

        if channel_mode == CHANNEL_THROUGH:
            chan_length = channel_extent + 2 * extra
        else:
            chan_length = channel_extent / 2.0 + extra

        # For half-channel, offset the socket center.
        if channel_mode == CHANNEL_HALF:
            open_sign = -1.0 if flip else 1.0
            open_dir = w_dir * open_sign
            offset = open_dir * (channel_extent / 4.0)
        else:
            offset = None

        # Dovetail socket depth (from face or housing bottom).
        if housing_depth > 0.1:
            dovetail_depth = socket_depth - housing_depth
        else:
            dovetail_depth = socket_depth

        # Build the tapered pocket.
        # If housing exists, we need to offset the pocket start inward.
        if housing_depth > 0.1:
            # Build housing pocket first (rectangular, full secondary cross-section).
            sec_extent_w = (abs(w_dir.dot(sec_y)) * sec_w
                            + abs(w_dir.dot(sec_z)) * sec_h)
            sec_extent_h = (abs(h_dir.dot(sec_y)) * sec_w
                            + abs(h_dir.dot(sec_z)) * sec_h)
            hw = sec_extent_w + 2 * clearance
            hh = sec_extent_h + 2 * clearance

            if channel_mode == CHANNEL_THROUGH:
                hous_chan = max(channel_extent + 2 * extra, hw)
            else:
                hous_chan = max(chan_length, hw)

            housing = face_pocket(pri_ctx, hh, hous_chan, housing_depth,
                                  h_dir, w_dir, offset=offset)

            # Dovetail socket starts at housing bottom.
            # Build socket as a deeper pocket and fuse.
            socket = face_tapered_pocket(
                pri_ctx, narrow_sock, wide_sock, dovetail_depth,
                socket_depth, h_dir, w_dir,
                channel_extent=chan_length,
            )
            # Offset for half-channel mode.
            if offset is not None:
                # Rebuild with offset by translating the socket.
                socket_offset = face_tapered_pocket(
                    pri_ctx, narrow_sock, wide_sock, dovetail_depth,
                    socket_depth, h_dir, w_dir,
                    channel_extent=chan_length,
                )
                # The face_tapered_pocket centers on face_point; we need
                # to shift it.  For now, just build the full socket and
                # rely on the common() clipping.
                socket = socket_offset

            try:
                result = socket.fuse(housing)
            except Exception:
                result = socket
            return result
        else:
            # No housing: just the tapered socket.
            socket = face_tapered_pocket(
                pri_ctx, narrow_sock, wide_sock, chan_length,
                socket_depth, h_dir, w_dir,
                channel_extent=chan_length,
            )
            return socket

    # -- secondary extension ------------------------------------------------

    def secondary_extension(self, params, primary, secondary, joint_cs):
        """Extension past the datum endpoint for the dovetail tenon."""
        socket_depth = params.get("socket_depth")
        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        afd = approach_face_distance(pri_ctx)
        return max(0.0, socket_depth - afd)

    # -- secondary profile (dovetail tenon + shoulder) ----------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the dovetail tenon and shoulder cut.

        The shoulder sits flat against the primary's approach face.
        The dovetail tenon extends from the shoulder into the primary,
        aligned with the face normal.
        """
        dh = params.get("dovetail_height")
        flare_h = params.get("flare_height")
        socket_depth = params.get("socket_depth")
        housing_depth = params.get("housing_depth")
        channel_mode = params.get("channel_mode")
        flip = params.get("flip_channel")

        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        sec_ctx = build_face_context(secondary, primary, joint_cs, "secondary")
        w_dir, h_dir = mortise_axes(pri_ctx)

        _sec_o, sec_x, sec_y, sec_z = member_local_cs(secondary)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        # Secondary extent along channel direction.
        sec_extent_w = (abs(w_dir.dot(sec_y)) * sec_w
                        + abs(w_dir.dot(sec_z)) * sec_h)

        # Shoulder plane.
        sh_origin, sh_normal = shoulder_plane(pri_ctx, housing_depth)

        # Effective dovetail depth (from shoulder face).
        dovetail_depth = socket_depth - housing_depth

        # Tail extent and center offset for half-channel mode.
        if channel_mode == CHANNEL_HALF:
            tail_extent_w = sec_extent_w / 2.0
            open_sign = -1.0 if flip else 1.0
            tail_offset = w_dir * (open_sign * sec_extent_w / 4.0)
            tail_center = sh_origin + tail_offset
        else:
            tail_extent_w = sec_extent_w
            tail_center = sh_origin

        # Build dovetail tenon.
        tenon = tapered_tenon(
            sec_ctx, tail_center, sh_normal,
            dh, flare_h, dovetail_depth,
            h_dir, w_dir, tail_extent_w,
        )

        # Shoulder cut.
        cut = shoulder_cut(sec_ctx, sh_origin, sh_normal, keep_shape=tenon)

        # In half-channel mode with housing, trim the non-tail half.
        if channel_mode == CHANNEL_HALF and housing_depth > 0.1:
            open_sign = -1.0 if flip else 1.0
            open_dir = w_dir * open_sign
            clearance = params.get("clearance")

            # Replicate the housing boundary from build_primary_tool().
            channel_extent = extent_along(pri_ctx, w_dir)
            extra = 2.0
            chan_half = channel_extent / 2.0 + extra
            hous_w = sec_extent_w + 2 * clearance
            hous_chan = max(chan_half, hous_w)

            housing_non_tail = chan_half / 2.0 - hous_chan / 2.0

            sec_non_tail = -sec_extent_w / 2.0
            if housing_non_tail > sec_non_tail + 0.1:
                overshoot = max(sec_w, sec_h)

                # Determine tenon_direction for the trim slab.
                if sec_ctx.at_start:
                    tenon_direction = sec_ctx.axis * -1.0
                else:
                    tenon_direction = FreeCAD.Vector(sec_ctx.axis)

                afd = approach_face_distance(pri_ctx)
                approach_face_pt = sec_ctx.datum_point + tenon_direction * -1.0 * afd

                trim_edge = approach_face_pt + open_dir * housing_non_tail

                far_w = abs(sec_non_tail - housing_non_tail) + 2.0

                tc1 = trim_edge - open_dir * far_w - h_dir * overshoot
                tc2 = trim_edge - h_dir * overshoot
                tc3 = trim_edge + h_dir * overshoot
                tc4 = trim_edge - open_dir * far_w + h_dir * overshoot

                trim_wire = Part.makePolygon([tc1, tc2, tc3, tc4, tc1])
                trim_face = Part.Face(trim_wire)
                trim_slab = trim_face.extrude(tenon_direction * housing_depth)

                try:
                    cut = cut.fuse(trim_slab)
                except Exception:
                    pass

        return SecondaryProfile(
            tenon_shape=tenon,
            shoulder_cut=cut,
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

        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        w_dir, h_dir = mortise_axes(pri_ctx)

        afd = approach_face_distance(pri_ctx)
        through_extent = afd * 2.0

        # Primary extent in the dovetail height direction.
        pri_extent_h = extent_along(pri_ctx, h_dir)

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
