"""Dovetail — a dovetail-shaped tenon in a matching slot.

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
        "A dovetail-shaped tenon fits into a matching trapezoidal slot. "
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

        # Slot depth: half the primary member width.
        slot_depth = pri_w * 0.5

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
                           description="Width at the narrow (surface) end"),
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
            JointParameter("slot_depth", "length",
                           slot_depth, slot_depth,
                           min_value=pri_w * 0.25, max_value=pri_w * 0.75,
                           group="Slot",
                           description="Depth of dovetail slot in primary member"),
            JointParameter("shoulder_depth", "length",
                           shoulder_depth, shoulder_depth,
                           min_value=0.0,
                           group="Dovetail",
                           description="Depth of shoulder above/below dovetail"),
            JointParameter("clearance", "length",
                           clearance, clearance,
                           min_value=0.0, max_value=3.0,
                           group="Slot",
                           description="Clearance per side in slot"),
            JointParameter("channel_mode", "enumeration",
                           CHANNEL_THROUGH, CHANNEL_THROUGH,
                           group="Slot",
                           description="Through = open both sides; "
                                       "Half = open toward nearer edge",
                           enum_options=[CHANNEL_THROUGH, CHANNEL_HALF]),
            JointParameter("flip_channel", "boolean",
                           False, False,
                           group="Slot",
                           description="Reverse which side the half-channel "
                                       "opens toward"),
        ]
        return ParameterSet(params)

    # -- primary cut (dovetail slot) ----------------------------------------

    def build_primary_tool(self, params, primary, secondary, joint_cs):
        """Build the dovetail slot to subtract from the primary member.

        The slot is on the face of the primary where the secondary
        approaches.  The dovetail cross-section (narrow at the approach
        face, wide at the back) prevents the secondary from being
        pulled straight out.

        The slot runs perpendicular to the approach face.  ``Through``
        mode opens both sides; ``Half`` opens toward one edge.
        """
        clearance = params.get("clearance")
        narrow_w = params.get("tail_width_narrow") + 2 * clearance
        wide_w = params.get("tail_width_wide") + 2 * clearance
        slot_depth = params.get("slot_depth")
        channel_mode = params.get("channel_mode")
        flip = params.get("flip_channel")

        _pri_o, pri_x, pri_y, pri_z = _member_local_cs(primary)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)

        # depth_dir: from the approach face INTO the primary.
        depth_dir = _approach_depth_dir(primary, secondary, joint_cs)

        # Taper direction: perpendicular to both primary axis and depth.
        # The dovetail taper (narrow→wide) is measured along pri_x.
        # The slot runs along taper_dir through the primary cross-section.
        taper_dir = depth_dir.cross(pri_x)
        taper_dir.normalize()

        # Through extent to locate the approach face.
        through_extent = (abs(depth_dir.dot(pri_y)) * pri_w
                          + abs(depth_dir.dot(pri_z)) * pri_h)

        # Approach face: the face of the primary nearest the secondary.
        approach_face = joint_cs.origin - depth_dir * (through_extent / 2.0)

        # Slot extent along taper_dir.
        taper_extent = (abs(taper_dir.dot(pri_y)) * pri_w
                        + abs(taper_dir.dot(pri_z)) * pri_h)

        extra = 2.0  # mm overshoot for boolean reliability

        if channel_mode == CHANNEL_THROUGH:
            slot_length = taper_extent + 2 * extra
            slot_center = approach_face
        else:
            # Half: open toward the nearer edge in taper_dir.
            # Check which edge of the primary is closer to the joint
            # in the taper_dir direction.
            slot_half = taper_extent / 2.0 + extra
            # Default: open in +taper_dir if joint is above centre,
            # otherwise -taper_dir.  flip reverses this.
            open_sign = 1.0
            if flip:
                open_sign = -1.0
            open_dir = taper_dir * open_sign
            slot_length = slot_half
            slot_center = approach_face + open_dir * (slot_half / 2.0)

        # The slot runs along taper_dir, so taper_dir is the "height"
        # parameter in _make_trapezoid_wire.  The dovetail taper
        # (narrow at approach face, wide at back) is along pri_x.
        slot = _make_trapezoid_wire(
            slot_center,
            pri_x,           # width param: dovetail taper
            taper_dir,       # height param: slot runs this way
            depth_dir,       # depth param: into the primary
            narrow_w,        # narrow at approach face
            wide_w,          # wide at back
            slot_length,     # slot extent
            slot_depth,      # depth into primary
        )

        return slot

    # -- secondary profile (dovetail tenon + shoulder) ----------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the dovetail tenon shape and shoulder cut.

        The tenon taper matches the slot: wider at the base (shoulder),
        narrower at the tip, so it locks against the dovetail profile
        and cannot be withdrawn.
        """
        narrow_w = params.get("tail_width_narrow")
        wide_w = params.get("tail_width_wide")
        tail_h = params.get("tail_height")
        slot_depth = params.get("slot_depth")

        sec_origin, sec_x, sec_y, sec_z = _member_local_cs(secondary)
        _pri_o, pri_x, _pri_y, _pri_z = _member_local_cs(primary)
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

        # Taper direction: matches the slot (perpendicular to both
        # the primary axis and the approach direction).
        depth_dir = _approach_depth_dir(primary, secondary, joint_cs)
        taper_dir = depth_dir.cross(pri_x)
        taper_dir.normalize()

        # Build tenon: wide at base (shoulder), narrow at tip.
        # _make_trapezoid_wire is narrow at origin, wide at back,
        # so pass wide_w as "narrow" and narrow_w as "wide".
        tenon = _make_trapezoid_wire(
            shoulder_origin,
            pri_x,               # dovetail taper along primary axis
            taper_dir,           # constant dimension
            tenon_direction,     # extends toward primary
            wide_w, narrow_w, tail_h, slot_depth,
        )

        # Shoulder cut: removes material around the dovetail tenon
        # from the secondary member's end.
        inward_dir = tenon_direction * -1.0

        full_corner = shoulder_origin - sec_y * (sec_w / 2.0) - sec_z * (sec_h / 2.0)
        fp1 = full_corner
        fp2 = full_corner + sec_y * sec_w
        fp3 = full_corner + sec_y * sec_w + sec_z * sec_h
        fp4 = full_corner + sec_z * sec_h

        full_wire = Part.makePolygon([fp1, fp2, fp3, fp4, fp1])
        full_face = Part.Face(full_wire)
        full_box = full_face.extrude(inward_dir * slot_depth)

        # Dovetail-shaped box going inward (the portion to keep).
        tenon_inward = _make_trapezoid_wire(
            shoulder_origin,
            pri_x, taper_dir, inward_dir,
            wide_w, narrow_w, tail_h, slot_depth,
        )

        try:
            shoulder_cut = full_box.cut(tenon_inward)
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
        slot_d = params.get("slot_depth")

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

        if slot_d > pri_w * 0.6:
            results.append(ValidationResult(
                "warning",
                f"Slot depth ({slot_d:.1f}mm) exceeds 60% of primary "
                f"member width ({pri_w:.1f}mm). May weaken the primary.",
                "SLOT_TOO_DEEP",
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
            "slot_depth": params.get("slot_depth"),
            "dovetail_angle": params.get("dovetail_angle"),
            "angle": round(joint_cs.angle, 1),
        }

    # -- structural properties (placeholder) --------------------------------

    def structural_properties(self, params, primary, secondary):
        return JointStructuralProperties()
