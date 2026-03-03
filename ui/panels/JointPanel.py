"""JointPanel — parameter editing panel for TimberJoint objects.

This is a pure QWidget with no FreeCAD task-panel coupling.  It can be
hosted inside a task dialog (via JointTaskPanel adapter) or embedded
directly in a persistent dock widget (ContextPanel, Phase 3).
"""

import json

from PySide2 import QtCore, QtWidgets

from joints.base import ParameterSet
from joints.loader import get_definition, get_ids
from ui.param_widgets import ParameterRow, format_param_name


# ---------------------------------------------------------------------------
# Validation level → indicator colour
# ---------------------------------------------------------------------------

_LEVEL_COLORS = {
    "error": "#e74c3c",
    "warning": "#f39c12",
    "info": "#3498db",
}


# ---------------------------------------------------------------------------
# JointPanel
# ---------------------------------------------------------------------------

class JointPanel(QtWidgets.QWidget):
    """Editable property panel for a single TimberJoint object.

    Parameters
    ----------
    obj : App::FeaturePython
        The TimberJoint document object to display and edit.
    parent : QWidget or None
        Optional parent widget.
    """

    def __init__(self, obj, parent=None):
        super().__init__(parent)
        self._obj = obj
        self._param_rows = {}       # name -> ParameterRow
        self._type_id_list = []     # parallel to combo box indices
        self._updating_type = False

        self._build_ui()
        self._populate()

    # ======================================================================
    # UI construction
    # ======================================================================

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # -- Joint header ---------------------------------------------------
        self._header_group = QtWidgets.QGroupBox("Joint")
        hdr = QtWidgets.QFormLayout(self._header_group)

        self._label_edit = QtWidgets.QLabel()
        hdr.addRow("Label:", self._label_edit)

        self._type_combo = QtWidgets.QComboBox()
        hdr.addRow("Type:", self._type_combo)

        root.addWidget(self._header_group)

        # -- Connection info (read-only) ------------------------------------
        self._conn_group = QtWidgets.QGroupBox("Connection")
        conn = QtWidgets.QFormLayout(self._conn_group)

        self._primary_label = QtWidgets.QLabel()
        conn.addRow("Primary:", self._primary_label)

        self._secondary_label = QtWidgets.QLabel()
        conn.addRow("Secondary:", self._secondary_label)

        self._itype_label = QtWidgets.QLabel()
        conn.addRow("Intersection:", self._itype_label)

        self._angle_label = QtWidgets.QLabel()
        conn.addRow("Angle:", self._angle_label)

        root.addWidget(self._conn_group)

        # -- Parameters (scrollable) ----------------------------------------
        self._params_scroll = QtWidgets.QScrollArea()
        self._params_scroll.setWidgetResizable(True)
        self._params_scroll.setMinimumHeight(160)
        self._params_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._params_container = QtWidgets.QWidget()
        self._params_layout = QtWidgets.QVBoxLayout(self._params_container)
        self._params_layout.setContentsMargins(0, 0, 0, 0)
        self._params_scroll.setWidget(self._params_container)
        root.addWidget(self._params_scroll, 1)

        # -- Validation -----------------------------------------------------
        self._validation_group = QtWidgets.QGroupBox("Validation")
        self._validation_layout = QtWidgets.QVBoxLayout(self._validation_group)
        self._validation_layout.setContentsMargins(4, 4, 4, 4)
        root.addWidget(self._validation_group)

        # -- Structural properties ------------------------------------------
        self._structural_group = QtWidgets.QGroupBox("Structural Properties")
        struct = QtWidgets.QFormLayout(self._structural_group)

        self._moment_label = QtWidgets.QLabel()
        struct.addRow("Allowable Moment:", self._moment_label)

        self._shear_label = QtWidgets.QLabel()
        struct.addRow("Allowable Shear:", self._shear_label)

        self._stiffness_label = QtWidgets.QLabel()
        struct.addRow("Rotational Stiffness:", self._stiffness_label)

        root.addWidget(self._structural_group)

        # -- Connect type combo signal --------------------------------------
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)

    # ======================================================================
    # Populate from object
    # ======================================================================

    def _populate(self):
        """Full refresh of every section from the current object."""
        obj = self._obj
        if obj is None:
            return

        # Header
        self._label_edit.setText(obj.Label)
        self._populate_type_combo()

        # Connection
        pm = obj.PrimaryMember
        sm = obj.SecondaryMember
        self._primary_label.setText(pm.Label if pm else "—")
        self._secondary_label.setText(sm.Label if sm else "—")
        self._itype_label.setText(str(obj.IntersectionType))
        self._angle_label.setText(f"{obj.IntersectionAngle:.1f}\u00b0")

        # Parameters
        self._rebuild_parameter_widgets()

        # Validation
        self._refresh_validation()

        # Structural
        self._refresh_structural()

    def _populate_type_combo(self):
        """Fill the joint type combo box with all registered definitions."""
        self._updating_type = True
        self._type_combo.clear()
        self._type_id_list = []

        current_id = str(self._obj.JointType)

        for jid in get_ids():
            defn = get_definition(jid)
            display = defn.NAME if defn and defn.NAME else jid
            self._type_combo.addItem(display)
            self._type_id_list.append(jid)

        # Select the current type.
        if current_id in self._type_id_list:
            self._type_combo.setCurrentIndex(
                self._type_id_list.index(current_id)
            )

        self._updating_type = False

    # ======================================================================
    # Parameter section
    # ======================================================================

    def _rebuild_parameter_widgets(self):
        """Destroy and recreate all parameter group boxes and rows."""
        # Clear existing widgets from the params layout.
        self._param_rows.clear()
        while self._params_layout.count():
            item = self._params_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        obj = self._obj
        if obj is None or not obj.Parameters:
            lbl = QtWidgets.QLabel("Parameters not yet computed.")
            lbl.setStyleSheet("color: #888888; font-style: italic;")
            self._params_layout.addWidget(lbl)
            return

        params = ParameterSet.from_json(obj.Parameters)
        if len(params) == 0:
            lbl = QtWidgets.QLabel("No parameters.")
            lbl.setStyleSheet("color: #888888; font-style: italic;")
            self._params_layout.addWidget(lbl)
            return

        # Group parameters by their group field, preserving definition order.
        groups = {}
        group_order = []
        for name, p in params.items():
            if p.group not in groups:
                groups[p.group] = []
                group_order.append(p.group)
            groups[p.group].append(p)

        for group_name in group_order:
            gbox = QtWidgets.QGroupBox(group_name)
            glayout = QtWidgets.QVBoxLayout(gbox)
            glayout.setContentsMargins(4, 4, 4, 4)
            glayout.setSpacing(2)

            for p in groups[group_name]:
                row = ParameterRow(p)
                row.value_changed.connect(self._on_param_value_changed)
                row.revert_requested.connect(self._on_param_revert)
                glayout.addWidget(row)
                self._param_rows[p.name] = row

            self._params_layout.addWidget(gbox)

        # Push remaining space to the bottom.
        self._params_layout.addStretch()

    def _refresh_parameter_values(self):
        """Update existing ParameterRow widgets from current obj.Parameters.

        Used after an external recompute changes derived defaults.
        """
        obj = self._obj
        if obj is None or not obj.Parameters:
            return

        params = ParameterSet.from_json(obj.Parameters)
        for name, p in params.items():
            row = self._param_rows.get(name)
            if row is not None:
                row.refresh(p)

    # ======================================================================
    # Validation section
    # ======================================================================

    def _refresh_validation(self):
        """Rebuild validation message rows from obj.ValidationResults."""
        # Clear existing.
        while self._validation_layout.count():
            item = self._validation_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        obj = self._obj
        results = []
        if obj is not None and obj.ValidationResults:
            try:
                results = json.loads(obj.ValidationResults)
            except (json.JSONDecodeError, TypeError):
                pass

        if not results:
            ok = QtWidgets.QLabel("\u2714 No issues found.")
            ok.setStyleSheet("color: #27ae60;")
            self._validation_layout.addWidget(ok)
            return

        for r in results:
            row_w = QtWidgets.QWidget()
            row_l = QtWidgets.QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 1, 0, 1)

            # Colour dot
            level = r.get("level", "info")
            colour = _LEVEL_COLORS.get(level, "#3498db")
            dot = QtWidgets.QLabel("\u25cf")
            dot.setStyleSheet(f"color: {colour}; font-size: 14px;")
            dot.setFixedWidth(18)
            row_l.addWidget(dot)

            # Message
            msg = QtWidgets.QLabel(r.get("message", ""))
            msg.setWordWrap(True)
            row_l.addWidget(msg, 1)

            self._validation_layout.addWidget(row_w)

    # ======================================================================
    # Structural properties section
    # ======================================================================

    def _refresh_structural(self):
        """Update structural property labels; hide section if all zero."""
        obj = self._obj
        if obj is None:
            self._structural_group.setVisible(False)
            return

        moment = obj.AllowableMoment
        shear = obj.AllowableShear
        stiffness = obj.RotationalStiffness

        if moment == 0.0 and shear == 0.0 and stiffness == 0.0:
            self._structural_group.setVisible(False)
            return

        self._structural_group.setVisible(True)
        self._moment_label.setText(f"{moment:,.0f} N\u00b7mm" if moment else "N/A")
        self._shear_label.setText(f"{shear:,.0f} N" if shear else "N/A")
        self._stiffness_label.setText(
            f"{stiffness:,.0f} N\u00b7mm/rad" if stiffness else "N/A"
        )

    # ======================================================================
    # Slot: joint type changed
    # ======================================================================

    def _on_type_changed(self, index):
        if self._updating_type or self._obj is None:
            return
        if index < 0 or index >= len(self._type_id_list):
            return

        new_id = self._type_id_list[index]
        if new_id == str(self._obj.JointType):
            return  # no change

        import FreeCAD
        doc = self._obj.Document

        doc.openTransaction("Change Joint Type")
        try:
            self._obj.JointType = new_id
        except Exception:
            doc.abortTransaction()
            return
        doc.commitTransaction()
        doc.recompute()

        # Rebuild parameter widgets for the new joint type.
        self._rebuild_parameter_widgets()
        self._refresh_validation()
        self._refresh_structural()

    # ======================================================================
    # Slot: parameter value edited
    # ======================================================================

    def _on_param_value_changed(self, name, value):
        obj = self._obj
        if obj is None or not obj.Parameters:
            return

        display_name = format_param_name(name)

        import FreeCAD
        doc = obj.Document

        doc.openTransaction(f"Edit Joint Parameter: {display_name}")
        try:
            params = ParameterSet.from_json(obj.Parameters)
            params.set_override(name, value)
            obj.Parameters = params.to_json()
            obj.touch()
        except Exception:
            doc.abortTransaction()
            return
        doc.commitTransaction()
        doc.recompute()

        # Refresh to pick up any clamped values or recomputed defaults.
        self._refresh_parameter_values()
        self._refresh_validation()
        self._refresh_structural()

    # ======================================================================
    # Slot: parameter revert
    # ======================================================================

    def _on_param_revert(self, name):
        obj = self._obj
        if obj is None or not obj.Parameters:
            return

        display_name = format_param_name(name)

        import FreeCAD
        doc = obj.Document

        doc.openTransaction(f"Revert Joint Parameter: {display_name}")
        try:
            params = ParameterSet.from_json(obj.Parameters)
            params.clear_override(name)
            obj.Parameters = params.to_json()
            obj.touch()
        except Exception:
            doc.abortTransaction()
            return
        doc.commitTransaction()
        doc.recompute()

        self._refresh_parameter_values()
        self._refresh_validation()
        self._refresh_structural()

    # ======================================================================
    # External notification
    # ======================================================================

    def notify_property_changed(self, prop):
        """Called by the ViewProvider when the joint recomputes externally.

        Parameters
        ----------
        prop : str
            The name of the property that changed.
        """
        if self._obj is None:
            return

        if prop in ("Parameters", "Shape"):
            self._refresh_parameter_values()
        if prop in ("ValidationResults", "Shape"):
            self._refresh_validation()
        if prop in ("AllowableMoment", "AllowableShear",
                     "RotationalStiffness", "Shape"):
            self._refresh_structural()
        if prop in ("IntersectionAngle", "IntersectionPoint"):
            self._angle_label.setText(
                f"{self._obj.IntersectionAngle:.1f}\u00b0"
            )
        if prop == "Label":
            self._label_edit.setText(self._obj.Label)

    # ======================================================================
    # Cleanup
    # ======================================================================

    def _disconnect(self):
        """Null out the object reference when the panel is closed."""
        self._obj = None

    def get_object(self):
        """Return the FreeCAD object this panel is editing, or None."""
        return self._obj
