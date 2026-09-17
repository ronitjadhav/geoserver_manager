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

    def test_prefill_for_an_unsupported_type_still_builds(self):
        values = self.dlg._datastore_form_values("ws", "shp", "Shapefile", {}, {})
        # shown against the first supported type only so the combo has a value;
        # the caller hides Save for these
        self.assertEqual(values["type"], "PostGIS")
        self.assertEqual(values["pg_port"], 5432)

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


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
