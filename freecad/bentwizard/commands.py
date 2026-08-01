"""GUI commands for the BentWizard workbench.

Imported only from init_gui (needs FreeCADGui and Qt). Core logic lives
in GUI-free modules (timber.py); commands here are thin wrappers:
dialog -> transaction -> core call -> report.
"""

import re
from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import joint_handle, naming
from .apply_joint import (JointError, TemplateSpec, apply_joint,
                          create_preview, dims_varset, engagement_placement,
                          find_preview, joint_members, remove_joint,
                          remove_preview)
from .duplicate import (bent_joints, duplicate_bent, suggest_joint_ids,
                        suggest_member_labels)
from .timber import TimberError, new_timber

LIBRARY_DIR = Path(__file__).resolve().parents[2] / "library"

def _quantity_field(default, unit="mm"):
    """A native Gui::QuantitySpinBox — parses and displays in the user's
    unit schema, so unitless input means whatever their schema says
    (inches under Building US, cm under Building Euro), same as every
    stock workbench field. `unit` is the raw-value unit: mm for length
    parameters, deg for angle parameters."""
    field = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
    field.setProperty("unit", unit)
    field.setProperty("minimum", 0.0)
    field.setProperty("maximum", 1e9)
    field.setProperty("rawValue", default)
    return field


# Property types worth offering in expression autocomplete (dimension
# and parameter bindings); strings like Position_Tag stay out.
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


def _expression_candidates(doc, include_dims=True, include_joints=True):
    """Sorted '<<VarSet Label>>.Property' completion candidates: every
    numeric user property on every VarSet in the document — the values
    an expression can bind to under the project conventions.
    `include_dims=False` drops Dims VarSets: a timber's own Dims
    should couple to group VarSets, never directly to another timber's
    Dims (§4.3 — cross-timber coupling goes through the joint VarSet),
    while joint parameters legitimately bind to timber Dims (junction
    bindings).

    Every other VarSet in the document is offered, project/group
    VarSets included — a user may keep several to drive different parts
    of the structure, and binding to them is the whole point of the
    layered-parameter-groups design."""
    out = []
    for obj in doc.Objects:
        if obj.TypeId != "App::VarSet":
            continue
        if not include_dims and naming.is_dims_label(obj.Label):
            continue
        if not include_joints and (
                naming.is_joint_varset_label(obj.Label)
                or getattr(obj, naming.VARSET_ROLE_PROP, None)
                == naming.VARSET_ROLE_LAYOUT):
            # a span comes from a project/group VarSet, never from one
            # joint's own parameters — offering Tenon_Length as a bay
            # dimension is noise a framer has to read past
            continue
        for prop in obj.PropertiesList:
            if prop in _FRAMEWORK_PROPERTIES:
                continue
            if obj.getTypeIdOfProperty(prop) in _NUMERIC_PROPERTY_TYPES:
                out.append(f"<<{obj.Label}>>.{prop}")
    return sorted(out)


class _ExpressionEdit(QtWidgets.QLineEdit):
    """Expression entry with autocomplete over the document's VarSet
    properties — the native Expression Editor can't be reused here (it
    binds to an already-existing property, and its widgets aren't
    reachable from Python), so this recreates its completion for our
    pre-creation dialogs. Completion is token-aware: it tracks the
    reference under the cursor, so '<<Group>>.Height * 2' completes the
    reference without eating the arithmetic."""

    def __init__(self, doc, parent=None, include_dims=True):
        super().__init__(parent)
        self._doc = doc
        self._include_dims = include_dims
        self._completer = QtWidgets.QCompleter(
            _expression_candidates(doc, include_dims=include_dims), self)
        self._completer.setCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self._completer.setFilterMode(QtCore.Qt.MatchContains)
        self._completer.setWidget(self)
        self._completer.activated.connect(self._insert_completion)
        self.textEdited.connect(self._update_popup)

    def refresh(self):
        """Re-scan the document — picks up variables stored while the
        dialog is open."""
        self._completer.model().setStringList(
            _expression_candidates(self._doc,
                                   include_dims=self._include_dims))

    def _token_start(self):
        """Where the reference under the cursor begins: an unclosed
        '<<', else just after the last operator/space."""
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
        """Open the full candidate list (used when the fx toggle turns
        the field on, so the available values are discoverable)."""
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
    """VarSets that may receive stored variables: the group layer —
    not a timber's Dims, not a joint instance's VarSet."""
    return [o for o in doc.Objects
            if o.TypeId == "App::VarSet"
            and not naming.is_dims_label(o.Label)
            and not naming.is_joint_varset_label(o.Label)]


