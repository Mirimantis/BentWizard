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
        obj = self._obj
        if obj is None:
            return

        self._refreshing = True
        try:
            self._name_edit.setText(obj.BentName)
            self._number_spin.setValue(obj.BentNumber)
            self._template_label.setText(obj.BentTemplate or "None")
        finally:
            self._refreshing = False

        self._refresh_member_list()

    def _refresh_member_list(self):
        """Rebuild the member list widget from current Members property."""
        self._member_list.clear()
        obj = self._obj
        if obj is None:
            return

        members = obj.Members or []
        self._member_count_label.setText(f"{len(members)} member(s)")

        for m in members:
            role = str(getattr(m, "Role", "?"))
            mid = getattr(m, "MemberID", "") or m.Label
            self._member_list.addItem(f"{mid}  ({role})")

    # ======================================================================
    # Slot: bent name changed
    # ======================================================================

    def _on_name_changed(self):
        if self._refreshing or self._obj is None:
            return
        new_name = self._name_edit.text()
        if new_name == self._obj.BentName:
            return

        import FreeCAD
        doc = self._obj.Document
        doc.openTransaction("Rename Bent")
        self._obj.BentName = new_name
        doc.commitTransaction()

    # ======================================================================
    # Slot: bent number changed
    # ======================================================================

    def _on_number_changed(self):
        if self._refreshing or self._obj is None:
            return
        new_num = self._number_spin.value()
        if new_num == self._obj.BentNumber:
            return

        import FreeCAD
        from objects.Bent import Bent

        doc = self._obj.Document
        doc.openTransaction("Change Bent Number")
        self._obj.BentNumber = new_num
        Bent.assign_member_ids(self._obj)
        doc.commitTransaction()
        doc.recompute()
        self._refresh_member_list()

    # ======================================================================
    # Slot: member list double-click
    # ======================================================================

    def _on_member_double_clicked(self, item):
        """Select the member in the 3D viewport."""
        if self._obj is None:
            return
        row = self._member_list.row(item)
        members = self._obj.Members or []
        if 0 <= row < len(members):
            import FreeCADGui
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(members[row])

    # ======================================================================
    # Slot: add selected members
    # ======================================================================

    def _on_add_members(self):
        """Add currently-selected TimberMember objects to this bent."""
        if self._obj is None:
            return

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
        except Exception as e:
            FreeCAD.Console.PrintError(f"Failed to add members: {e}\n")
        finally:
            doc.commitTransaction()
            doc.recompute()

        self._refresh_member_list()

    # ======================================================================
    # Slot: remove selected member
    # ======================================================================

    def _on_remove_member(self):
        """Remove the highlighted member from this bent."""
        if self._obj is None:
            return

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
        except Exception as e:
            FreeCAD.Console.PrintError(f"Failed to remove member: {e}\n")
        finally:
            doc.commitTransaction()
            doc.recompute()

        self._refresh_member_list()

    # ======================================================================
    # External notification
    # ======================================================================

    def notify_property_changed(self, prop):
        """Called by the ViewProvider when the bent recomputes externally.

        Parameters
        ----------
        prop : str
            The name of the property that changed.
        """
        if self._obj is None:
            return

        if prop in ("Members", "MemberCount", "Shape"):
            self._refresh_member_list()
        if prop == "BentName":
            self._refreshing = True
            self._name_edit.setText(self._obj.BentName)
            self._refreshing = False
        if prop == "BentNumber":
            self._refreshing = True
            self._number_spin.setValue(self._obj.BentNumber)
            self._refreshing = False

    # ======================================================================
    # Cleanup
    # ======================================================================

    def _disconnect(self):
        """Null out the object reference when the panel is closed."""
        self._obj = None

    def get_object(self):
        """Return the FreeCAD object this panel is editing, or None."""
        return self._obj
