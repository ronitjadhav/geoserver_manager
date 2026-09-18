#! python3  # noqa: E265

"""
Main plugin dialog — GeoServer resource browser.

Left panel: navigation tabs, one per resource type (see TABS).
Right panel: search bar + results table for the selected tab.

Every load runs in a QgsTask: a loader arms the GUI and hands a fetch function
to _start_load, which returns immediately and renders the rows when they land.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from qgis.core import Qgis, QgsApplication, QgsTask
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
from geoserver_manager.gui.scope import scope
from geoserver_manager.gui.tab_coveragestores import CoverageStoreTabMixin
from geoserver_manager.gui.tab_datastores import DatastoreTabMixin
from geoserver_manager.gui.tab_layergroups import LayerGroupTabMixin
from geoserver_manager.gui.tab_layers import LayerTabMixin
from geoserver_manager.gui.tab_styles import StyleTabMixin
from geoserver_manager.gui.tab_workspaces import WorkspaceTabMixin
from geoserver_manager.gui.theme import status_colour
from geoserver_manager.toolbelt.log_handler import PlgLogger
from geoserver_manager.toolbelt.preferences import PlgOptionsManager

# Listing a nested resource needs one GET per parent plus one per item. Eight
# parallel requests keep that bearable. They run inside a _FetchTask, so they
# never block the GUI thread.
_MAX_PARALLEL_REQUESTS = 8

# The connection probe is the request the user waits for before anything is on
# screen, so it gets its own short ceiling. The library cannot do this: its
# RestClient hardcodes timeout=TIMEOUT (120 s) — see _probe and issue #50.
_PROBE_TIMEOUT = 10


class _FetchTask(QgsTask):
    """Runs one dialog fetch off the GUI thread.

    QgsTask brings QGIS's own progress bar and Cancel button, and calls
    finished() back on the GUI thread — the only thread allowed to touch a
    widget. Whatever run() collects is handed to the callback untouched.
    """

    def __init__(self, description, work, on_finished):
        super().__init__(description, QgsTask.Flag.CanCancel)
        self._work = work
        self._on_finished = on_finished
        self._result = None
        self._error = None
        # Set by _cancel_load: tells "the user pressed Cancel" apart from
        # "another load superseded this one".
        self.user_cancelled = False

    def run(self):
        """Worker thread. No widget may be touched from here."""
        try:
            self._result = self._work(self)
        except Exception as e:  # reported on the GUI thread, by _run_in_task
            self._error = e
            return False
        return not self.isCanceled()

    def finished(self, result):
        """Back on the GUI thread, whatever happened."""
        self._on_finished(self, result, self._result, self._error)


class GeoServerMainDialog(
    QDialog,
    WorkspaceTabMixin,
    DatastoreTabMixin,
    CoverageStoreTabMixin,
    LayerTabMixin,
    LayerGroupTabMixin,
    StyleTabMixin,
):
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
        self.message_bar.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
        )
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
        self._extra_click_callbacks = {}  # col_header -> callback(row_data)
        self._delete_selected_callback = (
            None  # callback(list[row_data]) for bulk delete
        )

        # Background loading state
        self._task = None  # the running _FetchTask, if any
        self._closing = False  # set in closeEvent: a late finish must stay away
        self._announce_after_load = None  # banner to show once rows have landed

        # Tooltips
        self.btn_close.setToolTip(self.tr("Close the dialog"))
        self.btn_refresh.setToolTip(
            self.tr("Refresh resources from the GeoServer (F5)")
        )
        self.btn_edit_credentials.setToolTip(
            self.tr("Open settings to edit GeoServer credentials")
        )
        self.searchBox.setToolTip(
            self.tr(
                "Search resources by name or other attributes "
                "(Ctrl+F to jump here, Esc to clear)"
            )
        )
        self.searchBox.setPlaceholderText(self.tr("Filter this list…  (Ctrl+F)"))
        self.btn_page_first.setToolTip(self.tr("First page"))
        self.btn_page_prev.setToolTip(self.tr("Previous page"))
        self.btn_page_next.setToolTip(self.tr("Next page"))
        self.btn_page_last.setToolTip(self.tr("Last page"))
        self.btn_delete_selected.setToolTip(
            self.tr("Delete the selected resources (Del)")
        )

        # Signals
        self.btn_close.clicked.connect(self.close)
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)
        self.btn_edit_credentials.clicked.connect(self._edit_credentials)
        self.navList.currentRowChanged.connect(self._on_nav_changed)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._apply_filter)
        self.searchBox.textChanged.connect(self._search_timer.start)
        self.btn_page_first.clicked.connect(self._page_first)
        self.btn_page_prev.clicked.connect(self._page_prev)
        self.btn_page_next.clicked.connect(self._page_next)
        self.btn_page_last.clicked.connect(self._page_last)
        self.resultsTable.itemSelectionChanged.connect(self._on_selection_changed)
        self.resultsTable.cellClicked.connect(self._on_cell_clicked)

        self._restore_settings()

    # -- Keyboard -----------------------------------------------------------

    def keyPressEvent(self, event):  # noqa: N802 — Qt's own spelling
        """F5 refresh, Ctrl+F search, Esc clear, Enter open, Del delete.

        Handled here rather than with QShortcut so each key can look at where
        the focus is: Del must delete resources only when the *table* has it,
        never while the same key is erasing a character in the search box, and
        Esc must keep closing the dialog when there is no search to clear.
        """
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key.Key_F5:
            self.refresh_ui(show_message=True)
            return
        if key == Qt.Key.Key_F and modifiers & Qt.KeyboardModifier.ControlModifier:
            self.searchBox.setFocus()
            self.searchBox.selectAll()
            return
        if key == Qt.Key.Key_Escape and self.searchBox.text():
            self.searchBox.clear()
            return
        if (
            key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self.resultsTable.hasFocus()
            and self._name_click_callback is not None
        ):
            selected = self._get_selected_rows()
            if len(selected) == 1 and self._require_connection():
                self._name_click_callback(selected[0])
            return
        if (
            key == Qt.Key.Key_Delete
            and self.resultsTable.hasFocus()
            and self.btn_delete_selected.isEnabled()
            and self._delete_selected_callback is not None
        ):
            self._delete_selected_callback(self._get_selected_rows())
            return
        super().keyPressEvent(event)

    # -- Settings persistence -----------------------------------------------

    def closeEvent(self, event):
        # A running task would call back into widgets that are on their way out.
        self._closing = True
        self._cancel_load()
        self._store_settings()
        super().closeEvent(event)

    def _store_settings(self):
        """Persist dialog geometry, splitter sizes and the open tab."""
        self.plg_settings.set_value_from_key("dialog_geometry", self.saveGeometry())
        self.plg_settings.set_value_from_key(
            "splitter_state", self.splitter.saveState()
        )
        self.plg_settings.set_value_from_key("last_tab", self.navList.currentRow())

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

    @staticmethod
    def _check(result):
        """Unpack a geoservercloud (content, status_code) tuple.

        The library's REST client raises for most HTTP errors, but deliberately
        lets three statuses through: 404 on GET/DELETE and 409 on POST. Those
        would otherwise read as success, so raise here too. TODO(#50).
        """
        content, status_code = result
        if status_code >= 400:
            raise RuntimeError(f"HTTP {status_code}: {content}")
        return content

    def _build_client(self, settings):
        """Return a GeoServerCloud client from the saved settings, or None.

        The constructor makes no network call; _probe does the real check.
        """
        if not settings.has_credentials():
            self._set_status(self.tr("Not configured"), "error")
            self.show_warning_message(
                self.tr("GeoServer not configured — open Settings to add credentials.")
            )
            return None

        username, password = settings.get_credentials()
        if not username or not password:
            self._set_status(self.tr("Auth error"), "error")
            self.show_error_message(
                self.tr("Could not read credentials from the auth store.")
            )
            return None

        from geoservercloud import GeoServerCloud

        return GeoServerCloud(
            url=settings.geoserver_url,
            user=username,
            password=password,
            verifytls=settings.geoserver_verify_tls,
        )

    def _probe(self, gs, url):
        """Make one bounded request. Return None if it worked, else (status, message).

        TODO(#50): the one call in the plugin that does not go through the
        library. `RestClient` hardcodes `timeout=TIMEOUT` (120 s) and takes no
        timeout argument, and this is the request the user waits for before the
        first table appears — so it uses `requests` directly with
        _PROBE_TIMEOUT, reusing the client's own auth and TLS setting.
        """
        import requests
        from requests.exceptions import SSLError

        client = gs.rest_service.rest_client
        try:
            response = requests.get(
                f"{url.rstrip('/')}/rest/workspaces.json",
                auth=client.auth,
                timeout=_PROBE_TIMEOUT,
                verify=client.verifytls,
            )
        except SSLError:
            # Before OSError (it is a ConnectionError): a private-CA or
            # self-signed certificate used to read as "is the server running?"
            return (
                self.tr("Certificate not trusted"),
                self.tr(
                    "{url} presented a TLS certificate this machine does not trust. "
                    "If it is your own private CA or a self-signed certificate, untick "
                    '"Verify the server\'s TLS certificate" in Settings.'
                ).format(url=url),
            )
        except OSError:
            # ConnectionError / Timeout: refused, unreachable, wrong host, or
            # a host that swallows the SYN — that one now gives up after
            # _PROBE_TIMEOUT instead of the library's two minutes.
            return (
                self.tr("Server unreachable"),
                self.tr(
                    "Cannot reach GeoServer at {url} — is the server running?"
                ).format(url=url),
            )
        except Exception as e:
            return (
                self.tr("Connection error"),
                self.tr("Connection failed: {}").format(e),
            )

        if response.status_code in (401, 403):
            return (
                self.tr("Authentication failed"),
                self.tr(
                    "Authentication failed — check your username and password in Settings."
                ),
            )
        if response.status_code >= 400:
            # The URL usually points at something that is not a GeoServer REST
            # endpoint at all.
            return (
                self.tr("HTTP error {}").format(response.status_code),
                self.tr(
                    "GeoServer returned HTTP {code} for {url} — check the URL in Settings."
                ).format(code=response.status_code, url=url),
            )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or "workspaces" not in payload:
            # An SSO / reverse-proxy login page answers 200 with HTML. Without
            # this check it showed a green "Connected" and empty tables.
            return (
                self.tr("Not a GeoServer REST endpoint"),
                self.tr(
                    "{url} answered, but not with the GeoServer REST API (a login "
                    "page?) — check the URL, or the proxy in front of it."
                ).format(url=url),
            )
        return None

    def _fetch_version_label(self, gs):
        """Best-effort 'GeoServer x.y.z' string for the status bar.

        Not required for a successful connection — if it fails, we still
        show "Connected" without the version suffix.
        """
        try:
            info = self._check(gs.get_version())
        except Exception:
            return ""
        if not isinstance(info, dict):
            return ""
        for res in info.get("about", {}).get("resource", []):
            if res.get("@name", "").lower().startswith("geoserver"):
                version = res.get("Version", "")
                return f"GeoServer {version}" if version else ""
        return ""

    def _set_status(self, text, kind="neutral"):
        """Show the connection state, in a colour this theme can carry.

        :param kind: "ok", "error", "busy" or "neutral" — never a literal
            colour: `red` on a dark theme is what this replaces.
        """
        self.lbl_status.setText(text)
        colour = status_colour(kind, self.palette())
        self.lbl_status.setStyleSheet(f"color: {colour};" if colour else "")

    # -- Public entry point ------------------------------------------------

    def refresh_ui(self, show_message=False):
        """Connect in the background, then reload the current tab.

        Returns as soon as the probe is on its way: nothing here waits for the
        server, so QGIS stays usable even when the host swallows the SYN.
        """
        self._set_status(self.tr("Connecting…"), "busy")
        self.setWindowTitle(__title__)
        self.gs = None
        # The rows on screen belong to the connection just dropped; the loader
        # re-arms these once the probe lands.
        self.btn_add.setEnabled(False)
        self.btn_delete_selected.setEnabled(False)
        settings = self.plg_settings.get_plg_settings()
        # Credentials come out of QgsAuthManager, so the client is built here on
        # the GUI thread; its constructor makes no network call.
        gs = self._build_client(settings)
        if gs is None:
            self._reset_table_state()
            return
        url = settings.geoserver_url

        def connect(task):
            problem = self._probe(gs, url)
            return problem, ("" if problem else self._fetch_version_label(gs))

        def connected(result):
            problem, version = result
            if problem is not None:
                status, message = problem
                self._set_status(status, "error")
                self.show_error_message(message)
                self.log(
                    f"Connection check failed: {status}", Qgis.MessageLevel.Critical
                )
                # Clearing only the visible rows would leave the dead server's
                # data in the row cache, reachable through search and pagination.
                self._reset_table_state()
                return
            self.gs = gs
            self.setWindowTitle(f"{__title__} — {urlparse(url).netloc or url}")
            status = self.tr("Connected — {}").format(url)
            if version:
                status += f" ({version})"
            self._set_status(status, "ok")
            if show_message:
                # The rows are still on their way; _render_rows says so once
                # they land, rather than claiming it now.
                self._announce_after_load = self.tr("Resources loaded.")
            self._on_nav_changed(self.navList.currentRow())

        self._run_in_task(self.tr("Connection failed"), connect, connected)

    # -- Background loading ------------------------------------------------

    def _run_in_task(self, failure_message, work, on_success):
        """Run work(task) off the GUI thread, then on_success(result) here.

        Only stateless REST reads belong in work: the client's wms / wmts
        attributes are shared state. A failed run reports itself and calls
        nothing; a cancelled one does neither — which is why every loader
        resets the table *before* starting a task, so an empty table is what
        either outcome leaves behind.
        """
        self._cancel_load()
        self._set_loading(True)

        def finished(task, ok, result, error):
            if self._closing or self._task is not task:
                # The dialog is going away, or a newer load took over: that
                # one owns the table and the Cancel button now.
                return
            self._task = None
            self._set_loading(False)
            if error is not None:
                detail = self._error_text(error)
                self.show_error_message(f"{failure_message}: {detail}")
                self.log(
                    f"{failure_message}: {detail}", log_level=Qgis.MessageLevel.Critical
                )
                return
            if not ok:
                if task.user_cancelled:
                    self.show_warning_message(self.tr("Loading cancelled."))
                return
            on_success(result)

        self._task = _FetchTask(failure_message, work, finished)
        QgsApplication.taskManager().addTask(self._task)

    def _start_load(self, failure_message, fetch):
        """Fetch a tab's rows in the background and render them when they land.

        `fetch(task) -> (rows, failures)` runs in a worker thread, so it must
        not touch a widget: everything it returns is rendered here instead.
        """
        self._run_in_task(
            failure_message, fetch, lambda result: self._render_rows(*result)
        )

    def _render_rows(self, rows, failures):
        """GUI side of a load: paint the rows, then report what could not load."""
        self._populate_rows(rows)
        self._report_partial_failures(failures)
        if self._announce_after_load:
            self.show_success_message(self._announce_after_load)
            self._announce_after_load = None

    def _cancel_load(self, user=False):
        """Cancel the running load, if any. `user` marks the Cancel button."""
        if self._task is not None:
            self._task.user_cancelled = user
            self._task.cancel()

    def _loading(self):
        """True while a background load is running."""
        return self._task is not None

    def _set_loading(self, loading):
        """Say that a load is running, and offer Cancel in place of Refresh."""
        self.btn_refresh.setText(self.tr("Cancel") if loading else self.tr("Refresh"))
        self.btn_refresh.setToolTip(
            self.tr("Stop loading")
            if loading
            else self.tr("Refresh resources from the GeoServer (F5)")
        )
        if loading:
            self.lbl_page_info.setText(self.tr("Loading…"))
        elif not self._all_rows:
            self.lbl_page_info.setText(self.tr("No results"))

    def _on_refresh_clicked(self):
        """One button: Refresh when idle, Cancel while loading."""
        if self._loading():
            self._cancel_load(user=True)
        else:
            self.refresh_ui(show_message=True)

    # -- Left navigation ---------------------------------------------------

    # One entry per tab: (label, QGIS icon, loader method name). Adding a
    # resource type means adding a line here and a mixin with that loader.
    TABS = (
        ("Workspaces", "mIconFolder.svg", "_load_workspaces"),
        ("Datastores", "mIconDbSchema.svg", "_load_datastores"),
        ("Coverage Stores", "mIconRasterLayer.svg", "_load_coverage_stores"),
        ("Layers", "mIconVector.svg", "_load_layers"),
        ("Layer Groups", "mActionAddGroup.svg", "_load_layer_groups"),
        ("Styles", "mActionStyleManager.svg", "_load_styles"),
    )

    def _setup_nav(self):
        """Build the navigation list on the left from TABS."""
        self.navList.clear()
        for label, icon, _loader in self.TABS:
            self.navList.addItem(
                QListWidgetItem(QIcon(QgsApplication.iconPath(icon)), label)
            )
        if self.navList.count():
            # Reopen on the tab this profile left open, if it still exists:
            # TABS can gain and lose entries between versions.
            remembered = self.plg_settings.get_value_from_key("last_tab", 0, int)
            try:
                remembered = int(remembered)
            except (TypeError, ValueError):
                remembered = 0
            if not 0 <= remembered < self.navList.count():
                remembered = 0
            self.navList.setCurrentRow(remembered)

    def _reload_current_tab(self):
        """Reload whichever tab is selected.

        Use this instead of a specific loader when the caller may have been
        reached from another tab (e.g. editing a workspace from the datastore
        list), otherwise the table gets repainted with the wrong resource type.
        """
        self._on_nav_changed(self.navList.currentRow())

    def _reset_table_state(self):
        """Clear the table, its row cache and every per-tab callback.

        Loaders arm the callbacks and headers before they fetch, so a fetch that
        raises would otherwise leave the previous resource type's rows in the
        cache, reachable through the search box and the pagination buttons and
        wired to the new tab's row actions — i.e. Delete aimed at the wrong
        resource. Resetting both halves together is what keeps that impossible.
        """
        self.btn_add.setVisible(False)
        self.btn_delete_selected.setVisible(False)
        self._name_click_callback = None
        self._delete_selected_callback = None
        self._row_actions = []
        self._extra_click_callbacks = {}
        self._all_rows = []
        self._filtered_rows = []
        self._current_page = 0
        self.resultsTable.clearContents()
        self.resultsTable.setRowCount(0)
        self.lbl_page_number.setText("1")
        self.lbl_page_info.setText(self.tr("No results"))
        for button in (
            self.btn_page_first,
            self.btn_page_prev,
            self.btn_page_next,
            self.btn_page_last,
        ):
            button.setEnabled(False)

    def _on_nav_changed(self, index):
        """Load data for the selected navigation tab."""
        if not self.gs or index < 0:
            return
        self.searchBox.clear()
        self._search_timer.stop()  # clear() may have armed it
        self._reset_table_state()
        getattr(self, self.TABS[index][2])()

    # -- Reusable table helpers --------------------------------------------

    def _setup_add_button(self, text, tooltip, callback):
        """Configure the header Add button for the current tab."""
        self.btn_add.setEnabled(True)
        self.btn_add.setText(text)
        self.btn_add.setToolTip(tooltip)
        self.btn_add.setVisible(True)
        try:
            self.btn_add.clicked.disconnect()
        except TypeError:
            pass
        # Guarded: the button stays armed while a refresh re-probes the server.
        self.btn_add.clicked.connect(lambda: self._require_connection() and callback())

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
            lambda: self._require_connection() and callback(self._get_selected_rows())
        )

    def _setup_table(self, columns):
        """Reset the table with the given column headers."""
        # Sorting must stay off: rows are paginated in Python and selections are
        # mapped back by row index, so a header click would make the table delete
        # a different resource than the one highlighted.
        self.resultsTable.setSortingEnabled(False)
        # Loaders call this before fetching, so drop the previous rows here too:
        # a fetch that raises must not leave them to be repainted under the new
        # headers (see _reset_table_state).
        self._all_rows = []
        self._filtered_rows = []
        self._current_page = 0
        self.resultsTable.clear()
        self.resultsTable.setColumnCount(len(columns))
        self.resultsTable.setHorizontalHeaderLabels(columns)
        self.resultsTable.setRowCount(0)
        header = self.resultsTable.horizontalHeader()
        actions = self.actions_column_label()
        for i in range(len(columns)):
            if columns[i] == actions:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)

    def actions_column_label(self):
        """The header text of the row-actions column.

        Every tab's last column is this one, and _setup_table recognises it by
        its text to size it to its buttons. The mixins take the label from
        here rather than translating "Actions" in their own context, so the
        two sides of that comparison cannot drift apart once a translation is
        installed (see invariant 10 in CLAUDE.md).
        """
        return self.tr("Actions")

    def _on_selection_changed(self):
        """Enable or disable the Delete Selected button based on selection."""
        has_selection = bool(self.resultsTable.selectionModel().selectedRows())
        self.btn_delete_selected.setEnabled(
            has_selection and self._delete_selected_callback is not None
        )

    def _get_selected_rows(self):
        """Return the row data for all currently selected table rows.

        Assumes the table renders _filtered_rows in order — see _setup_table.
        """
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
                item = QTableWidgetItem("—" if val is None else str(val))
                if self._cell_click_callback(col) is not None:
                    # Styled as a link; the click itself is handled by
                    # _on_cell_clicked. A real item (not a QPushButton) keeps
                    # the row selectable, so "Delete Selected" works here too.
                    item.setForeground(self.palette().link())
                    font = item.font()
                    font.setUnderline(True)
                    item.setFont(font)
                    item.setToolTip(
                        self.tr("Click to open (or select and press Enter)")
                    )
                self.resultsTable.setItem(row_idx, col, item)
            if self._row_actions:
                self.resultsTable.setCellWidget(
                    row_idx, data_col_count, self._make_action_widget(values)
                )

        # Update pagination controls
        self.lbl_page_number.setText(str(self._current_page + 1))

        if total == 0:
            self.lbl_page_info.setText(self._empty_state_text())
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

    def _open_workspace_from_row(self, row_data):
        """The Workspace column links to the workspace — column 1 on every tab.

        Styles and layer groups can live in the global scope, whose label is
        not a workspace, so that one is a dead link rather than an error.
        """
        if scope(row_data[1]) is not None:
            self._show_workspace_info([row_data[1]])

    def _empty_state_text(self):
        """What an empty table should say: why it is empty, and what helps."""
        search = self.searchBox.text().strip()
        if search and self._all_rows:
            return self.tr("Nothing matches '{}' — Esc clears the filter.").format(
                search
            )
        # isHidden(), not isVisible(): the latter is false for every widget of
        # a window that is not showing yet (invariant 8).
        if not self.btn_add.isHidden() and self.btn_add.text():
            return self.tr("Nothing here yet — start with '{}' above.").format(
                self.btn_add.text()
            )
        return self.tr("No results")

    def _cell_click_callback(self, col):
        """The callback a click in this column triggers, or None."""
        if col == 0:
            return self._name_click_callback
        header = self.resultsTable.horizontalHeaderItem(col)
        return self._extra_click_callbacks.get(header.text() if header else "")

    def _on_cell_clicked(self, row, col):
        """Open the resource behind a link cell; other cells just select."""
        callback = self._cell_click_callback(col)
        if callback is None or not self._require_connection():
            return
        index = self._current_page * self._page_size + row
        if index < len(self._filtered_rows):
            callback(self._filtered_rows[index])

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
            btn.clicked.connect(
                lambda _checked=False, cb=callback, row=row_data: (
                    self._require_connection() and cb(row)
                )
            )
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

    @staticmethod
    def _name_of(item):
        """Name of a list entry: geoservercloud returns dicts, tolerate strings."""
        return item.get("name", str(item)) if isinstance(item, dict) else str(item)

    @staticmethod
    def _error_text(error):
        """One line for the user, including GeoServer's own explanation.

        The library calls raise_for_status(), and HTTPError stringifies to
        "500 Server Error:  for url: …" — dropping the body, which is exactly
        where GeoServer puts the reason ("Unable to delete layer referenced by
        layer group 'tasmania'"). TODO(#50): a library that raised with the
        body would make this unnecessary.
        """
        response = getattr(error, "response", None)
        body = (getattr(response, "text", "") or "").strip()
        # Skip HTML error pages: a Tomcat stack trace is not an explanation
        if body and not body.startswith("<") and body not in str(error):
            return f"{error}: {body.splitlines()[0][:300]}"
        return str(error)

    def _require_connection(self):
        """True when there is a client to talk to; otherwise say so and refuse.

        A loaded table outlives the connection it came from: refresh_ui()
        clears self.gs the moment it starts and the probe that sets it again
        runs in a QgsTask, so for that window — up to _PROBE_TIMEOUT against a
        server that has gone away — the rows and their buttons are still on
        screen and clickable. Every user-triggered action passes through here,
        which is why the check lives at the four places actions are dispatched
        rather than in each of the twenty methods behind them.
        """
        if self.gs is not None:
            return True
        self.show_warning_message(
            self.tr("Not connected to GeoServer — press Refresh (F5) to connect.")
        )
        return False

    def _run_action(self, action, failure_message):
        """Run a server action under a wait cursor and report if it fails.

        Every add / edit / delete / load used to spell this out by hand. On an
        exception the message bar gets "<failure_message>: <error>", the QGIS
        log gets the same, and False comes back so the caller can stop.
        """
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            action()
            return True
        except Exception as e:
            detail = self._error_text(e)
            self.show_error_message(f"{failure_message}: {detail}")
            self.log(
                f"{failure_message}: {detail}", log_level=Qgis.MessageLevel.Critical
            )
            return False
        finally:
            self.unsetCursor()

    def _fetch(self, action, failure_message):
        """_run_action for reads: return the value, or None after reporting."""
        result = []
        if self._run_action(lambda: result.append(action()), failure_message):
            return result[0]
        return None

    def _raw_rest(self, method, path, **kwargs):
        """Call the REST client directly for what geoservercloud has no method for.

        Raises with GeoServer's own response body on any HTTP error, so the
        message the user sees is the same shape as _check's. Every caller is a
        library gap: list it in issue #50 and mark the call site TODO(#50).
        """
        response = getattr(self.gs.rest_service.rest_client, method)(path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
        return response

    def _resource_exists(self, getter, *args):
        """True when a GET for the resource returns 200, False on 404.

        The library's create_* calls are upserts (POST, then PUT on conflict),
        so an "Add" form has to refuse a name that is already taken — otherwise
        it silently overwrites a live resource and reports success. TODO(#50):
        an exist_ok=False option upstream would make this unnecessary.
        """
        _, status_code = getter(*args)
        return status_code == 200

    def _fetch_list(self, api_method, *args):
        """Call a geoservercloud list endpoint and return the list.

        Raises on HTTP errors and on a payload that is not a list — a proxy
        login page or an error document must surface, not render as an empty
        table.
        """
        result = self._check(api_method(*args))
        if not isinstance(result, list):
            raise RuntimeError(
                f"Unexpected response (not a JSON list): {str(result)[:200]}"
            )
        return result

    def _get_workspace_names(self):
        """Workspace names for combo boxes — fetched from the server every time.

        Deliberately not cached: a cache here survived a Refresh on the
        Workspaces tab, so a workspace created in the web UI showed in the list
        but not in the datastore form's combo. One GET per dialog open is
        cheaper than a stale picker.
        """
        return [self._name_of(ws) for ws in self._fetch_list(self.gs.get_workspaces)]

    @staticmethod
    def _fan_out(fn, items, task=None):
        """Run fn(item) for every item on a small thread pool.

        Returns [(result, error)] in input order. A worker that raises yields
        (None, exception) instead of aborting the whole listing, so one broken
        workspace cannot blank the table. Only stateless REST reads belong
        here: GeoServerCloud.wms / .wmts are shared state.

        Given the running task, each finished item reports progress and a
        cancel stops the loop. ponytail: the requests already in flight (up to
        _MAX_PARALLEL_REQUESTS) still run to the end — cancelling means "stop
        after this round", not "abort the sockets".
        """

        def guarded(item):
            try:
                return (fn(item), None)
            except Exception as e:  # reported by the caller, per item
                return (None, e)

        results = []
        with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_REQUESTS) as pool:
            for done, result in enumerate(pool.map(guarded, items), start=1):
                results.append(result)
                if task is not None:
                    # ponytail: a fetch with several fan-outs sweeps the
                    # progress bar once per stage; the task bar can live with it.
                    task.setProgress(100 * done / len(items))
                    if task.isCanceled():
                        break
        return results

    def _report_partial_failures(self, failures):
        """One warning banner for the items a listing could not fetch.

        :param failures: list of (label, exception); details go to the QGIS log.
        """
        if not failures:
            return
        for label, error in failures:
            self.log(
                f"Could not list {label}: {error}", log_level=Qgis.MessageLevel.Warning
            )
        shown = ", ".join(label for label, _ in failures[:5])
        if len(failures) > 5:
            shown += ", …"
        self.show_warning_message(
            self.tr("{count} item(s) could not be listed: {names}").format(
                count=len(failures), names=shown
            )
        )

    def _confirm_delete(self, kind, labels, cascade=""):
        """Ask before deleting one or more resources of one kind.

        :param kind: human-readable type (e.g. "workspace").
        :param labels: names of the resources about to be deleted.
        :param cascade: what else the deletion takes with it — both delete
            paths send recurse=true, so the user has to be told.
        """
        if len(labels) == 1:
            question = self.tr(
                "Are you sure you want to delete {kind} '{name}'?"
            ).format(kind=kind, name=labels[0])
        else:
            question = self.tr(
                "Are you sure you want to delete {count} {kind}(s)?\n\n{items}"
            ).format(
                count=len(labels),
                kind=kind,
                items="\n".join(f"  • {label}" for label in labels),
            )
        reply = QMessageBox.warning(
            self,
            self.tr("Confirm Delete"),
            f"{question}\n\n{cascade}" + self.tr("This action cannot be undone."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _delete_many(self, kind, labeled_deletes, reload_fn, cascade=""):
        """Confirm and run one or more deletions, then reload the table.

        :param kind: human-readable resource type (e.g. "workspace").
        :param labeled_deletes: list of (label, zero-arg callable) pairs.
        :param reload_fn: called afterwards to refresh the table.
        :param cascade: sentence naming what else goes, for the confirmation.
        """
        if not labeled_deletes:
            return
        labels = [label for label, _ in labeled_deletes]
        if not self._confirm_delete(kind, labels, cascade):
            return

        errors = []

        def delete_all():
            for label, delete_fn in labeled_deletes:
                try:
                    delete_fn()
                except Exception as e:
                    detail = self._error_text(e)
                    errors.append(f"{label}: {detail}")
                    self.log(
                        f"Delete {kind} error ({label}): {detail}",
                        log_level=Qgis.MessageLevel.Critical,
                    )

        self._run_action(delete_all, self.tr("Delete failed"))
        if errors:
            self.show_error_message(
                self.tr("Failed to delete some {kind}(s):\n{errors}").format(
                    kind=kind, errors="\n".join(errors)
                )
            )
        elif len(labels) == 1:
            self.show_success_message(
                self.tr("{kind} '{name}' deleted.").format(
                    kind=kind.capitalize(), name=labels[0]
                )
            )
        else:
            self.show_success_message(
                self.tr("{count} {kind}(s) deleted.").format(
                    count=len(labels), kind=kind
                )
            )
        reload_fn()

    # -- Dialog actions ----------------------------------------------------

    def _edit_credentials(self):
        """Open the plugin's settings page."""
        if self.iface:
            self.hide()
            self.iface.showOptionsDialog(currentPage=f"mOptionsPage{__title__}")
            self.refresh_ui(show_message=True)
            self.show()