_PROPERTY_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class _StoreInVarSetDialog(QtWidgets.QDialog):
    """Mirror of the native Expression Editor's 'Store in Variable
    Set': enter a value, add it as a new property on a group VarSet —
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
        self.varset.lineEdit().setPlaceholderText("PostDims_Balcony")
        self.varset.setToolTip(
            "The group VarSet to store the variable on — pick one, or "
            "type a new label to create it (Kind_Owner style, e.g. "
            "PostDims_Balcony). Timber Dims and joint VarSets are not "
            "offered: shared values belong on the group layer.")
        form.addRow("Variable Set:", self.varset)
        self.prop_name = QtWidgets.QLineEdit(self)
        self.prop_name.setPlaceholderText("Post_Height")
        self.prop_name.setToolTip(
            "New property name, Part_Attribute[_Qualifier] style "
            "(letters, digits, underscores; starts with a letter).")
        form.addRow("Variable:", self.prop_name)
        self.type_box = QtWidgets.QComboBox(self)
        for label, _tid, _unit in self.TYPES:
            self.type_box.addItem(label)
        self.type_box.currentIndexChanged.connect(self._retype)
        form.addRow("Type:", self.type_box)
        self.value = _quantity_field(default_mm)
        form.addRow("Value:", self.value)
        self.tooltip_edit = QtWidgets.QLineEdit(self)
        self.tooltip_edit.setPlaceholderText(
            "brief description — which face/end it measures from")
        self.tooltip_edit.setToolTip(
            "Tooltip for the new variable; the advisory linter expects "
            "every property to carry one.")
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
        QtWidgets.QMessageBox.warning(self, "Store in Variable Set",
                                      message)

    def accept(self):
        label = self.varset.currentText().strip()
        name = self.prop_name.text().strip()
        if not label:
            return self._complain("choose or name a Variable Set")
        bad = naming.reserved_in_label(label)
        if bad:
            return self._complain(
                f"VarSet label contains forbidden character(s) {bad!r}")
        if not _PROPERTY_IDENT.match(name):
            return self._complain(
                "the variable name must be letters, digits, and "
                "underscores, starting with a letter (Part_Attribute "
                "style, e.g. Post_Height)")
        existing = self.doc.getObjectsByLabel(label)
        vs = existing[0] if existing else None
        if vs is not None and vs.TypeId != "App::VarSet":
            return self._complain(
                f"{label!r} exists but is not a Variable Set")
        if vs is not None and name in vs.PropertiesList:
            return self._complain(
                f"{label!r} already has a property {name!r}")
        type_label, type_id, _unit = self.TYPES[self.type_box.currentIndex()]
        raw = float(self.value.property("rawValue"))
        self.doc.openTransaction("Store in Variable Set")
        try:
            if vs is None:
                vs = self.doc.addObject("App::VarSet", "VarSet")
                vs.Label = label
            vs.addProperty(type_id, name, "Parameters",
                           self.tooltip_edit.text().strip())
            setattr(vs, name,
                    int(round(raw)) if type_label == "Integer" else raw)
        except Exception as err:
            self.doc.abortTransaction()
            return self._complain(f"could not store the variable: {err}")
        self.doc.commitTransaction()
        self.reference = f"<<{vs.Label}>>.{name}"
        super().accept()


class _DimField(QtWidgets.QWidget):
    """One dimension row: a QuantitySpinBox with an 'fx' toggle that
    swaps in an autocompleting expression edit, plus a '+' button to
    store a new variable — literal OR binding, the dialog face of the
    parameter-groups design ("membership IS the binding")."""

    def __init__(self, default, doc, parent=None, include_dims=False,
                 unit="mm"):
        super().__init__(parent)
        self._doc = doc
        self.unit = unit
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.spin = _quantity_field(default, unit)
        self.expr = _ExpressionEdit(doc, self, include_dims=include_dims)
        self.expr.setPlaceholderText("<<PostDims.Balcony>>.PostHeight")
        self.expr.setToolTip(
            "Expression — binds this dimension to another VarSet's "
            "property; editing that VarSet later moves every timber "
            "bound to it. Autocompletes over the document's VarSets.")
        self.expr.hide()
        self.fx = QtWidgets.QToolButton(self)
        self.fx.setText("ƒx")
        self.fx.setCheckable(True)
        self.fx.setToolTip(
            "Toggle literal value / expression. An expression binds the "
            "dimension to a group VarSet (e.g. one that drives every "
            "balcony post).")
        self.fx.toggled.connect(self._swap)
        self.store = QtWidgets.QToolButton(self)
        self.store.setText("+")
        self.store.setToolTip(
            "Store in Variable Set — save the value as a new variable "
            "on a group VarSet (created here if needed) and bind this "
            "field to it.")
        self.store.hide()
        self.store.clicked.connect(self._store)
        lay.addWidget(self.spin)
        lay.addWidget(self.expr)
        lay.addWidget(self.fx)
        lay.addWidget(self.store)

    def _swap(self, on):
        self.spin.setVisible(not on)
        self.expr.setVisible(on)
        # the store dialog creates length variables; keep it off
        # non-length fields (an angle stored as mm would bind garbage)
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
        """A Quantity, or an '=expression' string for new_timber."""
        if self.fx.isChecked() and self.expr.text().strip():
            return "=" + self.expr.text().lstrip("= ").strip()
        raw = self.spin.property("rawValue")
        return App.Units.Quantity(f"{raw} {self.unit}")


class NewTimberDialog(QtWidgets.QDialog):
    """Copy-from picker + permanent name + section + length + optional
    position tag. Dimensions accept literals or expressions (fx toggle).
    Values persist across validation retries so the user fixes input
    instead of retyping it."""

    DEFAULTS = (203.2, 203.2, 2438.4)   # mm internally; displayed per schema

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("New Timber")
        form = QtWidgets.QFormLayout(self)
        self.copy_from = QtWidgets.QComboBox(self)
        self.copy_from.addItem("(new timber)", None)
        for body in _timber_bodies(doc):
            self.copy_from.addItem(body.Label, body)
        self.copy_from.setToolTip(
            "Prefill from an existing timber: its name base with the "
            "next serial, and its dimensions — expressions included, so "
            "group bindings carry over (bindings that point back at the "
            "source timber itself are copied as plain values instead).")
        form.addRow("Copy from:", self.copy_from)
        self.member_id = QtWidgets.QLineEdit(self)
        self.member_id.setPlaceholderText("T.Post.001")
        self.member_id.setToolTip(
            "Permanent name — describes what the stick IS, never its "
            "position (that goes in the position tag below). Free-form; "
            "T-<Role>[-<Qualifier>]-<serial> style recommended (e.g. "
            "T.Post.Balcony.001, T-Post-Level1-003). Ends in a separator "
            "+ number: that serial is what copy tools bump. Leave it off "
            "and the next free one is appended for you (end the name "
            "with your separator to pick it). Forbidden: '>', "
            "'\\' and ';'.")
        form.addRow("Name:", self.member_id)
        self.fields = {}
        for label, default in zip(("Width", "Depth", "Length"), self.DEFAULTS):
            field = _DimField(default, doc, self)
            self.fields[label] = field
            form.addRow(f"{label}:", field)
        self.position_tag = QtWidgets.QLineEdit(self)
        self.position_tag.setPlaceholderText("e.g. Bent 2, north post")
        self.position_tag.setToolTip(
            "Optional, display-only: where the stick lands in the "
            "structure, for layout drawings and lists. Stored as "
            "Position_Tag on the Dims VarSet; change it freely later — "
            "nothing binds to it.")
        form.addRow("Position tag:", self.position_tag)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.copy_from.currentIndexChanged.connect(self._prefill)
        # a timber selected in the 3D view / tree preselects the source
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
        exprs = {path.lstrip("."): expr
                 for path, expr in dims.ExpressionEngine}
        for name in ("Width", "Depth", "Length"):
            expr = exprs.get(name)
            if expr and self._portable(expr, body, dims):
                self.fields[name].set_expression(expr)
            else:
                self.fields[name].set_literal(getattr(dims, name).Value)

    @staticmethod
    def _portable(expr, body, dims):
        """Finding #2: a copied expression must never keep pointing at
        the source timber. Group-VarSet bindings copy; anything
        mentioning the source body or its Dims falls back to the
        literal value."""
        return not any(token and token in expr
                       for token in (body.Name, body.Label,
                                     dims.Name, dims.Label))

    def values(self):
        """(member_id, width, depth, length, position_tag) — each
        dimension a Quantity or an '=expression' string."""
        out = [self.member_id.text()]
        for name in ("Width", "Depth", "Length"):
            out.append(self.fields[name].value())
        out.append(self.position_tag.text())
        return tuple(out)


class NewTimberCommand:
    def GetResources(self):
        return {
            "MenuText": "New Timber",
            "ToolTip": "Create a pristine parametric timber — Body with "
                       "permanent name label, Dims VarSet, section "
                       "sketch on the reference planes, pad to the stick "
                       "length. Dimensions take literals or expressions; "
                       "select an existing timber first to copy from it",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        dialog = NewTimberDialog(doc, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                member_id, width, depth, length, tag = dialog.values()
                member_id = member_id.strip()
                # no trailing serial segment -> append the next free one
                if member_id and naming.split_serial(member_id)[1] is None:
                    member_id = naming.successor_label(
                        [o.Label for o in doc.Objects], member_id)
                doc.openTransaction(f"New timber {member_id}")
                try:
                    body, _dims = new_timber(doc, member_id, width, depth,
                                             length, position_tag=tag)
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


def _timber_bodies(doc):
    """Bodies with a Dims VarSet driving their base pad — valid joint
    targets, resolved structurally so renamed timbers still qualify."""
    return [o for o in doc.Objects
            if o.TypeId == "PartDesign::Body" and dims_varset(o) is not None]


def _pick_joint(doc, title):
    """Prompt for a timber-joint instance VarSet, preselected from the current
    selection (its handle, its VarSet, or any joint member — the marker
    and the landing frame are both 3D-clickable, and member labels carry
    the joint's suffix).
    Returns the VarSet, or None if cancelled / none present."""
    joints = joint_handle.joint_varsets(doc)
    if not joints:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), title, "No timber joints in this document.")
        return None
    labels = [j.Label for j in joints]
    current = 0
    selection = Gui.Selection.getSelection()
    # a selected marker names its joint outright — no suffix matching
    sel_labels = [o.Label for o in selection]
    for obj in selection:
        held = joint_handle.handle_varset(obj) \
            if joint_handle.is_handle(obj) else None
        if held is not None:
            sel_labels.append(held.Label)
    for i, joint in enumerate(joints):
        # member labels carry the joint's suffix: '.WHD.001' under the
        # current scheme, '_J-HousedMT-001' or legacy '_MT_B2a' for joints
        # applied before Template_Abbrev — accept whichever this one uses
        abbrev = getattr(joint, naming.TEMPLATE_ABBREV, None)
        suffixes = tuple(s for s in
                         {naming.joint_suffix_for(joint.Label, abbrev),
                          naming.member_suffix(joint.Label)} if s)
        if any(s == joint.Label or (suffixes and s.endswith(suffixes))
               for s in sel_labels):
            current = i
            break
    label, ok = QtWidgets.QInputDialog.getItem(
        Gui.getMainWindow(), title, "Timber joint:", labels, current, False)
    if not ok:
        return None
    return joints[labels.index(label)]


# --------------------------------------------------------------------------
# Whole-joint operations
#
# Shared by the toolbar commands (which pick a joint first) and the
# handle marker's context menu (which already knows which joint). Each
# owns its transaction, so either entry point is one undo step.
# --------------------------------------------------------------------------

def show_joint_parameters(varset):
    """Select the joint's VarSet: its parameters fill the Data property
    editor, editable in place."""
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(varset)


def select_joint_members(varset):
    """Select everything the joint is made of — both timbers' cuts,
    sketches and frames. A timber joint is scattered by nature; this is
    how you see its full extent in the tree and the 3D view."""
    Gui.Selection.clearSelection()
    for obj in joint_members(varset):
        Gui.Selection.addSelection(obj)
    Gui.Selection.addSelection(varset)


def preview_joint_interactive(varset):
    """Toggle Preview Mated Joint for one joint, reporting why not."""
    doc = varset.Document
    existing = find_preview(varset)
    if existing is not None:                 # toggle off
        doc.openTransaction(f"Clear preview {varset.Label}")
        try:
            remove_preview(existing)
        except Exception:
            doc.abortTransaction()
            raise
        doc.commitTransaction()
        return
    if engagement_placement(varset) is None:
        QtWidgets.QMessageBox.warning(
            Gui.getMainWindow(), "Preview Mated Timber Joint",
            f"{varset.Label} has no mate frame, so its engaged pose is "
            f"not defined. Joints applied before mate frames were added "
            f"to the template cannot be previewed; re-apply to enable it.")
        return
    doc.openTransaction(f"Preview {varset.Label}")
    try:
        group = create_preview(varset)
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    Gui.Selection.clearSelection()
    if group is not None:
        Gui.Selection.addSelection(group)
        try:
            Gui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass


def remove_joint_interactive(varset):
    """Remove one timber joint, after showing what goes with it."""
    doc = varset.Document
    label = varset.Label
    members = joint_members(varset)
    bodies = sorted({o.getParentGeoFeatureGroup().Label
                     for o in members if o.getParentGeoFeatureGroup()})
    answer = QtWidgets.QMessageBox.question(
        Gui.getMainWindow(), "Remove Timber Joint",
        f"Remove {label} — {len(members)} objects across "
        f"{', '.join(bodies) or 'no bodies'} — plus the VarSet?",
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


class ApplyJointDialog(QtWidgets.QDialog):
    """Template + role assignment + joint ID + the parameter form —
    generated from the template's VarSet schema, no per-joint code."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.spec = None
        self.setWindowTitle("Apply Timber Joint")
        layout = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QFormLayout()
        self.template_box = QtWidgets.QComboBox(self)
        for f in sorted(LIBRARY_DIR.glob("*.FCStd")):
            self.template_box.addItem(f.stem, str(f))
        self.template_box.currentIndexChanged.connect(self._load_template)
        top.addRow("Timber joint template:", self.template_box)
        self.joint_id = QtWidgets.QLineEdit(self)
        self.joint_id.setPlaceholderText("001")
        self.joint_id.setToolTip(
            "Joint serial — becomes J-<Kind>-<serial> (e.g. "
            "J-HousedMT-001) and the suffix on every cloned feature. "
            "Prefilled with the next free serial; position info belongs "
            "in the joint's Position_Tag, not here.")
        top.addRow("Joint serial:", self.joint_id)
        layout.addLayout(top)

        self.roles_form = QtWidgets.QFormLayout()
        layout.addLayout(self.roles_form)
        self.params_group = QtWidgets.QGroupBox("Parameters", self)
        self.params_form = QtWidgets.QFormLayout(self.params_group)
        layout.addWidget(self.params_group)

        self.assemble_now = QtWidgets.QCheckBox(
            "Assemble now (seat the joint in the structure assembly)", self)
        self.assemble_now.setChecked(True)
        self.assemble_now.setToolTip(
            "Seat this timber joint the moment it is created: the "
            "timbers join the structure assembly (created on the first "
            "joint, grounded at the Principal timber) and a Fixed "
            "assembly joint locks the engaged pose — visible "
            "immediately, parametric, undoable. Uncheck to only cut "
            "the joinery.")
        layout.addWidget(self.assemble_now)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.role_boxes = {}
        self.param_fields = {}
        self._load_template()

    def _clear(self, form):
        while form.rowCount():
            form.removeRow(0)

    def _load_template(self, *_):
        path = self.template_box.currentData()
        self._clear(self.roles_form)
        self._clear(self.params_form)
        self.role_boxes.clear()
        self.param_fields.clear()
        if not path:
            return
        try:
            self.spec = TemplateSpec(path)
        except (JointError, OSError) as err:
            QtWidgets.QMessageBox.warning(self, "Apply Timber Joint", str(err))
            self.spec = None
            return
        # next free serial in this kind's J-<Kind>-NNN family
        suggested = naming.next_serial(
            [o.Label for o in self.doc.Objects],
            naming.JOINT_PREFIX + self.spec.kind_token)
        self.joint_id.setText(naming.split_serial(suggested)[1])

        # Role assignment: one combo per template role, preseeded from
        # the current selection order.
        bodies = _timber_bodies(self.doc)
        selected = [o for o in Gui.Selection.getSelection() if o in bodies]
        self.end_boxes = {}
        self.face_boxes = {}
        self.hand_boxes = {}
        for i, role in enumerate(self.spec.roles):
            box = QtWidgets.QComboBox(self)
            # never guess a timber: preseed only from the selection,
            # otherwise force an explicit choice (a silent fallback once
            # applied a joint to a body the user never selected)
            box.addItem("— choose a timber —", None)
            for b in bodies:
                box.addItem(b.Label, b.Name)
            if i < len(selected):
                box.setCurrentIndex(bodies.index(selected[i]) + 1)
            self.role_boxes[role] = box
            self.roles_form.addRow(f"{role} timber:", box)
            if role in self.spec.end_landing_roles:
                end_box = QtWidgets.QComboBox(self)
                end_box.addItem("End A (butt, Z=0)", "A")
                end_box.addItem("End B (tip)", "B")
                end_box.setToolTip(
                    "Which stick end receives this joint. End B keeps the "
                    "setbacks measured from the same reference faces and "
                    "flips the drawbore toward the far shoulder.")
                self.end_boxes[role] = end_box
                self.roles_form.addRow(f"{role} end:", end_box)
            if role in self.spec.side_landing_roles:
                face_box = QtWidgets.QComboBox(self)
                for num, label in ((1, "Face 1 — reference face (XZ)"),
                                   (2, "Face 2 — reference face (YZ)"),
                                   (3, "Face 3 — opposite Face 1"),
                                   (4, "Face 4 — opposite Face 2")):
                    face_box.addItem(label, num)
                face_box.setCurrentIndex(3)          # Face 4, template face
                face_box.setToolTip(
                    "Which long face receives this joint. Reference-face "
                    "numbering: 1 and 2 are the reference faces on the XZ/YZ "
                    "origin planes; 3 and 4 are opposite them.")
                self.face_boxes[role] = face_box
                self.roles_form.addRow(f"{role} face:", face_box)
                if not self.spec.handed:
                    # Template_Handed false: a symmetrical joint has no
                    # mirrored variant — hide the choice entirely
                    continue
                hand_box = QtWidgets.QComboBox(self)
                hand_box.addItem("As templated", "template")
                hand_box.addItem("Mirrored (handed pair)", "mirrored")
                hand_box.setToolTip(
                    "Mirrored applies the §4.6 handed-mate transform: the "
                    "joint's across-face asymmetry (setbacks) mirrors, for "
                    "the second post of a pair facing the beam from the "
                    "opposite direction.")
                self.hand_boxes[role] = hand_box
                self.roles_form.addRow(f"{role} hand:", hand_box)

        # Parameter form from the schema. Junction-bound parameters stay
        # expressions (override later by editing the VarSet, per §4.9).
        for p in self.spec.parameters:
            if p["metadata"]:
                # template metadata (Handed flag, angle bounds): read by
                # the tools — the hand option and angle field limits —
                # never a per-application input
                continue
            if p.get("consumed"):
                # this joint parameter is consumed from the companion
                # layout VarSet, whose own row below is the editable
                # one; a read-only echo here would just be confusing
                continue
            if p["expression"]:
                note = QtWidgets.QLabel(f"= {p['expression']}   (tracks "
                                        f"the mating timber)", self)
                note.setToolTip(p["tooltip"])
                self.params_form.addRow(f"{p['name']}:", note)
                continue
            if p["type_id"] in ("App::PropertyInteger", "App::PropertyBool"):
                # counts (Peg_Count) and flags are set by the template's
                # geometry, not per application; editable later on the
                # VarSet's Data tab if the applied joint is reworked
                note = QtWidgets.QLabel(f"{p['value']}   (set by the "
                                        f"template)", self)
                note.setToolTip(p["tooltip"])
                self.params_form.addRow(f"{p['name']}:", note)
                continue
            # joint parameters legitimately bind to timber Dims
            # (junction bindings), so completion includes them here
            unit = "deg" if p["type_id"] == "App::PropertyAngle" else "mm"
            field = _DimField(float(p["value"]), self.doc, self,
                              include_dims=True, unit=unit)
            if unit == "deg":
                # the template's declared angle range clamps the field
                # (apply re-checks the resolved value either way)
                if self.spec.angle_min is not None:
                    field.spin.setProperty("minimum",
                                           float(self.spec.angle_min))
                if self.spec.angle_max is not None:
                    field.spin.setProperty("maximum",
                                           float(self.spec.angle_max))
            field.spin.setToolTip(p["tooltip"])
            field.expr.setToolTip(p["tooltip"])
            field.expr.setPlaceholderText("<<VarSet>>.Property")
            self.param_fields[p["name"]] = field
            self.params_form.addRow(f"{p['name']}:", field)

    def request(self):
        """(spec, joint_id, body_map, values); raises JointError."""
        if self.spec is None:
            raise JointError("no template loaded")
        body_map = {}
        for role, box in self.role_boxes.items():
            name = box.currentData()
            obj = self.doc.getObject(name) if name else None
            if obj is None:
                raise JointError(f"choose a timber for the {role!r} role")
            body_map[role] = obj
        if len({b.Name for b in body_map.values()}) != len(body_map):
            raise JointError("each role needs a different timber")
        values = {}
        for name, field in self.param_fields.items():
            if field.fx.isChecked():
                text = field.expr.text().strip()
                if not text:
                    raise JointError(
                        f"{name}: expression entry is on but empty")
                # '=' marks it an expression (spreadsheet convention,
                # same as New Timber's dimension fields)
                values[name] = f"={text}"
            else:
                raw = field.spin.property("rawValue")
                values[name] = App.Units.Quantity(f"{raw} {field.unit}")
        placement = {}
        for role, box in self.end_boxes.items():
            placement.setdefault(role, {})["end"] = box.currentData()
        for role, box in self.face_boxes.items():
            placement.setdefault(role, {})["face"] = box.currentData()
        for role, box in self.hand_boxes.items():
            placement.setdefault(role, {})["hand"] = box.currentData()
        return self.spec, self.joint_id.text(), body_map, values, placement


class ApplyJointCommand:
    def GetResources(self):
        return {
            "MenuText": "Apply Timber Joint",
            "ToolTip": "Apply a timber joint template between two timbers: "
                       "clones the template's cuts into both, driven by one "
                       "shared joint VarSet",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        from .assemble import assimilate_joint, is_misfit
        doc = App.ActiveDocument
        dialog = ApplyJointDialog(doc, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                spec, joint_id, body_map, values, placement = dialog.request()
                doc.openTransaction(f"Apply joint {joint_id.strip()}")
                try:
                    varset = apply_joint(doc, spec, joint_id, body_map,
                                         values=values, placement=placement)
                    result = (assimilate_joint(doc, varset)
                              if dialog.assemble_now.isChecked() else None)
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except JointError as err:
                QtWidgets.QMessageBox.warning(dialog, "Apply Timber Joint",
                                              str(err))
                continue
            if result is not None and result.new_assembly is not None:
                QtWidgets.QMessageBox.information(
                    Gui.getMainWindow(), "Apply Timber Joint",
                    f"{result.new_assembly.Label} created. Principal "
                    f"(grounded) member: {result.principal.Label} — "
                    f"everything else seats against it. Use Assemble "
                    f"Timbers to reground if another member should be "
                    f"the Principal.")
            if dialog.assemble_now.isChecked() and is_misfit(varset):
                QtWidgets.QMessageBox.warning(
                    Gui.getMainWindow(), "Apply Timber Joint",
                    f"{varset.Label} was created, but its halves "
                    f"disagree about where the timber sits (check the "
                    f"joint's stations/faces against the other joints "
                    f"on this timber).")
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(varset)
            return


class RemoveJointCommand:
    def GetResources(self):
        return {
            "MenuText": "Remove Timber Joint",
            "ToolTip": "Remove a timber joint completely: every cut, "
                       "sketch, and landing frame on both timbers, plus "
                       "the joint VarSet",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        varset = _pick_joint(App.ActiveDocument, "Remove Timber Joint")
        if varset is not None:
            remove_joint_interactive(varset)


class PreviewJointCommand:
    def GetResources(self):
        return {
            "MenuText": "Preview Mated Timber Joint",
            "ToolTip": "Show both halves of a joint engaged (a ghost view "
                       "with the joint centered at the origin), to verify "
                       "fit — real timber placements are untouched. Run "
                       "again to clear.",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        varset = _pick_joint(App.ActiveDocument, "Preview Mated Timber Joint")
        if varset is not None:
            preview_joint_interactive(varset)


class DuplicateBentDialog(QtWidgets.QDialog):
    """New permanent names for the selected timbers and new serials for
    their joints, prefilled with the next free serial per name family
    (only the trailing serial changes — descriptive parts are never
    rewritten). Every row stays editable."""

    def __init__(self, doc, bodies, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.bodies = bodies
        self.setWindowTitle("Duplicate Timbers")
        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.body_fields = {}
        suggested = suggest_member_labels(doc, bodies)
        for body in bodies:
            edit = QtWidgets.QLineEdit(self)
            edit.setText(suggested[body])
            edit.setToolTip(
                "Permanent name for the copy — same base, next free "
                "serial. Edit freely; only uniqueness is required.")
            self.body_fields[body] = edit
            form.addRow(f"{body.Label} →", edit)
        self.joints_inside, self.joints_outside = bent_joints(doc, bodies)
        self.joint_fields = {}
        suggested_ids = suggest_joint_ids(doc, self.joints_inside)
        for joint in self.joints_inside:
            edit = QtWidgets.QLineEdit(self)
            edit.setText(suggested_ids[joint])
            edit.setToolTip("New joint serial (becomes J-<Kind>-<serial>)")
            self.joint_fields[joint] = edit
            form.addRow(f"{joint.Label} →", edit)
        layout.addLayout(form)
        if self.joints_outside:
            note = QtWidgets.QLabel(
                "Skipped (other timber not selected): "
                + ", ".join(j.Label for j in self.joints_outside), self)
            note.setWordWrap(True)
            layout.addWidget(note)

        extras = QtWidgets.QFormLayout()
        self.position_tag = QtWidgets.QLineEdit(self)
        self.position_tag.setPlaceholderText("e.g. Bent 2")
        self.position_tag.setToolTip(
            "Optional, display-only Position_Tag written on every "
            "copy's Dims VarSet — where the new bent stands. Change it "
            "freely later; nothing binds to it.")
        extras.addRow("Position tag for copies:", self.position_tag)
        self.assembly_label = QtWidgets.QLineEdit(self)
        self.assembly_label.setText(naming.next_serial(
            [o.Label for o in doc.Objects], "Bent"))
        self.assembly_label.setToolTip(
            "Assemble the copies into a new bent sub-assembly of this "
            "name: rigid among themselves (their joints seat "
            "immediately), free-floating and user-movable until tie "
            "beams connect them to the frame — then their position "
            "becomes parametric. Clear the field to make loose copies "
            "instead.")
        extras.addRow("New bent assembly:", self.assembly_label)
        self.offset_fields = {}
        for axis in ("X", "Y", "Z"):
            field = _quantity_field(0.0)
            field.setProperty("minimum", -1e9)
            field.setToolTip(
                "Provisional offset of the copies from the originals "
                "along this axis (e.g. one bay depth) — replaced by "
                "the parametric position once connecting timber "
                "joints are applied.")
            self.offset_fields[axis] = field
            extras.addRow(f"Offset {axis}:", field)
        self.group_label = QtWidgets.QLineEdit(self)
        self.group_label.setPlaceholderText("e.g. Bent 2")
        self.group_label.setToolTip(
            "Without a bent assembly: put the copies in a Std Group of "
            "this name (created if absent). Groups are pure "
            "organization — drag timbers between them freely.")
        extras.addRow("Or add copies to group:", self.group_label)
        layout.addLayout(extras)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def request(self):
        member_map = {b: e.text().strip() for b, e in self.body_fields.items()}
        joint_ids = {j.Label: e.text().strip()
                     for j, e in self.joint_fields.items()}
        if any(not v for v in joint_ids.values()):
            raise JointError("every joint needs a new serial")
        offset = App.Vector(*(self.offset_fields[a].property("rawValue")
                              for a in ("X", "Y", "Z")))
        return (member_map, joint_ids, self.position_tag.text(),
                self.group_label.text(), self.assembly_label.text(), offset)


class DuplicateBentCommand:
    def GetResources(self):
        return {
            "MenuText": "Duplicate Timbers",
            "ToolTip": "Duplicate the selected timbers with their timber "
                       "joints — the next bent, one action: each copy owns "
                       "its Dims and joint VarSets (group bindings stay "
                       "shared), and the copies assemble into a new bent "
                       "sub-assembly at a provisional offset, ready for "
                       "tie beams.",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        bodies = [o for o in Gui.Selection.getSelection()
                  if o in _timber_bodies(doc)]
        if not bodies:
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Duplicate Timbers",
                "Select the timbers to duplicate first (their joints come "
                "along automatically when both mating timbers are selected).")
            return
        dialog = DuplicateBentDialog(doc, bodies, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                member_map, joint_ids, tag, group, asm_label, offset = \
                    dialog.request()
                doc.openTransaction("Duplicate timbers")
                try:
                    new_bodies, new_joints, skipped = duplicate_bent(
                        doc, member_map, joint_ids, LIBRARY_DIR,
                        position_tag=tag, group_label=group,
                        assembly_label=asm_label, offset=offset)
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except JointError as err:
                QtWidgets.QMessageBox.warning(dialog, "Duplicate Timbers",
                                              str(err))
                continue
            msg = (f"Created {len(new_bodies)} timber(s) and "
                   f"{len(new_joints)} joint(s).")
            if skipped:
                msg += f" Skipped (reach outside the set): {', '.join(skipped)}."
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Duplicate Timbers", msg)
            return


class AssembleTimbersDialog(QtWidgets.QDialog):
    """Assembly (new or existing) + Principal timber, with the timber
    joints that will become Fixed assembly joints listed."""

    def __init__(self, doc, bodies, parent=None):
        super().__init__(parent)
        from .assemble import _engagement_frames, pick_grounded
        self.doc = doc
        self.bodies = bodies
        self.setWindowTitle("Assemble Timbers")
        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.assembly_box = QtWidgets.QComboBox(self)
        self.assembly_box.addItem("New assembly:", None)
        for obj in doc.Objects:
            if obj.TypeId == "Assembly::AssemblyObject":
                self.assembly_box.addItem(obj.Label, obj.Name)
        self.assembly_box.setToolTip(
            "Where the timbers assemble: a new bent sub-assembly, or "
            "an existing assembly to extend.")
        form.addRow("Assembly:", self.assembly_box)
        self.new_name = QtWidgets.QLineEdit(self)
        self.new_name.setText(naming.next_serial(
            [o.Label for o in doc.Objects], "Bent"))
        self.new_name.setToolTip(
            "Name for the new bent sub-assembly (used only when "
            "creating one).")
        form.addRow("New assembly name:", self.new_name)
        self.assembly_box.currentIndexChanged.connect(
            lambda *_: self.new_name.setEnabled(
                self.assembly_box.currentData() is None))

        self.joints_inside, _outside = bent_joints(doc, bodies)
        seatable = [j for j in self.joints_inside if _engagement_frames(j)]
        self.grounded_box = QtWidgets.QComboBox(self)
        default = pick_grounded(bodies, seatable)
        for body in bodies:
            self.grounded_box.addItem(body.Label, body.Name)
        self.grounded_box.setCurrentIndex(bodies.index(default))
        self.grounded_box.setToolTip(
            "The Principal timber — the one that stays fixed; every "
            "other timber seats against it through the timber joints. "
            "Framers measure everything from the Principal Post. "
            "Default: a timber that only receives joints (the "
            "load-bearing primary).")
        form.addRow("Principal timber:", self.grounded_box)
        layout.addLayout(form)

        note = QtWidgets.QLabel(
            "Timber joints to assemble: "
            + (", ".join(j.Label for j in seatable) or "none — the "
               "timbers will only be grounded/collected"), self)
        note.setWordWrap(True)
        layout.addWidget(note)
        legacy = [j.Label for j in self.joints_inside if j not in seatable]
        if legacy:
            warn = QtWidgets.QLabel(
                "No engagement frames (re-apply to enable): "
                + ", ".join(legacy), self)
            warn.setWordWrap(True)
            layout.addWidget(warn)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def request(self):
        """(assembly or None, new label, grounded_body)."""
        name = self.assembly_box.currentData()
        assembly = self.doc.getObject(name) if name else None
        grounded = self.doc.getObject(self.grounded_box.currentData())
        return assembly, self.new_name.text(), grounded


class AssembleTimbersCommand:
    def GetResources(self):
        return {
            "MenuText": "Assemble Timbers",
            "ToolTip": "Assemble the selected timbers (bulk/repair): seat "
                       "every timber joint among them as Fixed assembly "
                       "joints in a new or existing assembly, grounded at "
                       "the Principal timber. Apply Timber Joint already "
                       "does this per joint as you work.",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        from .assemble import assemble_timbers
        doc = App.ActiveDocument
        bodies = [o for o in Gui.Selection.getSelection()
                  if o in _timber_bodies(doc)]
        if not bodies:
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Assemble Timbers",
                "Select the timbers to assemble first (their timber "
                "joints define how they seat together).")
            return
        dialog = AssembleTimbersDialog(doc, bodies, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                assembly, label, grounded = dialog.request()
                doc.openTransaction("Assemble timbers")
                try:
                    asm, skipped, misfits, adopted = assemble_timbers(
                        doc, bodies, assembly=assembly, label=label,
                        grounded=grounded)
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except JointError as err:
                QtWidgets.QMessageBox.warning(dialog, "Assemble Timbers",
                                              str(err))
                continue
            msg = f"Assembled {len(bodies)} timber(s) into {asm.Label}."
            if adopted:
                msg += (f" Gave {adopted} existing timber joint(s) a "
                        f"handle — the marker in the 3D view.")
            if skipped:
                msg += (f" No engagement frames (re-apply to enable): "
                        f"{', '.join(skipped)}.")
            if misfits:
                msg += (f" WARNING — these timber joints disagree about "
                        f"where their timber sits (check stations/faces): "
                        f"{', '.join(misfits)}.")
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Assemble Timbers", msg)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(asm)
            return


class DriveLengthFromSpanDialog(QtWidgets.QDialog):
    """Pick the layout distance a timber's Length derives from.

    The list holds every numeric project/group VarSet property plus a
    '(new distance...)' entry, so a framer never has to hand-author a
    VarSet before the tool is usable (CLAUDE.md audience note). Joint
    parameters are filtered out: Tenon_Length is not a bay dimension,
    and a long list of them buries everything else.

    The basis (O.C. or clear span) belongs to the DISTANCE, not to this
    dialog — picking an existing variable adopts its basis. All three
    numbers are shown live, so choosing the wrong one is visible rather
    than silent.
    """

    NEW = "(new distance…)"

    def __init__(self, doc, body, parent=None):
        super().__init__(parent)
        from . import naming
        from .span import available_bases, driving_span, entering_joints
        self.doc = doc
        self.body = body
        self.dims = dims_varset(body)
        self.bases = available_bases(body)
        self.setWindowTitle("Drive Length from Layout Distance")
        layout = QtWidgets.QVBoxLayout(self)

        joints = entering_joints(body)
        summary = QtWidgets.QLabel(
            f"<b>{body.Label}</b> lands on {len(joints)} timber(s). Its "
            f"stick length becomes the layout distance plus what each "
            f"end's joinery adds beyond it.", self)
        summary.setWordWrap(True)
        layout.addWidget(summary)

        form = QtWidgets.QFormLayout()
        self.basis_box = QtWidgets.QComboBox(self)
        for basis in self.bases:
            self.basis_box.addItem(naming.BASIS_LABEL[basis], basis)
        self.basis_box.setToolTip(
            "O.C. = On-Center, centerline of one timber to centerline "
            "of the next. Clear span = Face-to-Face, the open distance "
            "between them. Both give the same stick; they are two ways "
            "of writing down the same layout.\n\nClear span needs "
            "exactly two timbers to be between, so it is unavailable "
            "otherwise.")
        self.basis_box.currentIndexChanged.connect(self._refresh)
        form.addRow("Measured:", self.basis_box)

        self.span_box = QtWidgets.QComboBox(self)
        self.span_box.addItem(self.NEW, None)
        for ref in _expression_candidates(doc, include_dims=False,
                                          include_joints=False):
            self.span_box.addItem(ref, ref)
        self.span_box.setToolTip(
            "The layout distance this timber spans. Several bays bound "
            "to one distance move together when it is edited.")
        self.span_box.currentIndexChanged.connect(self._span_chosen)
        form.addRow("Distance:", self.span_box)

        self.new_name = QtWidgets.QLineEdit(self)
        self.new_name.setToolTip(
            "Name for the new distance variable, created on the "
            "project VarSet (Project_Main). The '_Dist_OC' / "
            "'_Dist_FTF' suffix marks which basis it is measured on, "
            "so the name is never ambiguous on its own.")
        form.addRow("New distance name:", self.new_name)
        # the stick's present length is the closest thing to a layout
        # distance the user already has; they adjust from there
        self.new_value = _quantity_field(
            self.dims.Length.Value if self.dims is not None else 3048.0)
        self.new_value.valueChanged.connect(self._refresh)
        self.new_value.setToolTip(
            "Starting distance. Edit it later on the project VarSet to "
            "move every bay bound to it.")
        form.addRow("New distance value:", self.new_value)
        layout.addLayout(form)

        self.readout = QtWidgets.QLabel(self)
        self.readout.setTextFormat(QtCore.Qt.RichText)
        self.readout.setToolTip(
            "What this layout gives, both ways round, plus the stick "
            "that gets cut. Shown together so the two bases cannot be "
            "quietly confused.")
        layout.addWidget(self.readout)

        # adopt the basis this timber is ALREADY driven on, if any
        self.driven = driving_span(body)
        if self.driven:
            ref, basis = self.driven
            at = self.basis_box.findData(basis)
            if at >= 0:
                self.basis_box.setCurrentIndex(at)
            at = self.span_box.findData(ref)
            if at >= 0:
                self.span_box.setCurrentIndex(at)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self)
        # Stopping is its own action, not a distance you could pick — as
        # a combo entry it sat at the bottom of a long list, present but
        # undiscoverable. Shown only when there is something to stop.
        self.stop_requested = False
        if self.driven:
            stop = buttons.addButton(
                "Stop driving", QtWidgets.QDialogButtonBox.DestructiveRole)
            stop.setToolTip(
                f"Keep {body.Label} at its present length and stop "
                f"following {self.driven[0]}. The stick does not move.")
            stop.clicked.connect(self._stop)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._span_chosen()

    # -- state -------------------------------------------------------------

    def basis(self):
        return self.basis_box.currentData()

    def _stop(self):
        self.stop_requested = True
        self.accept()

    def _span_chosen(self):
        """A named distance carries its own basis; adopt it and lock the
        selector, so a variable cannot be driven on the wrong one."""
        from . import naming
        ref = self.span_box.currentData()
        making = ref is None
        self.new_name.setEnabled(making)
        self.new_value.setEnabled(making)
        if making:
            self.basis_box.setEnabled(len(self.bases) > 1)
            self._suggest_name()
        else:
            advertised = naming.basis_from_name(ref.split(".")[-1])
            at = self.basis_box.findData(advertised) if advertised else -1
            if at >= 0:
                self.basis_box.setCurrentIndex(at)
            # only lock when the name actually declares a basis
            self.basis_box.setEnabled(at < 0 and len(self.bases) > 1)
        self._refresh()

    def _suggest_name(self):
        from .span import suggested_name
        self.new_name.setText(suggested_name("Bay", self.basis()))

    def _refresh(self):
        from .span import readout
        if self.span_box.currentData() is None:
            self._suggest_name()
        try:
            values = readout(self.body, self._distance_mm(), self.basis())
        except Exception:
            self.readout.setText("")
            return

        def show(mm):
            if mm is None:
                return "—"
            return App.Units.Quantity(mm, App.Units.Length).UserString

        self.readout.setText(
            "<table cellpadding=3>"
            f"<tr><td>On-Center (O.C.)</td><td><b>{show(values['OC'])}"
            "</b></td></tr>"
            f"<tr><td>Clear span (F.T.F.)</td><td><b>"
            f"{show(values['FTF'])}</b></td></tr>"
            f"<tr><td>Stick length cut</td><td><b>"
            f"{show(values['Length'])}</b></td></tr></table>")

    def _distance_mm(self):
        """The distance being proposed, in mm."""
        ref = self.span_box.currentData()
        if ref is None:
            return float(self.new_value.property("rawValue"))
        label, _, prop = ref.partition(">>.")
        holder = self.doc.getObjectsByLabel(label.lstrip("<"))
        if not holder:
            raise ValueError(ref)
        value = getattr(holder[0], prop)
        return value.Value if hasattr(value, "Value") else float(value)

    def span_ref(self):
        """The expression term to bind to; creates the property when the
        user asked for a new distance."""
        from .span import ensure_span_property
        chosen = self.span_box.currentData()
        if chosen:
            return chosen
        return ensure_span_property(
            self.doc, self.new_name.text().strip(),
            App.Units.Quantity(f"{self.new_value.property('rawValue')} mm"),
            basis=self.basis())


def _offer_cleanup(doc, span_ref):
    """Offer to delete a layout distance nothing consumes any more.

    Offered, never automatic: it is the user's variable, and a distance
    is shared on purpose — so this stays silent while anything still
    references it, and only speaks when the value is provably an orphan.
    """
    from .span import SpanError, references_to, remove_distance
    if references_to(doc, span_ref):
        return
    name = span_ref.split(".")[-1]
    answer = QtWidgets.QMessageBox.question(
        Gui.getMainWindow(), "Drive Length from Layout Distance",
        f"Nothing uses {name} any more.\n\nRemove it from the project "
        f"variables?",
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        QtWidgets.QMessageBox.Yes)
    if answer != QtWidgets.QMessageBox.Yes:
        return
    try:
        doc.openTransaction("Remove unused layout distance")
        try:
            remove_distance(doc, span_ref)
        except Exception:
            doc.abortTransaction()
            raise
        doc.commitTransaction()
        doc.recompute()
    except SpanError as err:
        QtWidgets.QMessageBox.warning(
            Gui.getMainWindow(), "Drive Length from Layout Distance",
            str(err))


def _span_ready(body):
    """Explain, once, why a timber cannot be driven yet."""
    from .span import available_bases
    if available_bases(body):
        return True
    QtWidgets.QMessageBox.information(
        Gui.getMainWindow(), "Drive Length from Layout Distance",
        f"{body.Label} does not land on any timber joint that publishes "
        f"a stick allowance yet.\n\nApply its end joints first, using a "
        f"joint template that declares a layout VarSet.")
    return False


class DriveLengthFromSpanCommand:
    def GetResources(self):
        return {
            "MenuText": "Drive Length from Layout Distance",
            "ToolTip": "Derive the selected timber's stick length from a "
                       "layout distance: O.C. (On-Center, centerline to "
                       "centerline) or clear span (Face-to-Face). Length "
                       "= distance + what each end's joinery adds beyond "
                       "it. Edit the distance later and every timber "
                       "bound to it re-cuts, with the bays moving to "
                       "match. Run it on a timber after its end joints "
                       "exist.",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        from .span import (SpanError, drive_length, driving_span,
                           freeze_length)
        doc = App.ActiveDocument
        bodies = [o for o in Gui.Selection.getSelection()
                  if o in _timber_bodies(doc)]
        if len(bodies) != 1:
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Drive Length from Layout Distance",
                "Select one timber — the one whose stick length should "
                "follow the layout distance.")
            return
        body = bodies[0]
        if not _span_ready(body):
            return
        was_driven = driving_span(body)
        dialog = DriveLengthFromSpanDialog(doc, body, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            stopping = dialog.stop_requested
            try:
                doc.openTransaction("Stop driving length" if stopping
                                    else "Drive length from layout distance")
                try:
                    if stopping:
                        freeze_length(body)
                        length = dims_varset(body).Length
                    else:
                        length = drive_length(body, dialog.span_ref(),
                                              dialog.basis())
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except SpanError as err:
                QtWidgets.QMessageBox.warning(
                    dialog, "Drive Length from Layout Distance", str(err))
                continue
            doc.recompute()
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Drive Length from Layout Distance",
                f"{body.Label} stays at {length.UserString}, no longer "
                f"following a layout distance." if stopping else
                f"{body.Label} is now {length.UserString} and follows "
                f"the layout distance. Edit it to move the bay.")
            # the distance it used to follow may now be an orphan — both
            # from stopping and from switching to a different one
            now = driving_span(body)
            if was_driven and (now is None or now[0] != was_driven[0]):
                _offer_cleanup(doc, was_driven[0])
            return


def register():
    # the handle marker's context menu: whole-joint operations, in one
    # place a future joint-wide tool can extend without touching the
    # ViewProvider
    joint_handle.CONTEXT_ACTIONS[:] = [
        ("Joint parameters", show_joint_parameters),
        ("Select joint members", select_joint_members),
        ("Preview mated joint", preview_joint_interactive),
        ("Remove timber joint", remove_joint_interactive),
    ]
    Gui.addCommand("BentWizard_NewTimber", NewTimberCommand())
    Gui.addCommand("BentWizard_ApplyJoint", ApplyJointCommand())
    Gui.addCommand("BentWizard_RemoveJoint", RemoveJointCommand())
    Gui.addCommand("BentWizard_PreviewJoint", PreviewJointCommand())
    Gui.addCommand("BentWizard_DuplicateBent", DuplicateBentCommand())
    Gui.addCommand("BentWizard_AssembleTimbers", AssembleTimbersCommand())
    Gui.addCommand("BentWizard_DriveLengthFromSpan",
                   DriveLengthFromSpanCommand())


ALL_COMMANDS = ["BentWizard_NewTimber", "BentWizard_ApplyJoint",
                "BentWizard_RemoveJoint", "BentWizard_PreviewJoint",
                "BentWizard_DuplicateBent", "BentWizard_AssembleTimbers",
                "BentWizard_DriveLengthFromSpan"]
