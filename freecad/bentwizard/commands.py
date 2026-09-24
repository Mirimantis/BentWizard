"""GUI commands for the BentWizard workbench.

Imported only from init_gui (needs FreeCADGui and Qt). Core logic lives
in GUI-free modules (timber.py, datums.py, measure.py); commands here
are thin wrappers: dialog -> transaction -> core call -> report.
"""

import functools
import re
import traceback
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import (datums, facetable, joint_handle, measure, naming,
               template_check, template_library)
from .apply import (JointError, apply_joint, bent_joints, joint_datums,
                    joint_members, joint_varsets, next_serial, remove_joint)
from .datums import DatumError
from .template import TemplateSpec
from .timber import TimberError, dims_varset, new_timber, timber_bodies


def _quantity_field(default, unit="mm"):
    """A native Gui::QuantitySpinBox — displays in the user's unit
    schema, same as every stock workbench field. `unit` is the raw-value
    unit.

    Bounds go through `_set_range`, never straight in: the widget reads
    `minimum`/`maximum` in the DISPLAYED unit while `rawValue` stays
    internal, so a range meant as 50.8 mm was taken as 50.8 in and the
    first step clamped a 4" default up to 4' 2¾" (Adam's GUI round,
    2026-09-21). Reproduced identically on 1.1.3 and 26.3 — not a 26.3
    regression, it was always wrong.

    Note a bare typed number means mm on 26.3 and the displayed unit on
    1.1.3; that one is upstream's, with no property-level workaround
    (docs/spike-26-3-gui-results.md, finding 9)."""
    global _STEP_COMMIT
    field = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
    field.setProperty("unit", unit)
    field.setProperty("_bw_unit", unit)     # `unit` reads back as the
                                            # DISPLAY unit, so keep ours
    _set_range(field, -1e9, 1e9, unit)
    field.setProperty("rawValue", default)
    if _STEP_COMMIT is None:
        _STEP_COMMIT = _StepCommit()
    field.installEventFilter(_STEP_COMMIT)
    return field


class _StepCommit(QtCore.QObject):
    """Commit a stepper change that FreeCAD 26.3 leaves uncommitted.

    On 26.3 `Gui::QuantitySpinBox`'s up/down buttons (and Up/Down, and
    the wheel) move the *displayed text* but never write it to the
    widget's value, so the next focus-out redraws from the stale value
    and the edit vanishes — Adam's GUI round, 2026-09-21: "the spinner
    buttons are what reset immediately when I click away". Reproduced in
    all seven ways of configuring the widget; 1.1.3 holds in all seven.

    **This is upstream's bug, not ours** — Adam confirmed Part → Box's
    Length stepper reverts identically on the same build, so every
    FreeCAD dialog using this widget is affected in 26.3.0 `a4ce44d33b`.
    1.1.3 holds in all seven configurations.

    So after a step we push the shown text back into the value, which
    the same probe confirmed sticks. The check is on the VALUE, not the
    version: when upstream fixes the widget the text and the value agree
    and this does nothing, so it retires itself. **Delete this class and
    its install once a fixed weekly lands** — it is a stopgap so the
    dialogs work while 26.3 is the test environment, not a design.
    """

    def eventFilter(self, field, event):
        kind = event.type()
        stepped = (kind in (QtCore.QEvent.Wheel,
                            QtCore.QEvent.MouseButtonPress,
                            QtCore.QEvent.MouseButtonRelease)
                   or (kind == QtCore.QEvent.KeyPress
                       and event.key() in (QtCore.Qt.Key_Up,
                                           QtCore.Qt.Key_Down)))
        if stepped:
            # After Qt has handled the event, and only if it changed the
            # text. A plain click in the field changes nothing, and
            # committing it anyway would re-parse the ROUNDED display —
            # a 30 1/16" value shown at 1/8" resolution would be
            # silently truncated by clicking into it.
            before = field.lineEdit().text()
            QtCore.QTimer.singleShot(
                0, lambda: (field.lineEdit().text() != before
                            and _commit_shown(field)))
        return False            # never consume: the widget still steps


_STEP_COMMIT = None


def _commit_shown(field):
    """Make the widget's value agree with the text it is showing."""
    try:
        shown = field.lineEdit().text().strip()
        if not shown:
            return
        unit = field.property("_bw_unit") or "mm"
        quantity = App.Units.Quantity(shown)
        if not quantity.Unit:           # bare number: the field's own unit
            quantity = App.Units.Quantity(float(shown), unit)
        raw = float(field.property("rawValue"))
        if abs(float(quantity.getValueAs(unit)) - raw) > 1e-9:
            field.setProperty("value", quantity)
    except Exception:
        pass        # a half-typed value is not an error


def _display_factor(unit="mm"):
    """How many raw `unit`s one displayed unit is worth, under the
    user's schema (25.4 for mm under Building US, 1.0 under Standard)."""
    try:
        factor = App.Units.Quantity(1.0, unit).getUserPreferred()[1]
        return float(factor) or 1.0
    except Exception:
        return 1.0


def _set_range(field, low, high, unit="mm"):
    """Deliberately does NOT bound the widget — the range is enforced in
    `ApplyJointDialog.request`, where the unit is unambiguous.

    `Gui::QuantitySpinBox` reads `minimum`/`maximum` in the DISPLAYED
    unit when stepping but as RAW values on focus-out, so no number is
    right for both paths:

    - 50.8 meant as mm made a 4" value step to 4' 2¾" (it was read as
      50.8 in, and the step clamped up to that "minimum")
    - converting to 6.0 in for a 152.4 mm maximum then let focus-out
      clamp a legitimate 4" down to 6 mm — silently destroying it
    - a `Base::Quantity` is accepted but leaves the bound unset

    Both misreads are present on 1.1.3 as well as 26.3. Leaving the
    widget unbounded is the only behaviour that is correct in both
    paths, and the guard loses nothing: it never worked."""
    return


def _mm(value):
    """A length in mm shown in the user's unit schema."""
    return App.Units.Quantity(float(value), "mm").UserString


def _shown(value, unit="mm"):
    """A raw value in `unit`, shown in the user's unit schema (angles
    are in degrees, so `_mm` is not enough)."""
    return App.Units.Quantity(float(value), unit).UserString


# Property types worth offering in expression autocomplete (dimension
# and parameter bindings); strings like PositionTag stay out.
_NUMERIC_PROPERTY_TYPES = (
    "App::PropertyLength", "App::PropertyDistance", "App::PropertyAngle",
    "App::PropertyFloat", "App::PropertyInteger", "App::PropertyQuantity",
    "App::PropertyArea", "App::PropertyVolume", "App::PropertyPercent",
)

# Framework properties every object carries — excluded by name, never by
# property group. FreeCAD's "add property" dialog defaults the group to
# 'Base', so a hand-authored project VarSet's variables land there; a
# group-based filter silently hid every one of them from completion.
_FRAMEWORK_PROPERTIES = frozenset((
    "Label", "Label2", "Visibility", "ExpressionEngine", "Group", "Proxy",
))


def _is_joint_varset(obj):
    return (naming.is_joint_varset_label(obj.Label)
            or any(hasattr(obj, s + a) for s in naming.SIDES
                   for a in naming.ACCESSORS))


def _expression_candidates(doc, include_dims=True, include_joints=True):
    """Sorted '<<VarSet Label>>.Property' completion candidates: every
    numeric user property on every VarSet in the document — the values
    an expression can bind to. `include_dims=False` drops Dims VarSets
    (a timber's own Dims couple to project VarSets, never directly to
    another timber's Dims); `include_joints=False` drops joint VarSets
    (a station comes from a project variable, never from one joint's
    own parameters)."""
    out = []
    for obj in doc.Objects:
        if obj.TypeId != "App::VarSet":
            continue
        if not include_dims and naming.is_dims_label(obj.Label):
            continue
        if not include_joints and _is_joint_varset(obj):
            continue
        for prop in obj.PropertiesList:
            if prop in _FRAMEWORK_PROPERTIES or naming.is_accessor_property(prop):
                continue
            if obj.getTypeIdOfProperty(prop) in _NUMERIC_PROPERTY_TYPES:
                out.append(f"<<{obj.Label}>>.{prop}")
    return sorted(out)


