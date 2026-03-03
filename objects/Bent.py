"""Bent — a named transverse frame profile.

A Bent is a container for TimberMember objects forming one cross-section
of a timber frame building.  It groups posts, beams, rafters, and braces
into a named unit, manages MemberID assignment, and provides a bounding-box
wireframe shape for 3D viewport selection.

This module must work headless — no FreeCADGui / Qt imports at module level.
"""

import FreeCAD
import Part

from objects.TimberMember import ROLE_PREFIX


# ---------------------------------------------------------------------------
# FeaturePython proxy
# ---------------------------------------------------------------------------

class Bent:
    """Proxy object attached to a ``Part::FeaturePython`` document object."""

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    # -- properties ---------------------------------------------------------

    @staticmethod
    def _add_properties(obj):
        """Add all Bent properties.  Safe to call on restore."""

        def _ensure(ptype, name, group, doc, default=None):
            if hasattr(obj, name):
                return
            obj.addProperty(ptype, name, group, doc)
            if default is not None:
                setattr(obj, name, default)

        _ensure("App::PropertyLinkList", "Members", "Bent",
                "Child TimberMember objects in this bent")
        _ensure("App::PropertyString", "BentName", "Bent",
                "User name for this bent (e.g. 'King Post')")
        _ensure("App::PropertyInteger", "BentNumber", "Bent",
                "Sequential position in the frame (0 = unassigned)", 0)
        _ensure("App::PropertyString", "BentTemplate", "Bent",
                "Template ID used to create this bent")
        _ensure("App::PropertyInteger", "MemberCount", "Bent",
                "Number of members in this bent", 0)

        obj.setEditorMode("BentTemplate", 1)   # read-only
        obj.setEditorMode("MemberCount", 1)     # read-only

    # -- recompute ----------------------------------------------------------

    def execute(self, obj):
        """Build a bounding-box wireframe from member shapes.  Never raises."""
        try:
            shape = self._build_bounding_box(obj)
            obj.Shape = shape
            # MemberCount is a read-only display field with no downstream
            # listeners — safe to write here (same rationale as TimberJoint's
            # IntersectionAngle write in execute).
            obj.MemberCount = len(obj.Members) if obj.Members else 0
        except Exception as e:
            FreeCAD.Console.PrintError(f"Bent execute failed: {e}\n")
            obj.Shape = Part.makeBox(200, 200, 200)

    # Padding added to each side of the bounding box (mm).
    _BBOX_PADDING = 200.0

    @staticmethod
    def _build_bounding_box(obj):
        """Compute a Part.makeBox covering the bounding box of all members.

        Adds ``_BBOX_PADDING`` mm of clearance on every side so the
        wireframe remains visually distinct from the member solids.
        """
        pad = Bent._BBOX_PADDING
        members = obj.Members
        if not members:
            return Part.makeBox(200, 200, 200)

        # Collect valid member shapes.
        shapes = []
        for m in members:
            if hasattr(m, "Shape") and m.Shape and not m.Shape.isNull():
                shapes.append(m.Shape)

        if not shapes:
            return Part.makeBox(200, 200, 200)

        compound = Part.makeCompound(shapes)
        bb = compound.BoundBox

        # Padded dimensions (minimum 10 mm for degenerate cases).
        xl = max(bb.XLength, 10.0) + 2 * pad
        yl = max(bb.YLength, 10.0) + 2 * pad
        zl = max(bb.ZLength, 10.0) + 2 * pad

        cx, cy, cz = bb.Center.x, bb.Center.y, bb.Center.z
        origin = FreeCAD.Vector(cx - xl / 2, cy - yl / 2, cz - zl / 2)
        return Part.makeBox(xl, yl, zl, origin)

    # -- property change reactions ------------------------------------------

    def onChanged(self, obj, prop):
        """React to property changes on the Bent object.

        Note: MemberID assignment is NOT done here.  It is done explicitly
        in ``add_member()`` / ``remove_member()`` / ``reassign_all_ids()``
        so that the writes happen inside the caller's undo transaction.
        ``onChanged`` fires as a side effect of property writes, and any
        child-property modifications made here would not be captured by
        FreeCAD's undo system cleanly.
        """
        pass

    # -- MemberID assignment ------------------------------------------------

    @staticmethod
    def assign_member_ids(obj):
        """Reassign MemberIDs to all child members.

        Groups children by Role, then assigns sequential IDs within each
        role using the convention ``{RolePrefix}{BentNumber}-{position}``.

        Only writes to ``MemberID`` if the value would actually change,
        avoiding unnecessary recompute cascades.

        Call this explicitly inside a transaction — do NOT call from
        ``onChanged``, as the writes would fall outside the undo capture.
        """
        bent_num = obj.BentNumber
        if bent_num == 0:
            return  # Unassigned bent — don't renumber.

        members = obj.Members
        if not members:
            return

        # Group children by role, preserving list order.
        by_role = {}
        for child in members:
            if not hasattr(child, "Role") or not hasattr(child, "MemberID"):
                continue
            role = str(child.Role)
            by_role.setdefault(role, []).append(child)

        # Assign IDs.
        for role, role_members in by_role.items():
            prefix = ROLE_PREFIX.get(role, "M")
            for i, member in enumerate(role_members, start=1):
                new_id = f"{prefix}{bent_num}-{i}"
                if member.MemberID != new_id:
                    member.MemberID = new_id

    @staticmethod
    def clear_member_id(member):
        """Clear a member's MemberID if it has one."""
        if hasattr(member, "MemberID") and member.MemberID:
            member.MemberID = ""

    # -- member management convenience methods ------------------------------

    @staticmethod
    def add_member(obj, member):
        """Add a TimberMember to this Bent's Members list.

        If the member already belongs to another Bent, it is removed from
        that Bent first (single-bent enforcement).  If the member is
        already in this Bent, this is a no-op.

        Assigns MemberIDs to all members in this Bent after the addition.
        The caller must wrap this in an open transaction so that all
        property writes (including child MemberID changes) are captured
        by undo.

        Touches the Bent so it recomputes (bounding box update).
        """
        current = list(obj.Members) if obj.Members else []
        if member in current:
            return

        # Single-bent enforcement: remove from any other Bent first.
        doc = obj.Document
        if doc is not None:
            other = find_parent_bent(doc, member)
            if other is not None and other != obj:
                Bent.remove_member(other, member)

        current.append(member)
        obj.Members = current
        Bent.assign_member_ids(obj)
        obj.touch()

    @staticmethod
    def remove_member(obj, member):
        """Remove a TimberMember from this Bent's Members list.

        If the member is not in the list, this is a no-op.
        Clears the member's MemberID and reassigns IDs for remaining
        members.  The caller must wrap this in an open transaction.

        Touches the Bent so it recomputes.
        """
        current = list(obj.Members) if obj.Members else []
        if member not in current:
            return
        current.remove(member)
        obj.Members = current
        Bent.clear_member_id(member)
        Bent.assign_member_ids(obj)
        obj.touch()

    # -- serialization ------------------------------------------------------

    def onDocumentRestored(self, obj):
        """Re-add properties that might be missing after schema changes."""
        self._add_properties(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ---------------------------------------------------------------------------
# Utility: find parent bent for a given member
# ---------------------------------------------------------------------------

def find_parent_bent(doc, member_obj):
    """Return the Bent containing *member_obj*, or ``None``.

    Uses the document-scan pattern — iterates all objects in *doc*
    looking for Bent proxies whose Members list includes *member_obj*.
    """
    for obj in doc.Objects:
        if not hasattr(obj, "Proxy"):
            continue
        if obj.Proxy is None:
            continue
        if type(obj.Proxy).__name__ != "Bent":
            continue
        if hasattr(obj, "Members") and member_obj in (obj.Members or []):
            return obj
    return None


# ---------------------------------------------------------------------------
# ViewProvider (GUI only — conditionally defined)
# ---------------------------------------------------------------------------

if FreeCAD.GuiUp:
    import os
    import FreeCADGui

    _ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             "resources", "icons")

    class BentViewProvider:
        """View provider for Bent objects."""

        def __init__(self, vobj):
            vobj.Proxy = self

        def attach(self, vobj):
            self.Object = vobj.Object
            self._active_panel = None

        def getIcon(self):
            return os.path.join(_ICON_DIR, "bent.svg")

        def updateData(self, obj, prop):
            panel = getattr(self, "_active_panel", None)
            if panel is not None:
                try:
                    panel.notify_property_changed(prop)
                except (RuntimeError, AttributeError):
                    # Panel widget was deleted (dialog closed).
                    self._active_panel = None

        def onChanged(self, vobj, prop):
            pass

        def getDisplayModes(self, vobj):
            return ["Flat Lines", "Shaded", "Wireframe", "Points"]

        def getDefaultDisplayMode(self):
            return "Wireframe"

        def setDisplayMode(self, mode):
            return mode

        def onDelete(self, vobj, subelements):
            return True

        def doubleClicked(self, vobj):
            """Open the BentPanel task panel for editing."""
            from ui.BentTaskPanel import BentTaskPanel

            panel = BentTaskPanel(vobj.Object)
            FreeCADGui.Control.showDialog(panel)
            self._active_panel = panel.panel
            return True

        def claimChildren(self):
            """Tell the model tree which objects nest under this Bent."""
            return self.Object.Members or []

        def canDropObject(self, obj):
            """Accept TimberMember drops from the model tree."""
            if not hasattr(obj, "Proxy"):
                return False
            if obj.Proxy is None:
                return False
            return type(obj.Proxy).__name__ == "TimberMember"

        def dropObject(self, vobj, dropped):
            """Handle a TimberMember dropped onto this Bent in the tree."""
            FreeCAD.ActiveDocument.openTransaction("Add Member to Bent")
            try:
                Bent.add_member(self.Object, dropped)
            except Exception as e:
                FreeCAD.Console.PrintError(
                    f"Bent drop failed: {e}\n"
                )
            finally:
                FreeCAD.ActiveDocument.commitTransaction()
                FreeCAD.ActiveDocument.recompute()

        def dumps(self):
            return None

        def loads(self, state):
            return None


