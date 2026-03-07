import os

import FreeCAD
import FreeCADGui


_ROOT = os.path.dirname(__file__)


# ---------------------------------------------------------------------------
# Selection observer — promotes sub-element clicks to whole-object selection
# for TimberMember and TimberJoint objects.
# ---------------------------------------------------------------------------

class _WholeObjectSelectionObserver:
    """Replaces Face/Edge/Vertex selections with whole-object selection.

    When the user clicks a face or edge of a TimberMember or TimberJoint
    in the 3D view, FreeCAD normally selects just that sub-element.
    This observer intercepts those selections and promotes them to
    full-object selections so the contextual panel and property editor
    show the complete object.
    """

    _PROXY_CLASSES = ("TimberMember", "TimberJoint")

    def __init__(self):
        self._adjusting = False

    def addSelection(self, doc_name, obj_name, sub, pos):
        """Called when a selection is made in the 3D view."""
        if self._adjusting or not sub:
            return  # no sub-element, or we're in the middle of adjusting

        try:
            doc = FreeCAD.getDocument(doc_name)
            if doc is None:
                return
            obj = doc.getObject(obj_name)
            if obj is None:
                return

            # Check if this is one of our timber objects.
            proxy = getattr(obj, "Proxy", None)
            if proxy is None:
                return
            class_name = type(proxy).__name__
            if class_name not in self._PROXY_CLASSES:
                return

            # Promote: remove sub-element selection, add whole-object.
            self._adjusting = True
            FreeCADGui.Selection.removeSelection(doc_name, obj_name, sub)
            FreeCADGui.Selection.addSelection(doc_name, obj_name)
        except Exception:
            pass
        finally:
            self._adjusting = False

    # Required stubs for the observer interface.
    def removeSelection(self, doc_name, obj_name, sub):
        pass

    def setSelection(self, doc_name):
        pass

    def clearSelection(self, doc_name):
        pass


class TimberFrameWorkbench(FreeCADGui.Workbench):
    """FreeCAD workbench for traditional timber frame design."""

    MenuText = "BentWizard Timber Framing"
    ToolTip = "Design and analyze traditional timber frame structures"
    Icon = os.path.join(_ROOT, "resources", "icons", "workbench.svg")

    def GetClassName(self):
        return "Gui::PythonWorkbench"

    def Initialize(self):
        """Called when the workbench is first activated."""
        from commands import AddMember  # noqa: F401
        from commands import AddJoint   # noqa: F401
        from commands import AddBent    # noqa: F401
        from joints import loader
        loader.load_all()

        self.appendToolbar("Timber Frame", [
            "TF_AddMember", "TF_AddJoint", "TF_AddBent",
        ])
        self.appendMenu("Timber Frame", [
            "TF_AddMember", "TF_AddJoint", "TF_AddBent",
        ])

        self._selection_observer = None

    def Activated(self):
        """Called when switching to this workbench."""
        if self._selection_observer is None:
            self._selection_observer = _WholeObjectSelectionObserver()
        FreeCADGui.Selection.addObserver(self._selection_observer)

    def Deactivated(self):
        """Called when leaving this workbench."""
        if self._selection_observer is not None:
            FreeCADGui.Selection.removeObserver(self._selection_observer)

