"""Housed Dovetail — a dovetail-shaped tenon in a matching housing.

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


def _make_trapezoid_wire(origin, width_dir, height_dir, depth_dir,
                         narrow_width, wide_width, height, depth):
    """Create a trapezoidal prism wire for a dovetail shape.

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


# ---------------------------------------------------------------------------
# Joint Definition
# ---------------------------------------------------------------------------

class HousedDovetailDefinition(TimberJointDefinition):
    """Housed dovetail joint definition."""

    NAME = "Housed Dovetail"
    ID = "housed_dovetail"
    CATEGORY = "Dovetail"
    DESCRIPTION = (
        "A dovetail-shaped tenon fits into a matching trapezoidal housing. "
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
        tail_height = sec_h * 0.5
        tail_width_narrow = sec_w * 0.6

        # Calculate wide end from narrow end and dovetail angle.
        spread = 2.0 * tail_height * math.tan(math.radians(dovetail_angle))
        tail_width_wide = tail_width_narrow + spread

        # Housing depth: half the primary member width (half-housed).
        housing_depth = pri_w * 0.5

        # Shoulder: material above/below the dovetail on the secondary.
        shoulder_depth = (sec_h - tail_height) / 2.0

        clearance = 1.6  # 1/16 inch

        params = [
            JointParameter("dovetail_angle", "angle",
                           dovetail_angle, dovetail_angle,
                           min_value=8.0, max_value=20.0,
                           group="Dovetail",
                           description="Dovetail slope angle in degrees"),
            JointParameter("tail_width_narrow", "length",
                           tail_width_narrow, tail_width_narrow,
                           min_value=20.0, max_value=sec_w * 0.9,
                           group="Dovetail",
                           description="Width at the narrow (entry) end"),
            JointParameter("tail_width_wide", "length",
                           tail_width_wide, tail_width_wide,
                           min_value=tail_width_narrow,
                           group="Dovetail",
                           description="Width at the wide (back) end"),
            JointParameter("tail_height", "length",
                           tail_height, tail_height,
                           min_value=20.0, max_value=sec_h * 0.8,
                           group="Dovetail",
                           description="Height of the dovetail"),
            JointParameter("housing_depth", "length",
                           housing_depth, housing_depth,
                           min_value=pri_w * 0.25, max_value=pri_w * 0.75,
                           group="Housing",
                           description="Depth of housing in primary member"),
            JointParameter("shoulder_depth", "length",
                           shoulder_depth, shoulder_depth,
                           min_value=0.0,
                           group="Dovetail",
                           description="Depth of shoulder above/below dovetail"),
            JointParameter("clearance", "length",
                           clearance, clearance,
                           min_value=0.0, max_value=3.0,
                           group="Housing",
                           description="Clearance per side in housing"),
        ]
        return ParameterSet(params)

    # -- primary cut (housing) ----------------------------------------------

    def build_primary_tool(self, params, primary, secondary, joint_cs):
        """Build the dovetail housing to subtract from the primary member."""
        narrow_w = params.get("tail_width_narrow") + 2 * params.get("clearance")
        wide_w = params.get("tail_width_wide") + 2 * params.get("clearance")
        height = params.get("tail_height") + 2 * params.get("clearance")
        depth = params.get("housing_depth")

        _pri_o, pri_x, pri_y, pri_z = _member_local_cs(primary)
        _sec_o, sec_x, _sec_y, _sec_z = _member_local_cs(secondary)

        # The housing is cut into the face of the primary member where the
        # secondary meets it.
        # Width direction: along primary datum axis (the dovetail fans out
        # along the primary member).
        # Height direction: vertical (pri_z).
        # Depth direction: into the primary member.

        # Determine the face of the primary that the secondary enters.
        # The entry face normal is approximately the secondary datum direction
        # projected into the primary's cross-section.
        sec_in_plane = sec_x - pri_x * sec_x.dot(pri_x)
        sec_len = sec_in_plane.Length
        if sec_len < 1e-6:
            sec_in_plane = pri_y
        else:
            sec_in_plane.normalize()

        # The dovetail spreads along the primary datum axis.
        width_dir = pri_x
        height_dir = pri_z
        depth_dir = sec_in_plane

        origin = joint_cs.origin

        housing = _make_trapezoid_wire(
            origin, width_dir, height_dir, depth_dir,
            narrow_w, wide_w, height, depth,
        )

        return housing

    # -- secondary profile (dovetail tenon + shoulder) ----------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the dovetail tenon shape and shoulder cut."""
        narrow_w = params.get("tail_width_narrow")
        wide_w = params.get("tail_width_wide")
        height = params.get("tail_height")
        depth = params.get("housing_depth")
        shoulder_d = params.get("shoulder_depth")

        sec_origin, sec_x, sec_y, sec_z = _member_local_cs(secondary)
        _pri_o, pri_x, _pri_y, pri_z = _member_local_cs(primary)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        sec_start = FreeCAD.Vector(secondary.StartPoint)
        sec_end = FreeCAD.Vector(secondary.EndPoint)

        # Which end of the secondary is at the joint?
        dist_start = (joint_cs.origin - sec_start).Length
        dist_end = (joint_cs.origin - sec_end).Length

        if dist_start <= dist_end:
            tenon_direction = sec_x * -1.0
            shoulder_origin = sec_start
        else:
            tenon_direction = sec_x
            shoulder_origin = sec_end

        # The dovetail tenon extends from the secondary end into the primary.
        # Width direction: along primary datum (the dovetail fans along it).
        # Height direction: vertical (pri_z).
        # Depth direction: tenon_direction (into primary member).

        # Note: for the tenon, we reverse the depth direction and swap
        # narrow/wide because the tenon should be narrow at entry (which is
        # the face of the primary) and wide at the back (inside the primary).
        tenon = _make_trapezoid_wire(
            shoulder_origin,
            pri_x,         # width direction
            pri_z,         # height direction
            tenon_direction,  # depth direction
            narrow_w, wide_w, height, depth,
        )

        # Shoulder cut: remove the full cross-section except the tenon
        # at the member end.
        ref = secondary.ReferenceFace
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
        full_box = full_face.extrude(tenon_direction * depth)

        try:
            shoulder_cut = full_box.cut(tenon)
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
        tail_h = params.get("tail_height")
        narrow_w = params.get("tail_width_narrow")
        housing_d = params.get("housing_depth")

        if tail_h > sec_h * 0.7:
            results.append(ValidationResult(
                "warning",
                f"Dovetail height ({tail_h:.1f}mm) exceeds 70% of secondary "
                f"member height ({sec_h:.1f}mm).",
                "DOVETAIL_TOO_TALL",
            ))

        if narrow_w > sec_w * 0.8:
            results.append(ValidationResult(
                "warning",
                f"Dovetail narrow width ({narrow_w:.1f}mm) exceeds 80% of "
                f"secondary member width ({sec_w:.1f}mm).",
                "DOVETAIL_TOO_WIDE",
            ))

        if housing_d > pri_w * 0.6:
            results.append(ValidationResult(
                "warning",
                f"Housing depth ({housing_d:.1f}mm) exceeds 60% of primary "
                f"member width ({pri_w:.1f}mm). May weaken the primary.",
                "HOUSING_TOO_DEEP",
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
            "tail_width_narrow": params.get("tail_width_narrow"),
            "tail_width_wide": params.get("tail_width_wide"),
            "tail_height": params.get("tail_height"),
            "housing_depth": params.get("housing_depth"),
            "dovetail_angle": params.get("dovetail_angle"),
            "angle": round(joint_cs.angle, 1),
        }

    # -- structural properties (placeholder) --------------------------------

    def structural_properties(self, params, primary, secondary):
        return JointStructuralProperties()
