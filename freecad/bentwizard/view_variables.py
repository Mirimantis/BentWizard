"""The Timber Variables panel — docked, GUI-only, read-only.

Follows the selection: select a timber (or anything in it) and the panel
lists what sets it; select a timber joint (its marker, VarSet, a
component or its Boolean) and it lists what sets the joint. The listing
itself is `variables`; this module only draws it.

Read-only in this round. A click on a row selects the object that holds
the value, so FreeCAD's Property view opens on it, where it is edited.
That selection is the panel's own and does not move the panel to a new
subject; nor does selecting something that is neither a timber nor a
timber joint (ProjectVars, a frame group), so the listing stays put
while the framer edits.

Nothing here is an object or a property: nothing is saved.
"""

from __future__ import annotations

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import variables

_OBJECT_NAME = "BentWizardTimberVariables"
_TITLE = "Timber Variables"
_PLACEHOLDER = "Select a timber or a timber joint."
_COLUMNS = ("", "Value", "Var. Location", "Also drives")

_PANEL = None


def _report(where, err):
    App.Console.PrintError(f"BentWizard: Timber Variables, {where}: "
                           f"{type(err).__name__}: {err}\n")


class _SelectionObserver:
    def __init__(self, panel):
        self.panel = panel

    def addSelection(self, *_args):
        self.panel.schedule_selection()

    def removeSelection(self, *_args):
        self.panel.schedule_selection()

    def setSelection(self, *_args):
        self.panel.schedule_selection()

    def clearSelection(self, *_args):
        pass                     # keep the listing: nothing new was picked


class _DocumentObserver:
    def __init__(self, panel):
        self.panel = panel

    def slotRecomputedDocument(self, doc):
        self.panel.document_changed(doc)

    def slotUndoDocument(self, doc):
        self.panel.document_changed(doc)

    def slotRedoDocument(self, doc):
        self.panel.document_changed(doc)

    def slotChangedObject(self, obj, prop):
        if prop == "Label":
            self.panel.document_changed(obj.Document)

    def slotDeletedObject(self, obj):
        self.panel.object_deleted(obj)

    def slotDeletedDocument(self, doc):
        self.panel.document_deleted(doc)


class VariablesPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._subject = None          # (document Name, object Name)
        self._own_selection = None    # what a row click selected
        self._targets = []            # per row: (document Name, object Name)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.title = QtWidgets.QLabel(self)
        font = self.title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.title.setFont(font)
        self.subtitle = QtWidgets.QLabel(self)
        self.subtitle.setForegroundRole(QtGui.QPalette.PlaceholderText)
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setColumnCount(len(_COLUMNS))
        self.tree.setHeaderLabels(list(_COLUMNS))
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setAlternatingRowColors(True)
        # widths fit the contents until the framer drags a column; from
        # then on their widths are kept across refreshes
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        self._sizing = False
        self._user_sized = False
        header.sectionResized.connect(self._column_resized)
        self.tree.itemClicked.connect(self._clicked)
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle)
        lay.addWidget(self.tree, 1)

        # selection and recompute signals arrive in bursts (one per object
        # selected, one per feature recomputed): coalesce them
        self._selection_timer = QtCore.QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(0)
        self._selection_timer.timeout.connect(self._selection_settled)
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(100)
        self._refresh_timer.timeout.connect(self.refresh)
        self._show_empty()

    # --- the subject --------------------------------------------------------

    def subject(self):
        if self._subject is None:
            return None
        doc = App.listDocuments().get(self._subject[0])
        return doc.getObject(self._subject[1]) if doc is not None else None

    def set_subject(self, obj):
        self._subject = (obj.Document.Name, obj.Name) if obj is not None else None
        self.refresh()

    # --- signals ------------------------------------------------------------

    def _active(self):
        dock = self.parent()
        return dock is not None and dock.isVisible()

    def schedule_selection(self):
        if self._active():
            self._selection_timer.start()

    def _selection_settled(self):
        try:
            picked = {(o.Document.Name, o.Name) for o in Gui.Selection.getSelection()}
            if self._own_selection is not None and picked == self._own_selection:
                return
            self._own_selection = None
            for obj in Gui.Selection.getSelection():
                subject = variables.subject_of(obj)
                if subject is not None:
                    self.set_subject(subject)
                    return
        except Exception as err:
            _report("selection", err)

    def document_changed(self, doc):
        if self._active() and self._subject and doc.Name == self._subject[0]:
            self._refresh_timer.start()

    def object_deleted(self, obj):
        try:
            if self._subject == (obj.Document.Name, obj.Name):
                self._subject = None
                self._show_empty()
            elif self._subject and obj.Document.Name == self._subject[0]:
                self._refresh_timer.start()
        except Exception as err:
            _report("deletion", err)

    def document_deleted(self, doc):
        if self._subject and doc.Name == self._subject[0]:
            self._subject = None
            self._show_empty()

    # --- drawing ------------------------------------------------------------

    def _show_empty(self):
        self.tree.clear()
        self._targets = []
        self.title.setText(_TITLE)
        self.subtitle.setText(_PLACEHOLDER)

    def refresh(self):
        subject = self.subject()
        if subject is None:
            self._subject = None
            self._show_empty()
            return
        try:
            listing = variables.listing_for(subject)
        except Exception as err:
            _report("listing", err)
            return
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        self._targets = []
        self.title.setText(listing.title)
        self.subtitle.setText(listing.subtitle)
        self.subtitle.setVisible(bool(listing.subtitle))
        for section in listing.sections:
            head = QtWidgets.QTreeWidgetItem(self.tree, [section.title])
            head.setFirstColumnSpanned(True)
            font = head.font(0)
            font.setBold(True)
            head.setFont(0, font)
            self._attach(head, section.target)
            for note in section.notes:
                item = QtWidgets.QTreeWidgetItem(head, [note])
                item.setFirstColumnSpanned(True)
                font = item.font(0)
                font.setItalic(True)
                item.setFont(0, font)
                item.setForeground(0, self.palette().brush(QtGui.QPalette.PlaceholderText))
                self._attach(item, None)
            for row in section.rows:
                item = QtWidgets.QTreeWidgetItem(
                    head, [row.label, row.value, row.set_by,
                           variables.drives_text(row.drives)])
                for col in range(len(_COLUMNS)):
                    item.setToolTip(col, row.tip)
                if row.drives:
                    item.setToolTip(3, "Also drives: " + ", ".join(row.drives))
                self._attach(item, row.target)
        self.tree.expandAll()
        if not self._user_sized:
            self._sizing = True
            try:
                for col in range(len(_COLUMNS) - 1):
                    self.tree.resizeColumnToContents(col)
            finally:
                self._sizing = False
        self.tree.verticalScrollBar().setValue(scroll)

    def _column_resized(self, col, _old, _new):
        # the last column stretches with the dock: not the framer's doing
        if not self._sizing and col < len(_COLUMNS) - 1:
            self._user_sized = True

    def _attach(self, item, target):
        item.setData(0, QtCore.Qt.UserRole, len(self._targets))
        self._targets.append((target.Document.Name, target.Name)
                             if target is not None else None)

    def _clicked(self, item, _column):
        try:
            index = item.data(0, QtCore.Qt.UserRole)
            if index is None or self._targets[index] is None:
                return
            doc_name, name = self._targets[index]
            doc = App.listDocuments().get(doc_name)
            obj = doc.getObject(name) if doc is not None else None
            if obj is None:
                return
            # the panel's own selection: it must not move the panel
            self._own_selection = {(doc_name, name)}
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj)
        except Exception as err:
            _report("click", err)


def show():
    """Open the panel (once per session), raise it, and list what the
    current selection belongs to."""
    global _PANEL
    mw = Gui.getMainWindow()
    dock = mw.findChild(QtWidgets.QDockWidget, _OBJECT_NAME)
    if dock is None or _PANEL is None:
        dock = QtWidgets.QDockWidget(_TITLE, mw)
        dock.setObjectName(_OBJECT_NAME)
        _PANEL = VariablesPanel(dock)
        dock.setWidget(_PANEL)
        mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        _PANEL._observers = (_SelectionObserver(_PANEL), _DocumentObserver(_PANEL))
        Gui.Selection.addObserver(_PANEL._observers[0])
        App.addDocumentObserver(_PANEL._observers[1])
    dock.show()
    dock.raise_()
    _PANEL.schedule_selection()
    return _PANEL
