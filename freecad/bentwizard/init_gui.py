"""Workbench registration for BentWizard.

Phase 1 commands (New Timber, Apply Joint, Preview Mated Joint, linter)
register here as they are implemented. All actions are named in domain
terms, on one dedicated toolbar/menu (friction finding #5).
"""

import FreeCADGui as Gui


class BentWizardWorkbench(Gui.Workbench):
    MenuText = "BentWizard"
    ToolTip = "Timber framing — Mill Rule joinery on native geometry"

    def Initialize(self):
        from freecad.bentwizard import commands
        commands.register()
        self.appendToolbar("BentWizard", commands.ALL_COMMANDS)
        self.appendMenu("BentWizard", commands.ALL_COMMANDS)

    def Activated(self):
        # timber-joint markers: adopt handles in documents already open
        # (a headless-built file carries no view providers) and watch for
        # ones opened later
        from freecad.bentwizard import view_joint_handle
        view_joint_handle.install()
        # undo of a deletion restores expression text but not the
        # dependency it stands for (finding #15) — re-arm the bindings
        from freecad.bentwizard import undo_repair
        undo_repair.install()

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(BentWizardWorkbench())
