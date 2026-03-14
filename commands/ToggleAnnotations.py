"""ToggleAnnotations command — show/hide face numbers, labels, and chalk line."""

import FreeCAD
import FreeCADGui


class ToggleAnnotationsCommand:
    """Toggle ShowAnnotations on selected TimberMember objects.

    If no members are selected, toggles all TimberMember objects in the
    active document.
    """

    def GetResources(self):
        import os
        icon_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "resources", "icons",
        )
        return {
            "Pixmap": os.path.join(icon_dir, "toggle_annotations.svg"),
            "MenuText": "Toggle Annotations",
            "ToolTip": "Show/hide face numbers, endpoint labels, and chalk line",
            "Checkable": True,
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self, checked=None):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return

        # Collect target members
        sel = FreeCADGui.Selection.getSelection()
        members = [
            o for o in sel
            if hasattr(o, "Proxy")
            and type(o.Proxy).__name__ == "TimberMember"
        ]
        if not members:
            # No selection: toggle all members in document
            members = [
                o for o in doc.Objects
                if hasattr(o, "Proxy")
                and type(o.Proxy).__name__ == "TimberMember"
            ]

        if not members:
            return

        # Determine new state: toggle based on first member's current state
        first_vobj = members[0].ViewObject
        current = getattr(first_vobj, "ShowAnnotations", True)
        new_state = not current

        for m in members:
            vobj = m.ViewObject
            if hasattr(vobj, "ShowAnnotations"):
                vobj.ShowAnnotations = new_state


FreeCADGui.addCommand("TF_ToggleAnnotations", ToggleAnnotationsCommand())
