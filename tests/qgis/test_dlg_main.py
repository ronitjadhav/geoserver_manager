#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    # for whole tests
    python -m unittest tests.qgis.test_dlg_main
    # for specific test
    python -m unittest tests.qgis.test_dlg_main.TestTableState.test_failed_load_cannot_repaint_previous_rows
"""

# standard library
import time
from unittest.mock import patch

from qgis.PyQt.QtCore import QEventLoop, QTimer
from qgis.PyQt.QtWidgets import QDialog, QPushButton
from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui.dlg_main import GeoServerMainDialog
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_datastores import DatastoreTabMixin
from tests.qgis.sync_dialog import SyncDialog

start_app()

# ############################################################################
# ########## Classes #############
# ################################


class TestTableState(unittest.TestCase):
    """The table is paginated in Python and selections are mapped back by row
    index, so the row cache and what is on screen must never disagree.
    """

    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg._setup_table(["Workspace Name", "Actions"])
        self.dlg._populate_rows([[f"ws{i:02d}"] for i in range(25)])

    def test_selection_maps_to_the_right_row_across_pages(self):
        self.assertEqual(self.dlg._total_pages, 2)

        self.dlg.resultsTable.selectRow(3)
        self.assertEqual(self.dlg._get_selected_rows(), [["ws03"]])

        self.dlg._page_next()
        self.dlg.resultsTable.selectRow(0)
        self.assertEqual(self.dlg._get_selected_rows(), [["ws20"]])

    def test_filter_narrows_rows_and_resets_to_first_page(self):
        self.dlg._page_next()
        self.dlg.searchBox.setText("ws1")
        self.dlg._apply_filter()

        self.assertEqual(len(self.dlg._filtered_rows), 10)
        self.assertEqual(self.dlg._current_page, 0)
        self.assertEqual(self.dlg._total_pages, 1)

    def test_failed_load_cannot_repaint_previous_rows(self):
        """A loader arms the new tab's callbacks and headers, then fetches. If
        that fetch raises, the previous resource type's rows must be gone -
        otherwise search or pagination repaints them under the new tab's
        delete handler, and Delete targets the wrong resource.
        """
        # what a loader does before its (here: failing) network call
        self.dlg._setup_table(["Datastore Name", "Workspace", "Type", "Actions"])

        self.assertEqual(self.dlg._all_rows, [])
        self.assertEqual(self.dlg._filtered_rows, [])
        self.assertEqual(self.dlg._current_page, 0)

        # the debounced search timer fires on every tab switch
        self.dlg._apply_filter()
        self.assertEqual(self.dlg.resultsTable.rowCount(), 0)
        self.assertEqual(self.dlg._get_selected_rows(), [])

    def test_reset_clears_callbacks_and_pagination(self):
        self.dlg._name_click_callback = lambda row: None
        self.dlg._delete_selected_callback = lambda rows: None
        self.dlg._extra_click_callbacks = {"Workspace": lambda row: None}
        self.dlg._row_actions = [("icon.svg", "Delete", lambda row: None)]

        self.dlg._reset_table_state()

        self.assertIsNone(self.dlg._name_click_callback)
        self.assertIsNone(self.dlg._delete_selected_callback)
        self.assertEqual(self.dlg._extra_click_callbacks, {})
        self.assertEqual(self.dlg._row_actions, [])
        self.assertFalse(self.dlg.btn_page_next.isEnabled())
        self.assertFalse(self.dlg.btn_delete_selected.isVisible())


class TestDatastoreUpdate(unittest.TestCase):
    """Editing a datastore must not discard configuration it does not show."""

    STORED = {
        "host": "db.example.org",
        "port": "5432",
        "database": "gis",
        "user": "geo",
        "passwd": "crypt1:SECRET",
        "schema": "public",
        # none of these are on the form, all of them must survive an edit
        "max connections": "20",
        "Loose bbox": "false",
        "preparedStatements": "true",
        "namespace": "http://custom.example.org/ns",
        "Expose primary keys": "false",
    }

    def setUp(self):
        self.dlg = SyncDialog()
        self.captured = {}

        class FakeGS:
            def create_datastore(inner, **kwargs):
                self.captured.update(kwargs)
                return ("ok", 200)

        self.dlg.gs = FakeGS()

    def test_edit_preserves_unmodelled_parameters_and_disabled_state(self):
        detail = {"type": "PostGIS", "enabled": False}
        values = {
            "workspace": "ws",
            "name": "store",
            "description": "new description",
            "pg_host": "db.example.org",
            "pg_port": 5432,
            "pg_db": "gis",
            "pg_user": "geo",
            "pg_password": "typed-again",
            "pg_schema": "public",
        }

        self.dlg._update_datastore_from_values(values, detail, self.STORED)
        params = self.captured["connection_parameters"]

        # the form owns these
        self.assertEqual(params["passwd"], "typed-again")
        self.assertEqual(self.captured["description"], "new description")
        # the server owns these - they must come back unchanged
        self.assertEqual(params["max connections"], "20")
        self.assertEqual(params["Loose bbox"], "false")
        self.assertEqual(params["preparedStatements"], "true")
        self.assertEqual(params["namespace"], "http://custom.example.org/ns")
        self.assertEqual(params["Expose primary keys"], "false")
        # a disabled store must not be silently re-enabled
        self.assertFalse(self.captured["enabled"])
        # and the type comes from the server, not the combo box
        self.assertEqual(self.captured["datastore_type"], "PostGIS")

    def test_pmtiles_edit_keeps_its_range_reader_config(self):
        stored = {
            "pmtiles": "s3://bucket/tiles.pmtiles",
            "io.tileverse.rangereader.provider": "s3",
            "io.tileverse.rangereader.caching.enabled": "true",
        }
        detail = {"type": "PMTiles", "enabled": True}
        values = {
            "workspace": "ws",
            "name": "tiles",
            "description": "",
            "pmtiles_url": "s3://bucket/tiles.pmtiles",
        }

        self.dlg._update_datastore_from_values(values, detail, stored)
        params = self.captured["connection_parameters"]

        # "file" here would make the store unable to open its own data
        self.assertEqual(params["io.tileverse.rangereader.provider"], "s3")

    def test_prefill_comes_from_the_server_and_never_includes_the_password(self):
        detail = {"type": "PostGIS", "description": "prod"}
        values = self.dlg._datastore_form_values(
            "ws", "store", "PostGIS", detail, self.STORED
        )

        self.assertEqual(values["pg_host"], "db.example.org")
        self.assertEqual(values["pg_port"], 5432)
        self.assertEqual(values["description"], "prod")
        self.assertEqual(values["pg_password"], "")  # crypt1:SECRET must not leak in
        self.assertEqual(values["type"], "PostGIS")

    def test_prefill_keeps_the_real_type_and_dumps_the_parameters(self):
        stored = {"url": "file:data/shapes", "passwd": "crypt1:SECRET"}
        values = self.dlg._datastore_form_values("ws", "shp", "Shapefile", {}, stored)
        self.assertEqual(values["type"], "Shapefile")  # never shown as PostGIS
        self.assertEqual(values["pg_port"], 5432)
        self.assertIn("url = file:data/shapes", values["raw_params"])
        self.assertNotIn("SECRET", values["raw_params"])  # secrets masked

    def test_connection_params_tolerates_odd_payloads(self):
        self.assertEqual(self.dlg._connection_params("not a dict"), {})
        self.assertEqual(self.dlg._connection_params({}), {})
        self.assertEqual(
            self.dlg._connection_params(
                {"connectionParameters": {"entry": {"host": "h"}}}
            ),
            {"host": "h"},
        )

    def test_refuses_to_update_when_the_server_reports_no_type(self):
        with self.assertRaises(RuntimeError):
            self.dlg._update_datastore_from_values(
                {"workspace": "ws", "name": "store"}, {}, {}
            )


class TestListingTolerance(unittest.TestCase):
    """One broken workspace must cost one warning, not the whole table."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.warnings = []
        self.dlg.show_warning_message = self.warnings.append
        self.dlg.show_error_message = lambda t: self.fail(f"unexpected error: {t}")

        class FakeGS:
            def get_workspaces(inner):
                return ([{"name": "ok1"}, {"name": "broken"}, {"name": "ok2"}], 200)

            def get_datastores(inner, ws):
                if ws == "broken":
                    raise RuntimeError("HTTP 500: boom")
                return ([{"name": f"{ws}_ds"}], 200)

            def get_datastore(inner, ws, ds):
                return ({"type": "PostGIS", "enabled": True}, 200)

        self.dlg.gs = FakeGS()

    def test_fan_out_keeps_order_and_captures_errors(self):
        def fn(x):
            if x == 2:
                raise ValueError("two")
            return x * 10

        results = self.dlg._fan_out(fn, [1, 2, 3])
        self.assertEqual([r for r, _ in results], [10, None, 30])
        self.assertIsInstance(results[1][1], ValueError)

    def test_one_failing_workspace_leaves_the_others_and_warns_once(self):
        self.dlg._load_datastores()

        names = sorted(row[0] for row in self.dlg._all_rows)
        self.assertEqual(names, ["ok1_ds", "ok2_ds"])
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("broken", self.warnings[0])

    def test_report_partial_failures_is_silent_when_nothing_failed(self):
        self.dlg._report_partial_failures([])
        self.assertEqual(self.warnings, [])


