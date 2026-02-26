"""Through Mortise and Tenon — the most common timber frame joint.

A rectangular mortise is cut fully through the primary member, and a
matching tenon is formed on the end of the secondary member.  Drawbore
pegs secure the joint.

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
    PegDefinition,
    SecondaryProfile,
    TimberJointDefinition,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _member_local_cs(obj):
    """Return the member local coordinate system (origin, x, y, z).

    Duplicates the logic in ``TimberMember._build_solid`` so this module
    can remain independent of the objects package.
    """
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

class ThroughMortiseTenonDefinition(TimberJointDefinition):
    """Through mortise and tenon joint definition."""

    NAME = "Through Mortise and Tenon"
    ID = "through_mortise_tenon"
    CATEGORY = "Mortise and Tenon"
    DESCRIPTION = (
        "A rectangular tenon on the secondary member passes through a "
        "matching mortise in the primary member.  Secured with drawbore pegs."
    )
    ICON = ""
    DIAGRAM = ""

    PRIMARY_ROLES = [
        "Post", "Beam", "Girt", "TieBeam", "Plate", "Sill", "SummerBeam",
    ]
    SECONDARY_ROLES = [
        "Beam", "Girt", "TieBeam", "Rafter", "Brace", "FloorJoist",
    ]
    MIN_ANGLE = 45.0
    MAX_ANGLE = 135.0

    # -- parameters ---------------------------------------------------------

    def get_parameters(self, primary, secondary, joint_cs):
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)
        pri_w = float(primary.Width)

        # Clearance per side (1/16" = 1.6 mm)
        clearance = 1.6

        # Tenon dimensions
        tenon_width = sec_w / 3.0
        tenon_height = sec_h * 0.75
        tenon_length = pri_w  # through joint

        # Mortise dimensions (tenon + clearance)
        mortise_width = tenon_width + 2 * clearance
        mortise_height = tenon_height + 2 * clearance

        # Shoulder
        shoulder_depth = (sec_h - tenon_height) / 2.0

        # Pegs
        peg_diameter = 25.4        # 1 inch
        peg_count = 2 if sec_h >= 150.0 else 1
        peg_edge_distance = peg_diameter * 2.5
        peg_spacing = tenon_height - 2 * peg_edge_distance if peg_count > 1 else 0.0
        drawbore_offset = 3.2      # 1/8 inch

        params = [
            JointParameter("tenon_width", "length", tenon_width, tenon_width,
                           min_value=20.0, max_value=sec_w * 0.9,
                           group="Tenon",
                           description="Width of the tenon"),
            JointParameter("tenon_height", "length", tenon_height, tenon_height,
                           min_value=20.0, max_value=sec_h * 0.9,
                           group="Tenon",
                           description="Height of the tenon"),
            JointParameter("tenon_length", "length", tenon_length, tenon_length,
                           min_value=pri_w * 0.5, max_value=pri_w * 1.5,
                           group="Tenon",
                           description="Length of the tenon (through primary)"),
            JointParameter("mortise_width", "length", mortise_width, mortise_width,
                           min_value=20.0,
                           group="Mortise",
                           description="Width of the mortise opening"),
            JointParameter("mortise_height", "length", mortise_height, mortise_height,
                           min_value=20.0,
                           group="Mortise",
                           description="Height of the mortise opening"),
            JointParameter("shoulder_depth", "length", shoulder_depth, shoulder_depth,
                           min_value=0.0,
                           group="Tenon",
                           description="Depth of the shoulder (top and bottom)"),
            JointParameter("peg_diameter", "length", peg_diameter, peg_diameter,
                           min_value=12.0, max_value=38.0,
                           group="Pegs",
                           description="Peg diameter"),
            JointParameter("peg_count", "integer", peg_count, peg_count,
                           min_value=0, max_value=4,
                           group="Pegs",
                           description="Number of pegs"),
            JointParameter("peg_spacing", "length", peg_spacing, peg_spacing,
                           min_value=0.0,
                           group="Pegs",
                           description="Spacing between pegs"),
            JointParameter("peg_edge_distance", "length",
                           peg_edge_distance, peg_edge_distance,
                           min_value=peg_diameter * 1.5,
                           group="Pegs",
                           description="Minimum distance from peg to tenon edge"),
            JointParameter("drawbore_offset", "length",
                           drawbore_offset, drawbore_offset,
                           min_value=0.0, max_value=6.0,
                           group="Pegs",
                           description="Drawbore offset (0 = no drawbore)"),
        ]
        return ParameterSet(params)

    # -- primary cut (mortise) ----------------------------------------------

    def build_primary_tool(self, params, primary, secondary, joint_cs):
        """Build the mortise void to subtract from the primary member."""
        mw = params.get("mortise_width")
        mh = params.get("mortise_height")

        pri_origin, pri_x, pri_y, pri_z = _member_local_cs(primary)
        _sec_origin, sec_x, _sec_y, _sec_z = _member_local_cs(secondary)

        pri_w = float(primary.Width)

        # The mortise goes through the primary member along its Y axis
        # (the width direction).
        # Centre it on the intersection point.
        origin = joint_cs.origin

        # Mortise box: oriented so it cuts through the primary member
        # Along pri_y (width direction) for the through-cut
        # Along sec_x (secondary datum direction) for mortise width
        # Along pri_z (height direction) for mortise height

        # Determine the direction perpendicular to primary axis and in the
        # plane of the secondary member.  This is essentially the secondary
        # datum direction projected into the primary's cross-section plane.
        sec_in_plane = sec_x - pri_x * sec_x.dot(pri_x)
        sec_len = sec_in_plane.Length
        if sec_len < 1e-6:
            sec_in_plane = pri_y
        else:
            sec_in_plane.normalize()

        # The mortise height direction is perpendicular to both the through
        # direction and the mortise width direction.
        mortise_through_dir = pri_y
        mortise_width_dir = sec_in_plane
        mortise_height_dir = mortise_through_dir.cross(mortise_width_dir)
        mortise_height_dir.normalize()

        # Ensure mortise_height_dir points generally upward.
        if mortise_height_dir.dot(pri_z) < 0:
            mortise_height_dir = mortise_height_dir * -1.0

        # Build the mortise box.
        # Extra length on each side to ensure clean through-cut.
        extra = 2.0  # mm overshoot for boolean reliability
        through_length = pri_w + 2 * extra

        # Corner point of the mortise box.
        corner = (origin
                  - mortise_width_dir * (mw / 2.0)
                  - mortise_height_dir * (mh / 2.0)
                  - mortise_through_dir * (through_length / 2.0))

        # Create the box using a wire and extrusion.
        p1 = corner
        p2 = corner + mortise_width_dir * mw
        p3 = corner + mortise_width_dir * mw + mortise_height_dir * mh
        p4 = corner + mortise_height_dir * mh

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)
        mortise = face.extrude(mortise_through_dir * through_length)

        return mortise

    # -- secondary profile (tenon + shoulder) -------------------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the tenon shape and shoulder cut for the secondary member."""
        tw = params.get("tenon_width")
        th = params.get("tenon_height")
        tl = params.get("tenon_length")
        shoulder_d = params.get("shoulder_depth")

        sec_origin, sec_x, sec_y, sec_z = _member_local_cs(secondary)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        sec_start = FreeCAD.Vector(secondary.StartPoint)
        sec_end = FreeCAD.Vector(secondary.EndPoint)

        # Determine which end of the secondary member is at the joint.
        dist_start = (joint_cs.origin - sec_start).Length
        dist_end = (joint_cs.origin - sec_end).Length

        if dist_start <= dist_end:
            # Joint is at the start end.
            tenon_direction = sec_x * -1.0   # tenon extends beyond start
            shoulder_origin = sec_start
        else:
            # Joint is at the end end.
            tenon_direction = sec_x          # tenon extends beyond end
            shoulder_origin = sec_end

        # Tenon cross-section is centred on the secondary datum.
        # Tenon width is centred on sec_y, tenon height on sec_z.
        tenon_corner = (shoulder_origin
                        + tenon_direction * 0.0
                        - sec_y * (tw / 2.0)
                        + sec_z * shoulder_d)

        # Adjust for ReferenceFace offset:
        ref = secondary.ReferenceFace
        if ref == "Bottom":
            tenon_corner = (shoulder_origin
                            - sec_y * (tw / 2.0)
                            + sec_z * shoulder_d)
        elif ref == "Top":
            tenon_corner = (shoulder_origin
                            - sec_y * (tw / 2.0)
                            - sec_z * (sec_h - shoulder_d))
        elif ref == "Left":
            tenon_corner = (shoulder_origin
                            + sec_y * 0.0
                            - sec_z * (sec_h / 2.0) + sec_z * shoulder_d)
        elif ref == "Right":
            tenon_corner = (shoulder_origin
                            - sec_y * sec_w
                            - sec_z * (sec_h / 2.0) + sec_z * shoulder_d)
        else:
            tenon_corner = (shoulder_origin
                            - sec_y * (tw / 2.0)
                            + sec_z * shoulder_d)

        # Build tenon solid.
        tp1 = tenon_corner
        tp2 = tenon_corner + sec_y * tw
        tp3 = tenon_corner + sec_y * tw + sec_z * th
        tp4 = tenon_corner + sec_z * th

        tenon_wire = Part.makePolygon([tp1, tp2, tp3, tp4, tp1])
        tenon_face = Part.Face(tenon_wire)
        tenon_shape = tenon_face.extrude(tenon_direction * tl)

        # Build shoulder cut.
        # The shoulder cut removes the full cross-section minus the tenon
        # at the joint end of the secondary member.  This is the material
        # around the tenon that must be removed.
        # Approach: make a full-section box and boolean-subtract the tenon.
        # The result is the shoulder cut tool.

        # Full cross-section box at the joint end.
        if ref == "Bottom":
            full_corner = shoulder_origin - sec_y * (sec_w / 2.0)
        elif ref == "Top":
            full_corner = shoulder_origin - sec_y * (sec_w / 2.0) - sec_z * sec_h
        elif ref == "Left":
            full_corner = shoulder_origin - sec_z * (sec_h / 2.0)
        elif ref == "Right":
            full_corner = shoulder_origin - sec_y * sec_w - sec_z * (sec_h / 2.0)
        else:
            full_corner = shoulder_origin - sec_y * (sec_w / 2.0)

        fp1 = full_corner
        fp2 = full_corner + sec_y * sec_w
        fp3 = full_corner + sec_y * sec_w + sec_z * sec_h
        fp4 = full_corner + sec_z * sec_h

        full_wire = Part.makePolygon([fp1, fp2, fp3, fp4, fp1])
        full_face = Part.Face(full_wire)
        full_box = full_face.extrude(tenon_direction * tl)

        # Subtract the tenon from the full box to get the shoulder cut.
        try:
            shoulder_cut = full_box.cut(tenon_shape)
        except Exception:
            # If boolean fails, use the full box as a fallback.
            shoulder_cut = full_box

        return SecondaryProfile(
            tenon_shape=tenon_shape,
            shoulder_cut=shoulder_cut,
        )

    # -- pegs ---------------------------------------------------------------

    def build_pegs(self, params, primary, secondary, joint_cs):
        """Build drawbore pegs."""
        count = int(params.get("peg_count"))
        if count <= 0:
            return []

        diameter = params.get("peg_diameter")
        spacing = params.get("peg_spacing")
        edge_dist = params.get("peg_edge_distance")
        th = params.get("tenon_height")

        _pri_origin, _pri_x, pri_y, pri_z = _member_local_cs(primary)
        pri_w = float(primary.Width)

        pegs = []
        # Pegs are centred vertically within the tenon height, spaced evenly.
        # Peg axis goes through the primary member (along pri_y).
        if count == 1:
            offsets = [0.0]
        else:
            half_span = spacing / 2.0
            offsets = [-half_span + i * spacing / (count - 1)
                       for i in range(count)]

        for off_z in offsets:
            center = joint_cs.origin + pri_z * off_z
            pegs.append(PegDefinition(
                center=center,
                diameter=diameter,
                length=pri_w + 20.0,  # extend beyond both faces
                axis=pri_y,
                offset=params.get("drawbore_offset"),
            ))

        return pegs

    # -- validation ---------------------------------------------------------

    def validate(self, params, primary, secondary, joint_cs):
        results = []
        sec_h = float(secondary.Height)
        sec_w = float(secondary.Width)
        th = params.get("tenon_height")
        tw = params.get("tenon_width")
        peg_d = params.get("peg_diameter")
        peg_edge = params.get("peg_edge_distance")

        # Tenon height check.
        if th > sec_h * 0.80:
            results.append(ValidationResult(
                "warning",
                f"Tenon height ({th:.1f}mm) exceeds 80% of member "
                f"height ({sec_h:.1f}mm). Consider reducing.",
                "TENON_TOO_TALL",
            ))

        # Cheek material check.
        cheek = (sec_w - tw) / 2.0
        if cheek < 10.0:
            results.append(ValidationResult(
                "error",
                f"Cheek thickness ({cheek:.1f}mm) is too thin. "
                f"Minimum 10mm recommended.",
                "CHEEK_TOO_THIN",
            ))

        # Peg edge distance.
        if peg_edge < peg_d * 1.5:
            results.append(ValidationResult(
                "warning",
                f"Peg edge distance ({peg_edge:.1f}mm) is less than "
                f"1.5x peg diameter ({peg_d * 1.5:.1f}mm).",
                "PEG_EDGE_DISTANCE",
            ))

        # Angle range.
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
            "tenon_width": params.get("tenon_width"),
            "tenon_height": params.get("tenon_height"),
            "tenon_length": params.get("tenon_length"),
            "peg_count": params.get("peg_count"),
            "peg_diameter": params.get("peg_diameter"),
            "angle": round(joint_cs.angle, 1),
        }

    # -- structural properties (placeholder) --------------------------------

    def structural_properties(self, params, primary, secondary):
        # Placeholder — will be populated from reference data in Phase 6.
        return JointStructuralProperties()
