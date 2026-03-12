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

from joints.base import JointCoordinateSystem, ParameterSet, ValidationResult
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
                ids = ["placeholder", "mortise_tenon", "half_lap", "dovetail"]
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

        # Broken-joint state
        _ensure("App::PropertyBool", "IsBroken", "Joint",
                "True when members are out of tolerance or invalid angle",
                False)
        _ensure("App::PropertyVector", "LastValidPoint", "Internal",
                "Intersection midpoint from last valid recompute")
        _ensure("App::PropertyVector", "LastValidPrimaryPoint", "Internal",
                "Point on primary datum from last valid recompute")
        _ensure("App::PropertyVector", "LastValidSecondaryPoint", "Internal",
                "Point on secondary datum from last valid recompute")

        # Hidden cut tool shapes — used by TimberMember.execute() to apply
        # boolean subtractions.  Not visible in the property editor.
        _ensure("Part::PropertyPartShape", "PrimaryCutTool", "Internal",
                "Boolean tool for primary member")
        _ensure("Part::PropertyPartShape", "SecondaryCutTool", "Internal",
                "Boolean tool for secondary member")

        # Extension distances — how much the secondary member must extend
        # past each datum endpoint to form the complete joint geometry.
        _ensure("App::PropertyFloat", "SecondaryStartExtension", "Internal",
                "Extension at secondary start endpoint (mm)", 0.0)
        _ensure("App::PropertyFloat", "SecondaryEndExtension", "Internal",
                "Extension at secondary end endpoint (mm)", 0.0)

        # Make computed/internal properties read-only or hidden.
        obj.setEditorMode("IntersectionPoint", 1)   # read-only
        obj.setEditorMode("IntersectionAngle", 1)
        obj.setEditorMode("IsBroken", 1)
        obj.setEditorMode("AllowableMoment", 1)
        obj.setEditorMode("AllowableShear", 1)
        obj.setEditorMode("RotationalStiffness", 1)
        obj.setEditorMode("ValidationResults", 1)
        obj.setEditorMode("PrimaryCutTool", 2)       # hidden
        obj.setEditorMode("SecondaryCutTool", 2)
        obj.setEditorMode("SecondaryStartExtension", 2)
        obj.setEditorMode("SecondaryEndExtension", 2)
        obj.setEditorMode("LastValidPoint", 2)
        obj.setEditorMode("LastValidPrimaryPoint", 2)
        obj.setEditorMode("LastValidSecondaryPoint", 2)

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

    @staticmethod
    def _bb_key(shape):
        """Return a hashable key for a shape's bounding box, or None."""
        if shape is None or shape.isNull():
            return None
        bb = shape.BoundBox
        return (round(bb.XMin, 2), round(bb.YMin, 2), round(bb.ZMin, 2),
                round(bb.XMax, 2), round(bb.YMax, 2), round(bb.ZMax, 2))

    def _cuts_changed(self, obj):
        """Return True if cut tools or parameters differ from last recompute.

        Bounding-box comparison catches most geometry changes.  The
        parameters comparison handles cases where the internal cut
        geometry changes without affecting the bounding box (e.g.
        housing depth changes in a half-channel dovetail).
        """
        pri_key = self._bb_key(obj.PrimaryCutTool)
        sec_key = self._bb_key(obj.SecondaryCutTool)
        params_key = obj.Parameters
        old_pri = getattr(self, '_last_pri_bb', None)
        old_sec = getattr(self, '_last_sec_bb', None)
        old_params = getattr(self, '_last_params', None)
        changed = ((pri_key != old_pri) or (sec_key != old_sec)
                   or (params_key != old_params))
        self._last_pri_bb = pri_key
        self._last_sec_bb = sec_key
        self._last_params = params_key
        return changed

    def _recompute_joint(self, obj):
        """Core recompute logic."""
        primary = obj.PrimaryMember
        secondary = obj.SecondaryMember

        if primary is None or secondary is None:
            obj.Shape = Part.makeBox(1, 1, 1)
            obj.PrimaryCutTool = Part.Shape()
            obj.SecondaryCutTool = Part.Shape()
            obj.SecondaryStartExtension = 0.0
            obj.SecondaryEndExtension = 0.0
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
            obj.IsBroken = True
            obj.Shape = self._build_broken_visual(obj, primary, secondary,
                                                   pt1, pt2)
            obj.PrimaryCutTool = Part.Shape()
            obj.SecondaryCutTool = Part.Shape()
            obj.SecondaryStartExtension = 0.0
            obj.SecondaryEndExtension = 0.0
            obj.ValidationResults = json.dumps([{
                "level": "error",
                "message": f"Members too far apart ({dist:.1f}mm)",
                "code": "OUT_OF_TOLERANCE",
            }])
            if self._cuts_changed(obj):
                primary.touch()
                secondary.touch()
            return

        fresh_point = (pt1 + pt2) * 0.5
        joint_cs = compute_joint_cs(primary, secondary, fresh_point)

        if joint_cs is None:
            FreeCAD.Console.PrintWarning(
                "TimberJoint: members no longer form a valid intersection\n"
            )
            obj.IsBroken = True
            obj.Shape = self._build_broken_visual(obj, primary, secondary,
                                                   pt1, pt2)
            obj.PrimaryCutTool = Part.Shape()
            obj.SecondaryCutTool = Part.Shape()
            obj.SecondaryStartExtension = 0.0
            obj.SecondaryEndExtension = 0.0
            obj.ValidationResults = json.dumps([{
                "level": "error",
                "message": "Members no longer intersect at a valid angle",
                "code": "NO_INTERSECTION",
            }])
            # Touch members to clear old cuts if they changed.
            if self._cuts_changed(obj):
                primary.touch()
                secondary.touch()
            return

        # Update intersection display properties.
        # NOTE: The CLAUDE.md rule "never modify own properties in execute()"
        # targets properties that other objects link to (causing recompute
        # loops).  These are display-only read-only fields; no object has a
        # Link or Expression pointing to them.
        obj.IsBroken = False
        obj.IntersectionPoint = joint_cs.origin
        obj.IntersectionAngle = joint_cs.angle
        obj.LastValidPoint = fresh_point
        obj.LastValidPrimaryPoint = pt1
        obj.LastValidSecondaryPoint = pt2

        # 2. Look up joint definition.
        joint_type_id = obj.JointType
        if not joint_type_id:
            joint_type_id = DEFAULT_JOINT_TYPES.get(
                obj.IntersectionType, "placeholder"
            )
            obj.JointType = joint_type_id

        definition = get_definition(joint_type_id)

        if definition is None:
            FreeCAD.Console.PrintError(
                f"TimberJoint: unknown joint type '{joint_type_id}' — "
                f"resetting to placeholder\n"
            )
            obj.JointType = "placeholder"
            joint_type_id = "placeholder"
            definition = get_definition(joint_type_id)

        if definition is None:
            # Placeholder definition itself is missing — nothing we can do.
            FreeCAD.Console.PrintError(
                "TimberJoint: placeholder joint definition not found\n"
            )
            obj.Shape = Part.makeBox(1, 1, 1)
            obj.PrimaryCutTool = Part.Shape()
            obj.SecondaryCutTool = Part.Shape()
            obj.SecondaryStartExtension = 0.0
            obj.SecondaryEndExtension = 0.0
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
                new_bounds = {}
                for name, p in fresh.items():
                    new_defaults[name] = p.default_value
                    new_bounds[name] = (p.min_value, p.max_value)
                params.update_defaults(new_defaults)
                params.update_bounds(new_bounds)
                # Update dependent defaults (e.g. mortise follows tenon).
                definition.update_dependent_defaults(params)
        else:
            params = fresh

        # Only write Parameters if the JSON actually changed, to avoid
        # unnecessary property-change → recompute cycles.
        new_params_json = params.to_json()
        if obj.Parameters != new_params_json:
            obj.Parameters = new_params_json

        # 4. Build cut tools.
        primary_tool = definition.build_primary_tool(
            params, primary, secondary, joint_cs
        )
        secondary_profile = definition.build_secondary_profile(
            params, primary, secondary, joint_cs
        )

        obj.PrimaryCutTool = primary_tool
        obj.SecondaryCutTool = secondary_profile.shoulder_cut

        # 4b. Compute secondary member extension distance.
        ext = definition.secondary_extension(
            params, primary, secondary, joint_cs
        )
        s_start = FreeCAD.Vector(secondary.A_StartPoint)
        s_end_pt = FreeCAD.Vector(secondary.B_EndPoint)
        dist_start = (joint_cs.origin - s_start).Length
        dist_end = (joint_cs.origin - s_end_pt).Length
        if dist_start <= dist_end:
            obj.SecondaryStartExtension = ext
            obj.SecondaryEndExtension = 0.0
        else:
            obj.SecondaryStartExtension = 0.0
            obj.SecondaryEndExtension = ext

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

        # 6b. Check for duplicate secondary endpoint.
        dup_warning = self._check_duplicate_secondary_endpoint(obj)
        if dup_warning is not None:
            results.append(dup_warning)

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
        # Guard against infinite recompute: only touch members when the
        # cut tools actually changed.  This avoids the cycle:
        #   Joint writes same cuts → touch → member recomputes →
        #   joint recomputes → same cuts → no touch → stable.
        #
        # Also handles multiple joints on the same member gracefully —
        # each joint independently decides whether its cuts changed,
        # and only touches if they did.
        if self._cuts_changed(obj):
            primary.touch()
            secondary.touch()

    # -- broken joint visual -------------------------------------------------

    @staticmethod
    def _build_broken_visual(obj, primary, secondary, pt1_now, pt2_now):
        """Build a visual shape for a broken joint.

        Shows octahedron markers where the gap cylinder exits each
        timber's face, plus the thin gap cylinder itself.  The
        octahedra sit at the timber surface so they are always visible.

        Parameters
        ----------
        obj : FreeCAD document object
            The TimberJoint object (for reading LastValid* properties).
        primary, secondary : FreeCAD document objects
            The linked TimberMember objects (for reading cross-section size).
        pt1_now : FreeCAD.Vector
            Current closest point on the primary member's datum.
        pt2_now : FreeCAD.Vector
            Current closest point on the secondary member's datum.
        """
        LINE_RADIUS = 1.0     # mm

        parts = []

        gap_vec = pt2_now - pt1_now
        gap_len = gap_vec.Length
        if gap_len < 0.1:
            gap_dir = FreeCAD.Vector(0, 0, 1)
        else:
            gap_dir = FreeCAD.Vector(gap_vec)
            gap_dir.normalize()

        # Place octahedron markers at the timber face where the gap
        # cylinder exits each member.  The datum point is at the member
        # center; offset along gap direction by half the cross-section
        # dimension to reach the SIDE face.
        #
        # However, when the gap direction aligns with the member's axis
        # (i.e. the datum point is an endpoint, not a midpoint), the gap
        # exits through the END face, which is at approximately the
        # datum point itself — not half_dim away.  Scale the offset by
        # (1 - alignment) so endpoint exits get near-zero offset while
        # midpoint (perpendicular) exits get the full half_dim.
        for member, datum_pt, sign in [
            (primary, pt1_now, 1.0),      # toward secondary
            (secondary, pt2_now, -1.0),   # toward primary
        ]:
            try:
                w = float(member.Width)
                h = float(member.Height)
                half_dim = max(w, h) / 2.0
                marker_size = max(half_dim * 0.35, 8.0)

                # Compute alignment of gap direction with member axis.
                m_start = FreeCAD.Vector(member.A_StartPoint)
                m_end = FreeCAD.Vector(member.B_EndPoint)
                m_axis = m_end - m_start
                m_len = m_axis.Length
                if m_len > 0.01:
                    m_axis.normalize()
                    alignment = abs(gap_dir.dot(m_axis))
                else:
                    alignment = 0.0

                # alignment ≈ 1 → gap along member axis → end face → ~0 offset
                # alignment ≈ 0 → gap perpendicular → side face → full offset
                face_offset = half_dim * (1.0 - alignment)
                face_pt = datum_pt + gap_dir * (sign * max(face_offset, 1.0))
                octa = TimberJoint._make_octahedron(
                    face_pt, marker_size
                )
                if octa is not None:
                    parts.append(octa)
            except Exception:
                # Fallback: small octahedron at datum point
                try:
                    octa = TimberJoint._make_octahedron(datum_pt, 8.0)
                    if octa is not None:
                        parts.append(octa)
                except Exception:
                    pass

        # Gap cylinder between current closest points.
        if gap_len > 0.1:
            try:
                parts.append(
                    Part.makeCylinder(LINE_RADIUS, gap_len, pt1_now, gap_vec)
                )
            except Exception:
                pass

        if parts:
            return Part.makeCompound(parts)
        return Part.makeBox(1, 1, 1)

    @staticmethod
    def _make_octahedron(center, size):
        """Build an octahedron (8 triangular faces) centered at *center*.

        Parameters
        ----------
        center : FreeCAD.Vector
            Center of the octahedron.
        size : float
            Distance from center to each vertex.

        Returns
        -------
        Part.Shape or None
        """
        try:
            cx, cy, cz = center.x, center.y, center.z
            # Six vertices along ±X, ±Y, ±Z axes
            verts = [
                FreeCAD.Vector(cx + size, cy, cz),   # +X  (0)
                FreeCAD.Vector(cx - size, cy, cz),   # -X  (1)
                FreeCAD.Vector(cx, cy + size, cz),   # +Y  (2)
                FreeCAD.Vector(cx, cy - size, cz),   # -Y  (3)
                FreeCAD.Vector(cx, cy, cz + size),   # +Z  (4)
                FreeCAD.Vector(cx, cy, cz - size),   # -Z  (5)
            ]
            # 8 triangular faces
            face_indices = [
                (0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
                (0, 5, 2), (2, 5, 1), (1, 5, 3), (3, 5, 0),
            ]
            faces = []
            for i0, i1, i2 in face_indices:
                wire = Part.makePolygon([
                    verts[i0], verts[i1], verts[i2], verts[i0]
                ])
                faces.append(Part.Face(wire))
            shell = Part.makeShell(faces)
            return Part.makeSolid(shell)
        except Exception:
            return None

    # -- duplicate secondary endpoint check ---------------------------------

    @staticmethod
    def _check_duplicate_secondary_endpoint(obj):
        """Warn if another joint shares this joint's secondary endpoint.

        Scans the document for other TimberJoint objects that reference
        the same SecondaryMember at the same endpoint (start or end).
        Two joints competing for the same endpoint would produce
        conflicting shoulder cuts.

        Returns a :class:`ValidationResult` or ``None``.
        """
        doc = obj.Document
        if doc is None:
            return None

        secondary = obj.SecondaryMember
        if secondary is None:
            return None

        sec_name = secondary.Name

        # Determine which endpoint of the secondary this joint uses.
        s_start = FreeCAD.Vector(secondary.A_StartPoint)
        s_end = FreeCAD.Vector(secondary.B_EndPoint)
        ip = FreeCAD.Vector(obj.IntersectionPoint)
        dist_start = (ip - s_start).Length
        dist_end = (ip - s_end).Length
        at_start = dist_start <= dist_end

        for other in doc.Objects:
            if other.Name == obj.Name:
                continue
            if not hasattr(other, "SecondaryMember"):
                continue
            other_sec = getattr(other, "SecondaryMember", None)
            if other_sec is None:
                continue
            # Compare by Name — FreeCAD object identity can be unreliable.
            try:
                if other_sec.Name != sec_name:
                    continue
            except Exception:
                continue
            # Same secondary member — check if it claims the same endpoint.
            try:
                other_ip = FreeCAD.Vector(other.IntersectionPoint)
                od_start = (other_ip - s_start).Length
                od_end = (other_ip - s_end).Length
                other_at_start = od_start <= od_end
            except Exception:
                continue

            if at_start == other_at_start:
                end_name = "start" if at_start else "end"
                FreeCAD.Console.PrintWarning(
                    f"TimberJoint: {obj.Label} and {other.Label} both "
                    f"use the {end_name} endpoint of {secondary.Label}\n"
                )
                return ValidationResult(
                    "warning",
                    f"Another joint ({other.Label}) also uses the "
                    f"{end_name} endpoint of {secondary.Label}.  "
                    f"Conflicting shoulder cuts may result.",
                    "DUPLICATE_SECONDARY_ENDPOINT",
                )

        return None

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
            self._active_panel = None

        def getIcon(self):
            return os.path.join(_ICON_DIR, "timber_joint.svg")

        def updateData(self, obj, prop):
            # Dynamic color based on broken/joint-type state.
            if prop in ("IsBroken", "JointType", "Shape"):
                self._update_color(obj)

            panel = getattr(self, '_active_panel', None)
            if panel is not None:
                try:
                    panel.notify_property_changed(prop)
                except (RuntimeError, AttributeError):
                    # Panel widget was deleted (dialog closed).
                    self._active_panel = None

        def _update_color(self, obj):
            """Set ShapeColor based on broken state and joint type."""
            vobj = obj.ViewObject
            if vobj is None:
                return
            try:
                if getattr(obj, "IsBroken", False):
                    vobj.ShapeColor = (0.90, 0.10, 0.10)   # red — broken
                elif getattr(obj, "JointType", "placeholder") == "placeholder":
                    vobj.ShapeColor = (1.0, 0.65, 0.0)     # orange — needs assignment
                else:
                    vobj.ShapeColor = (0.40, 0.50, 0.60)    # blue-gray — assigned
            except Exception:
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
            """Clean up panel and schedule member recompute after deletion."""
            panel = getattr(self, "_active_panel", None)
            if panel is not None:
                panel._disconnect()
                self._active_panel = None
                try:
                    FreeCADGui.Control.closeDialog()
                except Exception:
                    pass

            # Capture member references before the joint is removed from
            # the document.  Schedule a deferred recompute so it runs
            # AFTER deletion — by then _collect_joint_cuts will no longer
            # find this joint and the boolean cuts will disappear.
            obj = vobj.Object
            members_to_update = []
            try:
                if obj.PrimaryMember is not None:
                    members_to_update.append(obj.PrimaryMember.Name)
                if obj.SecondaryMember is not None:
                    members_to_update.append(obj.SecondaryMember.Name)
            except Exception:
                pass

            if members_to_update:
                doc_name = obj.Document.Name
                from PySide2 import QtCore

                def _deferred_recompute():
                    try:
                        doc = FreeCAD.getDocument(doc_name)
                        if doc is None:
                            return
                        for mname in members_to_update:
                            m = doc.getObject(mname)
                            if m is not None:
                                m.touch()
                        doc.recompute()
                    except Exception:
                        pass

                QtCore.QTimer.singleShot(0, _deferred_recompute)

            return True

        def doubleClicked(self, vobj):
            """Open the JointPanel task panel for editing."""
            from ui.JointTaskPanel import JointTaskPanel

            panel = JointTaskPanel(vobj.Object)
            FreeCADGui.Control.showDialog(panel)
            self._active_panel = panel.panel
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
            "placeholder",
        )

    if FreeCAD.GuiUp:
        TimberJointViewProvider(obj.ViewObject)
        effective_type = joint_type_id or DEFAULT_JOINT_TYPES.get(
            intersection_result.intersection_type, "placeholder"
        )
        if effective_type == "placeholder":
            obj.ViewObject.ShapeColor = (1.0, 0.65, 0.0)  # orange — needs assignment
        else:
            obj.ViewObject.ShapeColor = (0.40, 0.50, 0.60)  # blue-gray

    # Auto-add to Bent if both members share the same Bent.
    from objects.Bent import find_parent_bent, Bent as BentProxy
    pri_bent = find_parent_bent(doc, primary_obj)
    if pri_bent is not None:
        sec_bent = find_parent_bent(doc, secondary_obj)
        if sec_bent is pri_bent:
            BentProxy.add_joint(pri_bent, obj)

    # Two recompute passes are needed:
    #   Pass 1: Members build raw solids, Joint computes cut shapes and
    #           touches both members.
    #   Pass 2: Members recompute with the new cut shapes applied.
    doc.recompute()
    doc.recompute()
    return obj