# ############################################################################
# ####### Probe fakes ############
# ################################


class ProbeResponse:
    """What requests.get gives the probe."""

    def __init__(self, status_code=200, payload=None, html=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"workspaces": ""}
        self._html = html

    def json(self):
        if self._html:
            raise ValueError("no JSON object could be decoded")
        return self._payload


class ProbeGS:
    """Only what _probe reads off the client: its auth and TLS setting."""

    class rest_service:
        class rest_client:
            auth = ("admin", "geoserver")
            verifytls = True


def patched_requests_get(response=None, raises=None, recorder=None):
    """A stand-in for requests.get that records its kwargs."""

    def fake_get(url, **kwargs):
        if recorder is not None:
            recorder.append((url, kwargs))
        if raises is not None:
            raise raises
        return response if response is not None else ProbeResponse()

    return fake_get


class TestNonJsonResponses(unittest.TestCase):
    """A proxy login page answers 200 with HTML; that is not 'Connected'."""

    def setUp(self):
        self.dlg = SyncDialog()

    def test_fetch_list_refuses_a_non_list_payload(self):
        with self.assertRaises(RuntimeError):
            self.dlg._fetch_list(lambda: ("<html>login</html>", 200))

    def test_probe_rejects_html_with_status_200(self):
        with patch("requests.get", patched_requests_get(ProbeResponse(html=True))):
            problem = self.dlg._probe(ProbeGS(), "http://proxy.example.org/geoserver")
        self.assertIsNotNone(problem)
        status, _message = problem
        self.assertIn("Not a GeoServer", status)

    def test_probe_accepts_a_workspaces_payload(self):
        payload = {"workspaces": {"workspace": [{"name": "topp"}]}}
        with patch(
            "requests.get", patched_requests_get(ProbeResponse(payload=payload))
        ):
            self.assertIsNone(self.dlg._probe(ProbeGS(), "http://gs"))

    def test_probe_reports_bad_credentials_as_such(self):
        with patch(
            "requests.get", patched_requests_get(ProbeResponse(status_code=401))
        ):
            status, message = self.dlg._probe(ProbeGS(), "http://gs")
        self.assertIn("Authentication", status)
        self.assertIn("password", message)

    def test_probe_gives_up_long_before_the_librarys_timeout(self):
        """A host that swallows the SYN must not hold the dialog for 120 s."""
        calls = []
        with patch("requests.get", patched_requests_get(recorder=calls)):
            self.dlg._probe(ProbeGS(), "http://gs/geoserver/")
        url, kwargs = calls[0]
        self.assertEqual(url, "http://gs/geoserver/rest/workspaces.json")
        self.assertLessEqual(kwargs["timeout"], 10)
        self.assertEqual(kwargs["auth"], ("admin", "geoserver"))
        self.assertIs(kwargs["verify"], True)


