"""Placeholder joint — visual marker with no geometry effect.

Assigned by default when a new joint is detected.  Renders as two
thin rectangular fins along each parent timber's datum near the
intersection so the user sees it needs to be assigned to a real
joint type.

This module must work headless — no FreeCADGui / Qt imports.
"""

import FreeCAD
import Part

from joints.base import (
    JointParameter,
    JointStructuralProperties,
    ParameterSet,
    SecondaryProfile,
    TimberJointDefinition,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Fin geometry helpers
# ---------------------------------------------------------------------------

def _build_fin(origin, length_dir, protrusion_dir, thickness_dir,
               half_length, half_protrusion, half_thickness):
    """Build a single thin rectangular fin centered at *origin*.

    Parameters
    ----------
    origin : FreeCAD.Vector
        Centre of the fin.
    length_dir : FreeCAD.Vector
        Unit vector along the member datum (long axis of fin).
    protrusion_dir : FreeCAD.Vector
        Unit vector for the fin's visible extent (joint plane normal).
    thickness_dir : FreeCAD.Vector
        Unit vector for the fin's thin dimension.
    half_length : float
        Half the fin extent along *length_dir*.
    half_protrusion : float
        Half the fin extent along *protrusion_dir*.
    half_thickness : float
        Half the fin thickness along *thickness_dir*.

    Returns
    -------
    Part.Shape
        A thin box solid.
    """
    corner = (origin
              - length_dir * half_length
              - protrusion_dir * half_protrusion
              - thickness_dir * half_thickness)

    p1 = corner
    p2 = corner + length_dir * (2.0 * half_length)
    p3 = (corner + length_dir * (2.0 * half_length)
          + protrusion_dir * (2.0 * half_protrusion))
    p4 = corner + protrusion_dir * (2.0 * half_protrusion)

    wire = Part.makePolygon([p1, p2, p3, p4, p1])
    face = Part.Face(wire)
    return face.extrude(thickness_dir * (2.0 * half_thickness))


def _build_fins(origin, primary_axis, secondary_axis, normal,
                primary_dims, secondary_dims):
    """Build two perpendicular rectangular fin planes at a joint.

    One fin runs along each parent member's datum axis for a short
    distance from the intersection, extending beyond the timber
    cross-sections along the joint-plane normal so they remain visible.

    Parameters
    ----------
    origin : FreeCAD.Vector
        Joint intersection point.
    primary_axis, secondary_axis : FreeCAD.Vector
        Unit directions of each member datum.
    normal : FreeCAD.Vector
        Joint plane normal (primary_axis x secondary_axis).
    primary_dims : tuple(float, float)
        (Width, Height) of the primary member in mm.
    secondary_dims : tuple(float, float)
        (Width, Height) of the secondary member in mm.

    Returns
    -------
    Part.Shape
        A compound of two thin box solids.
    """
    pri_w, pri_h = primary_dims
    sec_w, sec_h = secondary_dims

    # Protrusion: extend 50% beyond the largest member half-dimension.
    largest = max(pri_w, pri_h, sec_w, sec_h)
    half_protrusion = largest * 0.75

    # Thickness: constant thin slab (3 mm total).
    half_thickness = 1.5

    fins = []

    # One fin along each member's datum axis.
    for axis, dims in ((primary_axis, primary_dims),
                       (secondary_axis, secondary_dims)):
        half_length = max(dims[0], dims[1])  # 2x max dim total
        t_dir = axis.cross(normal)
        if t_dir.Length > 1e-6:
            t_dir.normalize()
        else:
            t_dir = FreeCAD.Vector(0, 0, 1)
        try:
            fin = _build_fin(origin, axis, normal, t_dir,
                             half_length, half_protrusion, half_thickness)
            fins.append(fin)
        except Exception:
            pass

    # Third fin perpendicular to the other two, running along the
    # secondary datum so it follows non-90-degree intersections.
    sec_half_length = max(sec_w, sec_h)
    sec_t_dir = secondary_axis.cross(normal)
    if sec_t_dir.Length > 1e-6:
        sec_t_dir.normalize()
    else:
        sec_t_dir = FreeCAD.Vector(0, 0, 1)
    try:
        fin = _build_fin(origin, secondary_axis, sec_t_dir, normal,
                         sec_half_length, half_protrusion, half_thickness)
        fins.append(fin)
    except Exception:
        pass

    if fins:
        return Part.makeCompound(fins)
    return Part.makeBox(1, 1, 1, origin)


# ---------------------------------------------------------------------------
# Joint Definition
# ---------------------------------------------------------------------------

class PlaceholderDefinition(TimberJointDefinition):
    """Placeholder joint — no cuts, just a visual marker."""

    NAME = "Unassigned"
    ID = "placeholder"
    CATEGORY = "Utility"
    DESCRIPTION = (
        "Placeholder joint marker.  Does not cut either member.  "
        "Assign a real joint type to enable joinery geometry."
    )
    ICON = ""
    DIAGRAM = ""

    # Accept any member role and angle.
    PRIMARY_ROLES = []
    SECONDARY_ROLES = []
    MIN_ANGLE = 0.1
    MAX_ANGLE = 179.9

    # -- parameters ---------------------------------------------------------

    def get_parameters(self, primary, secondary, joint_cs):
        """No editable parameters."""
        return ParameterSet([])

    # -- primary cut (none) -------------------------------------------------

    def build_primary_tool(self, params, primary, secondary, joint_cs):
        """Return a null shape — placeholder joints do not cut."""
        return Part.Shape()

    # -- secondary extension (none) -----------------------------------------

    def secondary_extension(self, params, primary, secondary, joint_cs):
        """No extension needed."""
        return 0.0

    # -- secondary profile (fin visual, no shoulder cut) --------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Return fin markers as tenon_shape, with a null shoulder cut."""
        fins = _build_fins(
            joint_cs.origin,
            joint_cs.primary_axis,
            joint_cs.secondary_axis,
            joint_cs.normal,
            (float(primary.Width), float(primary.Height)),
            (float(secondary.Width), float(secondary.Height)),
        )

        return SecondaryProfile(
            tenon_shape=fins,
            shoulder_cut=Part.Shape(),  # null — no cutting
        )

    # -- validation ---------------------------------------------------------

    def validate(self, params, primary, secondary, joint_cs):
        return [
            ValidationResult(
                "warning",
                "Joint type is unassigned.  Double-click to select a "
                "joint type.",
                "UNASSIGNED_JOINT",
            ),
        ]

    # -- fabrication signature (none — placeholder is not fabricated) -------

    def fabrication_signature(self, params, primary, secondary, joint_cs):
        return {}

    # -- structural properties (none) ---------------------------------------

    def structural_properties(self, params, primary, secondary):
        return JointStructuralProperties()
