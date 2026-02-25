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

        clearance = 1.6  # 1/16 inch

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
                           sec_w + clearance, sec_w + clearance,
                           min_value=sec_w * 0.5,
                           group="Lap",
                           description="Width of notch in primary (accepts secondary)"),
            JointParameter("lap_width_secondary", "length",
                           pri_w + clearance, pri_w + clearance,
                           min_value=pri_w * 0.5,
                           group="Lap",
                           description="Width of notch in secondary (accepts primary)"),
        ]
        return ParameterSet(params)

    # -- primary cut --------------------------------------------------------

    def build_primary_tool(self, params, primary, secondary, joint_cs):
        """Build the notch to subtract from the primary member."""
        lap_depth = params.get("lap_depth_primary")
        lap_width = params.get("lap_width_primary")

        _pri_o, pri_x, pri_y, pri_z = _member_local_cs(primary)
        _sec_o, sec_x, _sec_y, _sec_z = _member_local_cs(secondary)

        pri_h = float(primary.Height)

        # The notch is cut from the top face of the primary member,
        # centred on the intersection point.
        # Notch direction: along the secondary datum direction
        # Notch width: lap_width (along secondary datum)
        # Notch depth: lap_depth (from top of primary downward)
        # Notch length: extends through the primary member width

        # Project secondary axis into primary cross-section plane.
        sec_in_plane = sec_x - pri_x * sec_x.dot(pri_x)
        sec_len = sec_in_plane.Length
        if sec_len < 1e-6:
            sec_in_plane = pri_y
        else:
            sec_in_plane.normalize()

        origin = joint_cs.origin

        # Cut from top: start at (origin + pri_z * pri_h/2) down by lap_depth.
        # Actually: the notch goes along sec_in_plane by lap_width,
        # across pri cross-section.

        # Notch box dimensions:
        # Along sec_in_plane: lap_width
        # Along pri_z (downward from top): lap_depth
        # Along pri_y (through member): pri_w + extra

        pri_w = float(primary.Width)
        extra = 2.0  # overshoot for clean boolean

        # Determine the top surface position relative to intersection point.
        # For Bottom reference: datum at bottom, top at datum + pri_z * pri_h
        # We need the top of the member at the intersection.
        ref = primary.ReferenceFace
        if ref == "Bottom":
            top_offset = pri_z * pri_h
        elif ref == "Top":
            top_offset = FreeCAD.Vector(0, 0, 0)
        elif ref == "Left":
            top_offset = pri_z * (pri_h / 2.0)
        elif ref == "Right":
            top_offset = pri_z * (pri_h / 2.0)
        else:
            top_offset = pri_z * pri_h

        # Top of member at intersection point (approximately).
        # The actual top depends on where the datum is relative to the section.
        # For a Bottom-reference member, the top is at datum + z * Height.
        # The datum passes through the intersection point (approximately).

        # Corner of notch box: at top minus lap_depth, centred on intersection.
        notch_top = origin + top_offset
        notch_bottom = notch_top - pri_z * lap_depth

        corner = (notch_bottom
                  - sec_in_plane * (lap_width / 2.0)
                  - pri_y * ((pri_w + 2 * extra) / 2.0))

        p1 = corner
        p2 = corner + sec_in_plane * lap_width
        p3 = corner + sec_in_plane * lap_width + pri_z * lap_depth
        p4 = corner + pri_z * lap_depth

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)
        notch = face.extrude(pri_y * (pri_w + 2 * extra))

        return notch

    # -- secondary profile --------------------------------------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the notch for the secondary member."""
        lap_depth = params.get("lap_depth_secondary")
        lap_width = params.get("lap_width_secondary")

        _sec_o, sec_x, sec_y, sec_z = _member_local_cs(secondary)
        _pri_o, pri_x, _pri_y, _pri_z = _member_local_cs(primary)

        sec_h = float(secondary.Height)
        sec_w = float(secondary.Width)

        # Project primary axis into secondary cross-section plane.
        pri_in_plane = pri_x - sec_x * pri_x.dot(sec_x)
        pri_len = pri_in_plane.Length
        if pri_len < 1e-6:
            pri_in_plane = sec_y
        else:
            pri_in_plane.normalize()

        origin = joint_cs.origin

        extra = 2.0

        # Secondary notch is cut from the bottom (opposite face from primary).
        ref = secondary.ReferenceFace
        if ref == "Bottom":
            bottom_offset = FreeCAD.Vector(0, 0, 0)
        elif ref == "Top":
            bottom_offset = sec_z * (-sec_h)
        elif ref == "Left":
            bottom_offset = sec_z * (-sec_h / 2.0)
        elif ref == "Right":
            bottom_offset = sec_z * (-sec_h / 2.0)
        else:
            bottom_offset = FreeCAD.Vector(0, 0, 0)

        notch_bottom = origin + bottom_offset
        notch_top = notch_bottom + sec_z * lap_depth

        corner = (notch_bottom
                  - pri_in_plane * (lap_width / 2.0)
                  - sec_y * ((sec_w + 2 * extra) / 2.0))

        p1 = corner
        p2 = corner + pri_in_plane * lap_width
        p3 = corner + pri_in_plane * lap_width + sec_z * lap_depth
        p4 = corner + sec_z * lap_depth

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)
        shoulder_cut = face.extrude(sec_y * (sec_w + 2 * extra))

        # For a half lap, the "tenon" is the remaining half-section that
        # nests into the other member's notch.  We represent it as a thin
        # box at the lap depth for visualization.
        tenon_corner = notch_top - pri_in_plane * (lap_width / 2.0) - sec_y * (sec_w / 2.0)
        tp1 = tenon_corner
        tp2 = tenon_corner + pri_in_plane * lap_width
        tp3 = tenon_corner + pri_in_plane * lap_width + sec_z * (sec_h - lap_depth)
        tp4 = tenon_corner + sec_z * (sec_h - lap_depth)

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
