"""GUI commands for the BentWizard workbench.

Imported only from init_gui (needs FreeCADGui and Qt). Core logic lives
in GUI-free modules (timber.py); commands here are thin wrappers:
dialog -> transaction -> core call -> report.
"""

from pathlib import Path

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from . import naming
from .apply_joint import (JointError, TemplateSpec, apply_joint,
                          create_preview, dims_varset, engagement_placement,
                          find_preview, joint_members, remove_joint,
                          remove_preview)
from .duplicate import (bent_joints, duplicate_bent, suggest_joint_ids,
                        suggest_member_labels)
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
    """Permanent name + section + length + optional position tag. Values
    persist across validation retries so the user fixes input instead of
    retyping it."""

    DEFAULTS = (203.2, 203.2, 2438.4)   # mm internally; displayed per schema

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Timber")
        form = QtWidgets.QFormLayout(self)
        self.member_id = QtWidgets.QLineEdit(self)
        self.member_id.setPlaceholderText("T-Post-001")
        self.member_id.setToolTip(
            "Permanent name: T-<Role>[-<Qualifier>]-<serial>, e.g. "
            "T-Post-Level1-003 — describes what the stick IS, never its "
            "position (that goes in the position tag below). Leave the "
            "serial off and the next free one is appended for you. Any "
            "unique label is accepted; the linter nudges as advisory.")
        form.addRow("Name:", self.member_id)
        self.fields = {}
        for label, default in zip(("Width", "Depth", "Length"), self.DEFAULTS):
            field = _quantity_field(default)
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

    def values(self):
        """(member_id, width, depth, length, position_tag)."""
        out = [self.member_id.text()]
        for name in ("Width", "Depth", "Length"):
            raw = self.fields[name].property("rawValue")
            out.append(App.Units.Quantity(f"{raw} mm"))
        out.append(self.position_tag.text())
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
    """Prompt for a joint instance VarSet, preselected from the current
    selection (its VarSet, or any joint member — the landing frame is
    3D-clickable, and member labels carry the joint's _Kind_ID suffix).
    Returns the VarSet, or None if cancelled / none present."""
    joints = [o for o in doc.Objects
              if o.TypeId == "App::VarSet"
              and naming.is_joint_varset_label(o.Label)]
    if not joints:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), title, "No joint instances in this document.")
        return None
    labels = [j.Label for j in joints]
    current = 0
    sel_labels = [o.Label for o in Gui.Selection.getSelection()]
    for i, joint in enumerate(joints):
        # member labels carry the joint label as a suffix: "_J-HousedMT-001"
        # (legacy members: "_MT_B2a", the label minus its "Joint" prefix)
        if joint.Label.startswith(naming.JOINT_PREFIX):
            suffix = "_" + joint.Label
        else:
            suffix = joint.Label.replace("Joint", "", 1)  # "_MT_B2a"
        if any(s == joint.Label or s.endswith(suffix) for s in sel_labels):
            current = i
            break
    label, ok = QtWidgets.QInputDialog.getItem(
        Gui.getMainWindow(), title, "Joint instance:", labels, current, False)
    if not ok:
        return None
    return joints[labels.index(label)]


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
            expr_edit = QtWidgets.QLineEdit(self)
            expr_edit.setPlaceholderText("<<VarSet>>.Property")
            expr_edit.setToolTip(p["tooltip"])
            expr_edit.hide()
            fx = QtWidgets.QToolButton(self)
            fx.setText("ƒx")
            fx.setCheckable(True)
            fx.setToolTip("Bind this parameter to an expression instead "
                          "of a value (e.g. <<Floor>>.Height)")
            fx.toggled.connect(
                lambda checked, f=field, e=expr_edit:
                (f.setVisible(not checked), e.setVisible(checked)))
            row = QtWidgets.QWidget(self)
            hbox = QtWidgets.QHBoxLayout(row)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.addWidget(field)
            hbox.addWidget(expr_edit)
            hbox.addWidget(fx)
            self.param_fields[p["name"]] = (field, expr_edit, fx)
            self.params_form.addRow(f"{p['name']}:", row)

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
        for name, (field, expr_edit, fx) in self.param_fields.items():
            if fx.isChecked():
                text = expr_edit.text().strip()
                if not text:
                    raise JointError(
                        f"{name}: expression entry is on but empty")
                values[name] = text        # applied as an expression
            else:
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


