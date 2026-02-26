"""Half Lap — midpoint-to-midpoint crossing joint.

Both members are notched to half their depth at the crossing point so
their top surfaces remain flush.  Common for crossing girts, purlins,
or other members that cross at mid-span.

This module must work headless — no FreeCADGui / Qt imports.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _member_local_cs(obj):
    """Return the member local coordinate system (origin, x, y, z)."""
    start = FreeCAD.Vector(obj.StartPoint)
    end = FreeCAD.Vector(obj.EndPoint)
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


def _crossing_footprint(host_x, other_obj):
    """Compute the extent of the other member's cross-section along host_x.

    For a 90-degree crossing of a vertical post (150x200) through a
    horizontal beam, this returns the post's *width* (150) along the
    beam's datum, not the post's height.
    """
    _o, _ox, oy, oz = _member_local_cs(other_obj)
    w = float(other_obj.Width)
    h = float(other_obj.Height)
    return abs(oy.dot(host_x)) * w + abs(oz.dot(host_x)) * h


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

        _pri_o, pri_x, _pri_y, _pri_z = _member_local_cs(primary)
        _sec_o, sec_x, _sec_y, _sec_z = _member_local_cs(secondary)

        clearance = 1.6  # 1/16 inch

        # The notch width along each host's datum is the crossing member's
        # footprint projected onto that axis.
        sec_footprint = _crossing_footprint(pri_x, secondary)
        pri_footprint = _crossing_footprint(sec_x, primary)

        # Fallback: if footprint is near-zero (parallel datums — shouldn't
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

        The notch is constructed entirely in the primary member's local
        coordinate system (pri_x, pri_y, pri_z) to avoid degeneracy when
        the crossing member's direction is parallel to the host's height.
        """
        lap_depth = params.get("lap_depth_primary")
        lap_width = params.get("lap_width_primary")

        _pri_o, pri_x, pri_y, pri_z = _member_local_cs(primary)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)
        extra = 2.0

        origin = joint_cs.origin

        # The notch is a box:
        #   Along pri_x (datum): lap_width, centred on intersection
        #   Along pri_y (width): full member width + extra (through-cut)
        #   Along pri_z (height): lap_depth from the top face downward

        # Corner = bottom-corner of the notch box.
        # For "Bottom" reference: top face is at datum + pri_z * pri_h,
        # so notch goes from (pri_h - lap_depth) to pri_h in local z.
        ref = primary.ReferenceFace
        if ref == "Bottom":
            z_top = pri_h
        elif ref == "Top":
            z_top = 0.0
        elif ref in ("Left", "Right"):
            z_top = pri_h / 2.0
        else:
            z_top = pri_h

        corner = (origin
                  - pri_x * (lap_width / 2.0)
                  - pri_y * ((pri_w + 2 * extra) / 2.0)
                  + pri_z * (z_top - lap_depth))

        # Profile rectangle in the pri_x / pri_z plane.
        p1 = corner
        p2 = corner + pri_x * lap_width
        p3 = corner + pri_x * lap_width + pri_z * lap_depth
        p4 = corner + pri_z * lap_depth

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)
        notch = face.extrude(pri_y * (pri_w + 2 * extra))

        return notch

    # -- secondary profile --------------------------------------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the notch for the secondary member.

        Same approach as primary — entirely in the secondary member's
        local coordinate system.
        """
        lap_depth = params.get("lap_depth_secondary")
        lap_width = params.get("lap_width_secondary")

        _sec_o, sec_x, sec_y, sec_z = _member_local_cs(secondary)
        sec_h = float(secondary.Height)
        sec_w = float(secondary.Width)
        extra = 2.0

        origin = joint_cs.origin

        # The notch is cut from the BOTTOM face (opposite the primary's
        # top-face notch, so the two halves nest together).
        ref = secondary.ReferenceFace
        if ref == "Bottom":
            z_bottom = 0.0
        elif ref == "Top":
            z_bottom = -sec_h
        elif ref in ("Left", "Right"):
            z_bottom = -sec_h / 2.0
        else:
            z_bottom = 0.0

        corner = (origin
                  - sec_x * (lap_width / 2.0)
                  - sec_y * ((sec_w + 2 * extra) / 2.0)
                  + sec_z * z_bottom)

        # Profile rectangle in the sec_x / sec_z plane.
        p1 = corner
        p2 = corner + sec_x * lap_width
        p3 = corner + sec_x * lap_width + sec_z * lap_depth
        p4 = corner + sec_z * lap_depth

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)
        shoulder_cut = face.extrude(sec_y * (sec_w + 2 * extra))

        # The "tenon" for visualization: the remaining half-section that
        # nests into the other member's notch.
        tenon_corner = (origin
                        - sec_x * (lap_width / 2.0)
                        - sec_y * (sec_w / 2.0)
                        + sec_z * lap_depth)

        # Tenon extends from lap_depth to full height.
        remaining_h = sec_h - lap_depth
        if remaining_h < 1.0:
            remaining_h = 1.0

        tp1 = tenon_corner
        tp2 = tenon_corner + sec_x * lap_width
        tp3 = tenon_corner + sec_x * lap_width + sec_z * remaining_h
        tp4 = tenon_corner + sec_z * remaining_h

        tenon_wire = Part.makePolygon([tp1, tp2, tp3, tp4, tp1])
        tenon_face = Part.Face(tenon_wire)
        tenon_shape = tenon_face.extrude(sec_y * sec_w)

        return SecondaryProfile(
            tenon_shape=tenon_shape,
            shoulder_cut=shoulder_cut,
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
                f"the valid range ({self.MIN_ANGLE}–{self.MAX_ANGLE} deg).",
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