class _ExpressionEdit(QtWidgets.QLineEdit):
    """Expression entry with autocomplete over the document's VarSet
    properties — the native Expression Editor can't be reused here (it
    binds to an already-existing property, and its widgets aren't
    reachable from Python). Completion is token-aware: it tracks the
    reference under the cursor, so '<<Group>>.Height * 2' completes the
    reference without eating the arithmetic."""

    def __init__(self, doc, parent=None, include_dims=True, include_joints=True):
        super().__init__(parent)
        self._doc = doc
        self._include_dims = include_dims
        self._include_joints = include_joints
        self._completer = QtWidgets.QCompleter(self._candidates(), self)
        self._completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self._completer.setFilterMode(QtCore.Qt.MatchContains)
        self._completer.setWidget(self)
        self._completer.activated.connect(self._insert_completion)
        self.textEdited.connect(self._update_popup)

    def _candidates(self):
        return _expression_candidates(self._doc, include_dims=self._include_dims,
                                      include_joints=self._include_joints)

    def refresh(self):
        """Re-scan the document — picks up variables stored while the
        dialog is open."""
        self._completer.model().setStringList(self._candidates())

    def _token_start(self):
        text = self.text()[:self.cursorPosition()]
        open_ref = text.rfind("<<")
        if open_ref > text.rfind(">>"):
            return open_ref
        for i in range(len(text) - 1, -1, -1):
            if text[i] in " +-*/(),%^":
                return i + 1
        return 0

    def _update_popup(self, _text=""):
        prefix = self.text()[self._token_start():self.cursorPosition()]
        if not prefix.strip():
            self._completer.popup().hide()
            return
        self._completer.setCompletionPrefix(prefix)
        self._popup()

    def show_all(self):
        self._completer.setCompletionPrefix("")
        self._popup()

    def _popup(self):
        popup = self._completer.popup()
        rect = self.cursorRect()
        rect.setWidth(popup.sizeHintForColumn(0)
                      + popup.verticalScrollBar().sizeHint().width())
        self._completer.complete(rect)

    def _insert_completion(self, completion):
        start = self._token_start()
        tail = self.text()[self.cursorPosition():]
        self.setText(self.text()[:start] + completion + tail)
        self.setCursorPosition(start + len(completion))


def _group_varsets(doc):
    """VarSets that may receive stored variables: the project layer —
    not a timber's Dims, not a joint's VarSet."""
    return [o for o in doc.Objects
            if o.TypeId == "App::VarSet"
            and not naming.is_dims_label(o.Label)
            and not _is_joint_varset(o)]


