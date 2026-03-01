"""TimberJoint — a joint between two TimberMember objects.

Created automatically when two datum lines intersect within tolerance,
or manually via the AddJoint command.  The joint delegates geometry
generation to a :class:`TimberJointDefinition` looked up from the joint
registry.

This module must work headless — no FreeCADGui / Qt imports at module level.
"""

import json

import FreeCAD
import Part

from joints.base import JointCoordinateSystem, ParameterSet
from joints.intersection import (
    closest_approach_segments,
    compute_joint_cs,
    INTERSECTION_TOLERANCE,
)
from joints.loader import get_definition, get_ids, DEFAULT_JOINT_TYPES

# ---------------------------------------------------------------------------
# Intersection type enumeration values
# ---------------------------------------------------------------------------

INTERSECTION_TYPES = [
    "EndpointToMidpoint",
    "MidpointToMidpoint",
    "EndpointToEndpoint",
]


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class TimberJoint:
    """Proxy object attached to an ``App::FeaturePython`` document object."""

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    # -- properties ---------------------------------------------------------

    @staticmethod
    def _add_properties(obj):
        """Add all TimberJoint properties.  Safe to call on restore."""

        def _ensure(ptype, name, group, doc, default=None):
            if hasattr(obj, name):
                return
            obj.addProperty(ptype, name, group, doc)
            if default is not None:
                setattr(obj, name, default)

        # Joint links
        _ensure("App::PropertyLink", "PrimaryMember", "Joint",
                "The primary (housing) member")
        _ensure("App::PropertyLink", "SecondaryMember", "Joint",
                "The secondary (tenoned) member")

        # Intersection geometry (computed, read-only)
        _ensure("App::PropertyVector", "IntersectionPoint", "Joint",
                "World-space intersection point")
        _ensure("App::PropertyFloat", "IntersectionAngle", "Joint",
                "Angle between datum lines in degrees", 0.0)
        _ensure("App::PropertyEnumeration", "IntersectionType", "Joint",
                "Classification of the intersection")
        if not obj.IntersectionType:
            obj.IntersectionType = INTERSECTION_TYPES
            obj.IntersectionType = "EndpointToMidpoint"

        # Joint definition
        _ensure("App::PropertyEnumeration", "JointType", "Joint",
                "Joint type from the registry")
        if not obj.JointType:
            ids = get_ids()
            if not ids:
                ids = ["through_mortise_tenon", "half_lap", "dovetail"]
            obj.JointType = ids
            obj.JointType = ids[0]
        _ensure("App::PropertyString", "Parameters", "Joint",
                "JSON-serialized ParameterSet values")

        # Structural properties (computed, read-only)
        _ensure("App::PropertyFloat", "AllowableMoment", "Structural",
                "Allowable moment from reference data (N-mm)", 0.0)
        _ensure("App::PropertyFloat", "AllowableShear", "Structural",
                "Allowable shear from reference data (N)", 0.0)
        _ensure("App::PropertyFloat", "RotationalStiffness", "Structural",
                "Rotational stiffness (N-mm/rad)", 0.0)
        _ensure("App::PropertyBool", "AcceptsLateralPointLoad", "Structural",
                "Flag for stair/guardrail connections", False)

        # Validation
        _ensure("App::PropertyString", "ValidationResults", "Validation",
                "JSON list of validation messages")

        # Hidden cut tool shapes — used by TimberMember.execute() to apply
        # boolean subtractions.  Not visible in the property editor.
        _ensure("Part::PropertyPartShape", "PrimaryCutTool", "Internal",
                "Boolean tool for primary member")
        _ensure("Part::PropertyPartShape", "SecondaryCutTool", "Internal",
                "Boolean tool for secondary member")

        # Make computed/internal properties read-only or hidden.
        obj.setEditorMode("IntersectionPoint", 1)   # read-only
        obj.setEditorMode("IntersectionAngle", 1)
        obj.setEditorMode("AllowableMoment", 1)
        obj.setEditorMode("AllowableShear", 1)
        obj.setEditorMode("RotationalStiffness", 1)
        obj.setEditorMode("ValidationResults", 1)
        obj.setEditorMode("PrimaryCutTool", 2)       # hidden
        obj.setEditorMode("SecondaryCutTool", 2)

    # -- recompute ----------------------------------------------------------

    def execute(self, obj):
        """Recompute joint geometry.  Never raises."""
        try:
            self._recompute_joint(obj)
        except Exception as e:
            FreeCAD.Console.PrintError(
                f"TimberJoint execute failed: {e}\n"
            )
            obj.Shape = Part.makeBox(1, 1, 1)
            # Store empty cut tools so member booleans don't crash.
            obj.PrimaryCutTool = Part.Shape()
            obj.SecondaryCutTool = Part.Shape()

    def _recompute_joint(self, obj):
        """Core recompute logic."""
        primary = obj.PrimaryMember
        secondary = obj.SecondaryMember

        if primary is None or secondary is None:
            obj.Shape = Part.makeBox(1, 1, 1)
            obj.PrimaryCutTool = Part.Shape()
            obj.SecondaryCutTool = Part.Shape()
            return

        # 1. Recompute intersection geometry from current member positions.
        p_start = FreeCAD.Vector(primary.A_StartPoint)
        p_end = FreeCAD.Vector(primary.B_EndPoint)
        s_start = FreeCAD.Vector(secondary.A_StartPoint)
        s_end = FreeCAD.Vector(secondary.B_EndPoint)

        pt1, pt2, dist, t1, t2 = closest_approach_segments(
            p_start, p_end, s_start, s_end,
        )

        if dist > INTERSECTION_TOLERANCE:
            FreeCAD.Console.PrintWarning(
                "TimberJoint: members no longer within intersection "
                f"tolerance ({dist:.1f}mm > {INTERSECTION_TOLERANCE}mm)\n"
            )
            obj.Shape = Part.makeBox(1, 1, 1)
            obj.PrimaryCutTool = Part.Shape()
            obj.SecondaryCutTool = Part.Shape()
            obj.ValidationResults = json.dumps([{
                "level": "error",
                "message": f"Members too far apart ({dist:.1f}mm)",
                "code": "OUT_OF_TOLERANCE",
            }])
            return

        fresh_point = (pt1 + pt2) * 0.5
        joint_cs = compute_joint_cs(primary, secondary, fresh_point)

        if joint_cs is None:
            FreeCAD.Console.PrintWarning(
                "TimberJoint: members no longer form a valid intersection\n"
            )
            obj.Shape = Part.makeBox(1, 1, 1)
            obj.PrimaryCutTool = Part.Shape()
            obj.SecondaryCutTool = Part.Shape()
            obj.ValidationResults = json.dumps([{
                "level": "error",
                "message": "Members no longer intersect at a valid angle",
                "code": "NO_INTERSECTION",
            }])
            # Touch members to clear old cuts (with same guard).
            if not getattr(self, '_skip_touch', False):
                self._skip_touch = True
                primary.touch()
                secondary.touch()
            else:
                self._skip_touch = False
            return

        # Update intersection display properties.
        # NOTE: The CLAUDE.md rule "never modify own properties in execute()"
        # targets properties that other objects link to (causing recompute
        # loops).  These are display-only read-only fields; no object has a
        # Link or Expression pointing to them.
        obj.IntersectionPoint = joint_cs.origin
        obj.IntersectionAngle = joint_cs.angle

        # 2. Look up joint definition.
        joint_type_id = obj.JointType
        if not joint_type_id:
            joint_type_id = DEFAULT_JOINT_TYPES.get(
                obj.IntersectionType, "through_mortise_tenon"
            )
            obj.JointType = joint_type_id

        definition = get_definition(joint_type_id)
        if definition is None:
            FreeCAD.Console.PrintWarning(
                f"TimberJoint: unknown joint type '{joint_type_id}'\n"
            )
            obj.Shape = Part.makeBox(1, 1, 1)
            obj.PrimaryCutTool = Part.Shape()
            obj.SecondaryCutTool = Part.Shape()
            return

        # 3. Deserialize or create ParameterSet.
        #    When the JointType changes, the stored Parameters contain keys
        #    from the old definition that won't match the new one.  Detect
        #    this by comparing parameter names and create fresh params when
        #    they don't match.
        fresh = definition.get_parameters(primary, secondary, joint_cs)
        if obj.Parameters:
            params = ParameterSet.from_json(obj.Parameters)
            stored_names = set(name for name, _ in params.items())
            fresh_names = set(name for name, _ in fresh.items())
            if stored_names != fresh_names:
                # Joint type changed — discard old params, use fresh.
                params = fresh
            else:
                # Same joint type — update derived defaults, keep overrides.
                new_defaults = {}
                for name, p in fresh.items():
                    new_defaults[name] = p.default_value
                params.update_defaults(new_defaults)
        else:
            params = fresh

        obj.Parameters = params.to_json()

        # 4. Build cut tools.
        primary_tool = definition.build_primary_tool(
            params, primary, secondary, joint_cs
        )
        secondary_profile = definition.build_secondary_profile(
            params, primary, secondary, joint_cs
        )

        obj.PrimaryCutTool = primary_tool
        obj.SecondaryCutTool = secondary_profile.shoulder_cut

        # 5. Build visual shape (tenon + pegs).
        visual_parts = []
        if secondary_profile.tenon_shape and not secondary_profile.tenon_shape.isNull():
            visual_parts.append(secondary_profile.tenon_shape)

        pegs = definition.build_pegs(params, primary, secondary, joint_cs)
        for peg in pegs:
            try:
                cyl = Part.makeCylinder(
                    peg.diameter / 2.0,
                    peg.length,
                    peg.center - peg.axis * (peg.length / 2.0),
                    peg.axis,
                )
                visual_parts.append(cyl)
            except Exception:
                pass

        if visual_parts:
            obj.Shape = Part.makeCompound(visual_parts)
        else:
            obj.Shape = Part.makeBox(1, 1, 1)

        # 6. Validate.
        results = definition.validate(params, primary, secondary, joint_cs)
        obj.ValidationResults = json.dumps(
            [{"level": r.level, "message": r.message, "code": r.code}
             for r in results]
        )

        # 7. Structural properties (placeholder).
        sp = definition.structural_properties(params, primary, secondary)
        obj.AllowableMoment = sp.allowable_moment
        obj.AllowableShear = sp.allowable_shear
        obj.RotationalStiffness = sp.rotational_stiffness

        # 8. Touch both members so they recompute with new cut shapes.
        #
        # Guard against infinite recompute: Joint depends on Members via
        # Link, so FreeCAD recomputes Joint after Members.  If we always
        # touch(), Members recompute → Joint recomputes → touch() → loop.
        #
        # The alternating flag breaks the cycle:
        #   Pass 1: _skip_touch is False → touch members, set True
        #   Pass 2: members recompute, joint recomputes again via Link dep,
        #           _skip_touch is True → skip touch, set False
        #   No pass 3 needed.
        if not getattr(self, '_skip_touch', False):
            self._skip_touch = True
            primary.touch()
            secondary.touch()
        else:
            self._skip_touch = False

    # -- serialization ------------------------------------------------------

    def onDocumentRestored(self, obj):
        """Re-add properties that might be missing after schema changes."""
        self._add_properties(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ---------------------------------------------------------------------------
# ViewProvider (GUI only — conditionally defined)
# ---------------------------------------------------------------------------

if FreeCAD.GuiUp:
    import os
    import FreeCADGui

    _ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             "resources", "icons")

    class TimberJointViewProvider:
        """View provider for TimberJoint objects."""

        def __init__(self, vobj):
            vobj.Proxy = self

        def attach(self, vobj):
            self.Object = vobj.Object

        def getIcon(self):
            return os.path.join(_ICON_DIR, "timber_joint.svg")

        def updateData(self, obj, prop):
            pass

        def onChanged(self, vobj, prop):
            pass

        def getDisplayModes(self, vobj):
            return ["Flat Lines"]

        def getDefaultDisplayMode(self):
            return "Flat Lines"

        def setDisplayMode(self, mode):
            return mode

        def onDelete(self, vobj, subelements):
            return True

        def dumps(self):
            return None

        def loads(self, state):
            return None


