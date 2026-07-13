"""GUI commands for the BentWizard workbench.

Imported only from init_gui (needs FreeCADGui and Qt). Core logic lives
in GUI-free modules (timber.py); commands here are thin wrappers:
dialog -> transaction -> core call -> report.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from .timber import TimberError, new_timber

def _quantity_field(default_mm):
    """A native Gui::QuantitySpinBox — parses and displays in the user's
    unit schema, so unitless input means whatever their schema says
    (inches under Building US, cm under Building Euro), same as every
    stock workbench field."""
    field = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
    field.setProperty("unit", "mm")
    field.setProperty("minimum", 0.0)
    field.setProperty("maximum", 1e9)
    field.setProperty("rawValue", default_mm)
    return field


class NewTimberDialog(QtWidgets.QDialog):
    """Label + section + length. Values persist across validation
    retries so the user fixes input instead of retyping it."""

    DEFAULTS = (203.2, 203.2, 2438.4)   # mm internally; displayed per schema

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Timber")
        form = QtWidgets.QFormLayout(self)
        self.member_id = QtWidgets.QLineEdit(self)
        self.member_id.setPlaceholderText("P2-1")
        self.member_id.setToolTip(
            "MemberID ([RolePrefix][Bent]-[Position], e.g. P2-1) "
            "recommended — the linter flags other names as advisory. "
            "Any unique label is accepted for custom roles.")
        form.addRow("Label / MemberID:", self.member_id)
        self.fields = {}
        for label, default in zip(("Width", "Depth", "Length"), self.DEFAULTS):
            field = _quantity_field(default)
            self.fields[label] = field
            form.addRow(f"{label}:", field)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        """(member_id, width, depth, length); raises TimberError."""
        out = [self.member_id.text()]
        for name in ("Width", "Depth", "Length"):
            raw = self.fields[name].property("rawValue")
            out.append(App.Units.Quantity(f"{raw} mm"))
        return tuple(out)


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
