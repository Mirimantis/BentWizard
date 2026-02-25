# BentWizard workbench — no-GUI initialization
# This file is loaded by FreeCAD on startup regardless of GUI mode.
# It must NOT import FreeCADGui, PySide2, or any Qt modules.

import FreeCAD


FreeCAD.Console.PrintMessage("BentWizard workbench initialized\n")
