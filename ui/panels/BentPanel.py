"""BentPanel — property editing panel for Bent objects.

This is a pure QWidget with no FreeCAD task-panel coupling.  It can be
hosted inside a task dialog (via BentTaskPanel adapter) or embedded
directly in a persistent dock widget (ContextPanel, Phase 3).
"""

from PySide2 import QtCore, QtWidgets


class BentPanel(QtWidgets.QWidget):
    """Editable property panel for a single Bent object.

    Parameters
    ----------
    obj : Part::FeaturePython
        The Bent document object to display and edit.
    parent : QWidget or None
        Optional parent widget.
    """

    def __init__(self, obj, parent=None):
        super().__init__(parent)
        self._obj = obj
        self._refreshing = False

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
            "BentPanel: object no longer valid, closing panel\n"
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

        # -- Bent header ----------------------------------------------------
        self._header_group = QtWidgets.QGroupBox("Bent")
        hdr = QtWidgets.QFormLayout(self._header_group)

        self._name_edit = QtWidgets.QLineEdit()
        self._name_edit.setPlaceholderText("e.g. King Post, End Wall")
        self._name_edit.editingFinished.connect(self._on_name_changed)
        hdr.addRow("Name:", self._name_edit)

        self._number_spin = QtWidgets.QSpinBox()
        self._number_spin.setMinimum(0)
        self._number_spin.setMaximum(999)
        self._number_spin.setSpecialValueText("Unassigned")
        self._number_spin.editingFinished.connect(self._on_number_changed)
        hdr.addRow("Bent Number:", self._number_spin)

        self._template_label = QtWidgets.QLabel()
        self._template_label.setStyleSheet("color: #888888; font-style: italic;")
        hdr.addRow("Template:", self._template_label)

        root.addWidget(self._header_group)

        # -- Members list ---------------------------------------------------
        self._members_group = QtWidgets.QGroupBox("Members")
        mem_layout = QtWidgets.QVBoxLayout(self._members_group)

        self._member_count_label = QtWidgets.QLabel()
        mem_layout.addWidget(self._member_count_label)

        self._member_list = QtWidgets.QListWidget()
        self._member_list.setMinimumHeight(120)
        self._member_list.itemDoubleClicked.connect(
            self._on_member_double_clicked
        )
        mem_layout.addWidget(self._member_list, 1)

        # Add / Remove buttons
        btn_row = QtWidgets.QHBoxLayout()

        self._add_btn = QtWidgets.QPushButton("Add Selected")
        self._add_btn.setToolTip(
            "Add currently-selected timber members to this bent"
        )
        self._add_btn.clicked.connect(self._on_add_members)
        btn_row.addWidget(self._add_btn)

        self._remove_btn = QtWidgets.QPushButton("Remove")
        self._remove_btn.setToolTip(
            "Remove the highlighted member from this bent"
        )
        self._remove_btn.clicked.connect(self._on_remove_member)
        btn_row.addWidget(self._remove_btn)

        mem_layout.addLayout(btn_row)
        root.addWidget(self._members_group, 1)

        root.addStretch()

    # ======================================================================
    # Populate from object
    # ======================================================================

    def _populate(self):
        """Full refresh of every section from the current object."""
        if not self._obj_valid():
            return

        try:
            self._refreshing = True
            self._name_edit.setText(self._obj.BentName)
            self._number_spin.setValue(self._obj.BentNumber)
            self._template_label.setText(self._obj.BentTemplate or "None")
        except Exception:
            self._invalidate()
            return
        finally:
            self._refreshing = False

        self._refresh_member_list()

    def _refresh_member_list(self):
        """Rebuild the member list widget from current Members property."""
        self._member_list.clear()
        if not self._obj_valid():
            return

        try:
            members = self._obj.Members or []
        except Exception:
            self._invalidate()
            return

        self._member_count_label.setText(f"{len(members)} member(s)")

        for m in members:
            try:
                role = str(getattr(m, "Role", "?"))
                mid = getattr(m, "MemberID", "") or m.Label
            except Exception:
                role = "?"
                mid = "???"
            self._member_list.addItem(f"{mid}  ({role})")

    # ======================================================================
    # Slot: bent name changed
    # ======================================================================

    def _on_name_changed(self):
        if self._refreshing or not self._obj_valid():
            return
        try:
            new_name = self._name_edit.text()
            if new_name == self._obj.BentName:
                return

            import FreeCAD
            doc = self._obj.Document
            doc.openTransaction("Rename Bent")
            self._obj.BentName = new_name
            doc.commitTransaction()
        except Exception:
            self._invalidate()

    # ======================================================================
    # Slot: bent number changed
    # ======================================================================

    def _on_number_changed(self):
        if self._refreshing or not self._obj_valid():
            return
        try:
            new_num = self._number_spin.value()
            if new_num == self._obj.BentNumber:
                return

            import FreeCAD
            from objects.Bent import Bent

            doc = self._obj.Document
            doc.openTransaction("Change Bent Number")
            self._obj.BentNumber = new_num
            Bent.assign_member_ids(self._obj)
            doc.recompute()
            doc.commitTransaction()
            self._refresh_member_list()
        except Exception:
            self._invalidate()

    # ======================================================================
    # Slot: member list double-click
    # ======================================================================

    def _on_member_double_clicked(self, item):
        """Select the member in the 3D viewport."""
        if not self._obj_valid():
            return
        try:
            row = self._member_list.row(item)
            members = self._obj.Members or []
            if 0 <= row < len(members):
                import FreeCADGui
                FreeCADGui.Selection.clearSelection()
                FreeCADGui.Selection.addSelection(members[row])
        except Exception:
            self._invalidate()

    # ======================================================================
    # Slot: add selected members
    # ======================================================================

    def _on_add_members(self):
        """Add currently-selected TimberMember objects to this bent."""
        if not self._obj_valid():
            return

        try:
            import FreeCAD
            import FreeCADGui
            from objects.Bent import Bent

            sel = FreeCADGui.Selection.getSelection()
            members_to_add = []
            current = self._obj.Members or []
            for s in sel:
                if (hasattr(s, "Proxy") and s.Proxy is not None
                        and type(s.Proxy).__name__ == "TimberMember"
                        and s not in current):
                    members_to_add.append(s)

            if not members_to_add:
                return

            doc = self._obj.Document
            doc.openTransaction("Add Members to Bent")
            try:
                for m in members_to_add:
                    Bent.add_member(self._obj, m)
                doc.recompute()
            except Exception as e:
                FreeCAD.Console.PrintError(f"Failed to add members: {e}\n")
            finally:
                doc.commitTransaction()

            self._refresh_member_list()
        except Exception:
            self._invalidate()

    # ======================================================================
    # Slot: remove selected member
    # ======================================================================

    def _on_remove_member(self):
        """Remove the highlighted member from this bent."""
        if not self._obj_valid():
            return

        try:
            row = self._member_list.currentRow()
            members = self._obj.Members or []
            if row < 0 or row >= len(members):
                return

            import FreeCAD
            from objects.Bent import Bent

            doc = self._obj.Document
            doc.openTransaction("Remove Member from Bent")
            try:
                Bent.remove_member(self._obj, members[row])
                doc.recompute()
            except Exception as e:
                FreeCAD.Console.PrintError(
                    f"Failed to remove member: {e}\n"
                )
            finally:
                doc.commitTransaction()

            self._refresh_member_list()
        except Exception:
            self._invalidate()

    # ======================================================================
    # External notification
    # ======================================================================

    def notify_property_changed(self, prop):
        """Called by the ViewProvider when the bent recomputes externally.

        Uses a deferred refresh for the member list so that when undo
        restores multiple properties (Members + child MemberIDs), all
        restorations complete before we re-read the data.

        Parameters
        ----------
        prop : str
            The name of the property that changed.
        """
        if not self._obj_valid():
            return

        try:
            if prop in ("Members", "MemberCount", "Shape"):
                # Defer so all undo property restorations complete first.
                QtCore.QTimer.singleShot(0, self._deferred_refresh)
            if prop == "BentName":
                self._refreshing = True
                self._name_edit.setText(self._obj.BentName)
                self._refreshing = False
            if prop == "BentNumber":
                self._refreshing = True
                self._number_spin.setValue(self._obj.BentNumber)
                self._refreshing = False
        except Exception:
            self._invalidate()

    def _deferred_refresh(self):
        """Refresh member list and trigger recompute if Shape is stale.

        Called via QTimer.singleShot(0, ...) so all undo property
        restorations complete before we read back.
        """
        if not self._obj_valid():
            return
        self._refresh_member_list()
        # After undo, the Shape may be stale if it wasn't captured in the
        # original transaction.  Recompute to sync wireframe to Members.
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
