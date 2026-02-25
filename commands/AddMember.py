"""AddMember command — toolbar action for placing a new TimberMember."""

import FreeCAD
import FreeCADGui

from objects.TimberMember import create_timber_member, ROLES


class AddMemberCommand:
    """FreeCAD command that creates a TimberMember at the origin.

    Phase 1 creates the member with default datum points.  Interactive
    viewport placement (click-to-place with snapping) is planned for
    a later phase.
    """

    def GetResources(self):
        import os
        icon_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "resources", "icons",
        )
        return {
            "Pixmap": os.path.join(icon_dir, "add_member.svg"),
            "MenuText": "Add Timber Member",
            "ToolTip": "Create a new timber member in the active document",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        FreeCAD.ActiveDocument.openTransaction("Add Timber Member")
        try:
            obj = create_timber_member()
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(obj)
        except Exception as e:
            FreeCAD.Console.PrintError(f"AddMember failed: {e}\n")
        finally:
            FreeCAD.ActiveDocument.commitTransaction()


FreeCADGui.addCommand("TF_AddMember", AddMemberCommand())
