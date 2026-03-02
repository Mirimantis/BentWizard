"""AddBent command — toolbar action for creating a new Bent container."""

import FreeCAD
import FreeCADGui

from objects.Bent import Bent, create_bent


class AddBentCommand:
    """FreeCAD command that creates a new Bent container.

    If TimberMember objects are selected, they are moved into the new Bent.
    Otherwise, an empty Bent is created.
    """

    def GetResources(self):
        import os
        icon_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "resources", "icons",
        )
        return {
            "Pixmap": os.path.join(icon_dir, "add_bent.svg"),
            "MenuText": "Add Bent",
            "ToolTip": "Create a new bent (transverse frame profile)",
        }

    def IsActive(self):
        """Active when a document exists."""
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        doc = FreeCAD.ActiveDocument

        # Collect selected TimberMember objects (if any).
        sel = FreeCADGui.Selection.getSelection()
        members = []
        for s in sel:
            if (hasattr(s, "Proxy") and s.Proxy is not None
                    and type(s.Proxy).__name__ == "TimberMember"):
                members.append(s)

        doc.openTransaction("Add Bent")
        try:
            bent = create_bent()
            # Move selected members into the bent.
            for m in members:
                Bent.add_member(bent, m)
            # Recompute so the bounding box updates after members are added.
            doc.recompute()
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(bent)
        except Exception as e:
            FreeCAD.Console.PrintError(f"AddBent failed: {e}\n")
        finally:
            doc.commitTransaction()


FreeCADGui.addCommand("TF_AddBent", AddBentCommand())