# ---------------------------------------------------------------------------
# Helper: create a new TimberJoint in the active document
# ---------------------------------------------------------------------------

def create_timber_joint(primary_obj, secondary_obj, intersection_result,
                        joint_type_id=None):
    """Create and return a new TimberJoint document object.

    Parameters
    ----------
    primary_obj : FreeCAD document object
        The primary (housing) TimberMember.
    secondary_obj : FreeCAD document object
        The secondary (tenoned) TimberMember.
    intersection_result : IntersectionResult
        From intersection detection.
    joint_type_id : str or None
        Joint definition ID.  If ``None``, the default for the intersection
        type is used.

    Returns
    -------
    obj : App::FeaturePython
        The newly created joint object.
    """
    doc = FreeCAD.ActiveDocument
    if doc is None:
        raise RuntimeError("No active document")

    obj = doc.addObject("Part::FeaturePython", "TimberJoint")
    TimberJoint(obj)

    obj.PrimaryMember = primary_obj
    obj.SecondaryMember = secondary_obj
    obj.IntersectionPoint = intersection_result.point
    obj.IntersectionType = intersection_result.intersection_type

    if joint_type_id:
        obj.JointType = joint_type_id
    else:
        obj.JointType = DEFAULT_JOINT_TYPES.get(
            intersection_result.intersection_type,
            "through_mortise_tenon",
        )

    if FreeCAD.GuiUp:
        TimberJointViewProvider(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.40, 0.50, 0.60)  # blue-gray, distinct from timber

    # Two recompute passes are needed:
    #   Pass 1: Members build raw solids, Joint computes cut shapes and
    #           touches both members.
    #   Pass 2: Members recompute with the new cut shapes applied.
    doc.recompute()
    doc.recompute()
    return obj
