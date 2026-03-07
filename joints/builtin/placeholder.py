"""Placeholder joint — visual marker with no geometry effect.

Assigned by default when a new joint is detected.  Renders as a
6-pointed 3D star at the intersection so the user sees it needs to
be assigned to a real joint type.

This module must work headless — no FreeCADGui / Qt imports.
"""

import math

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
# Star geometry helper
# ---------------------------------------------------------------------------

def _build_star(origin, arm_length, base_radius):
    """Build a 6-pointed 3D star (jack shape) from six cones.

    Six cones radiate outward from *origin* along the +/-X, +/-Y, +/-Z
    axes.  Each cone has its base at the centre and its tip pointing
    outward.

    Parameters
    ----------
    origin : FreeCAD.Vector
        Centre of the star.
    arm_length : float
        Length of each cone arm.
    base_radius : float
        Radius of each cone at the base (centre).

    Returns
    -------
    Part.Shape
        A compound of six cones.
    """
    directions = [
        FreeCAD.Vector(1, 0, 0),
        FreeCAD.Vector(-1, 0, 0),
        FreeCAD.Vector(0, 1, 0),
        FreeCAD.Vector(0, -1, 0),
        FreeCAD.Vector(0, 0, 1),
        FreeCAD.Vector(0, 0, -1),
    ]

    cones = []
    for d in directions:
        try:
            cone = Part.makeCone(
                base_radius,    # radius at base (centre)
                0.0,            # radius at tip (point)
                arm_length,     # height
                origin,         # base position
                d,              # direction
            )
            cones.append(cone)
        except Exception:
            pass

    if cones:
        return Part.makeCompound(cones)
    # Fallback: tiny box at origin.
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

    # -- secondary profile (star visual, no shoulder cut) -------------------

    def build_secondary_profile(self, params, primary, secondary, joint_cs):
        """Return the star visual as tenon_shape, with a null shoulder cut."""
        pri_w = float(primary.Width)
        pri_h = float(primary.Height)
        sec_w = float(secondary.Width)
        sec_h = float(secondary.Height)

        # Size the star 20% bigger than the largest dimension across
        # both connected members so it's always clearly visible.
        largest = max(pri_w, pri_h, sec_w, sec_h)
        arm_length = largest * 1.2 / 2.0  # half because arms radiate both ways
        base_radius = arm_length * 0.25

        star = _build_star(joint_cs.origin, arm_length, base_radius)

        return SecondaryProfile(
            tenon_shape=star,
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
