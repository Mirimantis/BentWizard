"""GUI commands for the BentWizard workbench.

Imported only from init_gui (needs FreeCADGui and Qt). Core logic lives
in GUI-free modules (timber.py); commands here are thin wrappers:
dialog -> transaction -> core call -> report.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from .timber import TimberError, new_timber

_MM = App.Units.Quantity("1 mm").Unit


def _parse_length(text, field):
    """A user-entered length in any schema ('8 in', '20 cm', 8')."""
    try:
        q = App.Units.Quantity(text.strip())
    except (ValueError, OSError):
        raise TimberError(f"{field}: cannot parse {text.strip()!r}")
    if q.Unit != _MM:
        raise TimberError(
            f"{field}: {text.strip()!r} needs a length unit (e.g. 8 in, 200 mm)")
    return q


class NewTimberDialog(QtWidgets.QDialog):
    """MemberID + section + length. Values persist across validation
    retries so the user fixes input instead of retyping it."""

    DEFAULTS = ("203.2 mm", "203.2 mm", "2438.4 mm")   # shown in user's schema

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Timber")
        form = QtWidgets.QFormLayout(self)
        self.member_id = QtWidgets.QLineEdit(self)
        self.member_id.setPlaceholderText("P2-1")
        form.addRow("MemberID:", self.member_id)
        self.fields = {}
        for label, default in zip(("Width", "Depth", "Length"), self.DEFAULTS):
            edit = QtWidgets.QLineEdit(App.Units.Quantity(default).UserString, self)
            self.fields[label] = edit
            form.addRow(f"{label}:", edit)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        """(member_id, width, depth, length); raises TimberError."""
        return (self.member_id.text(),
                *(_parse_length(self.fields[f].text(), f)
                  for f in ("Width", "Depth", "Length")))


class NewTimberCommand:
    def GetResources(self):
        return {
            "MenuText": "New Timber",
            "ToolTip": "Create a pristine parametric timber — Body with "
                       "MemberID label, TimberDims VarSet, section sketch "
                       "on the reference planes, pad to the stick length",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        dialog = NewTimberDialog(Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                member_id, width, depth, length = dialog.values()
                doc.openTransaction(f"New timber {member_id.strip()}")
                try:
                    body, _dims = new_timber(doc, member_id, width, depth, length)
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except TimberError as err:
                QtWidgets.QMessageBox.warning(dialog, "New Timber", str(err))
                continue
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(body)
            return


def register():
    Gui.addCommand("BentWizard_NewTimber", NewTimberCommand())


ALL_COMMANDS = ["BentWizard_NewTimber"]
