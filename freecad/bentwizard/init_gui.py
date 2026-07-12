"""Workbench registration for BentWizard.

Phase 1 commands (New Timber, Apply Joint, Preview Mated Joint, linter)
register here as they are implemented. All actions are named in domain
terms, on one dedicated toolbar/menu (friction finding #5).
"""

import FreeCADGui as Gui


class BentWizardWorkbench(Gui.Workbench):
    MenuText = "BentWizard"
    ToolTip = "Timber framing — square-rule joinery on native geometry"

    def Initialize(self):
        self.commands = []
        if self.commands:
            self.appendToolbar("BentWizard", self.commands)
            self.appendMenu("BentWizard", self.commands)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(BentWizardWorkbench())
