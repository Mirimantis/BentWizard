"""Reusable Qt widgets for joint parameter editing.

Provides a factory function that returns the correct input widget for each
parameter type, and a composite row widget that includes label, value input,
override indicator, and revert button.

This module is shared by JointPanel, MemberPanel, and future panels.
"""

from PySide2 import QtCore, QtWidgets, QtGui

from joints.base import JointParameter


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def format_param_name(name):
    """Convert a snake_case parameter name to Title Case.

    >>> format_param_name("tenon_width")
    'Tenon Width'
    """
    return name.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Stylesheets
# ---------------------------------------------------------------------------

_DERIVED_STYLE = "color: #888888; font-style: italic;"
_OVERRIDE_STYLE = ""
_READ_ONLY_STYLE = "color: #888888;"


# ---------------------------------------------------------------------------
# Value formatting for read-only labels
# ---------------------------------------------------------------------------

def _format_value(param):
    """Return a human-readable string for a parameter value."""
    if param.param_type == "length":
        return f"{param.value:.1f} mm"
    if param.param_type == "angle":
        return f"{param.value:.1f}\u00b0"
    if param.param_type == "integer":
        return str(int(param.value))
    if param.param_type == "boolean":
        return "Yes" if param.value else "No"
    return str(param.value)


# ---------------------------------------------------------------------------
# Input widget factory
# ---------------------------------------------------------------------------

def create_input_widget(param):
    """Return the correct Qt input widget for a :class:`JointParameter`.

    Parameters
    ----------
    param : JointParameter
        The parameter whose type determines the widget.

    Returns
    -------
    QWidget
        A QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, or QLabel
        (for read-only parameters).
    """
    # Read-only parameters get a non-editable label.
    if param.read_only:
        w = QtWidgets.QLabel(_format_value(param))
        w.setStyleSheet(_READ_ONLY_STYLE)
        return w

    if param.param_type == "length":
        w = QtWidgets.QDoubleSpinBox()
        w.setSuffix(" mm")
        w.setDecimals(1)
        w.setSingleStep(1.0)
        w.setKeyboardTracking(False)  # only emit valueChanged on commit
        w.setMinimum(param.min_value if param.min_value is not None else 0.0)
        w.setMaximum(param.max_value if param.max_value is not None else 9999.0)
        w.setValue(param.value)
        return w

    if param.param_type == "angle":
        w = QtWidgets.QDoubleSpinBox()
        w.setSuffix(" deg")
        w.setDecimals(1)
        w.setSingleStep(0.5)
        w.setKeyboardTracking(False)
        w.setMinimum(param.min_value if param.min_value is not None else 0.0)
        w.setMaximum(param.max_value if param.max_value is not None else 180.0)
        w.setValue(param.value)
        return w

    if param.param_type == "integer":
        w = QtWidgets.QSpinBox()
        w.setKeyboardTracking(False)
        w.setMinimum(int(param.min_value) if param.min_value is not None else 0)
        w.setMaximum(int(param.max_value) if param.max_value is not None else 999)
        w.setValue(int(param.value))
        return w

    if param.param_type == "boolean":
        w = QtWidgets.QCheckBox()
        w.setChecked(bool(param.value))
        return w

    if param.param_type == "enumeration":
        w = QtWidgets.QComboBox()
        for opt in param.enum_options:
            w.addItem(str(opt))
        idx = 0
        if param.value in param.enum_options:
            idx = param.enum_options.index(param.value)
        w.setCurrentIndex(idx)
        return w

    # Fallback: plain text edit for unknown types.
    w = QtWidgets.QLineEdit(str(param.value))
    return w


# ---------------------------------------------------------------------------
# ParameterRow — composite widget for a single parameter
# ---------------------------------------------------------------------------

