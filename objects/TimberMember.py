"""TimberMember — the fundamental building block of a timber frame.

Every timber in the frame is a TimberMember.  It owns a datum line
(StartPoint → EndPoint), cross-section dimensions, material properties,
and derived solid geometry.

This module must work headless — no FreeCADGui / Qt imports at module level.
"""

import math
import uuid

import FreeCAD
import Part

# ---------------------------------------------------------------------------
# Role enumeration and MemberID prefix mapping
# ---------------------------------------------------------------------------

ROLES = [
    "Post",
    "Beam",
    "Rafter",
    "Purlin",
    "Girt",
    "TieBeam",
    "Brace",
    "Header",
    "Trimmer",
    "Ridge",
    "Valley",
    "Sill",
    "Plate",
    "FloorJoist",
    "SummerBeam",
]

ROLE_PREFIX = {
    "Post": "P",
    "Beam": "B",
    "Rafter": "R",
    "Purlin": "PU",
    "Girt": "G",
    "TieBeam": "B",
    "Brace": "BR",
    "Header": "H",
    "Trimmer": "T",
    "Ridge": "RD",
    "Valley": "V",
    "Sill": "S",
    "Plate": "PL",
    "FloorJoist": "FJ",
    "SummerBeam": "SB",
}

REFERENCE_FACES = ["Top", "Bottom", "Left", "Right"]

# Placeholder species list — will be replaced by CSV lookup in later phases.
SPECIES = [
    "Douglas Fir",
    "Eastern White Pine",
    "Red Oak",
    "White Oak",
    "Southern Yellow Pine",
    "Hem-Fir",
]

