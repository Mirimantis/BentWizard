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

# ---------------------------------------------------------------------------
# Face numbering system
# ---------------------------------------------------------------------------
# Faces are numbered 1-4 around the cross-section.  Face 1 is always the
# reference face (ReferenceFace property).  Faces 2-4 follow clockwise
# when looking from End A (butt) toward End B (top/tip).
#
# The member's local coordinate system:
#   X = along datum (A_StartPoint -> B_EndPoint)
#   Y = width direction (perpendicular to datum, from up-hint cross product)
#   Z = height direction (perpendicular to both X and Y)
#
# For a horizontal beam with ReferenceFace = "Bottom", looking from A -> B:
#
#          Face 3 (+Z)
#         +------------------+
#         |                  |
# Face 4  |     datum .      | Face 2
# (+Y)    |                  | (-Y)
#         +------------------+
#          Face 1 (-Z)  <- Reference Face
#
# End A (butt) = A_StartPoint   — look from here to establish CW numbering
# End B (top/tip) = B_EndPoint

# Maps ReferenceFace value -> (axis, sign) for the outward normal of that face.
# axis is 'y' or 'z' in the member's local CS.
_REFFACE_NORMAL = {
    "Top":    ("z", +1),
    "Bottom": ("z", -1),
    "Right":  ("y", +1),
    "Left":   ("y", -1),
}

# Clockwise rotation order (looking from A toward B) for each starting face.
# Given Face 1, Face 2/3/4 follow this sequence.
_CW_ORDER = {
    "Bottom": ["Bottom", "Left", "Top", "Right"],
    "Top":    ["Top", "Right", "Bottom", "Left"],
    "Right":  ["Right", "Bottom", "Left", "Top"],
    "Left":   ["Left", "Top", "Right", "Bottom"],
}


