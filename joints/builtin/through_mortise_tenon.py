"""Mortise and Tenon — the most common timber frame joint.

A rectangular tenon on the secondary member passes into a matching
mortise in the primary member.  Supports through mortise (tenon exits
far face), blind mortise (tenon stops inside primary), and housed
mortise (rectangular housing pocket around the tenon opening).

The shoulder is anchored at the primary member's approach face.
Changing ``tenon_length`` only moves the tenon tip; the shoulder
stays fixed.

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
    """Return a unit vector pointing from the approach face INTO the primary.

    ``sec_x`` points from secondary start toward secondary end.  When the
    joint is at the *start* end, ``sec_x`` points **away** from the primary,
    so we negate the projected direction.  When the joint is at the *end*
    end, ``sec_x`` already points toward the primary.
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

    # When joint is at the start end, sec_x (and its projection) points
    # away from the primary — flip to get the INTO direction.
    if dist_start <= dist_end:
        return sec_in_plane * -1.0
    return FreeCAD.Vector(sec_in_plane)


# ---------------------------------------------------------------------------
# Joint Definition
# ---------------------------------------------------------------------------

class ThroughMortiseTenonDefinition(TimberJointDefinition):
    """Through mortise and tenon joint definition."""

    NAME = "Mortise & Tenon"
    ID = "through_mortise_tenon"
    CATEGORY = "Mortise and Tenon"
    DESCRIPTION = (
        "A rectangular tenon on the secondary member passes into a "
        "matching mortise in the primary member.  Secured with drawbore "
        "pegs.  Supports through, blind, and housed configurations."
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

    # -- approach face helpers ----------------------------------------------

    @staticmethod
    def _approach_face_distance(primary, secondary, joint_cs):
        """Distance from the primary centerline to its approach face.

        This is the distance along the secondary's approach direction
        from the intersection point (centerline) to the near surface
        of the primary member.  Equal to ``through_extent / 2``.
        """
        _pri_o, pri_x, pri_y, pri_z = _member_local_cs(primary)
        depth_dir = _approach_depth_dir(primary, secondary, joint_cs)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)
        through_extent = (abs(depth_dir.dot(pri_y)) * pri_w
                          + abs(depth_dir.dot(pri_z)) * pri_h)
        return through_extent / 2.0

    # -- parameters ---------------------------------------------------------

    def get_parameters(self, primary, secondary, joint_cs):
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)

        # Clearance per side (1/16" = 1.6 mm)
        clearance = 1.6

        # Approach face distance and through extent.
        afd = self._approach_face_distance(primary, secondary, joint_cs)
        through_extent = afd * 2.0

        # Primary cross-section extent in the mortise width direction.
        _pri_o, _pri_x, pri_y, pri_z = _member_local_cs(primary)
        _sec_o, _sec_x, sec_y, _sec_z = _member_local_cs(secondary)
        pri_extent_mw = (abs(sec_y.dot(pri_y)) * pri_w
                         + abs(sec_y.dot(pri_z)) * pri_h)

        # Tenon dimensions.
        tenon_width = sec_w / 3.0
        tenon_height = sec_h * 0.75

        # Shoulder: 0 = flush with approach face, >0 = housed into primary.
        housing_depth = 0.0

        # Tenon length from shoulder to tip.
        # Default = through extent (through mortise, flush shoulder).
        tenon_length = through_extent - housing_depth

        # Mortise dimensions (tenon + clearance).
        mortise_width = tenon_width + 2 * clearance
        mortise_height = tenon_height + 2 * clearance

        # Max tenon width: mortise must stay ≤ 75% of primary's
        # perpendicular cross-section extent.
        max_tw = sec_w * 0.9
        if pri_extent_mw > 1.0:
            max_from_pri = pri_extent_mw * 0.75 - 2 * clearance
            if max_from_pri >= 20.0:
                max_tw = min(max_tw, max_from_pri)

        # Shoulder angle relative to secondary axis (90° = perpendicular).
        shoulder_angle = 90.0

        # Pegs.
        peg_diameter = 25.4        # 1 inch
        peg_count = 2 if sec_h >= 150.0 else 1
        peg_edge_distance = peg_diameter * 2.5
        peg_spacing = (tenon_height - 2 * peg_edge_distance
                       if peg_count > 1 else 0.0)
        drawbore_offset = 3.2      # 1/8 inch

        params = [
            # -- Tenon --
            JointParameter("tenon_width", "length", tenon_width, tenon_width,
                           min_value=20.0, max_value=max_tw,
                           group="Tenon",
                           description="Width of the tenon"),
            JointParameter("tenon_height", "length", tenon_height, tenon_height,
                           min_value=20.0, max_value=sec_h * 0.9,
                           group="Tenon",
                           description="Height of the tenon"),
            JointParameter("tenon_length", "length", tenon_length, tenon_length,
                           min_value=afd * 0.5,
                           max_value=through_extent + 25.4,
                           group="Tenon",
                           description="Tenon length from shoulder to tip"),
            # -- Shoulder --
            JointParameter("housing_depth", "length",
                           housing_depth, housing_depth,
                           min_value=0.0, max_value=afd,
                           group="Shoulder",
                           description="Housing depth into primary "
                                       "(0 = flush with face)"),
            JointParameter("shoulder_angle", "angle",
                           shoulder_angle, shoulder_angle,
                           min_value=45.0, max_value=135.0,
                           group="Shoulder",
                           description="Shoulder cut angle "
                                       "(90\u00b0 = perpendicular)"),
            # -- Mortise (display-only, derived from tenon + clearance) --
            JointParameter("mortise_width", "length",
                           mortise_width, mortise_width,
                           min_value=20.0,
                           group="Mortise",
                           description="Width of the mortise opening "
                                       "(tenon width + 2\u00d7 clearance)",
                           read_only=True),
            JointParameter("mortise_height", "length",
                           mortise_height, mortise_height,
                           min_value=20.0,
                           group="Mortise",
                           description="Height of the mortise opening "
                                       "(tenon height + 2\u00d7 clearance)",
                           read_only=True),
            # -- Pegs --
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
                           description="Minimum distance from peg to "
                                       "tenon edge"),
            JointParameter("drawbore_offset", "length",
                           drawbore_offset, drawbore_offset,
                           min_value=0.0, max_value=6.0,
                           group="Pegs",
                           description="Drawbore offset (0 = no drawbore)"),
        ]
        return ParameterSet(params)

    # -- dependent defaults -------------------------------------------------

    def update_dependent_defaults(self, params):
        """Keep mortise dimensions in sync with tenon dimensions.

        When the user overrides tenon_width or tenon_height, the mortise
        defaults (tenon + 2×clearance) must follow.  Without this, the
        mortise stays at the geometry-derived default.
        """
        clearance = 1.6

        tw = params.get("tenon_width")
        th = params.get("tenon_height")

        mw_param = params.get_param("mortise_width")
        if not mw_param.is_overridden:
            mw_param.default_value = tw + 2 * clearance
            mw_param.value = tw + 2 * clearance

        mh_param = params.get_param("mortise_height")
        if not mh_param.is_overridden:
            mh_param.default_value = th + 2 * clearance
            mh_param.value = th + 2 * clearance

    # -- primary cut (mortise + optional housing) ---------------------------

    def build_primary_tool(self, params, primary, secondary, joint_cs):
        """Build the mortise void to subtract from the primary member.

        The mortise starts at the primary's approach face and extends
        inward by ``tenon_length``.  When ``housing_depth > 0``, a
        wider housing pocket (matching the secondary's full cross-section)
        is cut from the approach face inward by ``housing_depth``.
        """
        mw = params.get("mortise_width")
        mh = params.get("mortise_height")
        tl = params.get("tenon_length")
        sd = params.get("housing_depth")

        _pri_origin, pri_x, pri_y, pri_z = _member_local_cs(primary)
        _sec_origin, sec_x, sec_y, sec_z = _member_local_cs(secondary)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        origin = joint_cs.origin
        afd = self._approach_face_distance(primary, secondary, joint_cs)
        depth_dir = _approach_depth_dir(primary, secondary, joint_cs)

        # Approach face position (on the secondary's side of the primary).
        approach_face = origin - depth_dir * afd

        extra = 2.0  # mm overshoot for boolean reliability

        # Mortise: tenon cross-section, from approach face inward by tl.
        mort_start = approach_face - depth_dir * extra
        mort_corner = (mort_start
                       - sec_y * (mw / 2.0)
                       - sec_z * (mh / 2.0))

        mp1 = mort_corner
        mp2 = mort_corner + sec_y * mw
        mp3 = mort_corner + sec_y * mw + sec_z * mh
        mp4 = mort_corner + sec_z * mh

        mort_wire = Part.makePolygon([mp1, mp2, mp3, mp4, mp1])
        mort_face = Part.Face(mort_wire)
        mortise = mort_face.extrude(depth_dir * (tl + 2 * extra))

        # Housing pocket: full secondary cross-section + clearance.
        if sd > 0.1:
            clearance = 1.6
            hw = sec_w + 2 * clearance
            hh = sec_h + 2 * clearance

            hous_start = approach_face - depth_dir * extra
            hous_corner = (hous_start
                           - sec_y * (hw / 2.0)
                           - sec_z * (hh / 2.0))

            hp1 = hous_corner
            hp2 = hous_corner + sec_y * hw
            hp3 = hous_corner + sec_y * hw + sec_z * hh
            hp4 = hous_corner + sec_z * hh

            hous_wire = Part.makePolygon([hp1, hp2, hp3, hp4, hp1])
            hous_face = Part.Face(hous_wire)
            housing = hous_face.extrude(depth_dir * (sd + 2 * extra))

            try:
                mortise = mortise.fuse(housing)
            except Exception:
                pass  # fall back to mortise alone

        return mortise

    # -- secondary extension ------------------------------------------------

    def secondary_extension(self, params, primary, secondary, joint_cs):
        """Distance the secondary member must extend past the datum endpoint.

        The datum endpoint is at the primary's centerline.  The tenon tip
        is at ``tenon_length - (afd - housing_depth)`` past the centerline.
        """
        afd = self._approach_face_distance(primary, secondary, joint_cs)
        sd = params.get("housing_depth")
        tl = params.get("tenon_length")
        return max(0.0, tl - (afd - sd))

    # -- secondary profile (tenon + shoulder) -------------------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the tenon shape and shoulder cut for the secondary member.

        The shoulder is anchored at the primary's approach face (plus
        ``housing_depth`` into the primary for housed joints).  Changing
        ``tenon_length`` only moves the tenon tip; the shoulder stays fixed.
        """
        tw = params.get("tenon_width")
        th = params.get("tenon_height")
        tl = params.get("tenon_length")
        sd = params.get("housing_depth")
        shoulder_angle = params.get("shoulder_angle")

        sec_origin, sec_x, sec_y, sec_z = _member_local_cs(secondary)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        sec_start = FreeCAD.Vector(secondary.A_StartPoint)
        sec_end = FreeCAD.Vector(secondary.B_EndPoint)

        # Determine which end of the secondary member is at the joint.
        dist_start = (joint_cs.origin - sec_start).Length
        dist_end = (joint_cs.origin - sec_end).Length

        if dist_start <= dist_end:
            tenon_direction = sec_x * -1.0   # tenon extends beyond start
            shoulder_origin = sec_start       # datum endpoint
        else:
            tenon_direction = sec_x          # tenon extends beyond end
            shoulder_origin = sec_end        # datum endpoint

        inward_dir = tenon_direction * -1.0

        # Approach face: the primary's near surface.
        afd = self._approach_face_distance(primary, secondary, joint_cs)
        approach_face = shoulder_origin + inward_dir * afd

        # Shoulder face: approach face + housing_depth into primary.
        shoulder_face = approach_face + tenon_direction * sd

        # -- Tenon: starts at shoulder face, extends tl in tenon_direction --
        tenon_corner = (shoulder_face
                        - sec_y * (tw / 2.0)
                        - sec_z * (th / 2.0))

        tp1 = tenon_corner
        tp2 = tenon_corner + sec_y * tw
        tp3 = tenon_corner + sec_y * tw + sec_z * th
        tp4 = tenon_corner + sec_z * th

        tenon_wire = Part.makePolygon([tp1, tp2, tp3, tp4, tp1])
        tenon_face = Part.Face(tenon_wire)
        tenon_shape = tenon_face.extrude(tenon_direction * tl)

        # -- Shoulder cut: removes material around the tenon from the
        # shoulder face outward.  Must extend at least to the datum
        # endpoint so that short tenons (blind mortise) don't leave a
        # full-section stub between the tenon tip and the datum end.
        #
        # Distance from shoulder_face to the datum endpoint:
        #   datum_reach = afd - sd
        # The cut must span max(tl, datum_reach) + overshoot.
        datum_reach = afd - sd
        cut_depth = max(tl, datum_reach + 2.0)  # 2.0 mm boolean overshoot

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

        # Tenon-shaped keep zone: only extends tl (the actual tenon).
        # The cut result = shoulder ring (around tenon) + full stub
        # (from tenon tip to datum endpoint, if any).
        tenon_zone_corner = (shoulder_face
                             - sec_y * (tw / 2.0)
                             - sec_z * (th / 2.0))

        tz1 = tenon_zone_corner
        tz2 = tenon_zone_corner + sec_y * tw
        tz3 = tenon_zone_corner + sec_y * tw + sec_z * th
        tz4 = tenon_zone_corner + sec_z * th

        tenon_zone_wire = Part.makePolygon([tz1, tz2, tz3, tz4, tz1])
        tenon_zone_face = Part.Face(tenon_zone_wire)
        tenon_zone = tenon_zone_face.extrude(tenon_direction * tl)

        try:
            shoulder_cut = full_box.cut(tenon_zone)
        except Exception:
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

        _pri_origin, pri_x, pri_y, pri_z = _member_local_cs(primary)
        _sec_origin, sec_x, sec_y, sec_z = _member_local_cs(secondary)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)

        # Peg axis: perpendicular to both the primary grain and the
        # mortise through-direction.  The drawbore pin is driven across
        # the grain, locking the tenon in place.
        sec_in_plane = sec_x - pri_x * sec_x.dot(pri_x)
        sec_len = sec_in_plane.Length
        if sec_len < 1e-6:
            sec_in_plane = pri_y
        else:
            sec_in_plane.normalize()

        peg_axis = pri_x.cross(sec_in_plane)
        peg_axis.normalize()

        # Peg length spans the primary member in the peg axis direction.
        peg_extent = (abs(peg_axis.dot(pri_y)) * pri_w
                      + abs(peg_axis.dot(pri_z)) * pri_h)

        # Pegs are spaced along the tenon height direction (sec_z).
        pegs = []
        if count == 1:
            offsets = [0.0]
        else:
            half_span = spacing / 2.0
            offsets = [-half_span + i * spacing / (count - 1)
                       for i in range(count)]

        for off_z in offsets:
            center = joint_cs.origin + sec_z * off_z
            pegs.append(PegDefinition(
                center=center,
                diameter=diameter,
                length=peg_extent + 20.0,
                axis=peg_axis,
                offset=params.get("drawbore_offset"),
            ))

        return pegs

    # -- validation ---------------------------------------------------------

    def validate(self, params, primary, secondary, joint_cs):
        results = []
        sec_h = float(secondary.Height)
        sec_w = float(secondary.Width)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)
        th = params.get("tenon_height")
        tw = params.get("tenon_width")
        tl = params.get("tenon_length")
        sd = params.get("housing_depth")
        mw = params.get("mortise_width")
        mh = params.get("mortise_height")
        peg_d = params.get("peg_diameter")
        peg_edge = params.get("peg_edge_distance")

        afd = self._approach_face_distance(primary, secondary, joint_cs)
        through_extent = afd * 2.0

        # Primary cross-section extents in mortise directions.
        _pri_o, _pri_x, pri_y, pri_z = _member_local_cs(primary)
        _sec_o, _sec_x, sec_y, sec_z = _member_local_cs(secondary)
        pri_extent_mw = (abs(sec_y.dot(pri_y)) * pri_w
                         + abs(sec_y.dot(pri_z)) * pri_h)
        pri_extent_mh = (abs(sec_z.dot(pri_y)) * pri_w
                         + abs(sec_z.dot(pri_z)) * pri_h)

        # -- Mortise vs primary cross-section --

        WARN_RATIO = 0.35

        if pri_extent_mw > 1.0:
            if mw > pri_extent_mw * 0.75:
                results.append(ValidationResult(
                    "error",
                    f"Mortise width ({mw:.1f}mm) exceeds 75% of primary "
                    f"cross-section ({pri_extent_mw:.1f}mm). Maximum: "
                    f"{pri_extent_mw * 0.75:.1f}mm.",
                    "MORTISE_WIDTH_EXCEEDS_LIMIT",
                ))
            elif mw > pri_extent_mw * WARN_RATIO:
                results.append(ValidationResult(
                    "warning",
                    f"Mortise width ({mw:.1f}mm) exceeds "
                    f"{WARN_RATIO:.0%} of primary cross-section "
                    f"({pri_extent_mw:.1f}mm) in that direction.",
                    "MORTISE_WIDTH_LARGE",
                ))

        if pri_extent_mh > 1.0 and mh > pri_extent_mh * WARN_RATIO:
            results.append(ValidationResult(
                "warning",
                f"Mortise height ({mh:.1f}mm) exceeds "
                f"{WARN_RATIO:.0%} of primary cross-section "
                f"({pri_extent_mh:.1f}mm) in that direction.",
                "MORTISE_HEIGHT_LARGE",
            ))

        # -- Housing depth vs primary through-dimension --

        if sd > through_extent * 0.50:
            results.append(ValidationResult(
                "error",
                f"Housing depth ({sd:.1f}mm) exceeds 50% of primary "
                f"through-dimension ({through_extent:.1f}mm). Maximum: "
                f"{through_extent * 0.50:.1f}mm.",
                "HOUSING_DEPTH_EXCEEDS_LIMIT",
            ))
        elif sd > through_extent * WARN_RATIO:
            results.append(ValidationResult(
                "warning",
                f"Housing depth ({sd:.1f}mm) exceeds "
                f"{WARN_RATIO:.0%} of primary through-dimension "
                f"({through_extent:.1f}mm).",
                "HOUSING_DEPTH_LARGE",
            ))

        # Blind mortise info.
        if tl < through_extent - sd:
            results.append(ValidationResult(
                "info",
                "Blind mortise \u2014 tenon does not pass through primary.",
                "BLIND_MORTISE",
            ))

        # Tenon too short.
        if tl < afd - sd:
            results.append(ValidationResult(
                "warning",
                f"Tenon ({tl:.1f}mm) does not reach primary centerline "
                f"\u2014 joint may be weak.",
                "TENON_TOO_SHORT",
            ))

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
                f"1.5\u00d7 peg diameter ({peg_d * 1.5:.1f}mm).",
                "PEG_EDGE_DISTANCE",
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
            "tenon_width": params.get("tenon_width"),
            "tenon_height": params.get("tenon_height"),
            "tenon_length": params.get("tenon_length"),
            "housing_depth": params.get("housing_depth"),
            "peg_count": params.get("peg_count"),
            "peg_diameter": params.get("peg_diameter"),
            "angle": round(joint_cs.angle, 1),
        }

    # -- structural properties (placeholder) --------------------------------

    def structural_properties(self, params, primary, secondary):
        # Placeholder — will be populated from reference data in Phase 6.
        return JointStructuralProperties()