GRADES = [
    "Select Structural",
    "No. 1",
    "No. 2",
    "No. 3",
]


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class TimberMember:
    """Proxy object attached to an ``App::FeaturePython`` document object."""

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    # -- properties ---------------------------------------------------------

    @staticmethod
    def _add_properties(obj):
        """Add all TimberMember properties.  Safe to call on restore."""

        def _ensure(ptype, name, group, doc, default=None):
            if hasattr(obj, name):
                return
            obj.addProperty(ptype, name, group, doc)
            if default is not None:
                setattr(obj, name, default)

        # Datum
        _ensure("App::PropertyVector", "StartPoint", "Datum",
                "Start of the datum line")
        _ensure("App::PropertyVector", "EndPoint", "Datum",
                "End of the datum line",
                FreeCAD.Vector(0, 0, 1000))
        _ensure("App::PropertyFloatList", "SupportFractions", "Datum",
                "Fractional support positions along datum (simple beam = [0, 1])",
                [0.0, 1.0])

        # Section
        _ensure("App::PropertyLength", "Width", "Section",
                "Member width (narrow face)", 150.0)
        _ensure("App::PropertyLength", "Height", "Section",
                "Member height (deep face)", 200.0)
        _ensure("App::PropertyEnumeration", "ReferenceFace", "Section",
                "Face aligned to the datum line")
        if not obj.ReferenceFace:
            obj.ReferenceFace = REFERENCE_FACES
            obj.ReferenceFace = "Bottom"

        # Material
        _ensure("App::PropertyEnumeration", "Species", "Material",
                "Wood species")
        if not obj.Species:
            obj.Species = SPECIES
            obj.Species = "Douglas Fir"
        _ensure("App::PropertyEnumeration", "Grade", "Material",
                "Lumber grade")
        if not obj.Grade:
            obj.Grade = GRADES
            obj.Grade = "Select Structural"

        # Structure
        _ensure("App::PropertyEnumeration", "Role", "Structure",
                "Structural role of this member")
        if not obj.Role:
            obj.Role = ROLES
            obj.Role = "Post"

        # Cuts
        _ensure("App::PropertyAngle", "StartCutAngle", "Cuts",
                "Start cut angle from perpendicular", 0.0)
        _ensure("App::PropertyAngle", "EndCutAngle", "Cuts",
                "End cut angle from perpendicular", 0.0)

        # Identity
        _ensure("App::PropertyString", "MemberID", "Identity",
                "Display label (e.g. P2-1)")
        _ensure("App::PropertyString", "FabricationSignature", "Identity",
                "Normalized hash for grouping identical members")
        _ensure("App::PropertyString", "InternalUUID", "Identity",
                "Stable internal identifier, never changes")
        if not obj.InternalUUID:
            obj.InternalUUID = str(uuid.uuid4())

        # Make computed identity fields read-only.
        obj.setEditorMode("FabricationSignature", 1)  # read-only
        obj.setEditorMode("InternalUUID", 1)

    # -- recompute ----------------------------------------------------------

    def execute(self, obj):
        """Build the member solid from datum line and section.

        Must never raise — FreeCAD puts the object in a permanent error state
        if execute() throws.
        """
        try:
            solid = self._build_solid(obj)
            # Apply boolean cuts from connected joints.
            cuts = self._collect_joint_cuts(obj)
            for cut_tool in cuts:
                try:
                    solid = solid.cut(cut_tool)
                except Exception as exc:
                    FreeCAD.Console.PrintWarning(
                        f"TimberMember boolean cut failed: {exc}\n"
                    )
            obj.Shape = solid
        except Exception as e:
            FreeCAD.Console.PrintError(
                f"TimberMember execute failed: {e}\n"
            )
            obj.Shape = Part.makeBox(1, 1, 1)

    # -- geometry helpers ---------------------------------------------------

    @staticmethod
    def _build_solid(obj):
        """Return a Part.Shape box oriented along the datum line.

        The cross-section is placed according to ``ReferenceFace``:
        - Bottom: datum runs along the bottom centre of the member.
        - Top:    datum runs along the top centre.
        - Left:   datum runs along the left centre.
        - Right:  datum runs along the right centre.
        """
        start = FreeCAD.Vector(obj.StartPoint)
        end = FreeCAD.Vector(obj.EndPoint)
        direction = end - start
        length = direction.Length

        if length < 1e-6:
            return Part.makeBox(1, 1, 1)

        w = float(obj.Width)
        h = float(obj.Height)
        if w < 1e-6 or h < 1e-6:
            return Part.makeBox(1, 1, 1)

        datum_axis = FreeCAD.Vector(direction)
        datum_axis.normalize()

        # Build a local coordinate system.
        # X = along datum, Y = width direction, Z = height direction.
        # Choose an 'up' hint that isn't parallel to the datum.
        world_z = FreeCAD.Vector(0, 0, 1)
        if abs(datum_axis.dot(world_z)) > 0.999:
            up_hint = FreeCAD.Vector(0, 1, 0)
        else:
            up_hint = world_z

        y_axis = datum_axis.cross(up_hint)
        y_axis.normalize()
        z_axis = y_axis.cross(datum_axis)
        z_axis.normalize()

        # Offset from datum depending on ReferenceFace.
        ref = obj.ReferenceFace
        if ref == "Bottom":
            offset = z_axis * 0.0 + y_axis * (-w / 2.0)
            offset_z = 0.0
        elif ref == "Top":
            offset = z_axis * (-h) + y_axis * (-w / 2.0)
            offset_z = 0.0
        elif ref == "Left":
            offset = z_axis * (-h / 2.0) + y_axis * 0.0
            offset_z = 0.0
        elif ref == "Right":
            offset = z_axis * (-h / 2.0) + y_axis * (-w)
            offset_z = 0.0
        else:
            offset = z_axis * 0.0 + y_axis * (-w / 2.0)
            offset_z = 0.0

        origin = start + offset

        # Create a rectangular cross-section wire.
        p1 = origin
        p2 = origin + y_axis * w
        p3 = origin + y_axis * w + z_axis * h
        p4 = origin + z_axis * h

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)
        solid = face.extrude(datum_axis * length)

        return solid

    # -- joint cut collection -----------------------------------------------

    @staticmethod
    def _collect_joint_cuts(obj):
        """Scan the document for TimberJoint cut tools targeting this member.

        Returns a list of ``Part.Shape`` cut tools to boolean-subtract from
        the member solid.  Uses a document scan (no Link) to avoid creating
        a circular dependency with TimberJoint objects.
        """
        doc = obj.Document
        if doc is None:
            return []

        cuts = []
        for doc_obj in doc.Objects:
            # Quick filter: must have PrimaryMember property.
            if not hasattr(doc_obj, "PrimaryMember"):
                continue
            if not hasattr(doc_obj, "PrimaryCutTool"):
                continue

            if doc_obj.PrimaryMember == obj:
                shape = doc_obj.PrimaryCutTool
                if shape and not shape.isNull():
                    cuts.append(shape)
            elif getattr(doc_obj, "SecondaryMember", None) == obj:
                shape = doc_obj.SecondaryCutTool
                if shape and not shape.isNull():
                    cuts.append(shape)

        return cuts

    # -- coordinate system export -------------------------------------------

    @staticmethod
    def get_member_local_cs(obj):
        """Return the member's local coordinate system.

        Returns ``(origin, x_axis, y_axis, z_axis)`` where:

        - ``origin`` = datum start point
        - ``x_axis`` = unit vector along datum (start -> end)
        - ``y_axis`` = unit vector in width direction
        - ``z_axis`` = unit vector in height direction

        This matches the coordinate system used in ``_build_solid()``.
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

        return (start, x_axis, y_axis, z_axis)

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

    class TimberMemberViewProvider:
        """View provider for TimberMember objects."""

        def __init__(self, vobj):
            vobj.Proxy = self

        def attach(self, vobj):
            self.Object = vobj.Object

        def getIcon(self):
            return os.path.join(_ICON_DIR, "timber_member.svg")

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
# Helper: create a new TimberMember in the active document
# ---------------------------------------------------------------------------

def create_timber_member(name="TimberMember", start=None, end=None, role="Post"):
    """Create and return a new TimberMember document object.

    Parameters
    ----------
    name : str
        Base label for the object.
    start : FreeCAD.Vector or None
        Datum start point.  Defaults to origin.
    end : FreeCAD.Vector or None
        Datum end point.  Defaults to (0, 0, 1000).
    role : str
        One of the ROLES values.

    Returns
    -------
    obj : App::FeaturePython
        The newly created document object.
    """
    doc = FreeCAD.ActiveDocument
    if doc is None:
        raise RuntimeError("No active document")

    obj = doc.addObject("Part::FeaturePython", name)
    TimberMember(obj)

    if start is not None:
        obj.StartPoint = start
    if end is not None:
        obj.EndPoint = end
    if role in ROLES:
        obj.Role = role

    prefix = ROLE_PREFIX.get(role, "M")
    if not obj.MemberID:
        obj.MemberID = prefix

    if FreeCAD.GuiUp:
        TimberMemberViewProvider(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.76, 0.60, 0.37)  # warm timber tone

    doc.recompute()
    return obj
