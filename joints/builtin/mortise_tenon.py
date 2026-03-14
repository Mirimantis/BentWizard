"""Mortise and Tenon --- the most common timber frame joint.

A rectangular tenon on the secondary member passes into a matching
mortise in the primary member.  Supports through mortise (tenon exits
far face), blind mortise (tenon stops inside primary, the default),
and housed mortise (rectangular housing pocket around the tenon opening).

Both the mortise and tenon are perpendicular to the primary's approach
face --- the traditional timber framing approach.  At non-90° angles
the perpendicular tenon block intersects the angled secondary body,
naturally producing a skewed trapezoidal tenon with two trimmed corners.
There is a triangular gap at the back of the mortise where the tenon
doesn't fill the full pocket; this is normal and traditional.

The shoulder is anchored at the primary member's approach face.
Changing ``tenon_length`` only moves the tenon tip; the shoulder
stays fixed.  ``tenon_length`` is measured perpendicular to the face.

The mortise rectangle is always oriented so that its height (long
dimension) runs along the primary member's grain direction.  This
prevents the mortise from cutting across the primary.

The optional housing pocket follows the secondary member's axis
(a sheared prism) so it matches the brace/rafter body footprint.

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
    PegDefinition,
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
    tenon_block,
    shoulder_cut,
    approach_face_distance,
    secondary_extension_for_tenon,
    extent_along,
)


# ---------------------------------------------------------------------------
# Joint Definition
# ---------------------------------------------------------------------------

class MortiseTenonDefinition(TimberJointDefinition):
    """Mortise and tenon joint definition."""

    NAME = "Mortise & Tenon"
    ID = "mortise_tenon"
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

    # -- parameters ---------------------------------------------------------

    def get_parameters(self, primary, secondary, joint_cs):
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)

        # Clearance per side (1/16" = 1.6 mm)
        clearance = 1.6

        # Build face context to get correct approach geometry.
        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        afd = approach_face_distance(pri_ctx)
        through_extent = afd * 2.0

        # Mortise axes: width perpendicular to primary grain, height along it.
        m_w_dir, m_h_dir = mortise_axes(pri_ctx)

        _sec_o, _sec_x, sec_y, sec_z = member_local_cs(secondary)

        # Primary cross-section extent in the mortise width direction.
        pri_extent_mw = extent_along(pri_ctx, m_w_dir)

        # Secondary member's extent in mortise width and height directions.
        sec_extent_w = (abs(m_w_dir.dot(sec_y)) * sec_w
                        + abs(m_w_dir.dot(sec_z)) * sec_h)
        sec_extent_h = (abs(m_h_dir.dot(sec_y)) * sec_w
                        + abs(m_h_dir.dot(sec_z)) * sec_h)

        # Tenon dimensions based on secondary extent in mortise directions.
        tenon_width = sec_extent_w / 3.0
        tenon_height = sec_extent_h * 0.75

        # Shoulder: 0 = flush with approach face, >0 = housed into primary.
        housing_depth = 0.0

        # Tenon length from shoulder to tip, measured perpendicular to the
        # primary face.  Default is a blind mortise at 75% of through depth.
        tenon_length = through_extent * 0.75

        # Mortise dimensions (tenon + clearance).
        mortise_width = tenon_width + 2 * clearance
        mortise_height = tenon_height + 2 * clearance

        # Max tenon width: mortise must stay <= 75% of primary's
        # perpendicular cross-section extent.
        max_tw = sec_extent_w * 0.9
        if pri_extent_mw > 1.0:
            max_from_pri = pri_extent_mw * 0.75 - 2 * clearance
            if max_from_pri >= 20.0:
                max_tw = min(max_tw, max_from_pri)

        # Shoulder angle relative to secondary axis (90 deg = perpendicular).
        shoulder_angle = 90.0

        # Pegs.
        peg_diameter = 25.4        # 1 inch
        peg_count = 2 if sec_extent_h >= 150.0 else 1
        peg_edge_distance = peg_diameter * 2.5
        peg_spacing = (tenon_height - 2 * peg_edge_distance
                       if peg_count > 1 else 0.0)
        drawbore_offset = 3.2      # 1/8 inch

        params = [
            # -- Tenon --
            JointParameter("tenon_width", "length", tenon_width, tenon_width,
                           min_value=20.0, max_value=max_tw,
                           group="Tenon",
                           description="Width of the tenon "
                                       "(perpendicular to primary grain)"),
            JointParameter("tenon_height", "length", tenon_height, tenon_height,
                           min_value=20.0, max_value=sec_extent_h * 0.9,
                           group="Tenon",
                           description="Height of the tenon "
                                       "(along primary grain)"),
            JointParameter("tenon_length", "length", tenon_length, tenon_length,
                           min_value=afd * 0.5,
                           max_value=through_extent + 25.4,
                           group="Tenon",
                           description="Tenon length from shoulder to tip "
                                       "(perpendicular to primary face)"),
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
        """Keep mortise dimensions in sync with tenon dimensions."""
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

        The mortise is a rectangular pocket cut perpendicular to the
        primary's approach face --- the traditional timber framing approach.
        At any intersection angle, the pocket goes straight into the
        timber from the face.  ``common()`` clips to the actual face
        boundary.

        At non-90° angles, the tenon (also perpendicular) is trimmed
        by the angled secondary body into a skewed trapezoid.  There will
        be a triangular gap at the back of the mortise where the tenon
        doesn't fill the full pocket --- this is normal and traditional.

        The optional housing pocket follows the secondary member's axis
        (a sheared prism) so it matches the secondary body's footprint
        on the primary face.
        """
        mw = params.get("mortise_width")
        mh = params.get("mortise_height")
        tl = params.get("tenon_length")
        sd = params.get("housing_depth")

        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        sec_ctx = build_face_context(secondary, primary, joint_cs, "secondary")
        m_w_dir, m_h_dir = mortise_axes(pri_ctx)

        # Perpendicular rectangular mortise pocket from the shoulder plane.
        # The pocket depth equals the tenon length.
        mortise = face_pocket(pri_ctx, mw, mh, tl + sd, m_w_dir, m_h_dir)

        # Housing pocket: accommodates the secondary member's full
        # cross-section from the face to the shoulder.  This is a sheared
        # prism along the secondary's axis so it follows the brace/rafter
        # body where it seats against the primary.
        if sd > 0.1:
            clearance = 1.6
            hw = sec_ctx.width + 2 * clearance
            hh = sec_ctx.height + 2 * clearance

            # Secondary direction toward primary (tenon_dir for housing).
            if sec_ctx.at_start:
                tenon_dir = sec_ctx.axis * -1.0
            else:
                tenon_dir = FreeCAD.Vector(sec_ctx.axis)
            cos_alpha = tenon_dir.dot(pri_ctx.face_normal)
            if cos_alpha < 0.1:
                cos_alpha = 0.1

            overshoot = 2.0
            housing_start = pri_ctx.face_point - pri_ctx.face_normal * overshoot
            h_corner = (housing_start
                        - sec_ctx.y_dir * (hw / 2.0)
                        - sec_ctx.z_dir * (hh / 2.0))
            hp1 = h_corner
            hp2 = h_corner + sec_ctx.y_dir * hw
            hp3 = h_corner + sec_ctx.y_dir * hw + sec_ctx.z_dir * hh
            hp4 = h_corner + sec_ctx.z_dir * hh

            h_wire = Part.makePolygon([hp1, hp2, hp3, hp4, hp1])
            h_face = Part.Face(h_wire)

            # Extrude along secondary axis to cover housing depth.
            housing_ext = (overshoot + sd) / max(cos_alpha, 0.01)
            housing = h_face.extrude(tenon_dir * housing_ext)

            try:
                housing_clipped = housing.common(pri_ctx.raw_solid)
                if housing_clipped.Volume > 0.01:
                    housing = housing_clipped
            except Exception:
                pass

            try:
                mortise = mortise.fuse(housing)
            except Exception:
                pass  # fall back to mortise alone

        return mortise

    # -- secondary extension ------------------------------------------------

    def secondary_extension(self, params, primary, secondary, joint_cs):
        """Distance the secondary member must extend past the datum endpoint.

        The tenon extends perpendicular to the primary face.  The
        secondary member's body is angled.  The extension along the
        secondary axis must cover the perpendicular tenon depth past
        the primary centerline, projected onto the secondary axis.
        """
        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        sec_ctx = build_face_context(secondary, primary, joint_cs, "secondary")
        sd = params.get("housing_depth")
        tl = params.get("tenon_length")

        if sec_ctx.at_start:
            tenon_dir = sec_ctx.axis * -1.0
        else:
            tenon_dir = FreeCAD.Vector(sec_ctx.axis)
        cos_alpha = tenon_dir.dot(pri_ctx.face_normal)
        if cos_alpha < 0.1:
            cos_alpha = 0.1

        return secondary_extension_for_tenon(pri_ctx, tl, sd, cos_alpha)

    # -- secondary profile (tenon + shoulder) -------------------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Build the tenon shape and shoulder cut for the secondary member.

        The shoulder sits flat against the primary's approach face.
        The tenon extends perpendicular to the face (along ``sh_normal``),
        matching the mortise direction.

        At non-90° angles, the perpendicular tenon block intersects the
        angled secondary body.  The boolean subtraction of the shoulder
        cut (which preserves only the tenon block region) naturally
        produces a skewed trapezoidal tenon --- the two corners where
        the perpendicular tenon extends beyond the secondary's body are
        trimmed away.  No special angle math needed.
        """
        tw = params.get("tenon_width")
        th = params.get("tenon_height")
        tl = params.get("tenon_length")
        sd = params.get("housing_depth")

        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        sec_ctx = build_face_context(secondary, primary, joint_cs, "secondary")
        m_w_dir, m_h_dir = mortise_axes(pri_ctx)

        # Shoulder plane: primary face, offset inward by housing_depth.
        sh_origin, sh_normal = shoulder_plane(pri_ctx, sd)

        # Tenon: extends perpendicular to the primary face (sh_normal).
        # At 90° this is identical to following the secondary axis.
        # At other angles, the perpendicular tenon block acts as a
        # keep zone; the angled secondary body trims it into a trapezoid.
        tenon_shape = tenon_block(sec_ctx, sh_origin, sh_normal,
                                  tw, th, tl, m_w_dir, m_h_dir)

        # Shoulder cut: removes material around the tenon.
        # The slab face is in the shoulder plane (primary's face),
        # producing an angled shoulder on the secondary.
        cut = shoulder_cut(sec_ctx, sh_origin, sh_normal,
                          keep_shape=tenon_shape)

        return SecondaryProfile(
            tenon_shape=tenon_shape,
            shoulder_cut=cut,
        )

    # -- pegs ---------------------------------------------------------------

    def build_pegs(self, params, primary, secondary, joint_cs):
        """Build drawbore pegs."""
        count = int(params.get("peg_count"))
        if count <= 0:
            return []

        diameter = params.get("peg_diameter")
        spacing = params.get("peg_spacing")
        th = params.get("tenon_height")

        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        _m_w_dir, m_h_dir = mortise_axes(pri_ctx)

        # Peg axis: perpendicular to both the primary grain and the
        # face normal.  The drawbore pin is driven across the grain,
        # locking the tenon in place.
        peg_axis = pri_ctx.axis.cross(pri_ctx.face_normal)
        if peg_axis.Length < 1e-6:
            peg_axis = pri_ctx.y_dir
        else:
            peg_axis.normalize()

        # Peg length spans the primary member in the peg axis direction.
        peg_extent = extent_along(pri_ctx, peg_axis)

        # Pegs are spaced along the mortise height direction (primary grain).
        pegs = []
        if count == 1:
            offsets = [0.0]
        else:
            half_span = spacing / 2.0
            offsets = [-half_span + i * spacing / (count - 1)
                       for i in range(count)]

        for off_h in offsets:
            center = joint_cs.origin + m_h_dir * off_h
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

        pri_ctx = build_face_context(primary, secondary, joint_cs, "primary")
        afd = approach_face_distance(pri_ctx)
        through_extent = afd * 2.0

        # Mortise axes and extents.
        m_w_dir, m_h_dir = mortise_axes(pri_ctx)
        _sec_o, _sec_x, sec_y, sec_z = member_local_cs(secondary)

        pri_extent_mw = extent_along(pri_ctx, m_w_dir)
        pri_extent_mh = extent_along(pri_ctx, m_h_dir)

        sec_extent_w = (abs(m_w_dir.dot(sec_y)) * sec_w
                        + abs(m_w_dir.dot(sec_z)) * sec_h)
        sec_extent_h = (abs(m_h_dir.dot(sec_y)) * sec_w
                        + abs(m_h_dir.dot(sec_z)) * sec_h)

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

        # Tenon height vs secondary extent in that direction.
        if sec_extent_h > 1.0 and th > sec_extent_h * 0.80:
            results.append(ValidationResult(
                "warning",
                f"Tenon height ({th:.1f}mm) exceeds 80% of secondary "
                f"extent in grain direction ({sec_extent_h:.1f}mm). "
                f"Consider reducing.",
                "TENON_TOO_TALL",
            ))

        # Cheek material check (secondary extent in mortise width direction).
        if sec_extent_w > 1.0:
            cheek = (sec_extent_w - tw) / 2.0
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
        # Placeholder --- will be populated from reference data in Phase 6.
        return JointStructuralProperties()