class ParameterRow(QtWidgets.QWidget):
    """A single row showing revert button + label + input widget.

    The revert button is always visible to the left of the label.  When
    the parameter is at its derived default the button is disabled and
    dimmed; when overridden it becomes active.  This avoids layout
    shifts that could cause mis-clicks on the spinbox arrows.

    Read-only parameters display a non-editable QLabel instead of a
    spinbox and the revert button is permanently hidden.

    Signals
    -------
    value_changed(str, object)
        Emitted when the user changes the parameter value.
        Arguments: (parameter_name, new_value).
    revert_requested(str)
        Emitted when the user clicks the revert button.
        Argument: parameter_name.
    """

    value_changed = QtCore.Signal(str, object)
    revert_requested = QtCore.Signal(str)

    def __init__(self, param, parent=None):
        super().__init__(parent)
        self._name = param.name
        self._param_type = param.param_type
        self._read_only = param.read_only
        self._refreshing = False

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        # Revert button — to the LEFT of the label so it never displaces
        # the spinbox arrows.  Always present but disabled when not
        # overridden.  Hidden entirely for read-only params.
        self._revert_btn = QtWidgets.QToolButton()
        self._revert_btn.setText("\u21A9")  # ↩ arrow
        self._revert_btn.setToolTip("Revert to derived value")
        self._revert_btn.setFixedSize(22, 22)
        self._revert_btn.clicked.connect(self._on_revert_clicked)
        if self._read_only:
            self._revert_btn.setVisible(False)
        layout.addWidget(self._revert_btn)

        # Label
        self._label = QtWidgets.QLabel(format_param_name(param.name))
        self._label.setMinimumWidth(110)
        layout.addWidget(self._label)

        # Input widget (or read-only label)
        self._input = create_input_widget(param)
        self._input.setToolTip(param.description)
        layout.addWidget(self._input, 1)

        # Apply initial visual state.
        self._apply_override_style(param.is_overridden)

        # Connect input signals (skipped for read-only params).
        if not self._read_only:
            self._connect_input_signals()

    # -- signal connections -------------------------------------------------

    def _connect_input_signals(self):
        """Connect the input widget's commit signal to our handler.

        Spinboxes use ``valueChanged`` (with ``keyboardTracking=False``)
        instead of ``editingFinished`` so that arrow-button clicks
        immediately update the model — ``editingFinished`` only fires on
        Enter / focus-loss, which caused values to appear changed in the
        field without the model updating.
        """
        w = self._input
        if isinstance(w, QtWidgets.QDoubleSpinBox):
            w.valueChanged.connect(self._on_spinbox_changed)
        elif isinstance(w, QtWidgets.QSpinBox):
            w.valueChanged.connect(self._on_spinbox_changed)
        elif isinstance(w, QtWidgets.QCheckBox):
            w.stateChanged.connect(self._on_checkbox_changed)
        elif isinstance(w, QtWidgets.QComboBox):
            w.currentIndexChanged.connect(self._on_combo_changed)
        elif isinstance(w, QtWidgets.QLineEdit):
            w.editingFinished.connect(self._on_lineedit_finished)

    def _on_spinbox_changed(self, value):
        if self._refreshing:
            return
        self.value_changed.emit(self._name, value)

    def _on_checkbox_changed(self, state):
        if self._refreshing:
            return
        self.value_changed.emit(self._name, bool(state))

    def _on_combo_changed(self, index):
        if self._refreshing:
            return
        self.value_changed.emit(self._name, self._input.currentText())

    def _on_lineedit_finished(self):
        if self._refreshing:
            return
        self.value_changed.emit(self._name, self._input.text())

    def _on_revert_clicked(self):
        self.revert_requested.emit(self._name)

    # -- visual state -------------------------------------------------------

    def _apply_override_style(self, is_overridden):
        """Update visual styling to reflect derived vs. overridden state.

        The revert button is always present (stable layout) but disabled
        and dimmed when the parameter is at its derived default.
        """
        if self._read_only:
            # Read-only params: always derived style, button hidden.
            self._input.setStyleSheet(_READ_ONLY_STYLE)
            self._label.setStyleSheet(_READ_ONLY_STYLE)
            return

        if is_overridden:
            self._input.setStyleSheet(_OVERRIDE_STYLE)
            self._label.setStyleSheet("")
            self._revert_btn.setEnabled(True)
            self._revert_btn.setStyleSheet("")
        else:
            self._input.setStyleSheet(_DERIVED_STYLE)
            self._label.setStyleSheet(_DERIVED_STYLE)
            self._revert_btn.setEnabled(False)
            self._revert_btn.setStyleSheet("color: #cccccc;")

    # -- public refresh -----------------------------------------------------

    def refresh(self, param):
        """Update widget value and style from a :class:`JointParameter`.

        Uses a flag to suppress signal emission during programmatic updates.
        Min/max bounds are updated BEFORE the value to avoid clamping a
        valid value to stale limits.
        """
        self._refreshing = True
        try:
            w = self._input

            if self._read_only:
                # Read-only: just update the label text.
                if isinstance(w, QtWidgets.QLabel):
                    w.setText(_format_value(param))
            elif isinstance(w, QtWidgets.QDoubleSpinBox):
                # Update min/max FIRST so the new value isn't clamped by
                # stale limits.
                if param.min_value is not None:
                    w.setMinimum(param.min_value)
                if param.max_value is not None:
                    w.setMaximum(param.max_value)
                w.setValue(param.value)
            elif isinstance(w, QtWidgets.QSpinBox):
                if param.min_value is not None:
                    w.setMinimum(int(param.min_value))
                if param.max_value is not None:
                    w.setMaximum(int(param.max_value))
                w.setValue(int(param.value))
            elif isinstance(w, QtWidgets.QCheckBox):
                w.setChecked(bool(param.value))
            elif isinstance(w, QtWidgets.QComboBox):
                idx = 0
                if param.value in param.enum_options:
                    idx = param.enum_options.index(param.value)
                w.setCurrentIndex(idx)
            elif isinstance(w, QtWidgets.QLineEdit):
                w.setText(str(param.value))

            self._apply_override_style(param.is_overridden)
        finally:
            self._refreshing = False