class _StoreInVarSetDialog(QtWidgets.QDialog):
    """Mirror of the native Expression Editor's 'Store in Variable
    Set': enter a value, add it as a new property on a project VarSet —
    picked or created right here — and bind to it without leaving the
    dialog. On success `reference` holds '<<Label>>.Property'."""

    TYPES = (("Length", "App::PropertyLength", "mm"),
             ("Angle", "App::PropertyAngle", "deg"),
             ("Float", "App::PropertyFloat", ""),
             ("Integer", "App::PropertyInteger", ""))

    def __init__(self, doc, default_mm, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.reference = None
        self.setWindowTitle("Store in Variable Set")
        form = QtWidgets.QFormLayout(self)
        self.varset = QtWidgets.QComboBox(self)
        self.varset.setEditable(True)
        for vs in _group_varsets(doc):
            self.varset.addItem(vs.Label)
        self.varset.lineEdit().setPlaceholderText("ProjectVars")
        self.varset.setToolTip(
            "The project VarSet to store the variable on — pick one, or "
            "type a new label to create it. Timber Dims and joint VarSets "
            "are not offered: shared values belong on the project layer.")
        form.addRow("Variable Set:", self.varset)
        self.prop_name = QtWidgets.QLineEdit(self)
        self.prop_name.setPlaceholderText("GirtLine")
        self.prop_name.setToolTip(
            "New property name, UpperCamelCase (letters and digits, "
            "starts with a capital letter): GirtLine, PostHeight.")
        form.addRow("Variable:", self.prop_name)
        self.type_box = QtWidgets.QComboBox(self)
        for label, _tid, _unit in self.TYPES:
            self.type_box.addItem(label)
        self.type_box.currentIndexChanged.connect(self._retype)
        form.addRow("Type:", self.type_box)
        self.value = _quantity_field(default_mm)
        form.addRow("Value:", self.value)
        self.tooltip_edit = QtWidgets.QLineEdit(self)
        self.tooltip_edit.setPlaceholderText("brief description")
        form.addRow("Tooltip:", self.tooltip_edit)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _retype(self, index):
        self.value.setProperty("unit", self.TYPES[index][2])

    def _complain(self, message):
        QtWidgets.QMessageBox.warning(self, "Store in Variable Set", message)

    def accept(self):
        label = self.varset.currentText().strip()
        name = self.prop_name.text().strip()
        if not label:
            return self._complain("choose or name a Variable Set")
        bad = naming.reserved_in_label(label)
        if bad:
            return self._complain(
                f"VarSet label contains forbidden character(s) {bad!r}")
        if not naming.is_camel_case(name):
            return self._complain(
                "the variable name must be UpperCamelCase — letters and "
                "digits, starting with a capital letter (GirtLine, "
                "PostHeight)")
        if naming.is_expression_word(name):
            return self._complain(
                f"{name!r} is a unit or constant in FreeCAD expressions, so "
                f"nothing could reference it — use a descriptive name "
                f"(BayWidth, not W)")
        existing = self.doc.getObjectsByLabel(label)
        vs = existing[0] if existing else None
        if vs is not None and vs.TypeId != "App::VarSet":
            return self._complain(f"{label!r} exists but is not a Variable Set")
        if vs is not None and name in vs.PropertiesList:
            return self._complain(f"{label!r} already has a property {name!r}")
        type_label, type_id, _unit = self.TYPES[self.type_box.currentIndex()]
        raw = float(self.value.property("rawValue"))
        self.doc.openTransaction("Store in Variable Set")
        try:
            if vs is None:
                vs = self.doc.addObject("App::VarSet", "VarSet")
                vs.Label = label
            vs.addProperty(type_id, name, "Layout",
                           self.tooltip_edit.text().strip())
            setattr(vs, name, int(round(raw)) if type_label == "Integer" else raw)
        except Exception as err:
            self.doc.abortTransaction()
            return self._complain(f"could not store the variable: {err}")
        self.doc.commitTransaction()
        self.reference = f"<<{vs.Label}>>.{name}"
        super().accept()


class _DimField(QtWidgets.QWidget):
    """One dimension row: a QuantitySpinBox with an 'fx' toggle that
    swaps in an autocompleting expression edit, plus a '+' button to
    store a new variable — literal OR binding ("membership IS the
    binding")."""

    def __init__(self, default, doc, parent=None, include_dims=False,
                 include_joints=True, unit="mm"):
        super().__init__(parent)
        self._doc = doc
        self.unit = unit
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.spin = _quantity_field(default, unit)
        self.expr = _ExpressionEdit(doc, self, include_dims=include_dims,
                                    include_joints=include_joints)
        self.expr.setPlaceholderText("<<ProjectVars>>.GirtLine")
        self.expr.setToolTip(
            "Expression — binds this value to another VarSet's property; "
            "editing that VarSet later moves everything bound to it. "
            "Autocompletes over the document's VarSets.")
        self.expr.hide()
        self.fx = QtWidgets.QToolButton(self)
        self.fx.setText("ƒx")
        self.fx.setCheckable(True)
        self.fx.setToolTip("Toggle literal value / expression.")
        self.fx.toggled.connect(self._swap)
        self.store = QtWidgets.QToolButton(self)
        self.store.setText("+")
        self.store.setToolTip(
            "Store in Variable Set — save the value as a new variable on a "
            "project VarSet (created here if needed) and bind this field "
            "to it.")
        self.store.hide()
        self.store.clicked.connect(self._store)
        lay.addWidget(self.spin)
        lay.addWidget(self.expr)
        lay.addWidget(self.fx)
        lay.addWidget(self.store)

    def _swap(self, on):
        self.spin.setVisible(not on)
        self.expr.setVisible(on)
        self.store.setVisible(on and self.unit == "mm")
        if on and not self.expr.text().strip():
            self.expr.setFocus()
            self.expr.show_all()

    def _store(self):
        dialog = _StoreInVarSetDialog(
            self._doc, float(self.spin.property("rawValue")), self)
        if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.reference:
            self.expr.refresh()
            self.expr.setText(dialog.reference)

    def set_literal(self, mm):
        self.fx.setChecked(False)
        self.spin.setProperty("rawValue", mm)

    def set_expression(self, expression):
        self.fx.setChecked(True)
        self.expr.setText(expression.lstrip("=").strip())

    def value(self):
        """A Quantity, or an '=expression' string."""
        if self.fx.isChecked() and self.expr.text().strip():
            return "=" + self.expr.text().lstrip("= ").strip()
        raw = self.spin.property("rawValue")
        return App.Units.Quantity(f"{raw} {self.unit}")


# --------------------------------------------------------------------------
# New Timber
# --------------------------------------------------------------------------

class NewTimberDialog(QtWidgets.QDialog):
    """Copy-from picker + permanent name + section + design length +
    optional position tag. Dimensions accept literals or expressions."""

    DEFAULTS = (203.2, 203.2, 2438.4)   # mm internally; displayed per schema
    LABELS = {"WidthX": "Width X:", "WidthY": "Width Y:", "LengthZ": "Length Z:"}

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("New Timber")
        form = QtWidgets.QFormLayout(self)
        self.copy_from = QtWidgets.QComboBox(self)
        self.copy_from.addItem("(new timber)", None)
        for body in timber_bodies(doc):
            self.copy_from.addItem(body.Label, body)
        self.copy_from.setToolTip(
            "Prefill from an existing timber: its name base with the "
            "next serial, and its dimensions — expressions included, so "
            "project bindings carry over (bindings that point back at the "
            "source timber itself are copied as plain values instead).")
        form.addRow("Copy from:", self.copy_from)
        self.member_id = QtWidgets.QLineEdit(self)
        self.member_id.setPlaceholderText("T-Post-001")
        self.member_id.setToolTip(
            "Permanent name — describes what the stick IS, never its "
            "position (that goes in the position tag below). Free-form; "
            "T-<Role>[-<Qualifier>]-<serial> style recommended. Ends in a "
            "separator + number: that serial is what copy tools bump. "
            "Leave it off and the next free one is appended. Forbidden: "
            "'>', '\\' and ';'.")
        form.addRow("Name:", self.member_id)
        self.fields = {}
        tips = {
            "WidthX": "Section extent along the timber's own X axis.",
            "WidthY": "Section extent along the timber's own Y axis.",
            "LengthZ": "Design length, bearing face to bearing face. "
                       "Joinery grows past it; the stick to order is "
                       "measured off the finished solid (Audit Timbers).",
        }
        for name, default in zip(naming.DIMS, self.DEFAULTS):
            field = _DimField(default, doc, self)
            field.setToolTip(tips[name])
            self.fields[name] = field
            form.addRow(self.LABELS[name], field)
        self.position_tag = QtWidgets.QLineEdit(self)
        self.position_tag.setPlaceholderText("e.g. Bent 2, north post")
        self.position_tag.setToolTip(
            "Optional, display-only: where the stick lands in the "
            "structure. Stored as PositionTag on the Dims VarSet; nothing "
            "binds to it.")
        form.addRow("Position tag:", self.position_tag)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.copy_from.currentIndexChanged.connect(self._prefill)
        selected = {o.Name for o in Gui.Selection.getSelection()}
        for i in range(1, self.copy_from.count()):
            if self.copy_from.itemData(i).Name in selected:
                self.copy_from.setCurrentIndex(i)   # fires _prefill
                break

    def _prefill(self):
        body = self.copy_from.currentData()
        if body is None:
            return
        dims = dims_varset(body)
        if dims is None:
            return
        labels = [o.Label for o in self.doc.Objects]
        self.member_id.setText(naming.successor_label(labels, body.Label))
        exprs = {path.lstrip("."): expr for path, expr in dims.ExpressionEngine}
        for name in naming.DIMS:
            expr = exprs.get(name)
            if expr and self._portable(expr, body, dims):
                self.fields[name].set_expression(expr)
            else:
                self.fields[name].set_literal(getattr(dims, name).Value)

    @staticmethod
    def _portable(expr, body, dims):
        """Finding #2: a copied expression must never keep pointing at
        the source timber."""
        named = naming.referenced_labels(expr)
        return not any(token and (token in expr or token in named)
                       for token in (body.Name, body.Label, dims.Name, dims.Label))

    def values(self):
        out = [self.member_id.text()]
        for name in naming.DIMS:
            out.append(self.fields[name].value())
        out.append(self.position_tag.text())
        return tuple(out)


class NewTimberCommand:
    def GetResources(self):
        return {
            "MenuText": "New Timber",
            "ToolTip": "Create a timber — a Body with its Dims VarSet "
                       "(WidthX, WidthY, LengthZ), a section centred on "
                       "its axis, the design-length stick, and a datum at "
                       "each end. Dimensions take literals or expressions; "
                       "select an existing timber first to copy from it",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        dialog = NewTimberDialog(doc, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                member_id, wx, wy, lz, tag = dialog.values()
                member_id = member_id.strip()
                if member_id and naming.split_serial(member_id)[1] is None:
                    member_id = naming.successor_label(
                        [o.Label for o in doc.Objects], member_id)
                doc.openTransaction(f"New timber {member_id}")
                try:
                    body, _dims = new_timber(doc, member_id, wx, wy, lz,
                                             position_tag=tag)
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except (TimberError, DatumError) as err:
                QtWidgets.QMessageBox.warning(dialog, "New Timber", str(err))
                continue
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(body)
            return


# --------------------------------------------------------------------------
# Add Datum
# --------------------------------------------------------------------------

def _selected_timbers(doc):
    """The timbers in the current selection, in selection order, each
    once (a selected datum or feature counts for its timber)."""
    out = []
    for obj in Gui.Selection.getSelection():
        body = obj if obj.TypeId == "PartDesign::Body" \
            else obj.getParentGeoFeatureGroup()
        if body is not None and body.TypeId == "PartDesign::Body" \
                and dims_varset(body) is not None and body not in out:
            out.append(body)
    return out


def _selected_timber(doc):
    timbers = _selected_timbers(doc)
    return timbers[0] if timbers else None


class AddDatumDialog(QtWidgets.QDialog):
    """Timber + face + station: the three things a datum is placed from.
    Position, rotation and accessors come from the face table."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Add Datum")
        form = QtWidgets.QFormLayout(self)
        self.timber = QtWidgets.QComboBox(self)
        for body in timber_bodies(doc):
            self.timber.addItem(body.Label, body)
        self.timber.setToolTip("The timber the datum belongs to.")
        form.addRow("Timber:", self.timber)
        self.face = QtWidgets.QComboBox(self)
        for face in facetable.FACES:
            self.face.addItem(facetable.display(face), face)
        self.face.setToolTip(
            "Which face of the timber the datum sits on, in the timber's "
            "own axes (Show Face && End Marks labels them in the 3D view). "
            "The datum's Z points out of that face.")
        form.addRow("Face:", self.face)
        self.station = _DimField(1219.2, doc, self, include_dims=False,
                                 include_joints=False)
        self.station.setToolTip(
            "Where along the timber (from end A) the datum sits. Bind it "
            "to a project variable to move a whole line of joints at once.")
        form.addRow("Station:", self.station)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        preselected = _selected_timber(doc)
        if preselected is not None:
            for i in range(self.timber.count()):
                if self.timber.itemData(i) is preselected:
                    self.timber.setCurrentIndex(i)
                    break

    def values(self):
        return (self.timber.currentData(), self.face.currentData(),
                self.station.value())


class AddDatumCommand:
    def GetResources(self):
        return {
            "MenuText": "Add Datum",
            "ToolTip": "Place a datum on a timber's face at a station — the "
                       "coordinate system a timber joint is applied to. "
                       "Position, rotation and accessors are written from "
                       "the face table; the station may be an expression "
                       "on a project variable",
        }

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and bool(timber_bodies(doc))

    def Activated(self):
        doc = App.ActiveDocument
        dialog = AddDatumDialog(doc, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            body, face, station = dialog.values()
            if body is None:
                return
            doc.openTransaction(f"Add datum on {body.Label}")
            try:
                datum = datums.add_datum(body, face, station)
            except (DatumError, TimberError) as err:
                doc.abortTransaction()
                QtWidgets.QMessageBox.warning(dialog, "Add Datum", str(err))
                continue
            except Exception:
                doc.abortTransaction()
                raise
            doc.commitTransaction()
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(datum)
            App.Console.PrintMessage(
                f"Datum {datum.Label} placed: {datums.describe(datum)}\n")
            return


# --------------------------------------------------------------------------
# Face and end marks
# --------------------------------------------------------------------------

class ShowFaceMarksCommand:
    def GetResources(self):
        return {
            "MenuText": "Show Face && End Marks",
            "ToolTip": "Label every timber's faces (+X, -X, +Y, -Y) and ends "
                       "(A/B) in the 3D view, so Add Datum's and Apply "
                       "Timber Joint's choices are readable off the model. "
                       "View-only — nothing is added to the document. Run "
                       "again to clear.",
            "Checkable": True,
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self, index=None):
        from . import view_face_marks
        doc = App.ActiveDocument
        if doc is None:
            return
        view_face_marks.install()
        if view_face_marks.toggle(doc):
            App.Console.PrintMessage(
                f"Face and end marks shown on {len(timber_bodies(doc))} timber(s).\n")
        else:
            App.Console.PrintMessage("Face and end marks cleared.\n")


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------

# Modeless report windows, kept alive here: a QDialog with no Python
# reference is garbage-collected out from under the user.
_OPEN_REPORTS = {}


class _ReportDialog(QtWidgets.QDialog):
    """A report in a window a user can read, copy out of, and leave open
    while they fix what it names. Modeless on purpose."""

    def __init__(self, title, headline, report, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.setWindowFlags(QtCore.Qt.Window)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.resize(760, 460)
        layout = QtWidgets.QVBoxLayout(self)
        lead = QtWidgets.QLabel(headline, self)
        lead.setWordWrap(True)
        lead.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(lead)
        self.text = QtWidgets.QPlainTextEdit(report, self)
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        layout.addWidget(self.text)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close,
                                             parent=self)
        copy = buttons.addButton("Copy", QtWidgets.QDialogButtonBox.ActionRole)
        copy.setToolTip("Copy the whole report to the clipboard.")
        copy.clicked.connect(
            lambda: QtWidgets.QApplication.clipboard().setText(
                self.text.toPlainText()))
        buttons.rejected.connect(self.close)
        buttons.accepted.connect(self.close)
        layout.addWidget(buttons)


def _show_report(key, title, headline, report, parent=None):
    """Open a modeless report window, replacing the previous one for the
    same key."""
    previous = _OPEN_REPORTS.pop(str(key), None)
    if previous is not None:
        try:
            previous.close()
        except RuntimeError:
            pass
    dialog = _ReportDialog(title, headline, report, parent)
    _OPEN_REPORTS[str(key)] = dialog
    dialog.finished.connect(lambda _r, k=str(key): _OPEN_REPORTS.pop(k, None))
    dialog.show()
    dialog.raise_()
    return dialog


# --------------------------------------------------------------------------
# Audit Timbers
# --------------------------------------------------------------------------

def audit_report(doc):
    """Per timber: design and order length, end projections, solid
    count, and every datum with its pairing and verification."""
    lines = []
    problems = 0
    for body in timber_bodies(doc):
        r = measure.report(body)
        status = "one solid" if r["whole"] else f"{r['solids']} SOLIDS"
        if not r["whole"]:
            problems += 1
        lines.append(f"{body.Label}: design {_mm(r['design_mm'])}, order "
                     f"{_mm(r['order_mm'])} (past A {_mm(r['past_A_mm'])}, "
                     f"past B {_mm(r['past_B_mm'])}) — {status}")
        for d in datums.datums_of(body):
            mate = datums.mate_of(d)
            vs = datums.joint_of(d)
            pairing = (f"paired with {mate.Label} under {vs.Label}"
                       if mate is not None and vs is not None else
                       "unpaired" if not datums.is_paired(d) else
                       "PAIRING BROKEN")
            bad = datums.verify_datum(d)
            if bad or pairing == "PAIRING BROKEN":
                problems += 1
            lines.append(f"    {d.Label}: {datums.describe(d)} — {pairing}"
                         + (f" — {'; '.join(bad)}" if bad else ""))
    return problems, "\n".join(lines) or "No timbers in this document."


class AuditTimbersCommand:
    def GetResources(self):
        return {
            "MenuText": "Audit Timbers",
            "ToolTip": "Report every timber's design and order length, how "
                       "far its joinery reaches past each end, whether it "
                       "is still one solid, and each datum's placement and "
                       "pairing",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        problems, report = audit_report(doc)
        headline = ("Everything checks out." if not problems else
                    f"{problems} problem(s) found — see below.")
        _show_report(("audit", doc.Name), "Audit Timbers", headline, report,
                     Gui.getMainWindow())


# --------------------------------------------------------------------------
# Timber joints: pick, whole-joint operations
# --------------------------------------------------------------------------

def _role_display(role_label):
    """'T-Post-000' -> 'Post': what the framer reads for a template role."""
    base, _serial = naming.split_serial(role_label)
    for prefix in ("T-", "T.", "T_"):
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    return base or role_label


def _role_caption(spec, role):
    """(row label, tooltip) for a template role in the apply dialog.

    The template's timbers are called Post and Girt, but a joint lands
    between many kinds of timber, so the dialog names the *roles*:
    Primary (the host — its datum is the landing datum) and Secondary
    (the mate — seated onto it). What each one does is read from where
    the template put its datum: on a side face, the timber passes through
    the intersection; on an end, it butts and terminates there."""
    passing = not _role_is_butting(spec, role)
    if role == spec.host_role:
        name, what = "Primary", "host"
    else:
        name, what = "Secondary", "mate"
    kind = "passing" if passing else "butting"
    if passing:
        does = ("the passing timber that runs continuously through the "
                "intersection, with the landing datum at a station on a side face")
    else:
        does = ("the butting timber that terminates at the joint, with the "
                "joinery attached to its end datum")
    tip = (f"{name} timber ({what}): {does}. Called "
           f"'{_role_display(role)}' in this template.")
    return f"{name} — {kind}:", tip


def _joint_of_selection(doc):
    """The joint VarSet the current selection points at: its handle, the
    VarSet itself, a paired datum, or any joint member."""
    for obj in Gui.Selection.getSelection():
        if joint_handle.is_handle(obj):
            vs = joint_handle.handle_varset(obj)
            if vs is not None:
                return vs
        if obj.TypeId == "App::VarSet" and naming.is_joint_varset_label(obj.Label):
            return obj
        if datums.is_datum(obj):
            vs = datums.joint_of(obj)
            if vs is not None:
                return vs
    selected = {o.Name for o in Gui.Selection.getSelection()}
    for vs in joint_varsets(doc):
        if any(m.Name in selected for m in joint_members(vs)):
            return vs
    return None


def _pick_joint(doc, title):
    """Prompt for a timber joint, preselected from the current selection.
    Returns the VarSet, or None if cancelled / none present."""
    joints = joint_varsets(doc)
    if not joints:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), title, "No timber joints in this document.")
        return None
    labels = [j.Label for j in joints]
    current = _joint_of_selection(doc)
    index = joints.index(current) if current in joints else 0
    label, ok = QtWidgets.QInputDialog.getItem(
        Gui.getMainWindow(), title, "Timber joint:", labels, index, False)
    if not ok:
        return None
    return joints[labels.index(label)]


def show_joint_parameters(varset):
    """Select the joint's VarSet: its parameters fill the Data property
    editor, editable in place."""
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(varset)


def select_joint_members(varset):
    """Select everything the joint is made of — both timbers' components,
    Booleans, datums and the VarSet."""
    Gui.Selection.clearSelection()
    for obj in joint_members(varset) + joint_datums(varset):
        Gui.Selection.addSelection(obj)
    Gui.Selection.addSelection(varset)


def remove_joint_interactive(varset):
    """Remove one timber joint, after showing what goes with it."""
    doc = varset.Document
    label = varset.Label
    members = joint_members(varset)
    bodies = sorted({datums.owner(d).Label for d in joint_datums(varset)
                     if datums.owner(d) is not None})
    answer = QtWidgets.QMessageBox.question(
        Gui.getMainWindow(), "Remove Timber Joint",
        f"Remove {label} — {len(members)} object(s) across "
        f"{', '.join(bodies) or 'no timbers'} — plus its VarSet and "
        f"assembly joint? The datums stay on their timbers.",
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    if answer != QtWidgets.QMessageBox.Yes:
        return
    doc.openTransaction(f"Remove joint {label}")
    try:
        remove_joint(varset)
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()


class RemoveJointCommand:
    def GetResources(self):
        return {
            "MenuText": "Remove Timber Joint",
            "ToolTip": "Remove a timber joint: its components, Booleans, "
                       "handle, assembly joint and VarSet. The timbers "
                       "return to their bare sticks and keep their datums",
        }

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and bool(joint_varsets(doc))

    def Activated(self):
        varset = _pick_joint(App.ActiveDocument, "Remove Timber Joint")
        if varset is not None:
            remove_joint_interactive(varset)


# --------------------------------------------------------------------------
# Apply Timber Joint
# --------------------------------------------------------------------------

def _datum_station(datum):
    """A datum's station as the field would hold it: ('expr', text) when
    Station is bound — a project variable, or LengthZ at end B — so the
    framer sees WHY it sits there; else ('literal', mm)."""
    for path, expr in datum.ExpressionEngine:
        if path.lstrip(".") == naming.PROP_STATION:
            return ("expr", expr)
    return ("literal", float(getattr(datum, naming.PROP_STATION).Value))


def _role_is_butting(spec, role):
    """Whether a template role butts (its datum is on an end) or passes
    (on a side face). The ONE place this is decided: the row caption,
    the rows the dialog shows, and the faces it offers all follow it, so
    they cannot disagree. It is read from the template's own datum —
    whose Face is declared, never guessed — so a template needs no extra
    flag: a half lap (both datums on side faces) gets two passing halves,
    a scarf (both on ends) two butting ones."""
    return facetable.is_end(spec.datum_face[spec.role_datum[role]])


class _DatumChoice(QtCore.QObject):
    """Where one role lands, as rows in the Apply dialog's Timbers form.

    A **passing** half — its template datum on a side face — takes three
    rows: the timber, *Face / Datum* (a free side-face datum, or a new
    datum on one of the four faces), and *…at station* — where a new one
    goes, or a free one's current station, editable to move it.

    A **butting** half — its template datum on an end — takes two: the
    timber and *End*, offering only that timber's free end datums. A
    component modelled on an end grows along the timber's axis, so it
    cannot land on a side face at all; the old picker offered side faces
    to a butting half anyway, and a station row it could never use.

    An object, not a widget: it owns the controls and adds them to the
    form as labelled rows (`add_rows`), so each gets its own label rather
    than sharing the role's."""

    def __init__(self, doc, parent, butting=False):
        super().__init__(parent)
        self.doc = doc
        self.butting = butting
        self.timber = QtWidgets.QComboBox(parent)
        for body in timber_bodies(doc):
            self.timber.addItem(body.Label, body)
        self.timber.setToolTip("The timber this half of the joint is cut into.")
        self.datum = QtWidgets.QComboBox(parent)
        if butting:
            self.datum.setToolTip(
                "The end of the timber this half of the joint is cut into. "
                "Only ends not already joined are offered. Show Face && "
                "End Marks labels the ends in the 3D view.")
            self.station = None     # an end's station is fixed: 0, or LengthZ
        else:
            self.datum.setToolTip(
                "A free datum already on one of the timber's side faces, or "
                "a new datum on a face at the station below. Show Face && "
                "End Marks labels the faces in the 3D view.")
            self.station = _DimField(1219.2, doc, parent, include_dims=False,
                                     include_joints=False)
            self.station.setToolTip(
                "Where along the timber (from end A) the datum sits. For a "
                "new datum, where to place it; for a free one already on "
                "the timber, its current station — change it to move that "
                "datum. May be an expression on a project variable.")
        # What the user has entered for a NEW datum, kept aside while the
        # field shows an existing datum's station instead — so picking a
        # free datum and then going back to "New datum" gives back their
        # value, never the datum's. Captured before the first refill.
        self._own_station = (self._capture_station()
                             if self.station is not None else None)
        self._showing_datum = False
        self._datum_shown = None     # the reused datum's station, as shown
        self.timber.currentIndexChanged.connect(self._refill)
        self.datum.currentIndexChanged.connect(self._toggle_station)
        # activated fires on a user pick only, never on a programmatic
        # setCurrentIndex — so a refill can tell a choice from a default
        self.datum.activated.connect(self._mark_user_choice)
        self._user_chose = False
        self._default_face = None
        self._refill()

    def set_default_face(self, face):
        self._default_face = face
        self._refill()

    def add_rows(self, form, caption, tip):
        """Lay this half out in `form`: the role caption labels the
        timber row, and each control below gets a label of its own."""
        parent = self.parent()
        label = QtWidgets.QLabel(caption, parent)
        label.setToolTip(tip)
        form.addRow(label, self.timber)
        if self.butting:
            form.addRow(QtWidgets.QLabel("End:", parent), self.datum)
        else:
            form.addRow(QtWidgets.QLabel("Face / Datum:", parent), self.datum)
            form.addRow(QtWidgets.QLabel("…at station:", parent), self.station)

    def _refill(self):
        body = self.timber.currentData()
        # A face the user already chose survives a change of timber — the
        # refill used to snap back to the template's face, silently
        # turning a chosen -X into +Y (Adam's GUI round, 2026-09-18). An
        # existing datum is per-timber, so only its face carries over.
        current = self.datum.currentData()
        if current is not None and getattr(self, "_user_chose", False):
            kind, value = current
            self._default_face = value if kind == "face" else datums.face_of(value)
        self.datum.blockSignals(True)
        self.datum.clear()
        if body is not None and self.butting:
            # an end datum is made with the timber, so there is never a
            # "new" one — just the ends not already joined
            for end in facetable.ENDS:
                d = datums.end_datum(body, end)
                if d is not None and not datums.is_paired(d):
                    self.datum.addItem(facetable.display(end), ("datum", d))
            if self.datum.count() == 0:
                self.datum.addItem("No free end — both are already joined", None)
        elif body is not None:
            for d in datums.datums_of(body):
                if (not datums.is_paired(d)
                        and not facetable.is_end(datums.face_of(d))):
                    self.datum.addItem(f"{d.Label} ({datums.describe(d)})",
                                       ("datum", d))
            for face in facetable.FACES:
                self.datum.addItem(f"New datum on {facetable.display(face)}",
                                   ("face", face))
        # default: the same face/end the template was authored on
        want = self._default_face
        for i in range(self.datum.count()):
            data = self.datum.itemData(i)
            if data is None:
                continue                # the "no free end" placeholder
            kind, value = data
            if want is not None and (
                    (kind == "face" and value == want)
                    or (kind == "datum" and datums.face_of(value) == want)):
                self.datum.setCurrentIndex(i)
                break
        self.datum.blockSignals(False)
        self._toggle_station()

    def _mark_user_choice(self, _index):
        self._user_chose = True

    def _toggle_station(self):
        """For a new datum, the station to place it at; for an existing
        one, THAT datum's station — editable, and Apply moves the datum
        if it is changed (`target`).

        It first only greyed the field, leaving the dialog's 4' default in
        it, so a freed datum at 2' 6" sat beside a field reading 4'; then
        it showed the datum's station but greyed, so a reused datum bound
        to a variable could not be re-bound or made a plain value (Adam's
        GUI rounds, 2026-09-22). Moving a reused datum is safe: only free
        datums are offered, and nothing reads a free one."""
        if self.station is None:
            return                  # a butting half has no station row
        data = self.datum.currentData()
        new = bool(data) and data[0] == "face"
        if new:
            if self._showing_datum:
                self._show_station(self._own_station)
                self._showing_datum = False
            self._datum_shown = None
        elif data:
            if not self._showing_datum:
                self._own_station = self._capture_station()
                self._showing_datum = True
            d = data[1]
            self._datum_shown = _datum_station(d)
            # the plain value under a binding too, so turning ƒx off to
            # make it a simple value starts from where the datum IS
            self.station.spin.setProperty(
                "rawValue", float(getattr(d, naming.PROP_STATION).Value))
            self._show_station(self._datum_shown)
        self.station.setEnabled(bool(data))

    def _station_changed(self):
        """Whether the framer changed a reused datum's station. Compared
        as DISPLAYED: the field shows a rounded value, and a datum more
        precise than the display must not move by the rounding just
        because the field was clicked or re-read."""
        was = getattr(self, "_datum_shown", None)
        if was is None:
            return False
        now = self._capture_station()
        if now[0] != was[0]:
            return True
        if now[0] == "expr":
            return now[1].lstrip("=").strip() != was[1].lstrip("=").strip()
        shown = lambda mm: App.Units.Quantity(float(mm), "mm").UserString
        return shown(now[1]) != shown(was[1])

    def _capture_station(self):
        """The field's own content: ('expr', text) or ('literal', mm).
        An ƒx toggle over an empty expression counts as the literal it
        falls back to in `_DimField.value` — restoring it as an empty
        expression would pop the autocomplete list."""
        f = self.station
        if f.fx.isChecked() and f.expr.text().strip():
            return ("expr", f.expr.text())
        return ("literal", float(f.spin.property("rawValue")))

    def _show_station(self, state):
        kind, value = state
        f = self.station
        if kind == "expr":
            # text BEFORE the toggle: `_DimField._swap` pops the
            # completer when ƒx turns on over an empty field
            f.expr.setText(value.lstrip("=").strip())
            f.fx.setChecked(True)
        else:
            f.fx.setChecked(False)
            f.spin.setProperty("rawValue", value)

    def target(self):
        body = self.timber.currentData()
        data = self.datum.currentData()
        if body is not None and data is None and self.butting:
            raise JointError(f"{body.Label}: both ends are already joined, so "
                             f"there is no free end for this timber joint")
        if body is None or data is None:
            raise JointError("pick a timber and a datum for every role")
        kind, value = data
        if kind == "datum":
            out = {"body": body, "datum": value}
            # only a CHANGED station moves the reused datum
            if self.station is not None and self._station_changed():
                out["station"] = self.station.value()
            return out
        return {"body": body, "face": value, "station": self.station.value()}


class ApplyJointDialog(QtWidgets.QDialog):
    """Template + per-role timber/datum + serial + the parameter form,
    generated from the template's VarSet — no per-joint code."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.spec = None
        self.setWindowTitle("Apply Timber Joint")
        layout = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QFormLayout()
        self.template_box = QtWidgets.QComboBox(self)
        for stem, path in template_library.templates():
            self.template_box.addItem(stem, str(path))
        self.template_box.setToolTip(
            "The joint template to apply. Your own template folder is "
            "searched ahead of the shipped library.")
        top.addRow("Template:", self.template_box)
        self.serial = QtWidgets.QLineEdit(self)
        self.serial.setToolTip("Serial of the new joint: J-<Kind>-<serial>.")
        top.addRow("Joint serial:", self.serial)
        layout.addLayout(top)
        self.problem = QtWidgets.QLabel("", self)
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        self.roles_box = QtWidgets.QGroupBox("Timbers", self)
        self.roles_form = QtWidgets.QFormLayout(self.roles_box)
        layout.addWidget(self.roles_box)
        self.params_box = QtWidgets.QGroupBox("Parameters", self)
        self.params_form = QtWidgets.QFormLayout(self.params_box)
        layout.addWidget(self.params_box)
        self.assemble = QtWidgets.QCheckBox("Seat the entering timber", self)
        self.assemble.setChecked(True)
        self.assemble.setToolTip(
            "Place the entering timber at its seat through this joint, by "
            "expression. Clear it to cut the joinery and leave the timber "
            "where it stands — Seat Timbers can place it later.")
        layout.addWidget(self.assemble)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.role_widgets = {}
        self.param_widgets = {}
        self.param_ranges = {}
        self.template_box.currentIndexChanged.connect(self._load)
        self._load()

    def _clear(self, form):
        while form.rowCount():
            form.removeRow(0)

    def _load(self):
        path = self.template_box.currentData()
        self._clear(self.roles_form)        # deletes the pickers' controls
        self._clear(self.params_form)
        for w in self.role_widgets.values():
            w.deleteLater()                 # and the pickers themselves
        self.role_widgets.clear()
        self.param_widgets.clear()
        self.param_ranges.clear()
        self.spec = None
        self.problem.setText("")
        if not path:
            self.problem.setText("No joint templates found.")
            return
        try:
            self.spec = TemplateSpec(path)
        except JointError as err:
            self.problem.setText(f"Cannot load this template: {err}")
            return
        self.serial.setText(next_serial(self.doc, self.spec.kind))
        # the selection fills the roles in order: first picked = Primary
        # (host), second = Secondary (mate)
        selected = _selected_timbers(self.doc)
        preset = dict(zip([self.spec.host_role, self.spec.mate_role], selected))
        for role in self.spec.roles:
            w = _DatumChoice(self.doc, self,
                             butting=_role_is_butting(self.spec, role))
            w.set_default_face(self.spec.datum_face[self.spec.role_datum[role]])
            if role in preset:
                for i in range(w.timber.count()):
                    if w.timber.itemData(i) is preset[role]:
                        w.timber.setCurrentIndex(i)
                        break
            self.role_widgets[role] = w
            caption, tip = _role_caption(self.spec, role)
            w.add_rows(self.roles_form, caption, tip)
        for p in self.spec.parameters:
            self.param_widgets[p["name"]] = self._param_widget(p)
            self.params_form.addRow(f"{p['name']}:", self.param_widgets[p["name"]])
        sweep = self.spec.varset.prop(naming.PROP_SWEEP_FINDINGS)
        if sweep is not None and sweep.value:
            note = QtWidgets.QLabel(
                f"Registration sweep found values where this joint fails: "
                f"{sweep.value}", self)
            note.setWordWrap(True)
            self.params_form.addRow(note)

    def _param_widget(self, p):
        t = p["type"]
        if t == "App::PropertyInteger":
            w = QtWidgets.QSpinBox(self)
            w.setRange(-1000000, 1000000)
            w.setValue(int(p["default"] or 0))
        elif t == "App::PropertyBool":
            w = QtWidgets.QCheckBox(self)
            w.setChecked(bool(p["default"]))
        elif t in ("App::PropertyLength", "App::PropertyDistance",
                   "App::PropertyAngle", "App::PropertyQuantity", "App::PropertyFloat"):
            unit = "deg" if t == "App::PropertyAngle" else "mm"
            w = _DimField(float(p["default"] or 0.0), self.doc, self,
                          include_dims=False, include_joints=False, unit=unit)
            if p["expression"]:
                w.set_expression(p["expression"])
            _set_range(w.spin, p["min"], p["max"], unit)
            if p["min"] is not None or p["max"] is not None:
                self.param_ranges[p["name"]] = (p["min"], p["max"], unit)
        else:
            w = QtWidgets.QLineEdit(str(p["default"] or ""), self)
        tip = p["doc"]
        if p["min"] is not None or p["max"] is not None:
            lo = _mm(p["min"]) if p["min"] is not None else "…"
            hi = _mm(p["max"]) if p["max"] is not None else "…"
            tip += f"  Range: {lo} to {hi}."
        if p.get("read_only"):
            # Shown so the framer sees it (a peg count feeds the schedule),
            # never editable, and never sent to Apply — see `request`.
            w.setEnabled(False)
            tip += "  Fixed by this template."
        w.setToolTip(tip)
        return w

    def request(self):
        if self.spec is None:
            raise JointError("choose a template")
        targets = {role: w.target() for role, w in self.role_widgets.items()}
        fixed = {p["name"] for p in self.spec.parameters if p.get("read_only")}
        values = {}
        for name, w in self.param_widgets.items():
            if name in fixed:
                # the template's value arrives with the copy; a value sent
                # here would be written straight through the ReadOnly flag
                continue
            if isinstance(w, QtWidgets.QSpinBox):
                values[name] = w.value()
            elif isinstance(w, QtWidgets.QCheckBox):
                values[name] = w.isChecked()
            elif isinstance(w, _DimField):
                values[name] = w.value()
            else:
                values[name] = w.text()
        self._check_ranges(values)
        return (self.spec, self.serial.text().strip(), targets, values,
                self.assemble.isChecked())

    def _check_ranges(self, values):
        """The template's declared ranges, enforced here rather than on
        the spin box — see `_set_range` for why the widget cannot hold
        them. An expression is passed through: its value is not known
        until it is bound."""
        out = []
        for name, (low, high, unit) in sorted(self.param_ranges.items()):
            value = values.get(name)
            if isinstance(value, str):
                continue                    # an expression, not a literal
            try:
                raw = float(App.Units.Quantity(value).getValueAs(unit))
            except Exception:
                continue
            if low is not None and raw < float(low) - 1e-9:
                out.append(f"{name} is {_shown(raw, unit)}, below the "
                           f"template's minimum of {_shown(low, unit)}")
            if high is not None and raw > float(high) + 1e-9:
                out.append(f"{name} is {_shown(raw, unit)}, above the "
                           f"template's maximum of {_shown(high, unit)}")
        if out:
            raise JointError("; ".join(out))


class ApplyJointCommand:
    def GetResources(self):
        return {
            "MenuText": "Apply Timber Joint",
            "ToolTip": "Apply a joint template between two timbers: each "
                       "half lands on a datum (existing, or a new one on a "
                       "face at a station), the template's components are "
                       "copied in and cut/fused, and the entering timber "
                       "is seated against the other by expression",
        }

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and len(timber_bodies(doc)) >= 2

    def Activated(self):
        from .frame import is_misfit, place_on_apply
        doc = App.ActiveDocument
        dialog = ApplyJointDialog(doc, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                spec, serial, targets, values, seat_it = dialog.request()
                doc.openTransaction(f"Apply {spec.kind} joint")
                try:
                    applied = apply_joint(doc, spec, serial, targets, values=values)
                    seating = place_on_apply(doc, applied.varset) if seat_it else None
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except (JointError, DatumError, TimberError) as err:
                QtWidgets.QMessageBox.warning(dialog, "Apply Timber Joint", str(err))
                continue
            vs = applied.varset
            msg = f"Applied {vs.Label}."
            if applied.warnings:
                msg += " " + " ".join(applied.warnings)
            if seating is not None and seating.mover is not None:
                msg += f" Seated {seating.mover.Label}."
                if seating.merged:
                    msg += " Its timbers came with it."
            elif seating is not None and seating.closing:
                msg += " It closes a loop — it places nothing, and is checked."
            if seat_it and is_misfit(vs):
                msg += (" WARNING — the joint did not seat cleanly; another "
                        "joint may disagree about where this timber sits.")
            App.Console.PrintMessage(msg + "\n")
            handle = joint_handle.find_handle(vs)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(handle if handle is not None else vs)
            return


# --------------------------------------------------------------------------
# Seat Timbers — the bulk and repair path
# --------------------------------------------------------------------------

class SeatTimbersDialog(QtWidgets.QDialog):
    """Frame (new or existing) + Principal timber, with the timber joints
    that will place a timber listed."""

    def __init__(self, doc, bodies, parent=None):
        super().__init__(parent)
        from .frame import is_frame_group, joint_timbers, pick_principal
        self.doc = doc
        self.bodies = bodies
        self.setWindowTitle("Seat Timbers")
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.assembly_box = QtWidgets.QComboBox(self)
        self.assembly_box.addItem("New frame:", None)
        for obj in doc.Objects:
            if is_frame_group(obj):
                self.assembly_box.addItem(obj.Label, obj.Name)
        form.addRow("Frame:", self.assembly_box)
        self.new_name = QtWidgets.QLineEdit(self)
        self.new_name.setText(naming.next_serial([o.Label for o in doc.Objects],
                                                 "Frame", sep="-"))
        form.addRow("New frame name:", self.new_name)
        self.assembly_box.currentIndexChanged.connect(
            lambda *_: self.new_name.setEnabled(self.assembly_box.currentData() is None))
        inside, _outside = bent_joints(doc, bodies)
        seatable = [j for j in inside if joint_timbers(j) is not None]
        self.grounded_box = QtWidgets.QComboBox(self)
        default = pick_principal(bodies, seatable)
        for body in bodies:
            self.grounded_box.addItem(body.Label, body.Name)
        self.grounded_box.setCurrentIndex(bodies.index(default))
        self.grounded_box.setToolTip(
            "The Principal timber — the one the frame is anchored at; every "
            "other timber is seated from it through the timber joints.")
        form.addRow("Principal timber:", self.grounded_box)
        layout.addLayout(form)
        note = QtWidgets.QLabel(
            "Timber joints to seat: "
            + (", ".join(j.Label for j in seatable) or "none — the timbers "
               "will only be collected into the frame"), self)
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def request(self):
        name = self.assembly_box.currentData()
        frame = self.doc.getObject(name) if name else None
        principal = self.doc.getObject(self.grounded_box.currentData())
        return frame, self.new_name.text(), principal


class SeatTimbersCommand:
    def GetResources(self):
        return {
            "MenuText": "Seat Timbers",
            "ToolTip": "Seat the selected timbers (bulk/repair): collect "
                       "them into the frame and place each one through the "
                       "timber joint that connects it, anchored at the "
                       "Principal timber. Apply Timber Joint already does "
                       "this per joint as you work; this rebuilds the seats "
                       "that are missing and reports loops that do not close.",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        from .frame import rebuild_seats
        doc = App.ActiveDocument
        bodies = [o for o in Gui.Selection.getSelection() if o in timber_bodies(doc)]
        if not bodies:
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Seat Timbers",
                "Select the timbers to seat first.")
            return
        dialog = SeatTimbersDialog(doc, bodies, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                frame, label, principal = dialog.request()
                doc.openTransaction("Seat timbers")
                try:
                    built = rebuild_seats(
                        doc, bodies, label=frame.Label if frame else label,
                        principal=principal)
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except JointError as err:
                QtWidgets.QMessageBox.warning(dialog, "Seat Timbers", str(err))
                continue
            msg = (f"Seated {len(bodies)} timber(s) in {built.frame.Label} "
                   f"({len(built.seated)} timber joint(s) place a timber).")
            if built.adopted:
                msg += f" Gave {built.adopted} timber joint(s) a handle."
            if built.closures:
                msg += (f" Closing a loop (checked, placing nothing): "
                        f"{', '.join(built.closures)}.")
            if built.skipped:
                msg += (f" Not seated — unpaired, or no joint reaches them: "
                        f"{', '.join(built.skipped)}.")
            if built.misfits:
                msg += (f" WARNING — these timber joints disagree about where "
                        f"their timber sits: {', '.join(built.misfits)}.")
            QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Seat Timbers", msg)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(built.frame)
            return


# --------------------------------------------------------------------------
# Joint templates: authoring a new one, and saving one into the library
# --------------------------------------------------------------------------

def _folder_row(parent, form, label, initial):
    field = QtWidgets.QLineEdit(str(initial), parent)
    browse = QtWidgets.QPushButton("Browse…", parent)
    row = QtWidgets.QWidget(parent)
    box = QtWidgets.QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    box.addWidget(field)
    box.addWidget(browse)

    def pick():
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            parent, "Template folder", field.text())
        if chosen:
            field.setText(chosen)

    browse.clicked.connect(pick)
    form.addRow(label, row)
    return field


def _template_kind_default(doc):
    for obj in doc.Objects:
        if obj.TypeId == "App::VarSet":
            parsed = naming.parse_joint_label(obj.Label)
            if parsed:
                return parsed[0]
    return ""


def _full_check(path, persist):
    findings = template_check.check(path)
    try:
        findings += template_check.check_geometry(path, persist=persist)
    except Exception as err:          # a geometry failure is itself a finding
        findings.append(template_check.Finding(
            "template-geometry", template_check.STRICT, "", Path(path).stem,
            f"geometry check failed: {err}"))
    return findings


class SaveJointTemplateDialog(QtWidgets.QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Save as Joint Template")
        form = QtWidgets.QFormLayout(self)
        self.kind = QtWidgets.QLineEdit(_template_kind_default(doc), self)
        self.kind.setPlaceholderText("BraceMT")
        self.kind.setToolTip(
            "The joint's kind — the file is Joint_<Kind>.FCStd and applied "
            "joints are labelled J-<Kind>-<serial>.")
        form.addRow("Joint kind:", self.kind)
        self.folder = _folder_row(self, form, "Folder:", template_library.user_dir())
        self.rename = QtWidgets.QCheckBox(
            "Relabel the joint VarSet and components to match", self)
        self.rename.setChecked(True)
        form.addRow(self.rename)
        check = QtWidgets.QPushButton("Check", self)
        check.setToolTip("Run the template bar on a temporary copy without saving.")
        check.clicked.connect(self._check)
        form.addRow(check)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _check(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            try:
                path = template_library.template_path(td, self.kind.text())
                self.doc.recompute()
                self.doc.saveCopy(str(path))
                findings = _full_check(path, persist=False)
            except (template_library.TemplateError, JointError) as err:
                QtWidgets.QMessageBox.warning(self, "Check", str(err))
                return
            _show_report(("check", self.doc.Name), "Template check",
                         "Findings for the document as it stands (nothing saved):",
                         template_check.format_report(path, findings), self)

    def request(self):
        return self.kind.text().strip(), Path(self.folder.text()), self.rename.isChecked()


class SaveJointTemplateCommand:
    def GetResources(self):
        return {
            "MenuText": "Save as Joint Template",
            "ToolTip": "Write the open document into your template folder "
                       "as a joint template and report what validation "
                       "found (it reports, never blocks)",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        dialog = SaveJointTemplateDialog(doc, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            kind, folder, rename = dialog.request()
            doc.openTransaction("Save as joint template")
            try:
                path = template_library.save_as_template(doc, folder, kind, rename=rename)
            except (template_library.TemplateError, JointError) as err:
                doc.abortTransaction()
                QtWidgets.QMessageBox.warning(dialog, "Save as Joint Template", str(err))
                continue
            except Exception:
                doc.abortTransaction()
                raise
            doc.commitTransaction()
            template_library.set_user_dir(folder)
            findings = _full_check(path, persist=True)
            _show_report(path, "Save as Joint Template",
                         f"Saved {path}.", template_check.format_report(path, findings),
                         Gui.getMainWindow())
            return


class NewJointTemplateDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Joint Template")
        form = QtWidgets.QFormLayout(self)
        self.starter = QtWidgets.QComboBox(self)
        for stem, path in template_library.starters():
            self.starter.addItem(stem, str(path))
        self.starter.setToolTip(
            "A jointless skeleton to author from: two timbers with a "
            "paired datum each and an empty joint VarSet.")
        form.addRow("Starter:", self.starter)
        self.kind = QtWidgets.QLineEdit(self)
        self.kind.setPlaceholderText("BraceMT")
        form.addRow("Joint kind:", self.kind)
        self.folder = _folder_row(self, form, "Folder:", template_library.user_dir())
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def request(self):
        return self.starter.currentData(), self.kind.text().strip(), Path(self.folder.text())


AUTHORING_GUIDE = """\
How to author the joint in this file:

  - The two timbers carry a paired datum each: the host's face datum and
    the mate's end datum, paired under the joint VarSet (J-<Kind>-000).
  - Add the joint's parameters to the VarSet (group 'Joint',
    UpperCamelCase, a tooltip on every one). Optional range bounds go in
    group 'Ranges' as <Name>Min / <Name>Max.
  - A value this joint always has and a framer must not change (a peg
    count the joint is built for) is still a parameter, but mark it
    read-only — in the Python console,
    <<VarSet>>.setPropertyStatus('PegCount', 'ReadOnly').
    Apply Timber Joint then shows it greyed and never changes it.
  - A CUTTER is a Body at the document root, modelled in -Z from its own
    origin, with ComponentRole = Cutter and a ComponentOrder; an ADDER is
    the same modelled in +Z with ComponentRole = Adder. Bind the body's
    Placement to the joint VarSet's accessor for the datum it sits on
    ('<<J-<Kind>-000>>.HostPlacement' on the host's datum,
    '.MatePlacement' on the mate's) — never to the datum itself: a Body
    reading a datum makes FreeCAD file the datum's axes under that Body,
    and the datum then fails its scope check on recompute.
  - A component reads ONLY its own datum's accessors (WidthU, WidthV,
    DepthW) and the joint VarSet, whose Host*/Mate* accessors give the
    other timber's section. Never a timber's Dims, never another datum.
  - Apply each component to its datum's timber with a PartDesign Boolean
    (Cut for a cutter, Fuse for an adder), cutters before adders.
  - Save as Joint Template reports the template bar: lint, skeleton,
    one-solid check and the parameter sweep."""


class NewJointTemplateCommand:
    def GetResources(self):
        return {
            "MenuText": "New Joint Template",
            "ToolTip": "Start a new joint template from a jointless starter "
                       "skeleton and open it for authoring",
        }

    def IsActive(self):
        return True

    def Activated(self):
        dialog = NewJointTemplateDialog(Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            starter, kind, folder = dialog.request()
            try:
                path, _doc = template_library.new_from_starter(starter, folder, kind)
            except (template_library.TemplateError, JointError) as err:
                QtWidgets.QMessageBox.warning(dialog, "New Joint Template", str(err))
                continue
            template_library.set_user_dir(folder)
            _show_report(path, "New Joint Template", f"Created {path}, open for authoring.",
                         AUTHORING_GUIDE, Gui.getMainWindow())
            return


# --------------------------------------------------------------------------
# Duplicate Timbers
# --------------------------------------------------------------------------

class DuplicateBentDialog(QtWidgets.QDialog):
    """New label per timber, new serial per inside joint, and where the
    copies go: a new offset bent sub-assembly, or a Std Group."""

    def __init__(self, doc, bodies, parent=None):
        super().__init__(parent)
        from .duplicate import suggest_joint_serials, suggest_member_labels
        self.doc = doc
        self.bodies = bodies
        self.setWindowTitle("Duplicate Timbers")
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.labels = {}
        for body, label in suggest_member_labels(doc, bodies).items():
            field = QtWidgets.QLineEdit(label, self)
            self.labels[body] = field
            form.addRow(f"{body.Label} →", field)
        self.inside, outside = bent_joints(doc, bodies)
        self.serials = {}
        for joint, serial in suggest_joint_serials(doc, self.inside).items():
            field = QtWidgets.QLineEdit(serial, self)
            self.serials[joint] = field
            form.addRow(f"{joint.Label} → serial", field)
        if outside:
            note = QtWidgets.QLabel("Not copied (reach outside the set): "
                                    + ", ".join(j.Label for j in outside), self)
            note.setWordWrap(True)
            form.addRow(note)
        self.position_tag = QtWidgets.QLineEdit(self)
        self.position_tag.setPlaceholderText("e.g. Bent 2")
        form.addRow("Position tag:", self.position_tag)
        self.offset = {}
        for axis in "XYZ":
            self.offset[axis] = _quantity_field(0.0)
            form.addRow(f"Offset {axis}:", self.offset[axis])
        self.group = QtWidgets.QLineEdit(
            naming.next_serial([o.Label for o in doc.Objects], "Bent", sep="-"), self)
        self.group.setToolTip(
            "Bent Std Group for the copies, inside the frame (leave empty to "
            "file them in the frame itself). Tree organisation only.")
        form.addRow("New bent group:", self.group)
        layout.addLayout(form)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def request(self):
        member_map = {b: f.text().strip() for b, f in self.labels.items()}
        serial_map = {j.Label: f.text().strip() for j, f in self.serials.items()}
        offset = App.Vector(*(float(self.offset[a].property("rawValue")) for a in "XYZ"))
        return (member_map, serial_map, self.position_tag.text(),
                self.group.text(), offset)


class DuplicateBentCommand:
    def GetResources(self):
        return {
            "MenuText": "Duplicate Timbers",
            "ToolTip": "Copy the selected timbers with their datums and the "
                       "timber joints among them (rebuilt, never blindly "
                       "cloned), into a new offset bent group",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        from .duplicate import duplicate_bent
        doc = App.ActiveDocument
        bodies = [o for o in Gui.Selection.getSelection() if o in timber_bodies(doc)]
        if not bodies:
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Duplicate Timbers",
                "Select the timbers to duplicate first.")
            return
        dialog = DuplicateBentDialog(doc, bodies, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                (member_map, serial_map, tag, group, offset) = dialog.request()
                doc.openTransaction("Duplicate timbers")
                try:
                    new_bodies, new_joints, skipped = duplicate_bent(
                        doc, member_map, serial_map, template_library.search_dirs(),
                        position_tag=tag, group_label=group, offset=offset)
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except (JointError, DatumError, TimberError) as err:
                QtWidgets.QMessageBox.warning(dialog, "Duplicate Timbers", str(err))
                continue
            msg = (f"Duplicated {len(new_bodies)} timber(s) and "
                   f"{len(new_joints)} timber joint(s).")
            if skipped:
                msg += f" Skipped (reach outside the set): {', '.join(skipped)}."
            App.Console.PrintMessage(msg + "\n")
            Gui.Selection.clearSelection()
            for body in new_bodies.values():
                Gui.Selection.addSelection(body)
            return


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# Unexpected errors
# --------------------------------------------------------------------------
# A command reports the errors it expects (JointError, DatumError, ...) in
# its own dialog and carries on. Anything else used to escape to FreeCAD,
# which prints "Running the Python command '...' failed:" with the
# traceback only in the Report view. A second Duplicate Timbers in a
# document hit a "cyclic reference" that way, and the framer saw a bare
# "failed:" (Adam's GUI round, 2026-09-23). Every command and context
# action is wrapped once, here, so none can be missed.

def report_unexpected(title, err):
    """Tell the framer an operation stopped, in a dialog, and keep the
    traceback for whoever fixes it: under "Show Details..." and in the
    Report view. Closes any transaction the operation left open. The
    commands abort their own before re-raising, so this is a safety net,
    and it means "any change it had not finished was undone" holds."""
    if App.getActiveTransaction():
        App.closeActiveTransaction(True)
    detail = "".join(traceback.format_exception(err))
    App.Console.PrintError(f"BentWizard: {title} stopped on an unexpected "
                           f"error:\n{detail}")
    message = str(err).strip() or "(no message)"
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Critical, title,
                                f"{title} stopped on an error BentWizard "
                                f"did not expect.", parent=Gui.getMainWindow())
    box.setInformativeText(
        f"{type(err).__name__}: {message}\n\n"
        f"Any change it had not finished was undone. The details are also "
        f"in the Report view; include them if you report this.")
    box.setDetailedText(detail)
    box.exec()


def _guarded(fn, title):
    """`fn` with unexpected errors reported by `report_unexpected`."""
    @functools.wraps(fn)
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as err:
            report_unexpected(title, err)
    return run


def _guard_command(command):
    """Wrap a command's Activated; the dialog is titled with its menu
    text, the name the framer clicked."""
    menu = command.GetResources().get("MenuText", "BentWizard")
    # Qt menu text: '&&' is a literal '&', a lone '&' marks the mnemonic
    title = menu.replace("&&", "\0").replace("&", "").replace("\0", "&")
    command.Activated = _guarded(command.Activated, title)
    return command


def register():
    # the handle marker's context menu: whole-joint operations, in one
    # place a future joint-wide tool can extend without touching the
    # ViewProvider
    joint_handle.CONTEXT_ACTIONS[:] = [
        (text, _guarded(action, text)) for text, action in (
            ("Joint parameters", show_joint_parameters),
            ("Select joint members", select_joint_members),
            ("Remove timber joint", remove_joint_interactive),
        )]
    for name, command in (
            ("BentWizard_NewTimber", NewTimberCommand()),
            ("BentWizard_AddDatum", AddDatumCommand()),
            ("BentWizard_ApplyJoint", ApplyJointCommand()),
            ("BentWizard_RemoveJoint", RemoveJointCommand()),
            ("BentWizard_DuplicateBent", DuplicateBentCommand()),
            ("BentWizard_AssembleTimbers", SeatTimbersCommand()),
            ("BentWizard_ShowFaceMarks", ShowFaceMarksCommand()),
            ("BentWizard_AuditTimbers", AuditTimbersCommand()),
            ("BentWizard_NewJointTemplate", NewJointTemplateCommand()),
            ("BentWizard_SaveJointTemplate", SaveJointTemplateCommand())):
        Gui.addCommand(name, _guard_command(command))


ALL_COMMANDS = ["BentWizard_NewTimber", "BentWizard_AddDatum",
                "BentWizard_ApplyJoint", "BentWizard_RemoveJoint",
                "BentWizard_DuplicateBent", "BentWizard_AssembleTimbers",
                "BentWizard_ShowFaceMarks",
                "BentWizard_AuditTimbers", "BentWizard_NewJointTemplate",
                "BentWizard_SaveJointTemplate"]