class RemoveJointCommand:
    def GetResources(self):
        return {
            "MenuText": "Remove Joint",
            "ToolTip": "Remove a joint instance completely: every cut, "
                       "sketch, and landing frame on both timbers, plus "
                       "the joint VarSet",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        varset = _pick_joint(doc, "Remove Joint")
        if varset is None:
            return
        label = varset.Label
        members = joint_members(varset)
        bodies = sorted({o.getParentGeoFeatureGroup().Label
                         for o in members if o.getParentGeoFeatureGroup()})
        answer = QtWidgets.QMessageBox.question(
            Gui.getMainWindow(), "Remove Joint",
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


class PreviewJointCommand:
    def GetResources(self):
        return {
            "MenuText": "Preview Mated Joint",
            "ToolTip": "Show both halves of a joint engaged (a ghost view "
                       "with the joint centered at the origin), to verify "
                       "fit — real timber placements are untouched. Run "
                       "again to clear.",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        varset = _pick_joint(doc, "Preview Mated Joint")
        if varset is None:
            return
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
                Gui.getMainWindow(), "Preview Mated Joint",
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


class DuplicateBentDialog(QtWidgets.QDialog):
    """New permanent names for the selected timbers and new serials for
    their joints, prefilled with the next free serial per name family
    (only the trailing serial changes — descriptive parts are never
    rewritten). Every row stays editable."""

    def __init__(self, doc, bodies, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.bodies = bodies
        self.setWindowTitle("Duplicate Bent")
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
        self.group_label = QtWidgets.QLineEdit(self)
        self.group_label.setPlaceholderText("e.g. Bent 2")
        self.group_label.setToolTip(
            "Optional: put the copies in a group of this name (created "
            "if absent) to keep the tree organized. Groups are pure "
            "organization — drag timbers between them freely.")
        extras.addRow("Add copies to group:", self.group_label)
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
        return (member_map, joint_ids,
                self.position_tag.text(), self.group_label.text())


class DuplicateBentCommand:
    def GetResources(self):
        return {
            "MenuText": "Duplicate Bent",
            "ToolTip": "Duplicate the selected timbers with their joints: "
                       "each copy owns its Dims and joint VarSets; group "
                       "bindings stay on the same shared VarSets",
        }

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        bodies = [o for o in Gui.Selection.getSelection()
                  if o in _timber_bodies(doc)]
        if not bodies:
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Duplicate Bent",
                "Select the timbers to duplicate first (their joints come "
                "along automatically when both mating timbers are selected).")
            return
        dialog = DuplicateBentDialog(doc, bodies, Gui.getMainWindow())
        while dialog.exec() == QtWidgets.QDialog.Accepted:
            try:
                member_map, joint_ids, tag, group = dialog.request()
                doc.openTransaction("Duplicate bent")
                try:
                    new_bodies, new_joints, skipped = duplicate_bent(
                        doc, member_map, joint_ids, LIBRARY_DIR,
                        position_tag=tag, group_label=group)
                except Exception:
                    doc.abortTransaction()
                    raise
                doc.commitTransaction()
            except JointError as err:
                QtWidgets.QMessageBox.warning(dialog, "Duplicate Bent",
                                              str(err))
                continue
            msg = (f"Created {len(new_bodies)} timber(s) and "
                   f"{len(new_joints)} joint(s).")
            if skipped:
                msg += f" Skipped (reach outside the set): {', '.join(skipped)}."
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Duplicate Bent", msg)
            return


def register():
    Gui.addCommand("BentWizard_NewTimber", NewTimberCommand())
    Gui.addCommand("BentWizard_ApplyJoint", ApplyJointCommand())
    Gui.addCommand("BentWizard_RemoveJoint", RemoveJointCommand())
    Gui.addCommand("BentWizard_PreviewJoint", PreviewJointCommand())
    Gui.addCommand("BentWizard_DuplicateBent", DuplicateBentCommand())


ALL_COMMANDS = ["BentWizard_NewTimber", "BentWizard_ApplyJoint",
                "BentWizard_RemoveJoint", "BentWizard_PreviewJoint",
                "BentWizard_DuplicateBent"]
