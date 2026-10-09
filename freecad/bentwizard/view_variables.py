"""The Timber Variables panel — docked, GUI-only, read-only.

Follows the selection: select a timber (or anything in it) and the panel
lists what sets it; select a timber joint (its marker, VarSet, a
component or its Boolean) and it lists what sets the joint. The listing
itself is `variables`; this module only draws it.

A click on a row selects the object that holds the value, so FreeCAD's
Property view opens on it. That selection is the panel's own and does
not move the panel to a new subject.

The listing is sticky (Adam, 2026-10-08): it changes only when another
timber or timber joint is selected, so a framer can browse the tree and
open a VarSet with the values still in view. Whenever nothing selected
belongs to what it lists — ProjectVars picked in the tree, a click on
empty space — a line under the title says so, so a listing is never
mistaken for the selection's, and the name in the title becomes a link
that selects the timber or timber joint again (a joint by its handle, so
its marker shows where it is).

A value that comes through bindings has an expand arrow: the chain,
step by step from the property the row reads to where the value is
typed, each step a click away from being selected in the tree. That is
how a binding is cut loose — on purpose, in the Property view — and
never from a double-click here (Adam, 2026-10-07).

A double-click edits the value in place: the variable at the row's Var.
Location (`variables.edit`), in one undoable transaction, recomputed at
once. The status line under the list says what changed and what else it
drives, and warns when the recompute broke something: an object in
error, or a timber that is no longer one solid.

Nothing here is an object or a property: nothing is saved.
"""

from __future__ import annotations

import html

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import variables

_OBJECT_NAME = "BentWizardTimberVariables"
_TITLE = "Timber Variables"
_PLACEHOLDER = "Select a timber or a timber joint."
_COLUMNS = ("", "Value", "Var. Location", "Also drives")

_PANEL = None
_ERROR_STYLE = "color: #c0392b;"
# amber, legible on the light and dark themes alike
_NOT_SELECTED_STYLE = "color: #c27c0e; font-style: italic;"


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
        self.panel.schedule_selection()


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


def _unchanged(value, original):
    """True when an editor closes on the value it opened with — leaving a
    field must not cost a transaction and a recompute."""
    if isinstance(value, str) or isinstance(original, str):
        return (isinstance(value, str) and isinstance(original, str)
                and value.replace(" ", "") == original.replace(" ", ""))
    if isinstance(value, bool) or isinstance(original, bool):
        return value == original
    try:
        return abs(float(value) - float(original)) < 1e-9
    except (TypeError, ValueError):
        return value == original