class TestDefaultWorkspaceHandling(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.warnings, self.calls = [], []
        self.dlg.show_warning_message = self.warnings.append

        outer = self

        class FakeGS:
            def get_workspace(inner, name):
                return ({"name": name}, 404)

            def create_workspace(inner, name, isolated=False):
                outer.calls.append(("create", name))
                return ("", 201)

        self.dlg.gs = FakeGS()

    def test_set_default_failure_does_not_fail_the_save(self):
        def boom(name):
            raise RuntimeError("HTTP 403: forbidden")

        self.dlg._set_default_workspace = boom
        ok = self.dlg._run_action(
            lambda: self.dlg._save_workspace(
                {"name": "ws", "isolated": False, "set_default": True}
            ),
            "Failed to create workspace 'ws'",
        )

        self.assertTrue(ok)  # the create itself succeeded and is reported so
        self.assertEqual(self.calls, [("create", "ws")])
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("could not be made the default", self.warnings[0])

    def test_default_workspace_name_is_none_when_unreadable(self):
        self.assertIsNone(
            self.dlg._default_workspace_name()
        )  # FakeGS has no REST client

    def test_default_flag_locks_the_checkbox_field(self):
        field = [
            f
            for f in self.dlg._workspace_fields(is_default=True)
            if f["key"] == "set_default"
        ][0]
        self.assertTrue(field["read_only"])
        field = [f for f in self.dlg._workspace_fields() if f["key"] == "set_default"][
            0
        ]
        self.assertFalse(field["read_only"])


class TestServerSync(unittest.TestCase):
    """What the dialog shows must come from the server, not from a cache."""

    def setUp(self):
        self.dlg = SyncDialog()
        outer = self
        self.calls = 0

        class FakeResponse:
            status_code = 200

            def json(inner):
                return {"workspace": {"name": "topp"}}

        class FakeClient:
            def get(inner, path, **kwargs):
                return FakeResponse()

        class FakeEndpoints:
            base_url = "/rest"

        class FakeRest:
            rest_endpoints = FakeEndpoints()
            rest_client = FakeClient()

        class FakeGS:
            rest_service = FakeRest()

            def get_workspaces(inner):
                outer.calls += 1
                return ([{"name": "cite"}, {"name": "topp"}], 200)

        self.dlg.gs = FakeGS()

    def test_workspace_names_are_fetched_on_every_call(self):
        self.dlg._get_workspace_names()
        self.dlg._get_workspace_names()
        self.assertEqual(self.calls, 2)  # no cache to go stale

    def test_workspace_list_marks_the_servers_default(self):
        self.dlg._load_workspaces()
        rows = {row[0]: row[1] for row in self.dlg._all_rows}
        self.assertEqual(rows["topp"], "default")
        self.assertEqual(rows["cite"], "")
        # column 0 is still the name: delete / edit callbacks rely on it
        self.assertEqual([row[0] for row in self.dlg._all_rows], ["cite", "topp"])


class TestUnsupportedTypeDialog(unittest.TestCase):
    """A type without dedicated fields gets the generic key = value editor."""

    def test_dialog_locks_the_type_and_offers_the_parameter_editor(self):
        from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox

        from geoserver_manager.gui import tab_datastores
        from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

        opened = []

        class Recording(ResourceFormDialog):
            def exec(self):
                opened.append(self)
                return QDialog.DialogCode.Rejected

        class FakeGS:
            def get_workspaces(inner):
                return ([{"name": "topp"}], 200)

            def get_datastore(inner, ws, ds):
                return (
                    {
                        # A type the form has no dedicated fields for: those
                        # are what the generic editor is for.
                        "type": "Web Feature Server (NG)",
                        "enabled": True,
                        "connectionParameters": {
                            "entry": {
                                "WFSDataStoreFactory:GET_CAPABILITIES_URL": (
                                    "http://other/geoserver/wfs?request=GetCapabilities"
                                )
                            }
                        },
                    },
                    200,
                )

        dlg = SyncDialog()
        dlg.gs = FakeGS()
        with patch.object(tab_datastores, "ResourceFormDialog", Recording):
            dlg._show_datastore_info(
                ["cascaded", "topp", "Web Feature Server (NG)", "True"]
            )

        self.assertEqual(len(opened), 1)
        form = opened[0]
        combo = form.get_widget("type")
        self.assertEqual(combo.currentText(), "Web Feature Server (NG)")
        self.assertFalse(combo.isEnabled())
        for key in ("pg_host", "pg_password", "jndi_reference", "pmtiles_url"):
            self.assertIn(key, form._hidden_keys)
        self.assertNotIn("raw_params", form._hidden_keys)
        editor = form.get_widget("raw_params")
        self.assertIn("WFSDataStoreFactory:GET_CAPABILITIES_URL", editor.toPlainText())
        self.assertFalse(editor.isReadOnly())  # it is an editor, not a view
        save = form._button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(save.isHidden())  # any type can be saved now


class TestLinkCells(unittest.TestCase):
    """Name cells open the resource but must stay real, selectable items."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = object()  # a click needs a connection; see TestConnectionGuard
        self.opened = []
        self.dlg._name_click_callback = self.opened.append
        self.dlg._extra_click_callbacks = {
            "Workspace": lambda row: self.opened.append(("ws", row))
        }
        self.dlg._setup_table(["Name", "Workspace", "Type", "Actions"])
        self.dlg._row_actions = [
            ("mActionDeleteSelected.svg", "Delete", lambda r: None)
        ]
        self.dlg._populate_rows([[f"ds{i:02d}", "topp", "PostGIS"] for i in range(25)])

    def test_link_cells_are_items_not_widgets(self):
        table = self.dlg.resultsTable
        self.assertIsNone(table.cellWidget(0, 0))
        self.assertEqual(table.item(0, 0).text(), "ds00")
        self.assertTrue(table.item(0, 0).font().underline())  # styled as a link
        self.assertFalse(table.item(0, 2).font().underline())  # plain data cell

    def test_rows_are_selectable_by_clicking_any_cell(self):
        self.dlg.resultsTable.setCurrentCell(
            3, 0
        )  # what a mouse press on the name does
        self.assertEqual(self.dlg._get_selected_rows(), [["ds03", "topp", "PostGIS"]])
        self.assertTrue(
            self.dlg.btn_delete_selected.isEnabled()
            or self.dlg._delete_selected_callback is None
        )

    def test_click_on_a_link_cell_opens_the_row_resource(self):
        self.dlg._on_cell_clicked(1, 0)
        self.assertEqual(self.opened, [["ds01", "topp", "PostGIS"]])
        self.dlg._on_cell_clicked(1, 1)  # extra link column
        self.assertEqual(self.opened[-1], ("ws", ["ds01", "topp", "PostGIS"]))

    def test_click_on_a_plain_cell_does_nothing(self):
        self.dlg._on_cell_clicked(1, 2)
        self.assertEqual(self.opened, [])

    def test_click_respects_the_current_page(self):
        self.dlg._page_next()
        self.dlg._on_cell_clicked(0, 0)
        self.assertEqual(self.opened, [["ds20", "topp", "PostGIS"]])


class TestTlsVerification(unittest.TestCase):
    """A certificate problem is named as such, and the setting reaches the client."""

    def test_probe_names_a_certificate_problem(self):
        import requests

        error = requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")
        with patch("requests.get", patched_requests_get(raises=error)):
            status, message = SyncDialog()._probe(ProbeGS(), "https://gs.example.org")
        self.assertIn("Certificate", status)
        self.assertNotIn("is the server running", message)
        self.assertIn("Verify the server", message)  # points at the setting

    def test_build_client_passes_the_setting_through(self):
        import sys
        import types

        seen = {}

        class FakeGeoServerCloud:
            def __init__(inner, **kwargs):
                seen.update(kwargs)

        fake = types.ModuleType("geoservercloud")
        fake.GeoServerCloud = FakeGeoServerCloud

        class Settings:
            geoserver_url = "https://gs.example.org"
            geoserver_verify_tls = False

            def has_credentials(inner):
                return True

            def get_credentials(inner):
                return ("admin", "secret")

        with patch.dict(sys.modules, {"geoservercloud": fake}):
            SyncDialog()._build_client(Settings())
        self.assertIs(seen["verifytls"], False)
        self.assertEqual(seen["url"], "https://gs.example.org")


class TestGenericParameterEditor(unittest.TestCase):
    """Any datastore type is editable through 'key = value' lines."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.sent = {}
        outer = self

        class FakeGS:
            def create_datastore(inner, **kwargs):
                outer.sent.update(kwargs)
                return ("ok", 200)

        self.dlg.gs = FakeGS()

    def test_parse_round_trips_and_ignores_noise(self):
        text = "url = file:data/shapes\n\n# a comment\ncharset = UTF-8\nkey with = sign = a=b\n"
        self.assertEqual(
            self.dlg._parse_params(text),
            {"url": "file:data/shapes", "charset": "UTF-8", "key with": "sign = a=b"},
        )

    def test_parse_rejects_a_line_without_equals(self):
        with self.assertRaises(ValueError) as ctx:
            self.dlg._parse_params("url = ok\njust words\n")
        self.assertIn("Line 2", str(ctx.exception))

    def test_editor_is_authoritative_but_keeps_masked_secrets(self):
        stored = {
            "WFSDataStoreFactory:GET_CAPABILITIES_URL": "http://old/wfs",
            "WFSDataStoreFactory:TIMEOUT": "3000",
            "WFSDataStoreFactory:PASSWORD": "crypt1:SECRET",
            "obsolete": "x",
        }
        detail = {"type": "Web Feature Server (NG)", "enabled": False}
        values = {
            "workspace": "topp",
            "name": "cascaded",
            "description": "",
            "raw_params": (
                "WFSDataStoreFactory:GET_CAPABILITIES_URL = http://new/wfs\n"
                "WFSDataStoreFactory:TIMEOUT = 5000\n"
                "WFSDataStoreFactory:PASSWORD = ••••\n"  # 'obsolete' removed
            ),
        }

        self.dlg._update_datastore_from_values(values, detail, stored)

        self.assertEqual(
            self.sent["connection_parameters"],
            {
                "WFSDataStoreFactory:GET_CAPABILITIES_URL": "http://new/wfs",
                "WFSDataStoreFactory:TIMEOUT": "5000",
                "WFSDataStoreFactory:PASSWORD": "crypt1:SECRET",
            },
        )
        self.assertEqual(
            self.sent["datastore_type"], "Web Feature Server (NG)"
        )  # server's type, not the combo
        self.assertIs(self.sent["enabled"], False)  # still disabled

    def test_bad_line_never_reaches_the_server(self):
        with self.assertRaises(ValueError):
            self.dlg._update_datastore_from_values(
                {"workspace": "w", "name": "n", "raw_params": "no equals here"},
                {"type": "Web Feature Server (NG)"},
                {"WFSDataStoreFactory:GET_CAPABILITIES_URL": "http://old/wfs"},
            )
        self.assertEqual(self.sent, {})


class TestErrorText(unittest.TestCase):
    """GeoServer's explanation must reach the user, not just the status line."""

    def _http_error(self, status, body):
        import requests

        response = requests.Response()
        response.status_code = status
        response._content = body.encode()
        return requests.exceptions.HTTPError(
            f"{status} Server Error:  for url: http://gs/rest/x", response=response
        )

    def test_body_is_appended(self):
        error = self._http_error(
            500, "Unable to delete layer referenced by layer group 'tasmania'"
        )
        text = GeoServerMainDialog._error_text(error)
        self.assertIn("layer group 'tasmania'", text)
        self.assertIn("500 Server Error", text)

    def test_html_error_pages_are_skipped(self):
        error = self._http_error(401, "<!doctype html><html><title>401</title></html>")
        self.assertNotIn("doctype", GeoServerMainDialog._error_text(error))

    def test_plain_exceptions_pass_through(self):
        self.assertEqual(GeoServerMainDialog._error_text(ValueError("nope")), "nope")

    def test_delete_failure_shows_the_reason(self):
        dlg = SyncDialog()
        errors = []
        dlg.show_error_message = errors.append
        dlg._confirm_delete = lambda kind, labels, cascade="": True

        def boom():
            raise self._http_error(
                500, "Unable to delete layer referenced by layer group 'x'"
            )

        dlg._delete_many("layer", [("ws/ds/l", boom)], lambda: None)
        self.assertEqual(len(errors), 1)
        self.assertIn("layer group 'x'", errors[0])


# ############################################################################
# ###### Background loading ######
# ################################


class SlowGS:
    """A server that answers correctly, but slowly."""

    def __init__(self, latency=0.2, workspaces=50):
        self.latency = latency
        self.names = [f"ws{index:02d}" for index in range(workspaces)]

    def get_workspaces(self):
        time.sleep(self.latency)
        return ([{"name": name} for name in self.names], 200)

    def get_datastores(self, workspace_name):
        time.sleep(self.latency)
        return ([{"name": f"{workspace_name}_store"}], 200)

    def get_datastore(self, workspace_name, datastore_name):
        time.sleep(self.latency)
        return ({"type": "PostGIS", "enabled": True}, 200)


def spin_until(predicate, timeout_ms=20000):
    """Run the event loop until predicate(); return how often a timer fired.

    A tick proves the GUI thread was free to process events while the load was
    running — which is the whole point of moving loads into a QgsTask.
    """
    ticks = []
    loop = QEventLoop()

    def tick():
        ticks.append(1)
        if predicate():
            loop.quit()

    heartbeat = QTimer()
    heartbeat.setInterval(20)
    heartbeat.timeout.connect(tick)
    guard = QTimer()
    guard.setSingleShot(True)
    guard.setInterval(timeout_ms)
    guard.timeout.connect(loop.quit)
    heartbeat.start()
    guard.start()
    loop.exec()
    heartbeat.stop()
    guard.stop()
    return len(ticks)


class TestBackgroundLoading(unittest.TestCase):
    """The real dialog, the real task manager: loads must not block the GUI."""

    def setUp(self):
        self.dlg = GeoServerMainDialog()  # not SyncDialog: the point is the task
        self.warnings, self.errors = [], []
        self.dlg.show_warning_message = self.warnings.append
        self.dlg.show_error_message = self.errors.append
        self.dlg.show_success_message = lambda text: None

    def tearDown(self):
        self.dlg._closing = True
        self.dlg._cancel_load()

    def test_a_slow_load_keeps_the_dialog_responsive(self):
        """50 workspaces at 200 ms a request: the event loop keeps running."""
        self.dlg.gs = SlowGS(latency=0.2, workspaces=50)
        self.dlg._load_workspaces()

        self.assertEqual(self.dlg._all_rows, [])  # nothing blocks, nothing yet
        self.assertEqual(self.dlg.lbl_page_info.text(), "Loading…")
        self.assertEqual(self.dlg.btn_refresh.text(), "Cancel")

        ticks = spin_until(lambda: bool(self.dlg._all_rows))
        self.assertGreater(ticks, 1)
        self.assertEqual(len(self.dlg._all_rows), 50)
        self.assertEqual(self.dlg.btn_refresh.text(), "Refresh")
        self.assertEqual(self.errors, [])

    def test_cancel_stops_the_load_and_leaves_no_rows(self):
        self.dlg.gs = SlowGS(latency=0.05, workspaces=50)
        self.dlg._load_datastores()  # fans out over every workspace
        spin_until(lambda: self.dlg._task is not None and self.dlg._task.progress() > 0)

        self.dlg._cancel_load(user=True)
        spin_until(lambda: self.dlg._task is None)

        self.assertEqual(self.dlg._all_rows, [])  # never stale rows
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("cancelled", self.warnings[0].lower())
        self.assertEqual(self.dlg.btn_refresh.text(), "Refresh")

    def test_the_refresh_button_cancels_while_loading(self):
        self.dlg.gs = SlowGS(latency=0.05, workspaces=20)
        self.dlg._load_datastores()
        self.assertTrue(self.dlg._loading())

        self.dlg._on_refresh_clicked()  # the same button, now Cancel
        spin_until(lambda: not self.dlg._loading())
        self.assertEqual(self.dlg._all_rows, [])
        self.assertIn("cancelled", self.warnings[0].lower())

    def test_a_failed_fetch_reports_and_leaves_no_rows(self):
        class BrokenGS(SlowGS):
            def get_workspaces(inner):
                raise RuntimeError("HTTP 500: boom")

        self.dlg.gs = BrokenGS(latency=0)
        self.dlg._load_workspaces()
        spin_until(lambda: not self.dlg._loading())

        self.assertEqual(self.dlg._all_rows, [])
        self.assertEqual(len(self.errors), 1)
        self.assertIn("boom", self.errors[0])
        self.assertEqual(self.dlg.lbl_page_info.text(), "No results")

    def test_a_load_that_lands_after_close_touches_nothing(self):
        """The task outlives the dialog; its callback must stay away."""
        self.dlg.gs = SlowGS(latency=0.05, workspaces=20)
        self.dlg._load_datastores()
        task = self.dlg._task
        self.dlg.close()

        spin_until(lambda: task.isCanceled() and self.dlg._task is task)
        self.assertTrue(self.dlg._closing)
        self.assertEqual(self.dlg._all_rows, [])
        self.assertEqual(self.warnings, [])  # not even a banner

    def test_a_second_load_supersedes_the_first(self):
        self.dlg.gs = SlowGS(latency=0.05, workspaces=30)
        self.dlg._load_datastores()
        first = self.dlg._task
        self.dlg._load_workspaces()  # e.g. the user switched tabs
        self.assertIsNot(self.dlg._task, first)
        self.assertTrue(first.isCanceled())

        spin_until(lambda: bool(self.dlg._all_rows))
        self.assertEqual(len(self.dlg._all_rows), 30)  # the workspace rows
        self.assertEqual(self.warnings, [])  # superseding is not "cancelled"

    def test_refresh_does_not_wait_for_the_probe(self):
        """plugin_main shows the dialog and calls this; it must return at once."""

        class Settings:
            geoserver_url = "http://gs.example.org/geoserver"
            geoserver_verify_tls = True
            geoserver_auth_cfg_id = ""

            def has_credentials(inner):
                return True

            def get_credentials(inner):
                return ("admin", "geoserver")

        class PlgSettings:
            def get_plg_settings(inner):
                return Settings()

            def get_value_from_key(inner, *args, **kwargs):
                return None

            def set_value_from_key(inner, *args, **kwargs):
                return True

        self.dlg.plg_settings = PlgSettings()
        self.dlg._build_client = lambda settings: SlowGS(latency=0)
        probed = []

        def slow_probe(gs, url):
            time.sleep(0.3)
            probed.append(url)
            return None

        self.dlg._probe = slow_probe
        self.dlg._fetch_version_label = lambda gs: "GeoServer 2.28.5"

        started = time.monotonic()
        self.dlg.refresh_ui()
        self.assertLess(time.monotonic() - started, 0.2)  # the probe is still running
        self.assertEqual(self.dlg.lbl_status.text(), "Connecting…")

        ticks = spin_until(lambda: bool(probed) and self.dlg.gs is not None)
        self.assertGreater(ticks, 1)
        self.assertIn("Connected", self.dlg.lbl_status.text())
        self.assertIn("2.28.5", self.dlg.lbl_status.text())


class TestFanOutProgress(unittest.TestCase):
    """_fan_out is where progress is reported and a cancel is noticed."""

    class FakeTask:
        def __init__(self, cancel_after=None):
            self.reported = []
            self.cancel_after = cancel_after

        def setProgress(self, value):
            self.reported.append(round(value))

        def isCanceled(self):
            return (
                self.cancel_after is not None
                and len(self.reported) >= self.cancel_after
            )

    def test_progress_is_reported_per_finished_item(self):
        task = self.FakeTask()
        results = GeoServerMainDialog._fan_out(lambda n: n * 2, [1, 2, 3, 4], task)
        self.assertEqual(task.reported, [25, 50, 75, 100])
        self.assertEqual(results, [(2, None), (4, None), (6, None), (8, None)])

    def test_a_cancel_stops_the_loop(self):
        task = self.FakeTask(cancel_after=2)
        results = GeoServerMainDialog._fan_out(lambda n: n * 2, [1, 2, 3, 4], task)
        self.assertEqual(task.reported, [25, 50])
        self.assertEqual(len(results), 2)

    def test_without_a_task_nothing_changes(self):
        results = GeoServerMainDialog._fan_out(lambda n: n * 2, [1, 2])
        self.assertEqual(results, [(2, None), (4, None)])


# ############################################################################
# ##### File-based datastores ####
# ################################


class TestFileStoreParams(unittest.TestCase):
    """The typed fields of a file-based store, as connection parameters."""

    def shapefile(self, **overrides):
        values = {
            "file_url": "file:data/shapefiles/states.shp",
            "charset": "UTF-8",
            "spatial_index": True,
        }
        values.update(overrides)
        return DatastoreTabMixin._file_store_params("Shapefile", values)

    def test_a_shapefile_carries_its_path_charset_and_index_flag(self):
        self.assertEqual(
            self.shapefile(),
            {
                "url": "file:data/shapefiles/states.shp",
                "charset": "UTF-8",
                "create spatial index": "true",
            },
        )

    def test_an_empty_charset_is_left_to_geoserver_rather_than_sent_blank(self):
        # A blank charset is not the same as "use your default".
        self.assertNotIn("charset", self.shapefile(charset=""))
        self.assertNotIn("charset", self.shapefile(charset="   "))

    def test_the_index_flag_is_a_geoserver_style_string_not_a_python_bool(self):
        self.assertEqual(
            self.shapefile(spatial_index=False)["create spatial index"], "false"
        )

    def test_a_directory_store_has_no_index_flag_of_its_own(self):
        params = DatastoreTabMixin._file_store_params(
            "Directory of spatial files (shapefiles)",
            {"file_url": "file:data/taz_shapes", "charset": "", "spatial_index": True},
        )
        self.assertEqual(params, {"url": "file:data/taz_shapes"})

    def test_a_geopackage_always_declares_its_dbtype(self):
        # That parameter is how GeoServer picks the GeoPackage factory.
        params = DatastoreTabMixin._file_store_params(
            "GeoPackage",
            {
                "gpkg_database": "file:data/ne/natural_earth.gpkg",
                "gpkg_read_only": True,
                "gpkg_expose_pk": False,
            },
        )
        self.assertEqual(
            params,
            {
                "database": "file:data/ne/natural_earth.gpkg",
                "dbtype": "geopkg",
                "read_only": "true",
                "Expose primary keys": "false",
            },
        )


class TestFileStoreCreate(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.sent = {}
        outer = self

        class FakeGS:
            def get_datastore(inner, ws, name):
                return ("not found", 404)

            def create_datastore(inner, **kwargs):
                outer.sent.update(kwargs)
                return ("", 201)

        self.dlg.gs = FakeGS()

    def test_a_shapefile_goes_through_the_librarys_generic_creator(self):
        self.dlg._create_datastore_from_values(
            {
                "workspace": "topp",
                "name": "states",
                "type": "Shapefile",
                "description": "US states",
                "file_url": "file:data/shapefiles/states.shp",
                "charset": "ISO-8859-1",
                "spatial_index": True,
            }
        )
        self.assertEqual(self.sent["datastore_type"], "Shapefile")
        self.assertEqual(self.sent["workspace_name"], "topp")
        self.assertEqual(self.sent["description"], "US states")
        self.assertEqual(
            self.sent["connection_parameters"]["url"],
            "file:data/shapefiles/states.shp",
        )

    def test_a_geopackage_too(self):
        self.dlg._create_datastore_from_values(
            {
                "workspace": "ne",
                "name": "natural_earth",
                "type": "GeoPackage",
                "description": "",
                "gpkg_database": "file:data/ne/natural_earth.gpkg",
                "gpkg_read_only": True,
                "gpkg_expose_pk": False,
            }
        )
        self.assertEqual(self.sent["datastore_type"], "GeoPackage")
        self.assertEqual(self.sent["connection_parameters"]["dbtype"], "geopkg")
        self.assertIsNone(self.sent["description"])

    def test_an_existing_name_is_still_refused_first(self):
        class Taken:
            def get_datastore(inner, ws, name):
                return ({"name": name}, 200)

        self.dlg.gs = Taken()
        with self.assertRaises(ValueError):
            self.dlg._create_datastore_from_values(
                {
                    "workspace": "topp",
                    "name": "taz_shapes",
                    "type": "Shapefile",
                    "file_url": "file:x.shp",
                    "charset": "",
                    "spatial_index": False,
                }
            )


class TestFileStoreEdit(unittest.TestCase):
    """An edit merges onto the server's map, like every other type."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.sent = {}
        outer = self

        class FakeGS:
            def create_datastore(inner, **kwargs):
                outer.sent.update(kwargs)
                return ("", 200)

        self.dlg.gs = FakeGS()

    def test_editing_a_shapefile_keeps_what_the_form_does_not_model(self):
        stored = {
            "url": "file:data/old",
            "charset": "ISO-8859-1",
            "namespace": "http://www.openplans.org/topp",
            "memory mapped buffer": "false",
            "cache and reuse memory maps": "false",
        }
        self.dlg._update_datastore_from_values(
            {
                "workspace": "topp",
                "name": "taz_shapes",
                "description": "",
                "file_url": "file:data/new",
                "charset": "UTF-8",
                "spatial_index": True,
            },
            {"type": "Shapefile", "enabled": True},
            stored,
        )
        params = self.sent["connection_parameters"]
        self.assertEqual(params["url"], "file:data/new")
        self.assertEqual(params["charset"], "UTF-8")
        self.assertEqual(params["create spatial index"], "true")
        # untouched by the form, kept by the merge
        self.assertEqual(params["namespace"], "http://www.openplans.org/topp")
        self.assertEqual(params["memory mapped buffer"], "false")

    def test_editing_a_geopackage_keeps_its_tuning_parameters(self):
        stored = {
            "database": "file:data/ne/natural_earth.gpkg",
            "dbtype": "geopkg",
            "namespace": "https://www.naturalearthdata.com",
            "fetch size": "1000",
            "Batch insert size": "1",
            "read_only": "true",
        }
        self.dlg._update_datastore_from_values(
            {
                "workspace": "ne",
                "name": "NaturalEarth",
                "description": "",
                "gpkg_database": "file:data/ne/natural_earth.gpkg",
                "gpkg_read_only": False,
                "gpkg_expose_pk": True,
            },
            {"type": "GeoPackage", "enabled": True},
            stored,
        )
        params = self.sent["connection_parameters"]
        self.assertEqual(params["read_only"], "false")  # the form owns this one
        self.assertEqual(params["Expose primary keys"], "true")
        self.assertEqual(params["fetch size"], "1000")  # it does not own these
        self.assertEqual(params["Batch insert size"], "1")
        self.assertEqual(params["namespace"], "https://www.naturalearthdata.com")


class TestFileStoreFormBehaviour(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.form = ResourceFormDialog(
            title="t", fields=self.dlg._datastore_fields(["topp"])
        )

    def visible_connection_fields(self, store_type):
        self.dlg._on_type_changed(self.form, store_type)
        return {
            field["key"]
            for field in self.dlg._datastore_fields(["topp"])
            if field.get("group") and field["key"] not in self.form._hidden_keys
        }

    def test_each_type_shows_only_its_own_fields(self):
        self.assertEqual(
            self.visible_connection_fields("Shapefile"),
            {"file_url", "charset", "spatial_index"},
        )
        self.assertEqual(
            self.visible_connection_fields("Directory of spatial files (shapefiles)"),
            {"file_url", "charset"},
        )
        self.assertEqual(
            self.visible_connection_fields("GeoPackage"),
            {"gpkg_database", "gpkg_read_only", "gpkg_expose_pk"},
        )
        self.assertEqual(
            self.visible_connection_fields("PostGIS"),
            {"pg_host", "pg_port", "pg_db", "pg_user", "pg_password", "pg_schema"},
        )

    def test_the_new_types_are_offered_in_the_type_combo(self):
        options = [
            field["options"]
            for field in self.dlg._datastore_fields(["topp"])
            if field["key"] == "type"
        ][0]
        for store_type in (
            "Shapefile",
            "Directory of spatial files (shapefiles)",
            "GeoPackage",
        ):
            self.assertIn(store_type, options)

    def test_the_prefill_reads_the_servers_parameters(self):
        values = self.dlg._datastore_form_values(
            "topp",
            "taz_shapes",
            "Shapefile",
            {"description": "Tasmania"},
            {
                "url": "file:data/taz_shapes",
                "charset": "UTF-8",
                "create spatial index": "false",
            },
        )
        self.assertEqual(values["file_url"], "file:data/taz_shapes")
        self.assertEqual(values["charset"], "UTF-8")
        self.assertIs(values["spatial_index"], False)

    def test_a_geopackage_prefill_reads_its_flags(self):
        values = self.dlg._datastore_form_values(
            "ne",
            "NaturalEarth",
            "GeoPackage",
            {},
            {
                "database": "file:data/ne/natural_earth.gpkg",
                "read_only": "true",
                "Expose primary keys": "false",
            },
        )
        self.assertEqual(values["gpkg_database"], "file:data/ne/natural_earth.gpkg")
        self.assertIs(values["gpkg_read_only"], True)
        self.assertIs(values["gpkg_expose_pk"], False)

    def test_a_missing_index_parameter_prefills_as_geoservers_own_default(self):
        # GeoServer creates the index unless told otherwise.
        values = self.dlg._datastore_form_values("topp", "s", "Shapefile", {}, {})
        self.assertIs(values["spatial_index"], True)


# ############################################################################
# ##### Connection guard #########
# ################################


class TestConnectionGuard(unittest.TestCase):
    """A table outlives its connection; its buttons must not crash.

    Reported from QGIS 3.44: clicking *Publish a Layer* raised
    AttributeError: 'NoneType' object has no attribute 'get_workspaces'.
    refresh_ui() clears self.gs immediately and probes in a QgsTask, so for
    that window the loaded rows and their armed buttons are still clickable.
    """

    class FakeGS:
        def get_workspaces(inner):
            return ([{"name": "topp"}], 200)

        def get_datastores(inner, workspace_name):
            return ([], 200)

    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = self.FakeGS()
        self.warnings = []
        self.dlg.show_warning_message = self.warnings.append
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        self.dlg.show_success_message = lambda text: None
        # If the guard ever breaks, a row action would reach the modal delete
        # confirmation and hang the suite instead of failing it.
        self.dlg._confirm_delete = lambda kind, labels, cascade="": False
        self.dlg._load_layers()  # arms the buttons, as a loaded tab does
        self.dlg.gs = None  # what refresh_ui() does while it re-probes

    def test_the_add_button_explains_itself_instead_of_raising(self):
        self.dlg.btn_add.click()
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("Not connected", self.warnings[0])

    def test_a_row_action_explains_itself_too(self):
        from geoserver_manager.gui import tab_layers
        from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

        class Rejecting(ResourceFormDialog):
            """A broken guard would open a modal here and hang the suite."""

            def exec(inner):
                return QDialog.DialogCode.Rejected

        widget = self.dlg._make_action_widget(["tasmania_roads", "topp", "taz_shapes"])
        button = widget.findChildren(QPushButton)[0]
        self.assertEqual(button.toolTip(), "Add to QGIS")  # the first row action
        with patch.object(tab_layers, "ResourceFormDialog", Rejecting):
            button.click()
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("Refresh", self.warnings[0])

    def test_delete_selected_is_refused(self):
        deleted = []
        self.dlg._setup_delete_selected_button(deleted.append)
        self.dlg._populate_rows([["a"], ["b"]])
        self.dlg.resultsTable.selectRow(0)
        self.dlg.btn_delete_selected.click()
        self.assertEqual(deleted, [])
        self.assertTrue(self.warnings)

    def test_a_link_cell_click_is_refused(self):
        opened = []
        self.dlg._name_click_callback = opened.append
        self.dlg._populate_rows([["tasmania_roads", "topp"]])
        self.dlg._on_cell_clicked(0, 0)
        self.assertEqual(opened, [])
        self.assertTrue(self.warnings)

    def test_everything_works_again_once_connected(self):
        self.dlg.gs = self.FakeGS()
        opened = []
        self.dlg._name_click_callback = opened.append
        self.dlg._populate_rows([["tasmania_roads", "topp"]])
        self.dlg._on_cell_clicked(0, 0)
        self.assertEqual(opened, [["tasmania_roads", "topp"]])
        self.assertEqual(self.warnings, [])

    def test_a_refresh_disarms_the_header_buttons_at_once(self):
        """Prevention, not just a catch: the buttons go grey immediately."""

        class Settings:
            geoserver_url = "http://gs.example.org/geoserver"
            geoserver_verify_tls = True
            geoserver_auth_cfg_id = ""

            def has_credentials(inner):
                return True

            def get_credentials(inner):
                return ("admin", "geoserver")

        class PlgSettings:
            def get_plg_settings(inner):
                return Settings()

            def get_value_from_key(inner, *args, **kwargs):
                return None

            def set_value_from_key(inner, *args, **kwargs):
                return True

        self.dlg.gs = self.FakeGS()
        self.dlg._load_layers()
        self.assertTrue(self.dlg.btn_add.isEnabled())

        self.dlg.plg_settings = PlgSettings()
        self.dlg._build_client = lambda settings: self.FakeGS()
        self.dlg._probe = lambda gs, url: None
        self.dlg._fetch_version_label = lambda gs: ""
        self.dlg._run_in_task = (
            lambda message, work, on_success: None
        )  # still in flight

        self.dlg.refresh_ui()
        self.assertIsNone(self.dlg.gs)
        self.assertFalse(self.dlg.btn_add.isEnabled())
        self.assertFalse(self.dlg.btn_delete_selected.isEnabled())


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
