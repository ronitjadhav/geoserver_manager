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
from geoserver_manager.gui.tab_cascaded import CascadedStoreTabMixin
from geoserver_manager.gui.tab_coveragestores import CoverageStoreTabMixin
from geoserver_manager.gui.tab_datastores import DatastoreTabMixin
from geoserver_manager.gui.tab_gwc import GwcTabMixin
from geoserver_manager.gui.tab_layergroups import LayerGroupTabMixin
from geoserver_manager.gui.tab_layers import LayerTabMixin
from geoserver_manager.gui.tab_styles import StyleTabMixin
from geoserver_manager.gui.tab_workspaces import WorkspaceTabMixin
from geoserver_manager.gui.theme import status_colour
from geoserver_manager.toolbelt.log_handler import PlgLogger
from geoserver_manager.toolbelt.payload import as_list, name_of, unwrap
from geoserver_manager.toolbelt.preferences import PlgOptionsManager
from geoserver_manager.toolbelt.probe import probe
from geoserver_manager.toolbelt.rest import raw_rest, summarise_body

# Listing a nested resource needs one GET per parent plus one per item. Eight
# parallel requests keep that bearable. They run inside a _FetchTask, so they
# never block the GUI thread.
_MAX_PARALLEL_REQUESTS = 8
_UNSAFE_IN_NAMES = "/?#%\\"

