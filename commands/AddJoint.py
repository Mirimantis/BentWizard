"""AddJoint command — toolbar action for creating a joint between two members."""

import FreeCAD
import FreeCADGui

from objects.TimberJoint import create_timber_joint
from joints.intersection import _test_pair, INTERSECTION_TOLERANCE


class AddJointCommand:
    """FreeCAD command that creates a joint between two selected TimberMember objects.

    The user selects exactly two members, then activates this command.
    The command detects the intersection between their datum lines and
    creates a TimberJoint with the default joint type for the detected
    intersection type.
    """

    def GetResources(self):
        import os
        icon_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "resources", "icons",
        )
        return {
            "Pixmap": os.path.join(icon_dir, "add_joint.svg"),
            "MenuText": "Add Joint",
            "ToolTip": "Create a joint between two selected timber members",
        }

    def IsActive(self):
        """Active when exactly two TimberMember objects are selected."""
        if FreeCAD.ActiveDocument is None:
            return False
        sel = FreeCADGui.Selection.getSelection()
        if len(sel) != 2:
            return False
        for s in sel:
            if not hasattr(s, "Proxy"):
                return False
            if s.Proxy is None:
                return False
            if type(s.Proxy).__name__ != "TimberMember":
                return False
        return True

    def Activated(self):
        sel = FreeCADGui.Selection.getSelection()
        obj_a = sel[0]
        obj_b = sel[1]

        # Detect intersection between the two members.
        result = _test_pair(obj_a, obj_b, INTERSECTION_TOLERANCE)

        if result is None:
            FreeCAD.Console.PrintWarning(
                "AddJoint: selected members do not intersect within "
                f"tolerance ({INTERSECTION_TOLERANCE}mm).\n"
            )
            return

        FreeCAD.ActiveDocument.openTransaction("Add Joint")
        try:
            joint = create_timber_joint(
                result.primary_obj,
                result.secondary_obj,
                result,
            )
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(joint)
        except Exception as e:
            FreeCAD.Console.PrintError(f"AddJoint failed: {e}\n")
        finally:
            FreeCAD.ActiveDocument.commitTransaction()


FreeCADGui.addCommand("TF_AddJoint", AddJointCommand())
