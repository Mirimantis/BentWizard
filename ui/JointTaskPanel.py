"""Task panel adapter for JointPanel.

Wraps the JointPanel QWidget so it can be shown via
``FreeCADGui.Control.showDialog()``.  This adapter is intentionally
minimal — when the persistent ContextPanel dock widget is built
(Phase 3), JointPanel will be embedded directly without this wrapper.
"""

from PySide2 import QtWidgets


class JointTaskPanel:
    """FreeCAD task panel wrapper for the JointPanel widget."""

    def __init__(self, obj):
        from ui.panels.JointPanel import JointPanel

        self._panel = JointPanel(obj)
        self.form = self._panel  # FreeCAD reads this attribute

    def getStandardButtons(self):
        return int(QtWidgets.QDialogButtonBox.Close)

    def reject(self):
        """Called when the user clicks Close or presses Escape."""
        import FreeCADGui

        self._panel._disconnect()
        FreeCADGui.Control.closeDialog()

    def accept(self):
        """Not used — changes are applied live."""
        self.reject()

    @property
    def panel(self):
        """Access the underlying JointPanel widget."""
        return self._panel
