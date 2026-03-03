"""Task panel adapter for BentPanel.

Wraps the BentPanel QWidget so it can be shown via
``FreeCADGui.Control.showDialog()``.  This adapter is intentionally
minimal — when the persistent ContextPanel dock widget is built,
BentPanel will be embedded directly without this wrapper.
"""

from PySide2 import QtWidgets


class BentTaskPanel:
    """FreeCAD task panel wrapper for the BentPanel widget."""

    def __init__(self, obj):
        from ui.panels.BentPanel import BentPanel

        self._panel = BentPanel(obj)
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
        """Access the underlying BentPanel widget."""
        return self._panel