# The connection probe is the request the user waits for before anything is on
# screen, so it gets its own short ceiling. The library cannot do this: its
# RestClient hardcodes timeout=TIMEOUT (120 s) — see _probe and issue #50.


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
    CascadedStoreTabMixin,
    LayerTabMixin,
    LayerGroupTabMixin,
    StyleTabMixin,
    GwcTabMixin,
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
        self._columns = []  # headers of the table as set up
        self._sort = None  # (column, descending) applied to _filtered_rows
        self._row_actions = []  # list of (icon, tooltip, callback) for action buttons
        self._name_click_callback = None  # callback(row_data) when name is clicked
        self._extra_click_callbacks = {}  # col_header -> callback(row_data)
        self._delete_selected_callback = (
            None  # callback(list[row_data]) for bulk delete
        )

        # Background loading state
        self._task = None  # the running _FetchTask, if any
        self._upload = None  # the running upload task, its own slot: _run_upload
        self._side = None  # a quiet side task (a dialog's legend): _run_quietly
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
        self.resultsTable.horizontalHeader().sectionClicked.connect(
            self._on_header_clicked
        )

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
            # The fifth dispatch point (invariant 10): the button is re-enabled
            # by a selection change even while a Refresh has no client yet.
            if self._require_connection():
                self._delete_selected_callback(self._get_selected_rows())
            return
        super().keyPressEvent(event)

    # -- Settings persistence -----------------------------------------------

    def closeEvent(self, event):
        # A running task would call back into widgets that are on their way out.
        # An upload is left to finish: stopping it mid-body would leave a
        # replaced store without its file (measured, see _run_upload), and the
        # task is visible in QGIS's own task bar with its own Cancel.
        self._closing = True
        self._cancel_load()
        if self._side is not None:
            self._side.cancel()
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
            self.tr("Error"), text, Qgis.MessageLevel.Critical, 0
        )

    def show_warning_message(self, text):
        self.message_bar.pushMessage(
            self.tr("Warning"), text, Qgis.MessageLevel.Warning, 0
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
            raise RuntimeError(f"HTTP {status_code}: {summarise_body(str(content))}")
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
                self.tr(
                    "Could not read the credentials from QGIS's authentication "
                    "database — its master password was probably declined. Open "
                    "Settings and save them again."
                )
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

        The request itself lives in toolbelt/probe.py, shared with the Settings
        page; this reuses the client's own auth and TLS setting.
        """
        client = gs.rest_service.rest_client
        return probe(url, client.auth, client.verifytls)

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
        # Reopened after Close: closeEvent set _closing so a late finish would
        # stay away from dying widgets. A new connection means we are alive
        # again — without this the dialog worked exactly once per QGIS session.
        self._closing = False
        # Stop the running load *before* dropping the client its worker reads.
        self._cancel_load()
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

    def _run_in_task(
        self, failure_message, work, on_success, on_cancel=None, busy_text=None
    ):
        """Run work(task) off the GUI thread, then on_success(result) here.

        Only stateless REST reads belong in work: the client's wms / wmts
        attributes are shared state. A failed run reports itself and calls
        nothing; a cancelled one calls on_cancel(task) when given, else says
        so — which is why every loader resets the table *before* starting a
        task, so an empty table is what either outcome leaves behind. A new
        load supersedes the running one.
        """
        self._cancel_load()

        def cancelled(task):
            if on_cancel is not None:
                on_cancel(task)
            elif task.user_cancelled:
                self.show_warning_message(self.tr("Loading cancelled."))

        self._launch_task(
            "_task", failure_message, work, on_success, cancelled, busy_text=busy_text
        )

    def _run_quietly(self, failure_message, work, on_success):
        """Run work(task) in a slot of its own, without the table's loading state.

        For a side fetch — a dialog's legend — that must neither supersede a
        running load nor turn Refresh into Cancel. A failure is still reported.
        """
        if self._side is not None:
            self._side.cancel()
        self._launch_task(
            "_side", failure_message, work, on_success, lambda task: None, quiet=True
        )

    def _run_upload(self, failure_message, work, on_success, on_cancel):
        """Stream a long PUT off the GUI thread, with progress and Cancel.

        `work(task)` runs in a worker: give it everything it needs as
        arguments — the REST client above all, because a Refresh clears
        `self.gs` while it runs — and hand `task.setProgress` /
        `task.isCanceled` to a `toolbelt.rest.ProgressReader` so the task bar
        moves and Cancel aborts the transfer instead of waiting for it. Unlike
        a load it is not superseded: a tab switch or F5 cancels `_task` only,
        and it does not touch the table — `on_success` reloads through
        `_reload_current_tab()` if it wants to, because the user may be on
        another tab by then. `on_cancel(task)` is where the caller says what
        the server was left with; measured for the raster upload, that is
        nothing for a new store and a store *without its file* for a replaced
        one, which is also why closing the dialog lets an upload finish.
        One upload at a time: a second is refused with a warning.
        """
        if self._upload is not None:
            self.show_warning_message(
                self.tr("An upload is already running — wait for it or cancel it.")
            )
            return False
        self._launch_task(
            "_upload",
            failure_message,
            work,
            on_success,
            on_cancel,
            busy_text=self.tr("Uploading…"),
        )
        return True

    def _launch_task(
        self,
        slot,
        failure_message,
        work,
        on_success,
        on_cancel,
        busy_text=None,
        quiet=False,
    ):
        """Park a _FetchTask in `slot` ("_task" or "_upload") and start it.

        The two slots never cancel each other. `finished` comes back on the
        GUI thread: a cancel — the user's, a superseding load's, or our own
        abort raised inside the worker — goes to on_cancel, an exception is
        reported, anything else is on_success(result).
        """

        def finished(task, ok, result, error):
            if getattr(self, slot) is not task:
                # A newer task took over the slot: that one owns the table and
                # the Cancel button now.
                if slot == "_upload" and error is not None:
                    self.log(
                        f"{failure_message}: {self._error_text(error)}",
                        log_level=Qgis.MessageLevel.Critical,
                    )
                return
            # Free the slot even when the dialog is closing — a slot left
            # occupied is what kept a reopened dialog on "Cancel" for good.
            setattr(self, slot, None)
            if self._closing:
                if error is not None:
                    self.log(
                        f"{failure_message}: {self._error_text(error)}",
                        log_level=Qgis.MessageLevel.Critical,
                    )
                return
            if not quiet:
                self._set_loading(self._loading())
            if task.isCanceled():
                on_cancel(task)
                return
            if error is not None:
                detail = self._error_text(error)
                self.show_error_message(f"{failure_message}: {detail}")
                self.log(
                    f"{failure_message}: {detail}", log_level=Qgis.MessageLevel.Critical
                )
                return
            if ok:
                on_success(result)

        task = _FetchTask(failure_message, work, finished)
        setattr(self, slot, task)
        if not quiet:
            self._set_loading(True, busy_text)
        QgsApplication.taskManager().addTask(task)

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
        """Cancel the running load, if any. `user` marks the Cancel button.

        The button stops a running upload first — that is the transfer the
        user sees a bar for — and only a user does: a superseding load
        (`user=False`) never touches an upload.
        """
        if user and self._upload is not None:
            self._upload.user_cancelled = True
            self._upload.cancel()
            return
        if self._task is not None:
            self._task.user_cancelled = user
            self._task.cancel()

    def _loading(self):
        """True while a background load or an upload is running."""
        return self._task is not None or self._upload is not None

    def _set_loading(self, loading, busy_text=None):
        """Say that a task is running, and offer Cancel in place of Refresh."""
        self.btn_refresh.setText(self.tr("Cancel") if loading else self.tr("Refresh"))
        if not loading:
            tooltip = self.tr("Refresh resources from the GeoServer (F5)")
        elif self._upload is not None:
            tooltip = self.tr("Cancel the upload")
        else:
            tooltip = self.tr("Stop loading")
        self.btn_refresh.setToolTip(tooltip)
        if loading:
            self.lbl_page_info.setText(busy_text or self.tr("Loading…"))
        elif not self._all_rows:
            self.lbl_page_info.setText(self._empty_state_text())
        else:
            # An upload borrowed the label while the rows stayed on screen.
            self.lbl_page_info.setText(self._page_info_text())

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
        ("Cascaded Stores", "mIconWms.svg", "_load_cascaded_stores"),
        ("Layers", "mIconVector.svg", "_load_layers"),
        ("Layer Groups", "mActionAddGroup.svg", "_load_layer_groups"),
        ("Styles", "mActionStyleManager.svg", "_load_styles"),
        ("Tile Cache", "mActionAddXyzLayer.svg", "_load_gwc_layers"),
    )

    def _tab_help(self):
        """One line per tab for its tooltip — GeoServer's words, not REST's.

        Keyed by the TABS label, which stays untranslated (invariant 11).
        """
        return {
            "Workspaces": self.tr(
                "Namespaces that group stores, layers and styles; one is the default."
            ),
            "Datastores": self.tr(
                "Vector sources — databases and files on the server — that layers "
                "are published from."
            ),
            "Coverage Stores": self.tr(
                "Raster sources: GeoTIFFs, COGs and image mosaics."
            ),
            "Cascaded Stores": self.tr(
                "WMS and WMTS stores that proxy another server's layers."
            ),
            "Layers": self.tr(
                "Everything published — vector, raster and cascaded — with its "
                "store and default style."
            ),
            "Layer Groups": self.tr("Several layers served as one, in drawing order."),
            "Styles": self.tr(
                "SLD (or CSS, MBStyle) definitions, global or per workspace."
            ),
            "Tile Cache": self.tr(
                "What GeoWebCache caches: tiles per layer, gridset and format."
            ),
        }

    def _setup_nav(self):
        """Build the navigation list on the left from TABS."""
        self.navList.clear()
        for label, icon, _loader in self.TABS:
            item = QListWidgetItem(QIcon(QgsApplication.iconPath(icon)), label)
            item.setToolTip(self._tab_help().get(label, ""))
            self.navList.addItem(item)
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
        self.lbl_page_info.setText(self._empty_state_text())
        for button in (
            self.btn_page_first,
            self.btn_page_prev,
            self.btn_page_next,
            self.btn_page_last,
        ):
            button.setEnabled(False)

    def _on_nav_changed(self, index):
        """Load data for the selected navigation tab."""
        if index < 0:
            return
        if not self.gs:
            # Nothing to load from; the empty table says why instead of
            # looking like an empty server.
            self.lbl_page_info.setText(self._empty_state_text())
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

    def _setup_delete_selected_button(self, callback, text=None):
        """Configure the header Delete Selected button for the current tab.

        :param text: the button's label when the action is not a delete
            (the Tile Cache tab only stops caching).
        """
        self.btn_delete_selected.setText(text or self.tr("Delete Selected"))
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
        # Qt's own sorting stays off: it would reorder the items but not
        # _filtered_rows, which every index-based lookup (selection, Enter, link
        # clicks) reads — Delete would act on a different resource than the one
        # highlighted. A header click sorts the rows themselves instead.
        self.resultsTable.setSortingEnabled(False)
        if list(columns) != self._columns:
            # Another resource type: its columns mean something else.
            self._sort = None
        self._columns = list(columns)
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
        self._show_sort_indicator()

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
        if self._sort is not None:
            column, descending = self._sort

            def sort_key(row):
                value = row[column] if column < len(row) else None
                return ("" if value is None else str(value)).casefold()

            self._filtered_rows.sort(key=sort_key, reverse=descending)
        self._show_sort_indicator()
        self._current_page = 0
        self._show_page()

    def _on_header_clicked(self, column):
        """Sort the rows by this column; a second click reverses the order."""
        is_actions = self._row_actions and column == self.resultsTable.columnCount() - 1
        if not is_actions:
            same = self._sort is not None and self._sort[0] == column
            self._sort = (column, same and not self._sort[1])
        # Re-rendering also puts the indicator back where _sort says, after Qt
        # moved it to the section that was clicked.
        self._apply_filter()

    def _show_sort_indicator(self):
        """Draw the header arrow for _sort, or none."""
        header = self.resultsTable.horizontalHeader()
        header.setSortIndicatorShown(self._sort is not None)
        if self._sort is not None:
            column, descending = self._sort
            order = (
                Qt.SortOrder.DescendingOrder
                if descending
                else Qt.SortOrder.AscendingOrder
            )
            header.setSortIndicator(column, order)

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
        self.lbl_page_info.setText(self._page_info_text())

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

    def _page_info_text(self):
        """The line under the table: which rows are shown, or why there are none."""
        total = len(self._filtered_rows)
        if total == 0:
            return self._empty_state_text()
        start = self._current_page * self._page_size
        return self.tr("Results {} to {} (out of {} items)").format(
            start + 1, min(start + self._page_size, total), total
        )

    def _empty_state_text(self):
        """What an empty table should say: why it is empty, and what helps."""
        if self.gs is None:
            return self.tr("Not connected — press Refresh (F5), or open Settings.")
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
        for action in self._row_actions:
            icon_name, label, callback = action[:3]
            # An optional fourth element says more than the label can — the
            # button is icon-only, so the tooltip is all the user reads.
            tooltip = action[3] if len(action) > 3 else label
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

    # GeoServer's payload shapes, in one place (toolbelt/payload.py); the
    # class attributes win over any copy a mixin still carries.
    _name_of = staticmethod(name_of)
    _unwrap = staticmethod(unwrap)
    _as_list = staticmethod(as_list)

    def _yes_no(self, value):
        """A boolean cell: Yes / No, translated — never Python's True / False."""
        if isinstance(value, str):
            value = value.strip().lower() == "true"
        return self.tr("Yes") if value else self.tr("No")

    def _require_safe_name(self, name):
        """Refuse a name the REST paths cannot carry, before it reaches them.

        `/`, `?`, `#` and `%` change what a URL means — `requests` sends
        `datastores/a#b.json` as `datastores/a`, a different resource — and
        GeoServer itself does not stop them. Every Add form calls this first.
        """
        if not name or name != name.strip() or any(c in name for c in _UNSAFE_IN_NAMES):
            raise ValueError(
                self.tr(
                    "'{}' cannot be used as a name: no slash, '?', '#', '%' or "
                    "leading and trailing spaces."
                ).format(name)
            )

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
        runs in a QgsTask, so for that window — up to the probe's 10 s timeout against a
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
        A worker thread calls `toolbelt.rest.raw_rest` with the client it was
        handed instead: `self.gs` is not its to read.
        """
        return raw_rest(self.gs.rest_service.rest_client, method, path, **kwargs)

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
            self.tr(
                "{count} item(s) could not be listed: {names} — details in the "
                "QGIS log (GeoServer Manager tab)."
            ).format(count=len(failures), names=shown)
        )

    def _confirm_delete(self, kind, labels, cascade="", verb=None):
        """Ask before acting on one or more resources of one kind.

        :param kind: human-readable type (e.g. "workspace"), or "" for none.
        :param labels: names of the resources about to be acted on.
        :param cascade: what else the action takes with it — both delete
            paths send recurse=true, so the user has to be told.
        :param verb: the action, "delete" by default; the Tile Cache tab
            passes "stop caching" and "truncate".
        """
        verb = verb or self.tr("delete")
        if len(labels) == 1:
            subject = f"{kind} '{labels[0]}'" if kind else f"'{labels[0]}'"
            question = self.tr("Are you sure you want to {verb} {subject}?").format(
                verb=verb, subject=subject
            )
        else:
            question = self.tr(
                "Are you sure you want to {verb} {count} {kind}(s)?\n\n{items}"
            ).format(
                verb=verb,
                count=len(labels),
                kind=kind,
                items="\n".join(f"  • {label}" for label in labels),
            )
        # The separator lives here, so a translation cannot glue the sentences.
        parts = [question, cascade.strip(), self.tr("This action cannot be undone.")]
        reply = QMessageBox.warning(
            self,
            self.tr("Please confirm"),
            "\n\n".join(part for part in parts if part),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _delete_many(
        self, kind, labeled_deletes, reload_fn, cascade="", verb=None, done=None
    ):
        """Confirm and run one or more deletions in a task, then reload the table.

        :param kind: human-readable resource type (e.g. "workspace").
        :param labeled_deletes: list of (label, zero-arg callable) pairs.
        :param reload_fn: called afterwards to refresh the table.
        :param cascade: sentence naming what else goes, for the confirmation.
        :param verb: the action for the confirmation ("delete" by default).
        :param done: the past participle for the banner ("deleted" by default).

        The requests run off the GUI thread with progress and Cancel: fifty
        workspaces with recurse=true are minutes, not a wait cursor.
        """
        if not labeled_deletes:
            return
        labels = [label for label, _ in labeled_deletes]
        if not self._confirm_delete(kind, labels, cascade, verb=verb):
            return
        verb = verb or self.tr("delete")
        done = done or self.tr("deleted")

        def delete_all(task):
            errors = []
            for index, (label, delete_fn) in enumerate(labeled_deletes):
                if task is not None and task.isCanceled():
                    break
                try:
                    delete_fn()
                except Exception as e:
                    errors.append((label, self._error_text(e)))
                if task is not None:
                    task.setProgress(100 * (index + 1) / len(labeled_deletes))
            return errors

        def report(errors):
            for label, detail in errors:
                self.log(
                    f"{verb} {kind} error ({label}): {detail}",
                    log_level=Qgis.MessageLevel.Critical,
                )
            if errors:
                self.show_error_message(
                    self.tr("Failed to {verb} some {kind}(s):\n{errors}").format(
                        verb=verb,
                        kind=kind,
                        errors="\n".join(f"{label}: {d}" for label, d in errors),
                    )
                )
            elif len(labels) == 1:
                self.show_success_message(
                    self.tr("{kind} '{name}' {done}.").format(
                        kind=kind.capitalize(), name=labels[0], done=done
                    )
                )
            else:
                self.show_success_message(
                    self.tr("{count} {kind}(s) {done}.").format(
                        count=len(labels), kind=kind, done=done
                    )
                )
            reload_fn()

        def cancelled(_task):
            self.show_warning_message(
                self.tr("Cancelled — what was already done stays done.")
            )
            reload_fn()

        self._run_in_task(
            self.tr("{verb} failed").format(verb=verb.capitalize()),
            delete_all,
            report,
            on_cancel=cancelled,
            busy_text=self.tr("Working…"),
        )

    # -- Dialog actions ----------------------------------------------------

    def _edit_credentials(self):
        """Open the plugin's settings page."""
        if self.iface:
            self.hide()
            self.iface.showOptionsDialog(currentPage=f"mOptionsPage{__title__}")
            self.refresh_ui(show_message=True)
            self.show()

    # -- Uploads shared by the tabs ------------------------------------------

    def _upload_slot_free(self):
        """True when an upload can start; else say so and return False.

        Callers check this *before* exporting: an export can take minutes and
        a refusal after it would leave the exported file behind.
        """
        if self._upload is None:
            return True
        self.show_warning_message(
            self.tr("An upload is already running — wait for it or cancel it.")
        )
        return False

    def _upload_file(
        self,
        failure_message,
        client,
        url,
        source,
        params,
        headers,
        on_success,
        on_cancel,
        folder=None,
        after=None,
    ):
        """Stream one file to a REST path through _run_upload.

        Everything a worker needs is an argument (invariant 9): the client
        held now, the URL, the path of the file. `folder`, when given, is the
        temporary folder holding `source` and is removed however the upload
        ends — including a refusal because another upload runs. `after(client)`
        runs in the worker once the PUT succeeded (a metadata PUT). Returns
        False when nothing was started.
        """
        import shutil

        from geoserver_manager.toolbelt.rest import ProgressReader

        if self._upload is not None:
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
            return self._upload_slot_free()

        def work(task):
            try:
                with open(source, "rb") as handle:
                    body = ProgressReader(
                        handle,
                        source.stat().st_size,
                        on_progress=task.setProgress if task is not None else None,
                        is_cancelled=task.isCanceled if task is not None else None,
                    )
                    raw_rest(
                        client, "put", url, params=params, data=body, headers=headers
                    )
                if after is not None:
                    after(client)
            finally:
                if folder is not None:
                    shutil.rmtree(folder, ignore_errors=True)

        return self._run_upload(failure_message, work, on_success, on_cancel)

    def _report_cancelled_upload(self, kind, tab, exists, name):
        """Say what a cancelled upload left behind — measured on 2.28.5.

        An aborted first upload leaves nothing: no store, no file, whatever
        was already sent. An aborted *Replace* keeps the store, its layer and
        its configuration, but GeoServer has already deleted the previous
        file — a layer with no data behind it — so that one is a warning with
        the way out.

        :param kind: "datastore" / "coverage store", translated by the caller.
        :param tab: the tab to look at, translated by the caller.
        :param exists: zero-arg callable saying whether the store is there;
            anything it raises (a Refresh dropped the client) reads as unknown.
        """
        try:
            kept = exists()
        except Exception:  # the report must not fail the cancel
            kept = None
        if kept:
            message = self.tr(
                "Upload of '{name}' cancelled. GeoServer kept the {kind} and its "
                "layer but had already removed their data file — upload it again "
                "with Replace ticked, or delete the {kind}."
            )
        elif kept is None:
            message = self.tr(
                "Upload of '{name}' cancelled — check the {tab} tab for what was left."
            )
        else:
            message = self.tr(
                "Upload of '{name}' cancelled — nothing was left on the server."
            )
        self.show_warning_message(message.format(name=name, kind=kind, tab=tab))
