#! python3  # noqa: E265

"""
Reusable modal form dialog for creating and editing GeoServer resources.

Usage:
    fields = [
        {"key": "name", "label": "Name", "type": "text", "required": True},
        {"key": "uri", "label": "Namespace URI", "type": "text",
         "help": "The namespace URI associated with this workspace"},
        {"key": "isolated", "label": "Isolated Workspace", "type": "checkbox"},
    ]
    dlg = ResourceFormDialog(
        title="New Workspace",
        description="Configure a new workspace",
        fields=fields,
        parent=self,
    )
    if dlg.exec() == QDialog.DialogCode.Accepted:
        values = dlg.get_values()

For edit mode, pass existing values:
    dlg = ResourceFormDialog(
        title="Edit Workspace 'my_ws'",
        fields=fields,
        values={"name": "my_ws", "isolated": False},
        parent=self,
    )

Supported field types:
    - "text"      -> QLineEdit
    - "checkbox"  -> QCheckBox
    - "combo"     -> QComboBox (provide "options": ["a", "b", ...])
    - "spinbox"   -> QSpinBox (optional "min", "max", "default")
    - "textarea"  -> QPlainTextEdit

Field options:
    - key (str): identifier used in get_values()
    - label (str): display label
    - type (str): widget type (see above)
    - required (bool): mark as mandatory (default False)
    - default: default value
    - help (str): hint text shown below the widget
    - placeholder (str): placeholder text for text/textarea
    - options (list[str]): choices for "combo"
    - min/max (int): range for "spinbox"
    - read_only (bool): disable editing
    - group (str): optional tab group name — fields with the same group
      appear under one tab; ungrouped fields go to the first tab
    - on_change (callable): for "combo" fields, called with (new_value)
      when the selection changes
    - visible (bool): initial visibility (default True)
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class ResourceFormDialog(QDialog):
    """Generic modal form dialog built from a field definition list."""

    def __init__(self, title, fields, values=None, description=None, parent=None):
        """
        :param title: dialog window title.
        :param fields: list of field dicts (see module docstring).
        :param values: dict of existing values to pre-fill (edit mode).
        :param description: optional subtitle shown below the title.
        :param parent: parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(450)

        self._fields = fields
        self._widgets = {}  # key -> widget
        self._row_widgets = {}  # key -> (label_widget, wrapper_widget) for visibility

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(title_label)

        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: gray; margin-bottom: 6px;")
            layout.addWidget(desc_label)

        # Group fields by tab
        groups = self._collect_groups(fields)

        if len(groups) == 1:
            # Single group — no tabs needed
            form = self._build_form(list(groups.values())[0], values)
            layout.addWidget(form)
        else:
            # Multiple groups — use tabs
            tabs = QTabWidget()
            for group_name, group_fields in groups.items():
                page = self._build_form(group_fields, values)
                tabs.addTab(page, group_name)
            layout.addWidget(tabs)

        # Stretch to push buttons to the bottom
        layout.addStretch()

        # Buttons
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.button(QDialogButtonBox.StandardButton.Ok).setText(
            self.tr("Save")
        )
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

    @staticmethod
    def _collect_groups(fields):
        """Organise fields into ordered groups (preserves insertion order)."""
        groups = {}
        default_group = "General"
        for field in fields:
            group = field.get("group", default_group)
            groups.setdefault(group, []).append(field)
        return groups

    def _build_form(self, fields, values):
        """Build a QWidget containing a QFormLayout for the given fields."""
        container = QWidget()
        form = QFormLayout(container)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        for field in fields:
            widget = self._create_widget(field, values)
            self._widgets[field["key"]] = widget

            # Label
            label_text = field["label"]
            if field.get("required"):
                label_text += " *"
            label = QLabel(label_text)

            # Build a wrapper that stacks the widget + optional help text
            wrapper_widget = QWidget()
            wrapper = QVBoxLayout(wrapper_widget)
            wrapper.setSpacing(2)
            wrapper.setContentsMargins(0, 0, 0, 0)
            wrapper.addWidget(widget)

            help_text = field.get("help")
            if help_text:
                help_label = QLabel(help_text)
                help_label.setWordWrap(True)
                help_label.setStyleSheet("color: gray; font-size: 11px;")
                help_label.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                )
                wrapper.addWidget(help_label)

            form.addRow(label, wrapper_widget)
            self._row_widgets[field["key"]] = (label, wrapper_widget)

            # Initial visibility
            if field.get("visible") is False:
                label.setVisible(False)
                wrapper_widget.setVisible(False)

            # on_change callback for combo widgets
            if field.get("type") == "combo" and field.get("on_change"):
                cb = field["on_change"]
                widget.currentTextChanged.connect(cb)

        return container

    def _create_widget(self, field, values):
        """Instantiate the appropriate widget for a field definition."""
        ftype = field.get("type", "text")
        key = field["key"]
        default = field.get("default", "" if ftype == "text" else None)
        value = values.get(key, default) if values else default
        read_only = field.get("read_only", False)

        if ftype == "text":
            w = QLineEdit()
            if field.get("echo_password"):
                w.setEchoMode(QLineEdit.EchoMode.Password)
            if value:
                w.setText(str(value))
            placeholder = field.get("placeholder")
            if placeholder:
                w.setPlaceholderText(placeholder)
            if read_only:
                w.setEnabled(False)
            return w

        if ftype == "checkbox":
            w = QCheckBox()
            w.setChecked(bool(value))
            if read_only:
                w.setEnabled(False)
            return w

        if ftype == "combo":
            w = QComboBox()
            options = field.get("options", [])
            w.addItems(options)
            if value and value in options:
                w.setCurrentText(str(value))
            if read_only:
                w.setEnabled(False)
            return w

        if ftype == "spinbox":
            w = QSpinBox()
            w.setMinimum(field.get("min", 0))
            w.setMaximum(field.get("max", 99999))
            if value is not None:
                w.setValue(int(value))
            if read_only:
                w.setReadOnly(True)
            return w

        if ftype == "textarea":
            w = QPlainTextEdit()
            w.setMaximumHeight(120)
            if value:
                w.setPlainText(str(value))
            placeholder = field.get("placeholder")
            if placeholder:
                w.setPlaceholderText(placeholder)
            if read_only:
                w.setReadOnly(True)
            return w

        # Fallback to text
        w = QLineEdit()
        if value:
            w.setText(str(value))
        return w

    def get_values(self):
        """Return a dict of field key -> current value."""
        result = {}
        for field in self._fields:
            key = field["key"]
            widget = self._widgets[key]
            ftype = field.get("type", "text")

            if ftype == "text":
                result[key] = widget.text().strip()
            elif ftype == "checkbox":
                result[key] = widget.isChecked()
            elif ftype == "combo":
                result[key] = widget.currentText()
            elif ftype == "spinbox":
                result[key] = widget.value()
            elif ftype == "textarea":
                result[key] = widget.toPlainText().strip()
            else:
                result[key] = widget.text().strip()
        return result

    def set_field_visible(self, key, visible):
        """Show or hide a field by key.

        :param key: field key identifier.
        :param visible: True to show, False to hide.
        """
        if key in self._row_widgets:
            label, wrapper = self._row_widgets[key]
            label.setVisible(visible)
            wrapper.setVisible(visible)

    def get_widget(self, key):
        """Return the widget for a field by key.

        :param key: field key identifier.
        :return: the widget, or None if key not found.
        """
        return self._widgets.get(key)

    def set_all_fields_enabled(self, enabled):
        """Enable or disable all field widgets."""
        for widget in self._widgets.values():
            widget.setEnabled(enabled)

    def hide_save_button(self):
        """Hide the Save button, leaving only Cancel (for view-only dialogs)."""
        self._button_box.button(QDialogButtonBox.StandardButton.Ok).setVisible(False)
        self._button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(
            self.tr("Close")
        )

    def _on_accept(self):
        """Validate required fields before accepting."""
        # Reset styles
        for field in self._fields:
            widget = self._widgets[field["key"]]
            if not field.get("read_only"):
                widget.setStyleSheet("")

        for field in self._fields:
            if not field.get("required"):
                continue
            # Skip hidden fields
            key = field["key"]
            if key in self._row_widgets:
                _, wrapper = self._row_widgets[key]
                if not wrapper.isVisible():
                    continue
            value = self.get_values()[key]
            if not value:
                widget = self._widgets[key]
                widget.setFocus()
                widget.setStyleSheet("border: 1px solid red;")
                return

        self.accept()

    def set_field_value(self, key, value):
        """Programmatically set a field value by key."""
        if key not in self._widgets:
            return
        widget = self._widgets[key]
        field = next((f for f in self._fields if f["key"] == key), None)
        if not field:
            return
        ftype = field.get("type", "text")
        if ftype == "text":
            widget.setText(str(value) if value else "")
        elif ftype == "checkbox":
            widget.setChecked(bool(value))
        elif ftype == "combo":
            widget.setCurrentText(str(value))
        elif ftype == "spinbox":
            widget.setValue(int(value) if value else 0)
        elif ftype == "textarea":
            widget.setPlainText(str(value) if value else "")
