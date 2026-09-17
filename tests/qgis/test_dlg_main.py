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
from unittest.mock import patch

from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui.dlg_main import GeoServerMainDialog

start_app()

# ############################################################################
# ########## Classes #############
# ################################


class TestTableState(unittest.TestCase):
    """The table is paginated in Python and selections are mapped back by row
    index, so the row cache and what is on screen must never disagree.
    """

    def setUp(self):
        self.dlg = GeoServerMainDialog()
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
        self.dlg = GeoServerMainDialog()
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
        self.dlg = GeoServerMainDialog()
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


class TestNonJsonResponses(unittest.TestCase):
    """A proxy login page answers 200 with HTML; that is not 'Connected'."""

    def setUp(self):
        self.dlg = GeoServerMainDialog()

    def test_fetch_list_refuses_a_non_list_payload(self):
        with self.assertRaises(RuntimeError):
            self.dlg._fetch_list(lambda: ("<html>login</html>", 200))

    def test_probe_rejects_html_with_status_200(self):
        class FakeGS:
            def get_workspaces(inner):
                return ("<html>login</html>", 200)

        problem = self.dlg._probe(FakeGS(), "http://proxy.example.org/geoserver")
        self.assertIsNotNone(problem)
        status, message = problem
        self.assertIn("Not a GeoServer", status)

    def test_probe_accepts_a_real_list(self):
        class FakeGS:
            def get_workspaces(inner):
                return ([{"name": "ws"}], 200)

        self.assertIsNone(self.dlg._probe(FakeGS(), "http://gs"))


class TestDefaultWorkspaceHandling(unittest.TestCase):
    def setUp(self):
        self.dlg = GeoServerMainDialog()
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
        self.dlg = GeoServerMainDialog()
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
                        "type": "Shapefile",
                        "enabled": True,
                        "connectionParameters": {"entry": {"url": "file:x.shp"}},
                    },
                    200,
                )

        dlg = GeoServerMainDialog()
        dlg.gs = FakeGS()
        with patch.object(tab_datastores, "ResourceFormDialog", Recording):
            dlg._show_datastore_info(["taz_shapes", "topp", "Shapefile", "True"])

        self.assertEqual(len(opened), 1)
        form = opened[0]
        combo = form.get_widget("type")
        self.assertEqual(combo.currentText(), "Shapefile")
        self.assertFalse(combo.isEnabled())
        for key in ("pg_host", "pg_password", "jndi_reference", "pmtiles_url"):
            self.assertIn(key, form._hidden_keys)
        self.assertNotIn("raw_params", form._hidden_keys)
        editor = form.get_widget("raw_params")
        self.assertIn("url = file:x.shp", editor.toPlainText())
        self.assertFalse(editor.isReadOnly())  # it is an editor, not a view
        save = form._button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.assertFalse(save.isHidden())  # any type can be saved now


class TestLinkCells(unittest.TestCase):
    """Name cells open the resource but must stay real, selectable items."""

    def setUp(self):
        self.dlg = GeoServerMainDialog()
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

        class FakeGS:
            def get_workspaces(inner):
                raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED")

        status, message = GeoServerMainDialog()._probe(
            FakeGS(), "https://gs.example.org"
        )
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
            GeoServerMainDialog()._build_client(Settings())
        self.assertIs(seen["verifytls"], False)
        self.assertEqual(seen["url"], "https://gs.example.org")


class TestGenericParameterEditor(unittest.TestCase):
    """Any datastore type is editable through 'key = value' lines."""

    def setUp(self):
        self.dlg = GeoServerMainDialog()
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
            "url": "file:old",
            "charset": "ISO-8859-1",
            "passwd": "crypt1:SECRET",
            "obsolete": "x",
        }
        detail = {"type": "Shapefile", "enabled": False}
        values = {
            "workspace": "topp",
            "name": "shp",
            "description": "",
            "raw_params": "url = file:new\ncharset = UTF-8\npasswd = ••••\n",  # 'obsolete' removed
        }

        self.dlg._update_datastore_from_values(values, detail, stored)

        self.assertEqual(
            self.sent["connection_parameters"],
            {"url": "file:new", "charset": "UTF-8", "passwd": "crypt1:SECRET"},
        )
        self.assertEqual(
            self.sent["datastore_type"], "Shapefile"
        )  # server's type, not the combo
        self.assertIs(self.sent["enabled"], False)  # still disabled

    def test_bad_line_never_reaches_the_server(self):
        with self.assertRaises(ValueError):
            self.dlg._update_datastore_from_values(
                {"workspace": "w", "name": "n", "raw_params": "no equals here"},
                {"type": "GeoPackage"},
                {"database": "x.gpkg"},
            )
        self.assertEqual(self.sent, {})


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
