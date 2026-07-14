"""GUI commands for the BentWizard workbench.

Imported only from init_gui (needs FreeCADGui and Qt). Core logic lives
in GUI-free modules (timber.py); commands here are thin wrappers:
dialog -> transaction -> core call -> report.
"""

from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from .apply_joint import JointError, TemplateSpec, apply_joint, dims_varset
from .timber import TimberError, new_timber

LIBRARY_DIR = Path(__file__).resolve().parents[2] / "library"

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


def _timber_bodies(doc):
    """Bodies with a Dims VarSet driving their base pad — valid joint
    targets, resolved structurally so renamed timbers still qualify."""
    return [o for o in doc.Objects
            if o.TypeId == "PartDesign::Body" and dims_varset(o) is not None]


class ApplyJointDialog(QtWidgets.QDialog):
    """Template + role assignment + joint ID + the parameter form —
    generated from the template's VarSet schema, no per-joint code."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.spec = None
        self.setWindowTitle("Apply Joint")
        layout = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QFormLayout()
        self.template_box = QtWidgets.QComboBox(self)
        for f in sorted(LIBRARY_DIR.glob("*.FCStd")):
            self.template_box.addItem(f.stem, str(f))
        self.template_box.currentIndexChanged.connect(self._load_template)
        top.addRow("Joint template:", self.template_box)
        self.joint_id = QtWidgets.QLineEdit(self)
        self.joint_id.setPlaceholderText("B2a")
        self.joint_id.setToolTip(
            "Joint instance ID — becomes Joint_<Kind>_<ID> and the "
            "suffix on every cloned feature (e.g. B2a for bent 2, joint a)")
        top.addRow("Joint ID:", self.joint_id)
        layout.addLayout(top)

        self.roles_form = QtWidgets.QFormLayout()
        layout.addLayout(self.roles_form)
        self.params_group = QtWidgets.QGroupBox("Parameters", self)
        self.params_form = QtWidgets.QFormLayout(self.params_group)
        layout.addWidget(self.params_group)

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
            QtWidgets.QMessageBox.warning(self, "Apply Joint", str(err))
            self.spec = None
            return

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
                    "Which long face receives this joint. Square-rule "
                    "faces: 1 and 2 are the reference faces on the XZ/YZ "
                    "origin planes; 3 and 4 are opposite them.")
                self.face_boxes[role] = face_box
                self.roles_form.addRow(f"{role} face:", face_box)
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
            if p["expression"]:
                note = QtWidgets.QLabel(f"= {p['expression']}   (tracks "
                                        f"the mating timber)", self)
                note.setToolTip(p["tooltip"])
                self.params_form.addRow(f"{p['name']}:", note)
                continue
            if p["type_id"] == "App::PropertyInteger":
                # counts (Peg_Count) are set by the template's geometry,
                # not per application; editable later on the VarSet's
                # Data tab if the applied joint is reworked
                note = QtWidgets.QLabel(f"{int(p['value'])}   (set by the "
                                        f"template)", self)
                note.setToolTip(p["tooltip"])
                self.params_form.addRow(f"{p['name']}:", note)
                continue
            field = _quantity_field(float(p["value"]))
            field.setToolTip(p["tooltip"])
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
            raw = field.property("rawValue")
            values[name] = App.Units.Quantity(f"{raw} mm")
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
            "MenuText": "Apply Joint",
            "ToolTip": "Apply a joint template between two timbers: clones "
                       "the template's cuts into both, driven by one shared "
                       "joint VarSet",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        dialog = ApplyJointDialog(doc, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                spec, joint_id, body_map, values, placement = dialog.request()
                doc.openTransaction(f"Apply joint {joint_id.strip()}")
                try:
                    varset = apply_joint(doc, spec, joint_id, body_map,
                                         values=values, placement=placement)
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except JointError as err:
                QtWidgets.QMessageBox.warning(dialog, "Apply Joint", str(err))
                continue
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(varset)
            return


def register():
    Gui.addCommand("BentWizard_NewTimber", NewTimberCommand())
    Gui.addCommand("BentWizard_ApplyJoint", ApplyJointCommand())


ALL_COMMANDS = ["BentWizard_NewTimber", "BentWizard_ApplyJoint"]
