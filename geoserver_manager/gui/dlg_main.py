#! python3  # noqa: E265

"""
Main plugin dialog — GeoServer resource browser.

Left panel: navigation tabs (Workspaces, Datastores, Layers, Styles).
Right panel: search bar + results table for the selected tab.
"""

from functools import partial
from pathlib import Path

from qgis.core import Qgis, QgsApplication
from qgis.gui import QgsMessageBar
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QByteArray, Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidgetItem,
    QWidget,
)

from geoserver_manager.__about__ import __title__
from geoserver_manager.gui.tab_datastores import DatastoreTabMixin
from geoserver_manager.gui.tab_workspaces import WorkspaceTabMixin
from geoserver_manager.toolbelt.log_handler import PlgLogger
from geoserver_manager.toolbelt.preferences import PlgOptionsManager


class GeoServerMainDialog(QDialog, WorkspaceTabMixin, DatastoreTabMixin):
    """Main dialog — GeoServer resource browser."""

    def __init__(self, parent=None, iface=None):
        super().__init__(parent)
        self.iface = iface
        self.log = PlgLogger().log
        self.gs = None

        uic.loadUi(Path(__file__).parent / "dlg_main.ui", self)
        self.plg_settings = PlgOptionsManager()

        # Inline message bar (sits above the splitter)
        self.message_bar = QgsMessageBar(self)
        self.message_bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.message_bar_layout.insertWidget(0, self.message_bar)

        self.splitter.setSizes([160, 740])

        self._setup_nav()

        # Pagination state
        self._page_size = 20
        self._current_page = 0
        self._all_rows = []  # all fetched rows (list of list-of-str)
        self._filtered_rows = []  # rows after search filter
        self._row_actions = []  # list of (icon, tooltip, callback) for action buttons
        self._name_click_callback = None  # callback(row_data) when name is clicked
        self._extra_click_callbacks = {}  # extra col_index -> callback(row_data)
        self._delete_selected_callback = (
            None  # callback(list[row_data]) for bulk delete
        )

        # Tooltips
        self.btn_close.setToolTip(self.tr("Close the dialog"))
        self.btn_refresh.setToolTip(self.tr("Refresh resources from the GeoServer"))
        self.btn_edit_credentials.setToolTip(
            self.tr("Open settings to edit GeoServer credentials")
        )
        self.searchBox.setToolTip(
            self.tr("Search resources by name or other attributes")
        )
        self.btn_page_first.setToolTip(self.tr("First page"))
        self.btn_page_prev.setToolTip(self.tr("Previous page"))
        self.btn_page_next.setToolTip(self.tr("Next page"))
        self.btn_page_last.setToolTip(self.tr("Last page"))
        self.btn_delete_selected.setToolTip(self.tr("Delete the selected resources"))

        # Signals
        self.btn_close.clicked.connect(self.close)
        self.btn_refresh.clicked.connect(lambda: self.refresh_ui(show_message=True))
        self.btn_edit_credentials.clicked.connect(self._edit_credentials)
        self.navList.currentRowChanged.connect(self._on_nav_changed)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_filter)
        self.searchBox.textChanged.connect(lambda _: self._search_timer.start())
        self.btn_page_first.clicked.connect(self._page_first)
        self.btn_page_prev.clicked.connect(self._page_prev)
        self.btn_page_next.clicked.connect(self._page_next)
        self.btn_page_last.clicked.connect(self._page_last)
        self.resultsTable.itemSelectionChanged.connect(self._on_selection_changed)

        self._restore_settings()

    # -- Settings persistence -----------------------------------------------

    def closeEvent(self, event):
        self._store_settings()
        super().closeEvent(event)

    def _store_settings(self):
        """Persist dialog geometry and splitter sizes."""
        self.plg_settings.set_value_from_key("dialog_geometry", self.saveGeometry())
        self.plg_settings.set_value_from_key(
            "splitter_state", self.splitter.saveState()
        )

    def _restore_settings(self):
        """Restore dialog geometry and splitter sizes."""
        geometry = self.plg_settings.get_value_from_key(
            "dialog_geometry", None, QByteArray
        )
        if geometry is not None:
            self.restoreGeometry(geometry)

        splitter_state = self.plg_settings.get_value_from_key(
            "splitter_state", None, QByteArray
        )
        if splitter_state is not None:
            self.splitter.restoreState(splitter_state)

    # -- Messages (inline banners) -----------------------------------------

    def show_success_message(self, text):
        self.message_bar.pushMessage(
            self.tr("Success"), text, Qgis.MessageLevel.Success, 5
        )

    def show_error_message(self, text):
        self.message_bar.pushMessage(
            self.tr("Error"), text, Qgis.MessageLevel.Critical, 5
        )

    def show_warning_message(self, text):
        self.message_bar.pushMessage(
            self.tr("Warning"), text, Qgis.MessageLevel.Warning, 5
        )

    # -- Connection --------------------------------------------------------

    def _connect(self):
        """Create a GeoServerCloud client from stored credentials.
        Returns True on success."""
        settings = self.plg_settings.get_plg_settings()

        if not settings.has_credentials():
            self._set_status(self.tr("Not configured"), "red")
            self.show_warning_message(
                self.tr("GeoServer not configured — open Settings to add credentials.")
            )
            self.gs = None
            return False

        username, password = settings.get_credentials()
        if not username or not password:
            self._set_status(self.tr("Auth error"), "red")
            self.show_error_message(
                self.tr("Could not read credentials from the auth store.")
            )
            self.gs = None
            return False

        try:
            from geoservercloud import GeoServerCloud

            self.gs = GeoServerCloud(
                url=settings.geoserver_url,
                user=username,
                password=password,
            )
            self._set_status(
                self.tr("Connected — {}").format(settings.geoserver_url), "green"
            )
            return True
        except Exception as e:
            self._set_status(self.tr("Connection error"), "red")
            self.show_error_message(self.tr("Failed to connect: {}").format(e))
            self.log(f"Connection error: {e}", log_level=Qgis.MessageLevel.Critical)
            self.gs = None
            return False

    def _set_status(self, text, color="black"):
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"color: {color};")

    # -- Public entry point ------------------------------------------------

    def refresh_ui(self, show_message=False):
        """Connect and reload the current tab."""
        if self._connect():
            self._on_nav_changed(self.navList.currentRow())
            if show_message:
                self.show_success_message(self.tr("Resources loaded."))
        else:
            self.resultsTable.setRowCount(0)

    # -- Left navigation ---------------------------------------------------

    def _setup_nav(self):
        """Build the navigation tabs on the left."""
        self.navList.clear()
        tabs = [
            ("Workspaces", "mIconFolder.svg"),
            ("Datastores", "mIconDbSchema.svg"),
            # ("Layers",     "mIconVector.svg"),
            # ("Styles",     "mIconRendererCategory.svg"),
        ]
        for label, icon in tabs:
            self.navList.addItem(
                QListWidgetItem(QIcon(QgsApplication.iconPath(icon)), label)
            )
        if self.navList.count():
            self.navList.setCurrentRow(0)

    def _on_nav_changed(self, index):
        """Load data for the selected navigation tab."""
        if not self.gs or index < 0:
            return
        self.searchBox.clear()

        # Reset per-tab state
        self.btn_add.setVisible(False)
        self.btn_delete_selected.setVisible(False)
        self._name_click_callback = None
        self._delete_selected_callback = None
        self._row_actions = []

        label = self.navList.item(index).text()

        # Route to the appropriate loader
        if label == "Workspaces":
            self._load_workspaces()
        elif label == "Datastores":
            self._load_datastores()
        # elif label == "Layers":
        #     self._load_layers()
        # elif label == "Styles":
        #     self._load_styles()

    # -- Reusable table helpers --------------------------------------------

    def _setup_add_button(self, text, tooltip, callback):
        """Configure the header Add button for the current tab."""
        self.btn_add.setText(text)
        self.btn_add.setToolTip(tooltip)
        self.btn_add.setVisible(True)
        try:
            self.btn_add.clicked.disconnect()
        except TypeError:
            pass
        self.btn_add.clicked.connect(callback)

    def _setup_delete_selected_button(self, callback):
        """Configure the header Delete Selected button for the current tab."""
        self.btn_delete_selected.setVisible(True)
        self.btn_delete_selected.setEnabled(False)
        self._delete_selected_callback = callback
        try:
            self.btn_delete_selected.clicked.disconnect()
        except TypeError:
            pass
        self.btn_delete_selected.clicked.connect(
            lambda: callback(self._get_selected_rows())
        )

    def _setup_table(self, columns):
        """Reset the table with the given column headers."""
        self.resultsTable.clear()
        self.resultsTable.setColumnCount(len(columns))
        self.resultsTable.setHorizontalHeaderLabels(columns)
        self.resultsTable.setRowCount(0)
        header = self.resultsTable.horizontalHeader()
        for i in range(len(columns)):
            if columns[i] == self.tr("Actions"):
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)

    def _on_selection_changed(self):
        """Enable or disable the Delete Selected button based on selection."""
        has_selection = bool(self.resultsTable.selectionModel().selectedRows())
        self.btn_delete_selected.setEnabled(
            has_selection and self._delete_selected_callback is not None
        )

    def _get_selected_rows(self):
        """Return the row data for all currently selected table rows."""
        selected = []
        start = self._current_page * self._page_size
        for index in self.resultsTable.selectionModel().selectedRows():
            row_idx = start + index.row()
            if row_idx < len(self._filtered_rows):
                selected.append(self._filtered_rows[row_idx])
        return selected

    def _populate_rows(self, rows):
        """Store all rows and show the first page."""
        self._all_rows = rows
        self._current_page = 0
        self._apply_filter()

    def _apply_filter(self):
        """Filter _all_rows by the current search text, then show page."""
        search = self.searchBox.text().lower()
        if search:
            self._filtered_rows = [
                row
                for row in self._all_rows
                if any(search in str(v).lower() for v in row)
            ]
        else:
            self._filtered_rows = list(self._all_rows)
        self._current_page = 0
        self._show_page()

    @property
    def _total_pages(self):
        """Total number of pages for the current filtered rows."""
        return max(
            1, (len(self._filtered_rows) + self._page_size - 1) // self._page_size
        )

    def _show_page(self):
        """Render the current page of _filtered_rows into the table."""
        total = len(self._filtered_rows)
        start = self._current_page * self._page_size
        end = min(start + self._page_size, total)
        page_rows = self._filtered_rows[start:end]

        data_col_count = self.resultsTable.columnCount()
        if self._row_actions:
            data_col_count -= 1  # last column is for action buttons

        self.resultsTable.setRowCount(len(page_rows))
        for row_idx, values in enumerate(page_rows):
            for col, val in enumerate(values):
                click_cb = None
                if col == 0 and self._name_click_callback:
                    click_cb = self._name_click_callback
                elif col in self._extra_click_callbacks:
                    click_cb = self._extra_click_callbacks[col]
                if click_cb:
                    # Clickable cell
                    link = QPushButton(str(val))
                    link.setFlat(True)
                    link.setCursor(Qt.PointingHandCursor)
                    link.setStyleSheet(
                        "text-align: left; color: palette(link); "
                        "text-decoration: underline; padding: 0 4px;"
                    )
                    link.clicked.connect(partial(click_cb, values))
                    self.resultsTable.setCellWidget(row_idx, col, link)
                else:
                    self.resultsTable.setItem(
                        row_idx,
                        col,
                        QTableWidgetItem("—" if val is None else str(val)),
                    )
            if self._row_actions:
                self.resultsTable.setCellWidget(
                    row_idx, data_col_count, self._make_action_widget(values)
                )

        # Update pagination controls
        self.lbl_page_number.setText(str(self._current_page + 1))

        if total == 0:
            self.lbl_page_info.setText(self.tr("No results"))
        else:
            self.lbl_page_info.setText(
                self.tr("Results {} to {} (out of {} items)").format(
                    start + 1, end, total
                )
            )

        self.btn_page_first.setEnabled(self._current_page > 0)
        self.btn_page_prev.setEnabled(self._current_page > 0)
        self.btn_page_next.setEnabled(self._current_page + 1 < self._total_pages)
        self.btn_page_last.setEnabled(self._current_page + 1 < self._total_pages)

    def _make_action_widget(self, row_data):
        """Create a widget with icon action buttons for a table row."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)
        for icon_name, tooltip, callback in self._row_actions:
            btn = QPushButton()
            btn.setIcon(QIcon(QgsApplication.iconPath(icon_name)))
            btn.setToolTip(tooltip)
            btn.setFlat(True)
            btn.setFixedSize(24, 24)
            btn.clicked.connect(partial(callback, row_data))
            layout.addWidget(btn)
        return widget

    # -- Pagination slots --------------------------------------------------

    def _page_first(self):
        self._current_page = 0
        self._show_page()

    def _page_prev(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._show_page()

    def _page_next(self):
        if self._current_page + 1 < self._total_pages:
            self._current_page += 1
            self._show_page()

    def _page_last(self):
        self._current_page = self._total_pages - 1
        self._show_page()

    def _fetch_list(self, api_method, *args):
        """Call a geoservercloud list endpoint. Returns a list or []."""
        try:
            result, _ = api_method(*args)
            return result if isinstance(result, list) else []
        except Exception as e:
            self.log(
                f"API error ({api_method.__name__}): {e}",
                log_level=Qgis.MessageLevel.Warning,
            )
            return []

    def _filter_table(self, _text):
        """Filter rows by search text and reset to first page."""
        self._apply_filter()

    def _confirm_delete(self, resource_type, name):
        """Show a confirmation dialog before deleting a resource.

        :param resource_type: human-readable type (e.g. "workspace").
        :param name: name of the resource to delete.
        :return: True if the user confirmed deletion.
        """
        reply = QMessageBox.warning(
            self,
            self.tr("Confirm Delete"),
            self.tr(
                "Are you sure you want to delete {type} '{name}'?\n\n"
                "This action cannot be undone."
            ).format(type=resource_type, name=name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    # -- Dialog actions ----------------------------------------------------

    def _edit_credentials(self):
        """Open the plugin's settings page."""
        if self.iface:
            self.hide()
            self.iface.showOptionsDialog(currentPage=f"mOptionsPage{__title__}")
            self.refresh_ui(show_message=True)
            self.show()
