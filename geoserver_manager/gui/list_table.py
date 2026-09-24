#! python3  # noqa: E265

"""
An editable list of rows: items picked from the server's names, in order when
order matters, each with typed columns (a style, a zoom range).

Qt and QGIS have the simple cases, and the forms use them: `QgsListWidget`
for plain strings (keywords), `QgsKeyValueWidget` for key/value pairs. Neither
reorders rows, picks from known names or holds a typed column, which a layer
group's layers (order and style), a cached layer's gridsets (zoom range) and a
layer's other styles need. This widget does that, on a `QTableWidget`, with the
plugin's own icons, recoloured with the theme like every other.
"""

from qgis.PyQt.QtCore import QCoreApplication, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from geoserver_manager.gui.icons import icon

translate = QCoreApplication.translate


def short_combo(combo, length=30):
    """Size a combo box to `length` characters rather than to its longest entry.

    A form is never narrower than its fields' minimum, so one long layer
    or style name widened the whole dialog past a laptop screen. Thirty fit
    a form's own choices ("A layer from this QGIS project"); a table cell
    takes fewer. The combo still grows with the form; a longer entry is
    elided until then.
    """
    combo.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    )
    combo.setMinimumContentsLength(length)


class ListTable(QWidget):
    """Rows of values, the first one an item picked or typed.

    :param columns: one dict per column: "label", and "type" among
        "text" (the default), "combo" (with "options" and an optional
        "placeholder" for a blank cell; an editable combo, so a name not
        listed can still be typed) and "spin" (with "min", "max";
        "none_text" shown for "no value", read back as None).
    :param choices: what the picker offers for the first column. Typing a
        name not listed is allowed: GeoServer, not this list, decides.
    :param ordered: rows can be moved up and down; their order is the value.
    """

    changed = pyqtSignal()

    def __init__(
        self, columns, choices=(), ordered=False, read_only=False, parent=None
    ):
        super().__init__(parent)
        self._columns = [dict(column) for column in columns]
        self._read_only = read_only

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, len(self._columns))
        self.table.setHorizontalHeaderLabels([c["label"] for c in self._columns])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for index in range(1, len(self._columns)):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        if len(self._columns) == 1:
            header.setVisible(False)
        if read_only:
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        self.picker = QComboBox()
        short_combo(self.picker, 12)
        self.picker.setEditable(True)  # completion, and names not listed
        self.picker.addItems(list(choices))
        self.picker.setCurrentIndex(-1)
        self.picker.lineEdit().setPlaceholderText(
            translate("ListTable", "Pick or type, then Add")
        )
        self.picker.lineEdit().returnPressed.connect(self._add_picked)

        buttons = QHBoxLayout()
        buttons.addWidget(self.picker, 1)
        self.add_button = self._button(
            "list-add", translate("ListTable", "Add"), self._add_picked
        )
        self.remove_button = self._button(
            "list-remove", translate("ListTable", "Remove"), self._remove
        )
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        self.up_button = self.down_button = None
        if ordered:
            self.up_button = self._button(
                "move-up", translate("ListTable", "Move up"), self._up
            )
            self.down_button = self._button(
                "move-down",
                translate("ListTable", "Move down"),
                self._down,
            )
            buttons.addWidget(self.up_button)
            buttons.addWidget(self.down_button)
        if not read_only:
            layout.addLayout(buttons)

    def isReadOnly(self):  # noqa: N802 (the name QgsTableWidgetBase uses)
        return self._read_only

    def _button(self, icon_name, tooltip, slot):
        button = QToolButton()
        button.setIcon(icon(icon_name))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.clicked.connect(slot)
        return button

    # -- Rows ----------------------------------------------------------------

    def set_rows(self, rows):
        """Replace the rows. A single-column table also takes plain strings."""
        self.table.setRowCount(0)
        for row in rows or ():
            self._append(row if isinstance(row, (list, tuple)) else [row])

    def rows(self):
        """The rows as lists, in table order; plain strings for one column."""
        values = [
            [self._cell(index, column) for column in range(len(self._columns))]
            for index in range(self.table.rowCount())
        ]
        if len(self._columns) == 1:
            return [row[0] for row in values if row[0]]
        return [row for row in values if row[0]]

    def _append(self, row):
        index = self.table.rowCount()
        self.table.insertRow(index)
        for column, spec in enumerate(self._columns):
            value = row[column] if column < len(row) else None
            kind = spec.get("type", "text")
            if kind == "combo":
                cell = QComboBox()
                short_combo(cell, 12)
                cell.setEditable(True)
                cell.addItems(list(spec.get("options", ())))
                cell.setCurrentText("" if value is None else str(value))
                if spec.get("placeholder"):  # what a blank cell means
                    cell.lineEdit().setPlaceholderText(spec["placeholder"])
                cell.setEnabled(not self._read_only)
                cell.currentTextChanged.connect(self.changed)
                self.table.setCellWidget(index, column, cell)
            elif kind == "spin":
                cell = QSpinBox()
                # One below the minimum is "no value", shown as none_text:
                # Qt's own special-value mechanism, not a sentinel string.
                cell.setRange(spec.get("min", 0) - 1, spec.get("max", 99))
                cell.setSpecialValueText(spec.get("none_text", "-"))
                cell.setValue(cell.minimum() if value is None else int(value))
                cell.setReadOnly(self._read_only)
                cell.valueChanged.connect(self.changed)
                self.table.setCellWidget(index, column, cell)
            else:
                self.table.setItem(
                    index, column, QTableWidgetItem("" if value is None else str(value))
                )
        self.changed.emit()

    def _cell(self, index, column):
        widget = self.table.cellWidget(index, column)
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        if isinstance(widget, QSpinBox):
            return None if widget.value() == widget.minimum() else widget.value()
        item = self.table.item(index, column)
        return item.text().strip() if item is not None else ""

    # -- Buttons -------------------------------------------------------------

    def _add_picked(self):
        name = self.picker.currentText().strip()
        if not name:
            return
        self._append([name])
        self.table.selectRow(self.table.rowCount() - 1)
        self.picker.setCurrentIndex(-1)
        self.picker.clearEditText()

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _remove(self):
        index = self._selected()
        if index is not None:
            self.table.removeRow(index)
            self.changed.emit()

    def _up(self):
        self._move(-1)

    def _down(self):
        self._move(1)

    def _move(self, step):
        index = self._selected()
        if index is None or not 0 <= index + step < self.table.rowCount():
            return
        values = self.rows_with_empty()
        values[index], values[index + step] = values[index + step], values[index]
        self.table.setRowCount(0)
        for row in values:
            self._append(row)
        self.table.selectRow(index + step)

    def rows_with_empty(self):
        """Every row as a list, blank ones included: what a move reorders."""
        return [
            [self._cell(index, column) for column in range(len(self._columns))]
            for index in range(self.table.rowCount())
        ]
