import os

import FreeCADGui


_ROOT = os.path.dirname(__file__)


class TimberFrameWorkbench(FreeCADGui.Workbench):
    """FreeCAD workbench for traditional timber frame design."""

    MenuText = "BentWizard Timber Frame"
    ToolTip = "Design and analyze traditional timber frame structures"
    Icon = os.path.join(_ROOT, "resources", "icons", "workbench.svg")

    def GetClassName(self):
        return "Gui::PythonWorkbench"

    def Initialize(self):
        """Called when the workbench is first activated."""
        from commands import AddMember  # noqa: F401

        self.appendToolbar("Timber Frame", ["TF_AddMember"])
        self.appendMenu("Timber Frame", ["TF_AddMember"])

    def Activated(self):
        """Called when switching to this workbench."""
        pass

    def Deactivated(self):
        """Called when leaving this workbench."""
        pass