class _ValueDelegate(QtWidgets.QStyledItemDelegate):
    """Edits the Value column: the variable at the row's Var. Location.
    A quantity or a formula gets the dialogs' dimension field
    (`commands._DimField`): FreeCAD's own spin box in the framer's unit
    schema, and 'ƒx' or a typed '=' for an expression, autocompleting
    over the project's variable sets, with '+' to store a new one."""

    def __init__(self, panel):
        super().__init__(panel.tree)
        self.panel = panel
        # Qt owns the open editor, but nothing on the Python side held
        # it: the dimension field's Python half (its `spin`, its '='
        # filter) could be collected while the editor was still open,
        # leaving "Internal C++ object already deleted" on the next
        # keystroke. Held here until Qt destroys it.
        self._open = None
        # a plain editor commits when it loses focus, but the dimension
        # field never has focus itself (its spin box or expression box
        # does), so Qt never sees it leave: clicking away dropped the edit
        # (Adam's GUI round, 2026-10-08). Watch where focus goes instead.
        QtWidgets.QApplication.instance().focusChanged.connect(self._focus_moved)

    def _focus_moved(self, _old, new):
        editor = self._open
        if editor is None or new is None or not hasattr(editor, "fx"):
            return
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return                  # the '+' dialog, opened from the field
        if new.window().windowType() == QtCore.Qt.Popup:
            return                  # the autocomplete list
        if editor.isAncestorOf(new):
            return
        self._finish(editor)

    def destroyEditor(self, editor, index):
        if editor is self._open:
            self._open = None
        super().destroyEditor(editor, index)

    def createEditor(self, parent, option, index):
        editor = self._create(parent, index)
        self._open = editor
        return editor

    def _create(self, parent, index):
        row = self.panel.row_at(index)
        if index.column() != 1 or row is None:
            return None
        target = variables.editable(row.source)
        if target is None:
            return None
        obj, prop = target
        type_id = obj.getTypeIdOfProperty(prop)
        value = getattr(obj, prop)
        if type_id in variables.QUANTITY_UNITS:
            from .commands import _DimField
            unit = variables.QUANTITY_UNITS[type_id]
            raw = float(value.getValueAs(unit))
            # the project layer only, as in the dialogs: a value binds to
            # a shared variable, never to a timber's Dims or a joint's own
            editor = _DimField(raw, obj.Document, None, include_dims=False,
                               include_joints=False, unit=unit)
            expr = variables.expression_of(obj, prop)
            if expr:
                editor.set_expression(expr)
                original = "=" + expr
            else:
                original = editor.value()
            editor.setParent(parent)
            editor.setAutoFillBackground(True)
            editor.spin.lineEdit().returnPressed.connect(lambda: self._finish(editor))
            editor.expr.returnPressed.connect(lambda: self._finish(editor))
        elif row.source.kind == variables.FORMULA:
            editor = QtWidgets.QLineEdit(parent)
            original = "=" + (variables.expression_of(obj, prop) or "")
            editor.setText(original)
        elif type_id == "App::PropertyInteger":
            editor = QtWidgets.QSpinBox(parent)
            editor.setRange(-1000000, 1000000)
            original = int(value)
            editor.setValue(original)
        elif type_id == "App::PropertyFloat":
            editor = QtWidgets.QDoubleSpinBox(parent)
            editor.setRange(-1e12, 1e12)
            editor.setDecimals(6)
            original = float(value)
            editor.setValue(original)
        elif type_id == "App::PropertyBool":
            editor = QtWidgets.QComboBox(parent)
            editor.addItems(["yes", "no"])
            original = bool(value)
            editor.setCurrentIndex(0 if original else 1)
        else:
            editor = QtWidgets.QLineEdit(parent)
            original = str(value)
            editor.setText(original)
        editor._bw_original = original
        return editor

    def setEditorData(self, _editor, _index):
        pass                     # filled once, in createEditor

    def _finish(self, editor):
        """Enter in either half of a dimension field commits it. The
        view would only see the key if the child passed it up."""
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QtWidgets.QAbstractItemDelegate.NoHint)

    def setModelData(self, editor, _model, index):
        row = self.panel.row_at(index)
        if row is None or getattr(editor, "_bw_done", False):
            return
        editor._bw_done = True          # Enter can reach here twice
        if hasattr(editor, "fx"):       # commands._DimField
            value = editor.value()      # a Quantity, or '=expression'
        elif isinstance(editor, QtWidgets.QLineEdit):
            value = editor.text()
        elif isinstance(editor, QtWidgets.QComboBox):
            value = editor.currentIndex() == 0
        elif isinstance(editor, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            value = editor.value()
        else:
            return
        if _unchanged(value, getattr(editor, "_bw_original", None)):
            return
        # the list is rebuilt after the recompute, so nothing is written
        # into the model: the document is the only store. Deferred, so the
        # editor has closed before the transaction runs.
        QtCore.QTimer.singleShot(0, lambda: self.panel.commit_edit(row, value))

    def updateEditorGeometry(self, editor, option, _index):
        # the Value column is sized to its values, far too narrow for a
        # field with an expression box, 'ƒx' and '+': run the editor on
        # over Var. Location (which it is editing anyway), within the view
        tree = self.panel.tree
        rect = QtCore.QRect(option.rect)
        across = tree.columnViewportPosition(2) + tree.columnWidth(2) - rect.left()
        wanted = max(rect.width(), across, editor.sizeHint().width(), 280)
        rect.setWidth(min(wanted, tree.viewport().width() - rect.left()))
        rect.setHeight(max(rect.height(), editor.sizeHint().height()))
        editor.setGeometry(rect)


class VariablesPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._subject = None          # (document Name, object Name)
        self._own_selection = None    # what a row click selected
        self._targets = []            # per row: (document Name, object Name)
        self._rows = []               # per tree item: its variables.Row, or None
        self._open_chains = set()     # (section title, row label) shown expanded

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.title = QtWidgets.QLabel(self)
        font = self.title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.title.setFont(font)
        self._title_text = _TITLE
        self.title.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse)
        self.title.linkActivated.connect(self._reselect)
        self.subtitle = QtWidgets.QLabel(self)
        self.subtitle.setForegroundRole(QtGui.QPalette.PlaceholderText)
        self.not_selected = QtWidgets.QLabel(self)
        self.not_selected.setWordWrap(True)
        self.not_selected.setStyleSheet(_NOT_SELECTED_STYLE)
        self.not_selected.hide()
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
        self.tree.setItemDelegateForColumn(1, _ValueDelegate(self))
        self.tree.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked
                                  | QtWidgets.QAbstractItemView.EditKeyPressed)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.tree.itemExpanded.connect(lambda item: self._chain_toggled(item, True))
        self.tree.itemCollapsed.connect(lambda item: self._chain_toggled(item, False))
        self.status = QtWidgets.QLabel(self)
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.status.hide()
        lay.addWidget(self.title)
        lay.addWidget(self.subtitle)
        lay.addWidget(self.not_selected)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.status)

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
        new = (obj.Document.Name, obj.Name) if obj is not None else None
        if new != self._subject:
            self._say("")
        self._subject = new
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
            selection = Gui.Selection.getSelection()
            subjects = [variables.subject_of(o) for o in selection]
            picked = {(o.Document.Name, o.Name) for o in selection}
            if self._own_selection is None or picked != self._own_selection:
                self._own_selection = None
                subject = next((s for s in subjects if s is not None), None)
                if subject is not None:
                    self.set_subject(subject)
            self._mark_selected(subjects)
        except Exception as err:
            _report("selection", err)

    def _mark_selected(self, subjects):
        """Say so when nothing selected belongs to what the panel lists,
        and make its name a link that selects it again."""
        current = self.subject()
        selected = current is None or any(
            s is not None and s.Name == current.Name and s.Document is current.Document
            for s in subjects)
        if selected:
            self.not_selected.hide()
        else:
            self.not_selected.setText("Not selected. Click to re-select.")
            self.not_selected.show()
        self._draw_title()

    def _set_title(self, text):
        self._title_text = text
        self._draw_title()

    def _draw_title(self):
        """The title as plain text, or as a link while the subject is not
        selected."""
        if not self.not_selected.isHidden() and self.subject() is not None:
            self.title.setTextFormat(QtCore.Qt.RichText)
            self.title.setText(f'<a href="reselect">{html.escape(self._title_text)}</a>')
            self.title.setToolTip("Select it again.")
        else:
            self.title.setTextFormat(QtCore.Qt.PlainText)
            self.title.setText(self._title_text)
            self.title.setToolTip("")

    def _reselect(self, _link=None):
        """Select the listed timber (its Body) or timber joint again — the
        panel then follows it as any selection. A joint is selected by its
        handle, so its marker lights up where it sits in the 3D view: the
        panel already shows its parameters (Adam, 2026-10-08). Its VarSet
        when it has no handle."""
        try:
            subject = self.subject()
            if subject is None:
                return
            if subject.TypeId == "App::VarSet":
                from . import joint_handle
                subject = joint_handle.find_handle(subject) or subject
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(subject)
        except Exception as err:
            _report("re-select", err)

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
        self._rows = []
        self.not_selected.hide()
        self._set_title(_TITLE)
        self.subtitle.setText(_PLACEHOLDER)
        self.subtitle.setVisible(True)

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
        self._rows = []
        self._set_title(listing.title)
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
                tip = row.tip
                if variables.editable(row.source) is not None:
                    item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
                    tip += "\nDouble-click to edit."
                    if row.drives:
                        tip += " Editing it changes every timber it also drives."
                for col in range(len(_COLUMNS)):
                    item.setToolTip(col, tip)
                if row.drives:
                    item.setToolTip(3, "Also drives: " + ", ".join(row.drives))
                self._attach(item, row.target, row)
                if self._add_chain(item, row) and \
                        (section.title, row.label) in self._open_chains:
                    item.setExpanded(True)
            head.setExpanded(True)
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

    def _attach(self, item, target, row=None):
        item.setData(0, QtCore.Qt.UserRole, len(self._targets))
        self._targets.append((target.Document.Name, target.Name)
                             if target is not None else None)
        self._rows.append(row)

    def _add_chain(self, item, row):
        """The chain under a row's item; True when it has one."""
        steps = variables.chain_steps(row.source)
        for i, (obj, prop) in enumerate(steps):
            expr = variables.expression_of(obj, prop)
            value = row.value if i == 0 else variables.value_text(obj, prop)
            how = f"= {variables.pretty(expr)}" if expr else "typed in"
            child = QtWidgets.QTreeWidgetItem(
                item, [variables.location(obj, prop), value, how, ""])
            tip = ("Bound by an expression here. Click to select it; remove "
                   "its expression in the Property view to cut it loose from "
                   "the shared value." if expr else
                   "Where the value is typed in. Click to select it.")
            for col in range(len(_COLUMNS)):
                child.setToolTip(col, tip)
            self._attach(child, obj)
        if row.source is not None and row.source.kind == variables.FORMULA:
            for obj, prop in row.source.reads:
                src = variables.resolve(obj, prop)
                child = QtWidgets.QTreeWidgetItem(
                    item, [f"reads {variables.location(src.holder, src.prop)}",
                           variables.value_text(src.holder, src.prop),
                           variables.describe(src), ""])
                for col in range(len(_COLUMNS)):
                    child.setToolTip(col, variables.chain_text(src))
                self._attach(child, src.holder)
        return item.childCount() > 0

    def _chain_toggled(self, item, expanded):
        head = item.parent()
        if head is None or head.parent() is not None:
            return                  # a section heading, or a chain step
        key = (head.text(0), item.text(0))
        if expanded:
            self._open_chains.add(key)
        else:
            self._open_chains.discard(key)

    def row_at(self, index):
        """The variables.Row behind a model index, or None."""
        item = self.tree.itemFromIndex(index)
        i = item.data(0, QtCore.Qt.UserRole) if item is not None else None
        return self._rows[i] if i is not None and i < len(self._rows) else None

    def _double_clicked(self, item, column):
        # anywhere on an editable row edits its value
        if column != 1 and item.flags() & QtCore.Qt.ItemIsEditable:
            self.tree.editItem(item, 1)

    # --- editing --------------------------------------------------------------

    def _say(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet(_ERROR_STYLE if error else "")
        self.status.setVisible(bool(text))

    def commit_edit(self, row, value):
        """Write one edit in its own transaction, recompute, and report."""
        from . import measure
        source = row.source
        doc = source.holder.Document
        where = variables.location(source.holder, source.prop)
        affected = [doc.getObject(n) for n in row.own]
        affected += [hit for label in row.drives for hit in doc.getObjectsByLabel(label)]
        affected = [b for b in affected
                    if b is not None and b.TypeId == "PartDesign::Body"]

        def broken():
            bad = {o.Name for o in doc.Objects if "Invalid" in o.State}
            bad |= {b.Name for b in affected if not measure.is_whole(b)}
            return bad

        before = broken()
        doc.openTransaction(f"Edit {where}")
        try:
            variables.edit(source, value)
            doc.recompute()
        except variables.EditError as err:
            doc.abortTransaction()
            self._say(f"Not changed: {err}.", error=True)
            return
        except Exception as err:
            doc.abortTransaction()
            from .commands import report_unexpected
            report_unexpected("Timber Variables", err)
            return
        doc.commitTransaction()
        now = variables.value_text(source.holder, source.prop)
        expr = variables.expression_of(source.holder, source.prop)
        text = f"{where} is now {now}"
        if expr:
            text += f" (= {variables.pretty(expr)})"
        text += "."
        if row.drives:
            text += f" It also drives {variables.drives_text(row.drives)}."
        new = broken() - before
        if new:
            labels = sorted(doc.getObject(n).Label for n in new if doc.getObject(n))
            text += (f" But {', '.join(labels)} no longer recompute cleanly or "
                     f"are no longer one solid; Undo (Ctrl+Z) reverts the change.")
            self._say(text, error=True)
            App.Console.PrintWarning(f"BentWizard: Timber Variables: {text}\n")
        else:
            self._say(text)

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
