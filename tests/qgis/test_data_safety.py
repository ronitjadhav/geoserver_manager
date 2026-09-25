#! python3  # noqa E265

"""
Guards against the review's data-loss findings: each test failed on the code
before its fix.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_data_safety
"""

import sys
from unittest.mock import patch

from qgis.testing import start_app, unittest

from geoserver_manager.toolbelt.dependencies import BUNDLED_WHLS
from tests.qgis.sync_dialog import SyncDialog

for _whl in BUNDLED_WHLS:  # conftest does this under pytest; unittest needs it too
    if str(_whl) not in sys.path:
        sys.path.insert(0, str(_whl))

start_app()

# GET /rest/layers/sf:roads.json on 2.28.5: one other style, as a bare object.
ROADS = {
    "layer": {
        "name": "roads",
        "path": "/",
        "type": "VECTOR",
        "defaultStyle": {"name": "simple_roads", "href": "…/styles/simple_roads.json"},
        "styles": {
            "@class": "linked-hash-set",
            "style": {"name": "line", "href": "…/styles/line.json"},
        },
        "resource": {
            "@class": "featureType",
            "name": "sf:roads",
            "href": "…/workspaces/sf/datastores/sf/featuretypes/roads.json",
        },
        "attribution": {"logoWidth": 0, "logoHeight": 0},
    }
}


class Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeGS:
    """A client whose rest_service answers what each test sets."""

    def __init__(self, documents=None, existing=()):
        from geoservercloud.models.layer import Layer

        documents = documents or {}
        existing = set(existing)

        class Client:
            def get(inner, path, **kwargs):
                if path in documents:
                    return Response(documents[path])
                return Response("not found", 404)

        class Endpoints:
            base_url = "/rest"

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

            def get_layer(inner, workspace_name, name):
                # What the library really answers: its own model of the document.
                path = f"/rest/layers/{workspace_name}:{name}.json"
                return (Layer.from_get_response_payload(documents[path]), 200)

            def resource_exists(inner, path):
                return path in existing

        self.rest_service = Rest()
        self._documents, self._existing = documents, existing

    def _store(self, collection, wrapper, workspace_name, name):
        # As the library answers: the store's own fields, type included.
        path = f"/rest/workspaces/{workspace_name}/{collection}/{name}.json"
        if path not in self._existing:
            return ("not found", 404)
        return ((self._documents.get(path) or {}).get(wrapper, {}), 200)

    def get_datastore(self, workspace_name, name):
        return self._store("datastores", "dataStore", workspace_name, name)

    def get_coverage_store(self, workspace_name, name):
        return self._store("coveragestores", "coverageStore", workspace_name, name)


class TestLayerStylesAsGeoServerWritesThem(unittest.TestCase):
    def test_a_single_other_style_is_one_style(self):
        # The library's model read its keys as two styles, "name" and "href":
        # Set style refused to save, and deleting them wiped the real one.
        dlg = SyncDialog()
        dlg.gs = FakeGS({"/rest/layers/sf:roads.json": ROADS})
        self.assertEqual(dlg._layer_styles("sf", "roads"), ("simple_roads", ["line"]))

    def test_an_unreadable_layer_is_an_error_not_no_styles(self):
        # (None, []) made the form offer the first style as the new default.
        dlg = SyncDialog()
        dlg.gs = FakeGS({"/rest/layers/sf:roads.json": ROADS})
        with self.assertRaises(Exception):
            dlg._layer_styles("sf", "missing")


class TestReconnectWaitsForWrites(unittest.TestCase):
    def test_no_new_connection_while_a_delete_batch_runs(self):
        # Its remaining deletes read self.gs: they went to the other server.
        dlg = SyncDialog()
        client = dlg.gs = object()
        warnings = []
        dlg.show_warning_message = warnings.append
        dlg._delete = object()  # a delete batch is running
        dlg.refresh_ui()
        self.assertIs(dlg.gs, client)
        self.assertEqual(len(warnings), 1)

    def test_no_profile_switch_while_an_upload_runs(self):
        dlg = SyncDialog()
        dlg.show_warning_message = lambda text: None
        dlg._upload = object()
        with (
            patch.object(
                dlg.plg_settings,
                "get_profiles",
                return_value=[{"name": "B", "url": "https://b.example.org"}],
            ),
            patch.object(dlg.plg_settings, "activate_profile") as activate,
        ):
            dlg._switch_profile("B")
        activate.assert_not_called()


