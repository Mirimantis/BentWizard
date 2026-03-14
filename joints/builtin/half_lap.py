"""Half Lap --- midpoint-to-midpoint crossing joint.

Both members are notched to half their depth at the crossing point so
their top surfaces remain flush.  Common for crossing girts, purlins,
or other members that cross at mid-span.

This module must work headless --- no FreeCADGui / Qt imports.
"""

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
    lap_notch,
    extent_along,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _crossing_footprint(host_ctx, other_obj):
    """Compute the extent of the other member's cross-section along the host's datum.

    For a 90-degree crossing of a vertical post (150x200) through a
    horizontal beam, this returns the post's *width* (150) along the
    beam's datum, not the post's height.
    """
    _o, _ox, oy, oz = member_local_cs(other_obj)
    w = float(other_obj.Width)
    h = float(other_obj.Height)
    return abs(oy.dot(host_ctx.axis)) * w + abs(oz.dot(host_ctx.axis)) * h


# ---------------------------------------------------------------------------
# Joint Definition
# ---------------------------------------------------------------------------

class HalfLapDefinition(TimberJointDefinition):
    """Half lap joint definition."""

    NAME = "Half Lap"
    ID = "half_lap"
    CATEGORY = "Lap Joints"
    DESCRIPTION = (
        "Both members are notched to half their depth at the crossing point. "
        "Top surfaces remain flush when assembled."
    )
    ICON = ""
    DIAGRAM = ""

    PRIMARY_ROLES = [
        "Beam", "Girt", "Plate", "Sill", "Purlin", "TieBeam",
    ]
    SECONDARY_ROLES = [
        "Beam", "Girt", "Plate", "Sill", "Purlin", "TieBeam",
    ]
    MIN_ANGLE = 60.0
    MAX_ANGLE = 120.0

    # -- parameters ---------------------------------------------------------

    def get_parameters(self, primary, secondary, joint_cs):
        pri_h = float(primary.Height)
        pri_w = float(primary.Width)
        sec_h = float(secondary.Height)
        sec_w = float(secondary.Width)

        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        sec_ctx = build_face_context(secondary, primary, joint_cs, "secondary")

        clearance = 1.6  # 1/16 inch

        # The notch width along each host's datum is the crossing member's
        # footprint projected onto that axis.
        sec_footprint = _crossing_footprint(pri_ctx, secondary)
        pri_footprint = _crossing_footprint(sec_ctx, primary)

        # Fallback: if footprint is near-zero (parallel datums --- shouldn't
        # happen for a valid joint), use the crossing member's width.
        if sec_footprint < 1.0:
            sec_footprint = sec_w
        if pri_footprint < 1.0:
            pri_footprint = pri_w

        params = [
            JointParameter("lap_depth_primary", "length",
                           pri_h / 2.0, pri_h / 2.0,
                           min_value=pri_h * 0.25, max_value=pri_h * 0.75,
                           group="Lap",
                           description="Depth of notch in primary member"),
            JointParameter("lap_depth_secondary", "length",
                           sec_h / 2.0, sec_h / 2.0,
                           min_value=sec_h * 0.25, max_value=sec_h * 0.75,
                           group="Lap",
                           description="Depth of notch in secondary member"),
            JointParameter("lap_width_primary", "length",
                           sec_footprint + clearance,
                           sec_footprint + clearance,
                           min_value=10.0,
                           group="Lap",
                           description="Width of notch in primary (accepts secondary)"),
            JointParameter("lap_width_secondary", "length",
                           pri_footprint + clearance,
                           pri_footprint + clearance,
                           min_value=10.0,
                           group="Lap",
                           description="Width of notch in secondary (accepts primary)"),
        ]
        return ParameterSet(params)

    # -- primary cut --------------------------------------------------------

    def build_primary_tool(self, params, primary, secondary, joint_cs):
        """Build the notch to subtract from the primary member.

        Uses the toolkit's ``lap_notch()`` to cut from the face closest
        to the secondary member, rather than hardcoding "top" or "bottom".
        """
        lap_depth = params.get("lap_depth_primary")
        lap_width = params.get("lap_width_primary")

        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")

        # The notch is on the face of the primary that faces the secondary.
        # Use the joint normal as the face direction hint.
        # For a standard lap joint, the primary is notched from the face
        # that the secondary approaches from.
        face_dir = pri_ctx.face_normal * -1.0  # outward normal toward secondary

        notch = lap_notch(pri_ctx, lap_width, lap_depth, face_dir)

        return notch

    # -- secondary profile --------------------------------------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the notch for the secondary member.

        The secondary is notched from the opposite face (facing away from
        the primary) so the two halves nest together.
        """
        lap_depth = params.get("lap_depth_secondary")
        lap_width = params.get("lap_width_secondary")

        sec_ctx = build_face_context(secondary, primary, joint_cs, "secondary")

        # The secondary is notched from the face AWAY from the primary,
        # so the two halves interlock.
        face_dir = sec_ctx.face_normal * -1.0  # outward toward primary
        opposite_dir = face_dir * -1.0         # opposite face

        shoulder_cut_shape = lap_notch(sec_ctx, lap_width, lap_depth, opposite_dir)

        # The "tenon" for visualization: the remaining half-section that
        # nests into the other member's notch.
        # Build it as the intersection zone.
        sec_h = float(secondary.Height)
        sec_w = float(secondary.Width)
        remaining_h = sec_h - lap_depth
        if remaining_h < 1.0:
            remaining_h = 1.0

        # Build a simple box for the tenon visualization.
        origin = joint_cs.origin

        # Use the same face direction logic to figure out which half remains.
        # The tenon is on the primary-facing side of the secondary.
        tenon_face_outward = face_dir
        tenon_face_inward = tenon_face_outward * -1.0

        # Distance from datum center to the face.
        half_ext = (abs(tenon_face_outward.dot(sec_ctx.y_dir)) * sec_w
                    + abs(tenon_face_outward.dot(sec_ctx.z_dir)) * sec_h) / 2.0

        # Through direction (perpendicular to datum and face normal).
        through_dir = sec_ctx.axis.cross(tenon_face_outward)
        if through_dir.Length < 1e-6:
            through_dir = sec_ctx.y_dir
        else:
            through_dir.normalize()
        through_extent = (abs(through_dir.dot(sec_ctx.y_dir)) * sec_w
                          + abs(through_dir.dot(sec_ctx.z_dir)) * sec_h)

        # Tenon: from face inward by remaining_h, centered on intersection.
        face_pos = origin + tenon_face_outward * half_ext
        tenon_corner = (face_pos
                        + tenon_face_inward * remaining_h
                        - sec_ctx.axis * (lap_width / 2.0)
                        - through_dir * (through_extent / 2.0))

        tp1 = tenon_corner
        tp2 = tenon_corner + sec_ctx.axis * lap_width
        tp3 = tenon_corner + sec_ctx.axis * lap_width + tenon_face_outward * remaining_h
        tp4 = tenon_corner + tenon_face_outward * remaining_h

        try:
            tenon_wire = Part.makePolygon([tp1, tp2, tp3, tp4, tp1])
            tenon_face = Part.Face(tenon_wire)
            tenon_shape = tenon_face.extrude(through_dir * through_extent)
        except Exception:
            tenon_shape = Part.makeBox(1, 1, 1)

        return SecondaryProfile(
            tenon_shape=tenon_shape,
            shoulder_cut=shoulder_cut_shape,
        )

    # -- validation ---------------------------------------------------------

    def validate(self, params, primary, secondary, joint_cs):
        results = []
        pri_h = float(primary.Height)
        sec_h = float(secondary.Height)
        lap_d_pri = params.get("lap_depth_primary")
        lap_d_sec = params.get("lap_depth_secondary")

        if lap_d_pri > pri_h * 0.6:
            results.append(ValidationResult(
                "warning",
                f"Primary lap depth ({lap_d_pri:.1f}mm) exceeds 60% of "
                f"member height ({pri_h:.1f}mm).",
                "LAP_TOO_DEEP",
            ))

        if lap_d_sec > sec_h * 0.6:
            results.append(ValidationResult(
                "warning",
                f"Secondary lap depth ({lap_d_sec:.1f}mm) exceeds 60% of "
                f"member height ({sec_h:.1f}mm).",
                "LAP_TOO_DEEP",
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
            "lap_depth_primary": params.get("lap_depth_primary"),
            "lap_depth_secondary": params.get("lap_depth_secondary"),
            "lap_width_primary": params.get("lap_width_primary"),
            "lap_width_secondary": params.get("lap_width_secondary"),
            "angle": round(joint_cs.angle, 1),
        }

    # -- structural properties (placeholder) --------------------------------

    def structural_properties(self, params, primary, secondary):
        return JointStructuralProperties()
