#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    # for whole tests
    python -m unittest tests.qgis.test_tab_layers
    # for specific test
    python -m unittest tests.qgis.test_tab_layers.TestLayersTab.test_lists_every_feature_type
"""

# standard library
from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui.dlg_main import GeoServerMainDialog

start_app()

# ############################################################################
# ########## Classes #############
# ################################

DETAIL = {
    "name": "tasmania_roads",
    "nativeName": "tasmania_roads",
    "srs": "EPSG:4326",
    "enabled": True,
    "advertised": True,
    "projectionPolicy": "FORCE_DECLARED",
    "title": "Tasmania roads",
    "abstract": "Main Tasmania roads",
    "keywords": {"string": ["Roads", "Tasmania"]},
    "nativeBoundingBox": {
        "minx": 145.19,
        "miny": -43.42,
        "maxx": 148.27,
        "maxy": -40.85,
        "crs": "EPSG:4326",
    },
    "attributes": {
        "attribute": [
            {
                "name": "the_geom",
                "binding": "org.locationtech.jts.geom.MultiLineString",
            },
            {"name": "TYPE", "binding": "java.lang.String"},
        ]
    },
}


class FakeGS:
    """Two workspaces, one with a store holding two feature types."""

    def __init__(self, broken_workspace=None, broken_detail=None):
        self.broken_workspace = broken_workspace
        self.broken_detail = broken_detail
        self.deleted = []

    def get_workspaces(self):
        return ([{"name": "topp"}, {"name": "empty"}], 200)

    def get_datastores(self, workspace_name):
        if workspace_name == self.broken_workspace:
            raise RuntimeError("HTTP 500: boom")
        if workspace_name == "empty":
            return ([], 200)
        return ([{"name": "taz_shapes"}], 200)

    def get_feature_types(self, workspace_name, datastore_name):
        return ([{"name": "tasmania_roads"}, {"name": "tasmania_cities"}], 200)

    def get_feature_type(self, workspace_name, datastore_name, name):
        if name == self.broken_detail:
            raise RuntimeError("HTTP 404: gone")
        detail = dict(DETAIL, name=name)
        if name == "tasmania_cities":
            detail["srs"] = "EPSG:3857"
            detail["enabled"] = False
        return (detail, 200)

    def delete_feature_type(self, workspace_name, datastore_name, name):
        self.deleted.append((workspace_name, datastore_name, name))
        return ("", 200)


class TestLayersTab(unittest.TestCase):
    def setUp(self):
        self.dlg = GeoServerMainDialog()
        self.warnings = []
        self.dlg.show_warning_message = self.warnings.append
        self.dlg.show_error_message = lambda text: self.fail(
            f"unexpected error: {text}"
        )
        self.dlg.show_success_message = lambda text: None
        self.dlg.gs = FakeGS()

    def test_registered_as_a_tab(self):
        labels = [label for label, _icon, _loader in self.dlg.TABS]
        self.assertIn("Layers", labels)
        loader = dict((label, loader) for label, _icon, loader in self.dlg.TABS)[
            "Layers"
        ]
        self.assertEqual(loader, "_load_layers")
        self.assertTrue(hasattr(self.dlg, loader))

    def test_lists_every_feature_type(self):
        self.dlg._load_layers()

        self.assertEqual(
            self.dlg._all_rows,
            [
                ["tasmania_roads", "topp", "taz_shapes", "EPSG:4326", "True"],
                ["tasmania_cities", "topp", "taz_shapes", "EPSG:3857", "False"],
            ],
        )
        headers = [
            self.dlg.resultsTable.horizontalHeaderItem(col).text()
            for col in range(self.dlg.resultsTable.columnCount())
        ]
        self.assertEqual(
            headers,
            ["Layer Name", "Workspace", "Datastore", "SRS", "Enabled", "Actions"],
        )
        self.assertEqual(self.warnings, [])

    def test_one_unreadable_workspace_costs_a_warning_not_the_table(self):
        self.dlg.gs = FakeGS(broken_workspace="topp")
        self.dlg._load_layers()

        self.assertEqual(self.dlg._all_rows, [])  # topp held them all
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("topp", self.warnings[0])

    def test_one_unreadable_detail_still_lists_the_row(self):
        self.dlg.gs = FakeGS(broken_detail="tasmania_cities")
        self.dlg._load_layers()

        rows = {row[0]: row for row in self.dlg._all_rows}
        self.assertEqual(rows["tasmania_roads"][3], "EPSG:4326")
        self.assertEqual(rows["tasmania_cities"][3], "—")  # placeholder, not missing
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("tasmania_cities", self.warnings[0])

    def test_name_and_workspace_columns_are_links(self):
        self.dlg._load_layers()
        self.assertIsNotNone(self.dlg._cell_click_callback(0))  # name
        self.assertIsNotNone(self.dlg._cell_click_callback(1))  # workspace
        self.assertIsNone(self.dlg._cell_click_callback(3))  # SRS is plain

    def test_delete_targets_the_right_feature_type(self):
        self.dlg._load_layers()
        confirmed = {}
        self.dlg._confirm_delete = (
            lambda kind, labels, cascade="": confirmed.update(
                kind=kind, labels=labels, cascade=cascade
            )
            or True
        )

        self.dlg._delete_selected_layers([self.dlg._all_rows[1]])

        self.assertEqual(
            self.dlg.gs.deleted, [("topp", "taz_shapes", "tasmania_cities")]
        )
        self.assertEqual(confirmed["labels"], ["topp/taz_shapes/tasmania_cities"])
        self.assertIn("layer group", confirmed["cascade"])  # recurse=true is stated


class TestLayerDetailPrefill(unittest.TestCase):
    """The view is built from what the server returned, not from the row."""

    def test_flattens_the_interesting_fields(self):
        values = GeoServerMainDialog._layer_form_values(
            ["tasmania_roads", "topp", "taz_shapes", "EPSG:4326", "True"], DETAIL
        )

        self.assertEqual(values["native_name"], "tasmania_roads")
        self.assertEqual(values["projection_policy"], "FORCE_DECLARED")
        self.assertEqual(values["keywords"], "Roads, Tasmania")
        self.assertIn("minx 145.19", values["bbox"])
        self.assertIn("crs EPSG:4326", values["bbox"])
        self.assertIn("the_geom : MultiLineString", values["attributes"])
        self.assertIn("TYPE : String", values["attributes"])
        self.assertIs(values["enabled"], True)

    def test_survives_a_sparse_payload(self):
        values = GeoServerMainDialog._layer_form_values(["l", "ws", "ds"], {})

        self.assertEqual(values["name"], "l")
        self.assertEqual(values["bbox"], "—")
        self.assertEqual(values["attributes"], "—")
        self.assertEqual(values["keywords"], "")

    def test_handles_translated_title_and_single_attribute(self):
        detail = {
            "title": {"en": "Roads", "fr": "Routes"},
            "keywords": "Solo",
            "attributes": {"attribute": {"name": "geom", "binding": "a.b.Point"}},
        }
        values = GeoServerMainDialog._layer_form_values(["l", "ws", "ds"], detail)

        self.assertIn("en: Roads", values["title"])
        self.assertEqual(values["keywords"], "Solo")
        self.assertEqual(values["attributes"], "geom : Point")


class TestLibraryPayloadShape(unittest.TestCase):
    """geoservercloud normalises the payload; raw REST does not. Both must work.

    Caught on a live server: FeatureType.asdict() returns attributes and
    keywords as lists, while /featuretypes/x.json wraps them in
    {"attribute": [...]} / {"string": [...]}.
    """

    LIBRARY_SHAPE = {
        "name": "tasmania_roads",
        "srs": "EPSG:4326",
        "keywords": ["Roads", "Tasmania"],
        "attributes": [
            {
                "name": "the_geom",
                "binding": "org.locationtech.jts.geom.MultiLineString",
                "nillable": True,
            },
            {"name": "TYPE", "binding": "java.lang.String"},
        ],
        "nativeBoundingBox": {"minx": 145.19, "crs": "EPSG:4326"},
    }

    def test_library_normalised_lists(self):
        values = GeoServerMainDialog._layer_form_values(
            ["tasmania_roads", "topp", "taz_shapes"], self.LIBRARY_SHAPE
        )
        self.assertEqual(values["keywords"], "Roads, Tasmania")
        self.assertIn("the_geom : MultiLineString", values["attributes"])
        self.assertIn("TYPE : String", values["attributes"])

    def test_raw_rest_wrapped_dicts(self):
        values = GeoServerMainDialog._layer_form_values(
            ["tasmania_roads", "topp", "taz_shapes"], DETAIL
        )
        self.assertEqual(values["keywords"], "Roads, Tasmania")
        self.assertIn("the_geom : MultiLineString", values["attributes"])

    def test_attribute_without_a_binding(self):
        values = GeoServerMainDialog._layer_form_values(
            ["l", "ws", "ds"], {"attributes": [{"name": "plain"}]}
        )
        self.assertEqual(values["attributes"], "plain : ")


class TestAddToQgis(unittest.TestCase):
    """URIs carry the auth config id, never a password; the right provider is used."""

    BASE = "http://gs.example.org/geoserver/"  # trailing slash must not matter

    def test_wms_uri(self):
        uri, provider = GeoServerMainDialog._layer_uri(
            "WMS", self.BASE, "topp:roads", "abc123"
        )
        self.assertEqual(provider, "wms")
        self.assertIn("layers=topp:roads", uri)
        self.assertIn("url=http://gs.example.org/geoserver/ows", uri)
        self.assertIn("authcfg=abc123", uri)
        self.assertNotIn("//geoserver//", uri)

    def test_wmts_goes_through_geowebcache(self):
        uri, provider = GeoServerMainDialog._layer_uri(
            "WMTS", self.BASE, "topp:roads", "abc123"
        )
        self.assertEqual(provider, "wms")
        self.assertIn("gwc/service/wmts", uri)
        self.assertIn("tileMatrixSet=EPSG:900913", uri)
        self.assertIn("authcfg=abc123", uri)

    def test_wfs_uri_uses_the_datasource_uri_and_no_password(self):
        uri, provider = GeoServerMainDialog._layer_uri(
            "WFS", self.BASE, "topp:roads", "abc123"
        )
        self.assertEqual(provider, "WFS")
        self.assertIn("typename='topp:roads'", uri)
        self.assertIn("authcfg=abc123", uri)
        self.assertIn("pagingEnabled='true'", uri)
        self.assertNotIn("password", uri.lower())

    def test_no_auth_config_means_anonymous(self):
        uri, _ = GeoServerMainDialog._layer_uri("WMS", self.BASE, "topp:roads", "")
        self.assertNotIn("authcfg", uri)

    def test_unknown_protocol_is_refused(self):
        with self.assertRaises(ValueError):
            GeoServerMainDialog._layer_uri("FTP", self.BASE, "x:y")

    def test_add_action_is_offered_before_delete(self):
        dlg = GeoServerMainDialog()
        dlg.gs = FakeGS()
        dlg.show_warning_message = lambda text: None
        dlg._load_layers()
        tooltips = [tooltip for _icon, tooltip, _cb in dlg._row_actions]
        self.assertEqual(tooltips, ["Add to QGIS", "Delete"])

    def test_unreachable_layer_is_a_banner_not_a_project_entry(self):
        from unittest.mock import patch

        from qgis.core import QgsProject
        from qgis.PyQt.QtWidgets import QDialog

        from geoserver_manager.gui import tab_layers
        from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

        class Accepting(ResourceFormDialog):
            def exec(self):
                return QDialog.DialogCode.Accepted

        class Settings:
            geoserver_url = "http://127.0.0.1:1/geoserver"  # nothing listens here
            geoserver_auth_cfg_id = ""

        class Prefs:
            def get_plg_settings(self):
                return Settings()

        dlg = GeoServerMainDialog()
        dlg.plg_settings = Prefs()
        errors = []
        dlg.show_error_message = errors.append
        before = len(QgsProject.instance().mapLayers())
        with patch.object(tab_layers, "ResourceFormDialog", Accepting):
            dlg._add_layer_to_qgis(["roads", "topp", "ds", "EPSG:4326", "True"])

        self.assertEqual(len(errors), 1)
        self.assertIn("Could not add 'roads'", errors[0])
        self.assertEqual(len(QgsProject.instance().mapLayers()), before)


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
