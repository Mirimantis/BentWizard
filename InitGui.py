# BentWizard workbench — GUI initialization
# This file is loaded by FreeCAD only when the GUI is available.

import FreeCADGui

from TimberFrameWorkbench import TimberFrameWorkbench  # noqa: F401

FreeCADGui.addWorkbench(TimberFrameWorkbench)
