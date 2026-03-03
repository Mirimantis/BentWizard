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
    # Object validity
    # ======================================================================

    def _obj_valid(self):
        """Return True if the wrapped FreeCAD object still exists.

        When undo removes the object from the document, accessing
        properties on the stale Python reference may raise RuntimeError,
        ReferenceError, or OSError (Access Violation).  This guard
        catches all of those and nulls the reference so subsequent
        calls are cheap no-ops.

        Note: even if this returns True, the object can become invalid
        between the check and the next property access (zombie state).
        All handlers must therefore also wrap property access in
        try/except as a safety net.
        """
        if self._obj is None:
            return False
        try:
            _ = self._obj.Name
            return True
        except Exception:
            self._obj = None
            return False

    def _invalidate(self):
        """Mark the object as gone and close the task dialog."""
        self._obj = None
        import FreeCAD
        FreeCAD.Console.PrintWarning(
            "JointPanel: object no longer valid, closing panel\n"
        )
        # Schedule dialog close on next event loop tick so we don't
        # close from inside a callback that FreeCAD is still processing.
        QtCore.QTimer.singleShot(0, self._close_dialog)

    @staticmethod
    def _close_dialog():
        """Close the FreeCAD task dialog if one is open."""
        try:
            import FreeCADGui
            FreeCADGui.Control.closeDialog()
        except Exception:
            pass

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
        if not self._obj_valid():
            return

        try:
            # Header
            self._label_edit.setText(self._obj.Label)
            self._populate_type_combo()

            # Connection
            pm = self._obj.PrimaryMember
            sm = self._obj.SecondaryMember
            self._primary_label.setText(pm.Label if pm else "—")
            self._secondary_label.setText(sm.Label if sm else "—")
            self._itype_label.setText(str(self._obj.IntersectionType))
            self._angle_label.setText(
                f"{self._obj.IntersectionAngle:.1f}\u00b0"
            )

            # Parameters
            self._rebuild_parameter_widgets()

            # Validation
            self._refresh_validation()

            # Structural
            self._refresh_structural()
        except Exception:
            self._invalidate()

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

        if not self._obj_valid() or not self._obj.Parameters:
            lbl = QtWidgets.QLabel("Parameters not yet computed.")
            lbl.setStyleSheet("color: #888888; font-style: italic;")
            self._params_layout.addWidget(lbl)
            return

        params = ParameterSet.from_json(self._obj.Parameters)
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
        if not self._obj_valid() or not self._obj.Parameters:
            return

        try:
            params = ParameterSet.from_json(self._obj.Parameters)
            for name, p in params.items():
                row = self._param_rows.get(name)
                if row is not None:
                    row.refresh(p)
        except Exception:
            self._invalidate()

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

        results = []
        if self._obj_valid():
            try:
                vr = self._obj.ValidationResults
                if vr:
                    results = json.loads(vr)
            except Exception:
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
        if not self._obj_valid():
            self._structural_group.setVisible(False)
            return

        try:
            moment = self._obj.AllowableMoment
            shear = self._obj.AllowableShear
            stiffness = self._obj.RotationalStiffness
        except Exception:
            self._invalidate()
            self._structural_group.setVisible(False)
            return

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
        if self._updating_type or not self._obj_valid():
            return
        if index < 0 or index >= len(self._type_id_list):
            return

        try:
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
            doc.recompute()
            doc.commitTransaction()

            # Rebuild parameter widgets for the new joint type.
            self._rebuild_parameter_widgets()
            self._refresh_validation()
            self._refresh_structural()
        except Exception:
            self._invalidate()

    # ======================================================================
    # Slot: parameter value edited
    # ======================================================================

    def _on_param_value_changed(self, name, value):
        if not self._obj_valid() or not self._obj.Parameters:
            return

        try:
            display_name = format_param_name(name)

            import FreeCAD
            doc = self._obj.Document

            doc.openTransaction(f"Edit Joint Parameter: {display_name}")
            try:
                params = ParameterSet.from_json(self._obj.Parameters)
                params.set_override(name, value)
                self._obj.Parameters = params.to_json()
                self._obj.touch()
            except Exception:
                doc.abortTransaction()
                return
            doc.recompute()
            doc.commitTransaction()

            # Refresh to pick up any clamped values or recomputed defaults.
            self._refresh_parameter_values()
            self._refresh_validation()
            self._refresh_structural()
        except Exception:
            self._invalidate()

    # ======================================================================
    # Slot: parameter revert
    # ======================================================================

    def _on_param_revert(self, name):
        if not self._obj_valid() or not self._obj.Parameters:
            return

        try:
            display_name = format_param_name(name)

            import FreeCAD
            doc = self._obj.Document

            doc.openTransaction(f"Revert Joint Parameter: {display_name}")
            try:
                params = ParameterSet.from_json(self._obj.Parameters)
                params.clear_override(name)
                self._obj.Parameters = params.to_json()
                self._obj.touch()
            except Exception:
                doc.abortTransaction()
                return
            doc.recompute()
            doc.commitTransaction()

            self._refresh_parameter_values()
            self._refresh_validation()
            self._refresh_structural()
        except Exception:
            self._invalidate()

    # ======================================================================
    # External notification
    # ======================================================================

    def notify_property_changed(self, prop):
        """Called by the ViewProvider when the joint recomputes externally.

        Uses a deferred refresh so that when undo restores multiple
        properties (Parameters, Shape, cut tools), all restorations
        complete before we re-read the data and trigger any recompute.

        Parameters
        ----------
        prop : str
            The name of the property that changed.
        """
        if not self._obj_valid():
            return

        try:
            if prop in ("Parameters", "Shape"):
                # Defer so all undo restorations complete first, then
                # refresh values and trigger recompute if geometry is stale.
                QtCore.QTimer.singleShot(0, self._deferred_refresh)
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
        except Exception:
            self._invalidate()

    def _deferred_refresh(self):
        """Refresh parameter values and sync geometry after undo.

        Called via QTimer.singleShot(0, ...) so all undo property
        restorations complete before we read back.
        """
        if not self._obj_valid():
            return
        self._refresh_parameter_values()
        # After undo, geometry may be stale if the original transaction
        # didn't capture computed shapes.  Recompute to sync.
        try:
            self._obj.Document.recompute()
        except Exception:
            pass

    # ======================================================================
    # Cleanup
    # ======================================================================

    def _disconnect(self):
        """Null out the object reference when the panel is closed."""
        self._obj = None

    def get_object(self):
        """Return the FreeCAD object this panel is editing, or None."""
        return self._obj
