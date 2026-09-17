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

    def test_refuses_to_update_when_the_server_reports_no_type(self):
        with self.assertRaises(RuntimeError):
            self.dlg._update_datastore_from_values(
                {"workspace": "ws", "name": "store"}, {}, {}
            )


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