# ---------------------------------------------------------------------------
# Helper: create a new Bent in the active document
# ---------------------------------------------------------------------------

def create_bent(name="Bent", bent_number=0, bent_name=""):
    """Create and return a new Bent document object.

    Parameters
    ----------
    name : str
        Base label for the document object.
    bent_number : int
        Sequential position in the frame.  0 = unassigned.
    bent_name : str
        User name for this bent.

    Returns
    -------
    obj : Part::FeaturePython
        The newly created Bent object.
    """
    doc = FreeCAD.ActiveDocument
    if doc is None:
        raise RuntimeError("No active document")

    obj = doc.addObject("Part::FeaturePython", name)
    Bent(obj)

    if bent_number:
        obj.BentNumber = bent_number
    if bent_name:
        obj.BentName = bent_name

    if FreeCAD.GuiUp:
        BentViewProvider(obj.ViewObject)
        # Set visual style after ViewProvider is fully attached.
        obj.ViewObject.ShapeColor = (0.55, 0.55, 0.70)
        obj.ViewObject.Transparency = 70

    doc.recompute()

    if FreeCAD.GuiUp:
        # Display mode can only be set after the first recompute
        # populates the Shape and the mode enumeration is built.
        try:
            obj.ViewObject.DisplayMode = "Wireframe"
        except ValueError:
            pass

    return obj