def face_numbering(obj):
    """Return the 4 outward-normal vectors in face-number order [1, 2, 3, 4].

    Face 1 is the reference face.  Faces 2-4 follow clockwise when
    looking from the A end toward the B end.

    Parameters
    ----------
    obj : App::FeaturePython
        A TimberMember document object.

    Returns
    -------
    list[FreeCAD.Vector]
        Four unit vectors, each being the outward normal of Face 1..4.
    """
    _, x_axis, y_axis, z_axis = TimberMember.get_member_local_cs(obj)
    axes = {"y": y_axis, "z": z_axis}

    ref = obj.ReferenceFace if obj.ReferenceFace else "Bottom"
    order = _CW_ORDER.get(ref, _CW_ORDER["Bottom"])

    normals = []
    for face_name in order:
        axis_key, sign = _REFFACE_NORMAL[face_name]
        normals.append(axes[axis_key] * sign)
    return normals

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
        # FreeCAD sorts properties alphabetically within a group.
        # "A_" / "B_" prefixes keep Start before End in the panel.
        _ensure("App::PropertyVector", "A_StartPoint", "Datum",
                "Start of the datum line")
        _ensure("App::PropertyVector", "B_EndPoint", "Datum",
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

        The datum line always runs through the geometric centre of the
        cross-section.  ``ReferenceFace`` is stored for future use
        (layout marks, positioning offsets) but does not affect the
        solid's position relative to the datum.

        Joint-driven extensions: if connected joints request extra length
        at either endpoint (e.g. a tenon protruding past the datum), the
        solid is lengthened accordingly.  The joint's shoulder cut then
        shapes the extension into the correct tenon profile.
        """
        start = FreeCAD.Vector(obj.A_StartPoint)
        end = FreeCAD.Vector(obj.B_EndPoint)
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

        # Query joint-driven extensions at each endpoint.
        start_ext, end_ext = TimberMember._collect_extensions(obj)
        effective_start = start - datum_axis * start_ext
        effective_length = length + start_ext + end_ext

        # Centre the cross-section on the datum line at the effective start.
        origin = effective_start + z_axis * (-h / 2.0) + y_axis * (-w / 2.0)

        # Create a rectangular cross-section wire.
        p1 = origin
        p2 = origin + y_axis * w
        p3 = origin + y_axis * w + z_axis * h
        p4 = origin + z_axis * h

        wire = Part.makePolygon([p1, p2, p3, p4, p1])
        face = Part.Face(wire)
        solid = face.extrude(datum_axis * effective_length)

        return solid

    # -- joint extension collection -----------------------------------------

    @staticmethod
    def _collect_extensions(obj):
        """Query connected joints for datum endpoint extensions.

        Scans the document for :class:`TimberJoint` objects that reference
        this member as ``SecondaryMember`` and reads their hidden
        ``SecondaryStartExtension`` / ``SecondaryEndExtension`` properties.

        Returns ``(start_ext, end_ext)`` in mm.  When multiple joints
        request extensions at the same endpoint, the maximum is used.
        """
        doc = obj.Document
        if doc is None:
            return 0.0, 0.0

        start_ext = 0.0
        end_ext = 0.0
        for doc_obj in doc.Objects:
            if getattr(doc_obj, "SecondaryMember", None) != obj:
                continue
            se = getattr(doc_obj, "SecondaryStartExtension", 0.0)
            ee = getattr(doc_obj, "SecondaryEndExtension", 0.0)
            start_ext = max(start_ext, se)
            end_ext = max(end_ext, ee)
        return start_ext, end_ext

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
        - ``x_axis`` = unit vector along datum (start → end)
        - ``y_axis`` = unit vector in width direction
        - ``z_axis`` = unit vector in height direction

        This matches the coordinate system used in ``_build_solid()``.
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
    from pivy import coin

    _ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             "resources", "icons")

    # -- colors ---------------------------------------------------------------
    _COLOR_TIMBER = (0.76, 0.60, 0.37)       # standard timber face
    _COLOR_REF_FACE = (0.55, 0.38, 0.20)     # darker tint for reference face
    _COLOR_CHALK = (1.0, 1.0, 0.85)          # chalk line on reference face
    _COLOR_LABEL = (1.0, 1.0, 1.0)           # white for A/B labels
    _COLOR_FACE_NUM = (0.95, 0.85, 0.55)     # warm gold for face numbers
    _LABEL_FONT_SIZE = 20
    _FACE_NUM_FONT_SIZE = 16
    _NORMAL_THRESHOLD = 0.7  # dot product threshold for face identification

    class TimberMemberViewProvider:
        """View provider for TimberMember objects.

        Provides visual landmarks:
        - Per-face coloring with reference face (Face 1) tinted darker
        - Chalk line along the center of the reference face
        - "A" / "B" labels at datum endpoints
        - "1"-"4" face number labels at face centers
        - All annotations togglable via ShowAnnotations property
        """

        def __init__(self, vobj):
            vobj.Proxy = self
            self._setup_view_properties(vobj)

        @staticmethod
        def _setup_view_properties(vobj):
            if not hasattr(vobj, "ShowAnnotations"):
                vobj.addProperty(
                    "App::PropertyBool", "ShowAnnotations", "Display",
                    "Show face numbers, endpoint labels, and chalk line",
                )
                vobj.ShowAnnotations = True

        def attach(self, vobj):
            self.Object = vobj.Object
            self._setup_view_properties(vobj)
            self._build_coin_nodes(vobj)

        def _build_coin_nodes(self, vobj):
            """Create Coin3D nodes for annotations."""
            # Root separator for all annotation geometry
            self._anno_root = coin.SoSeparator()
            self._anno_root.setName("TimberAnnotations")

            # -- A / B endpoint labels --
            self._label_a = self._make_text_node(
                "A", _COLOR_LABEL, _LABEL_FONT_SIZE)
            self._label_b = self._make_text_node(
                "B", _COLOR_LABEL, _LABEL_FONT_SIZE)
            self._anno_root.addChild(self._label_a["sep"])
            self._anno_root.addChild(self._label_b["sep"])

            # -- Face number labels 1-4 --
            self._face_labels = []
            for i in range(4):
                node = self._make_text_node(
                    str(i + 1), _COLOR_FACE_NUM, _FACE_NUM_FONT_SIZE)
                self._face_labels.append(node)
                self._anno_root.addChild(node["sep"])

            # -- Chalk line on reference face --
            self._chalk_sep = coin.SoSeparator()
            self._chalk_sep.setName("ChalkLine")
            mat = coin.SoMaterial()
            mat.diffuseColor.setValue(*_COLOR_CHALK)
            mat.emissiveColor.setValue(*_COLOR_CHALK)
            self._chalk_sep.addChild(mat)
            style = coin.SoDrawStyle()
            style.lineWidth.setValue(2.0)
            self._chalk_sep.addChild(style)
            self._chalk_coords = coin.SoCoordinate3()
            self._chalk_coords.point.setNum(2)
            self._chalk_sep.addChild(self._chalk_coords)
            line = coin.SoLineSet()
            line.numVertices.setValue(2)
            self._chalk_sep.addChild(line)
            self._anno_root.addChild(self._chalk_sep)

            # Add to the ViewProvider's root node
            vobj.RootNode.addChild(self._anno_root)

        @staticmethod
        def _make_text_node(text, color, size):
            """Create a SoSeparator with SoText2 for a screen-space label."""
            sep = coin.SoSeparator()
            trans = coin.SoTranslation()
            sep.addChild(trans)
            mat = coin.SoMaterial()
            mat.diffuseColor.setValue(*color)
            mat.emissiveColor.setValue(*color)
            sep.addChild(mat)
            font = coin.SoFont()
            font.size.setValue(size)
            font.name.setValue("Arial")
            sep.addChild(font)
            txt = coin.SoText2()
            txt.string.setValue(text)
            sep.addChild(txt)
            return {"sep": sep, "trans": trans, "text": txt}

        def getIcon(self):
            return os.path.join(_ICON_DIR, "timber_member.svg")

        def updateData(self, obj, prop):
            """Refresh visuals when data properties change."""
            if prop in ("A_StartPoint", "B_EndPoint", "Width", "Height",
                        "ReferenceFace", "Shape"):
                try:
                    self._update_annotations(obj)
                except Exception as e:
                    FreeCAD.Console.PrintWarning(
                        f"TimberMember annotation update failed: {e}\n"
                    )
                try:
                    self._apply_face_colors(obj)
                except Exception as e:
                    FreeCAD.Console.PrintWarning(
                        f"TimberMember face color update failed: {e}\n"
                    )

        def onChanged(self, vobj, prop):
            if prop == "ShowAnnotations":
                show = vobj.ShowAnnotations
                if hasattr(self, "_anno_root") and hasattr(vobj, "RootNode"):
                    root = vobj.RootNode
                    idx = root.findChild(self._anno_root)
                    if show and idx < 0:
                        root.addChild(self._anno_root)
                    elif not show and idx >= 0:
                        root.removeChild(self._anno_root)
                # Re-apply face colors (uniform when annotations off)
                if hasattr(self, "Object") and self.Object is not None:
                    try:
                        self._apply_face_colors(self.Object)
                    except Exception:
                        pass

        def _update_annotations(self, obj):
            """Reposition all Coin3D annotation nodes."""
            if not hasattr(self, "_anno_root"):
                return
            vobj = obj.ViewObject
            if not getattr(vobj, "ShowAnnotations", True):
                return

            _, x_axis, y_axis, z_axis = TimberMember.get_member_local_cs(obj)
            start = FreeCAD.Vector(obj.A_StartPoint)
            end = FreeCAD.Vector(obj.B_EndPoint)
            w = float(obj.Width)
            h = float(obj.Height)
            midpoint = (start + end) * 0.5

            # Offset labels above and inward from the member endpoints
            # so they don't overlap with snap handles at the datum tips.
            label_offset = z_axis * (h / 2.0 + 40.0)
            inward_nudge = x_axis * (w * 0.4)

            # A label at start, nudged inward toward member center
            pos_a = start + label_offset + inward_nudge
            self._label_a["trans"].translation.setValue(
                pos_a.x, pos_a.y, pos_a.z)

            # B label at end, nudged inward toward member center
            pos_b = end + label_offset - inward_nudge
            self._label_b["trans"].translation.setValue(
                pos_b.x, pos_b.y, pos_b.z)

            # Face number labels at face centers
            normals = face_numbering(obj)
            for i, normal in enumerate(normals):
                # Face center = midpoint + normal * half-extent + small offset
                if abs(normal.dot(y_axis)) > 0.5:
                    half_ext = w / 2.0
                else:
                    half_ext = h / 2.0
                pos = midpoint + normal * (half_ext + 30.0)
                self._face_labels[i]["trans"].translation.setValue(
                    pos.x, pos.y, pos.z)

            # Chalk line along center of reference face (Face 1)
            ref_normal = normals[0]
            if abs(ref_normal.dot(y_axis)) > 0.5:
                half_ext = w / 2.0
            else:
                half_ext = h / 2.0
            chalk_offset = ref_normal * (half_ext + 0.5)  # just above surface
            p1 = start + chalk_offset
            p2 = end + chalk_offset
            self._chalk_coords.point.set1Value(0, p1.x, p1.y, p1.z)
            self._chalk_coords.point.set1Value(1, p2.x, p2.y, p2.z)

        def _apply_face_colors(self, obj):
            """Set per-face DiffuseColor based on face numbering."""
            vobj = obj.ViewObject
            if vobj is None:
                return
            if not hasattr(obj, "Shape") or obj.Shape.isNull():
                return

            faces = obj.Shape.Faces
            if not faces:
                return

            # If annotations are off, use uniform color
            if not getattr(vobj, "ShowAnnotations", True):
                vobj.DiffuseColor = [_COLOR_TIMBER + (0.0,)] * len(faces)
                return

            normals = face_numbering(obj)
            ref_normal = normals[0]  # Face 1 = reference face

            colors = []
            for occ_face in faces:
                try:
                    # Get outward normal at face center
                    uv = occ_face.Surface.parameter(occ_face.CenterOfMass)
                    fn = occ_face.normalAt(uv[0], uv[1])
                    # Check if this face matches the reference face normal
                    if fn.dot(ref_normal) > _NORMAL_THRESHOLD:
                        colors.append(_COLOR_REF_FACE + (0.0,))
                    else:
                        colors.append(_COLOR_TIMBER + (0.0,))
                except Exception:
                    colors.append(_COLOR_TIMBER + (0.0,))

            vobj.DiffuseColor = colors

        def getDisplayModes(self, vobj):
            return ["Flat Lines"]

        def getDefaultDisplayMode(self):
            return "Flat Lines"

        def setDisplayMode(self, mode):
            return mode

        def onDelete(self, vobj, subelements):
            return True

        def onDocumentRestored(self, vobj):
            """Re-setup after document load."""
            self._setup_view_properties(vobj)
            self.Object = vobj.Object
            self._build_coin_nodes(vobj)

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
        obj.A_StartPoint = start
    if end is not None:
        obj.B_EndPoint = end
    if role in ROLES:
        obj.Role = role

    # MemberID is left empty at creation.  It is assigned automatically
    # when the member is added to a Bent (via Bent.assign_member_ids).

    if FreeCAD.GuiUp:
        TimberMemberViewProvider(obj.ViewObject)
        obj.ViewObject.ShapeColor = (0.76, 0.60, 0.37)  # warm timber tone

    doc.recompute()
    return obj