class TestRowsWhoseNameBreaksAPath(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.warnings = []
        self.dlg.show_warning_message = self.warnings.append

    def test_a_name_with_a_hash_is_refused_with_a_reason(self):
        # requests sends ".../datastores/a#b" as ".../datastores/a": deleting
        # "a#b" deleted "a", and reported success.
        self.dlg._setup_table(["Name", "Workspace"])
        for name in ("a#b", "a?b", "a%b", "a/b"):
            self.assertFalse(self.dlg._addressable([[name, "topp"]]), name)
        self.assertFalse(self.dlg._addressable([["roads", "w#x"]]))
        self.assertTrue(self.dlg._addressable([["roads", "topp"]]))
        self.assertIn("a#b", self.warnings[0])

    def test_a_click_on_such_a_row_opens_nothing(self):
        opened = []
        self.dlg._setup_table(["Name", "Workspace"])
        self.dlg._name_click_callback = opened.append
        self.dlg.gs = object()
        self.dlg._populate_rows([["a#b", "topp"]])
        self.dlg._on_cell_clicked(0, 0)
        self.assertEqual(opened, [])

    def test_only_the_cells_that_go_into_paths_are_checked(self):
        # The Server tab's summaries hold URLs; its paths hold no names.
        self.dlg._setup_table(["Name", "Summary"])
        self.dlg._path_columns = ()
        self.assertTrue(
            self.dlg._addressable([["Global settings", "Proxy base URL: https://x/"]])
        )


class TestPublishLandsOnItsOwnLayer(unittest.TestCase):
    """Measured on 2.28.5: a layer of the name in another store made the new
    one name1 while the style went to the old one; Replace over a PostGIS
    store had GeoServer import the GeoPackage into that database."""

    def dialog(self, existing, documents=None):
        dlg = SyncDialog()
        dlg.gs = FakeGS(documents or {}, existing)
        return dlg

    def test_a_layer_of_the_name_elsewhere_is_refused(self):
        dlg = self.dialog({"/rest/layers/topp:roads.json"})
        with self.assertRaises(ValueError):
            dlg._refuse_layer_clash("topp", "roads", False, "data", "GeoPackage")

    def test_replace_refuses_a_layer_from_another_store(self):
        dlg = self.dialog({"/rest/layers/topp:roads.json"})
        with patch.object(dlg, "_layer_summary", return_value=("VECTOR", "other", "-")):
            with self.assertRaises(ValueError) as caught:
                dlg._refuse_layer_clash("topp", "roads", True, "data", "GeoPackage")
        self.assertIn("other", str(caught.exception))

    def test_replace_refuses_a_store_of_another_type(self):
        path = "/rest/workspaces/topp/datastores/roads.json"
        dlg = self.dialog({path}, {path: {"dataStore": {"type": "PostGIS"}}})
        with self.assertRaises(ValueError) as caught:
            dlg._refuse_layer_clash("topp", "roads", True, "data", "GeoPackage")
        self.assertIn("PostGIS", str(caught.exception))

    def test_replacing_its_own_upload_is_allowed(self):
        path = "/rest/workspaces/topp/datastores/roads.json"
        dlg = self.dialog(
            {path, "/rest/layers/topp:roads.json"},
            {path: {"dataStore": {"type": "GeoPackage"}}},
        )
        with patch.object(dlg, "_layer_summary", return_value=("VECTOR", "roads", "-")):
            dlg._refuse_layer_clash("topp", "roads", True, "data", "GeoPackage")


class TestAnUntouchedSaveChangesNothing(unittest.TestCase):
    """Values a form cannot show exactly were rewritten by an unrelated Save."""

    def test_a_parametrised_postgis_port_is_kept(self):
        from geoserver_manager.gui.tab_datastores import DatastoreTabMixin

        stored = "${PG_PORT}"
        values = {"pg_port": 5432}  # what the spinbox shows for it
        self.assertEqual(DatastoreTabMixin._kept_port(stored, values), stored)
        self.assertEqual(DatastoreTabMixin._kept_port(stored, {"pg_port": 6543}), 6543)
        self.assertEqual(DatastoreTabMixin._kept_port("5432", values), "5432")

    def test_a_custom_logging_profile_stays_selected(self):
        from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

        dlg = SyncDialog()
        before = {"level": "MY_LOGGING", "location": "logs/x.log", "stdout": True}
        form = ResourceFormDialog(
            title="t", fields=dlg._server_fields("logging", before), values=before
        )
        self.assertEqual(form.get_values()["level"], "MY_LOGGING")

    def test_a_stored_number_beyond_a_spinbox_range_survives(self):
        # Clamped by the spinbox, an untouched Save wrote the clamped value
        # back: a 32x32 meta-tile, 200 cascaded connections (review 2026-09-24).
        from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

        stored = {"meta_width": 32, "gutter": 250}
        form = ResourceFormDialog(
            title="t", fields=SyncDialog()._gwc_fields([]), values=stored
        )
        self.assertEqual(form.get_values()["meta_width"], 32)
        self.assertEqual(form.get_values()["gutter"], 250)
        cascaded = ResourceFormDialog(
            title="t",
            fields=SyncDialog()._cascaded_store_info_fields(),
            values={"max_connections": 200},
        )
        self.assertEqual(cascaded.get_values()["max_connections"], 200)

    def test_a_new_own_wms_starts_from_the_global_limits(self):
        from geoserver_manager.gui.tab_workspaces import WorkspaceTabMixin

        values = WorkspaceTabMixin._wms_form_values(
            None,
            {"title": "Global", "maxRenderingTime": 60, "maxRenderingErrors": 1000},
        )
        self.assertFalse(values["wms_own"])
        self.assertEqual(values["wms_title"], "Global")
        self.assertEqual(values["wms_max_rendering_time"], 60)
        self.assertEqual(values["wms_max_rendering_errors"], 1000)


if __name__ == "__main__":
    unittest.main()
