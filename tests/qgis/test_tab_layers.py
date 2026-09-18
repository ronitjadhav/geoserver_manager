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
from unittest.mock import patch

from qgis.PyQt.QtWidgets import QDialog
from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui.dlg_main import GeoServerMainDialog
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from tests.qgis.sync_dialog import SyncDialog

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
        self.dlg = SyncDialog()
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

    def test_unreachable_layer_is_a_banner_not_a_project_entry(self):
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

        dlg = SyncDialog()
        dlg.plg_settings = Prefs()
        errors = []
        dlg.show_error_message = errors.append
        before = len(QgsProject.instance().mapLayers())
        with patch.object(tab_layers, "ResourceFormDialog", Accepting):
            dlg._add_layer_to_qgis(["roads", "topp", "ds", "EPSG:4326", "True"])

        self.assertEqual(len(errors), 1)
        self.assertIn("Could not add 'roads'", errors[0])
        self.assertEqual(len(QgsProject.instance().mapLayers()), before)


class PublishFakeGS(FakeGS):
    """Adds the pieces the publish flow touches: raw REST for ?list=available,
    an existence check, and a create that records what it was asked."""

    def __init__(self):
        super().__init__()
        self.created = []
        outer = self

        class Response:
            status_code = 200

            def json(inner):
                return {"list": {"string": ["plugin_demo", "another"]}}

        class Client:
            def get(inner, path, **kwargs):
                outer.last_query = (path, kwargs.get("params"))
                return Response()

        class Endpoints:
            def featuretypes(inner, ws, ds):
                return f"/rest/workspaces/{ws}/datastores/{ds}/featuretypes.json"

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

        self.rest_service = Rest()

    def get_feature_type(self, ws, ds, name):
        if name == "plugin_demo":
            return ("<html>Not Found</html>", 404)  # free
        return ({"name": name}, 200)  # taken

    def create_feature_type(self, **kwargs):
        self.created.append(kwargs)
        return ("", 201)


class TestPublish(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = PublishFakeGS()
        self.dlg.show_warning_message = lambda t: None

    def test_available_tables_uses_the_list_available_query(self):
        tables = self.dlg._available_tables("topp", "pg")
        self.assertEqual(tables, ["another", "plugin_demo"])
        path, params = self.dlg.gs.last_query
        self.assertTrue(path.endswith("/topp/datastores/pg/featuretypes.json"))
        self.assertEqual(params, {"list": "available"})

    def test_available_tables_tolerates_odd_payloads(self):
        for payload, expected in (
            ({"list": {"string": "solo"}}, ["solo"]),  # one table is unwrapped
            ({"list": ""}, []),  # none available
            ("not json at all", []),
        ):

            class R:
                status_code = 200

                def json(inner, p=payload):
                    return p

            self.dlg.gs.rest_service.rest_client.get = lambda *a, **k: R()
            self.assertEqual(self.dlg._available_tables("w", "d"), expected)

    def test_publish_sends_what_the_form_collected(self):
        self.dlg._publish_layer_from_values(
            {
                "workspace": "topp",
                "datastore": "pg",
                "table": "plugin_demo",
                "epsg": 2056,
                "title": "Demo",
                "abstract": "",
                "keywords": "a, b,, c ",
            }
        )
        sent = self.dlg.gs.created[0]
        self.assertEqual(sent["layer_name"], "plugin_demo")
        self.assertEqual(sent["workspace_name"], "topp")
        self.assertEqual(sent["datastore_name"], "pg")
        self.assertEqual(sent["epsg"], 2056)
        self.assertEqual(sent["title"], "Demo")
        self.assertIsNone(sent["abstract"])  # empty stays None, not ""
        self.assertEqual(sent["keywords"], ["a", "b", "c"])

    def test_publish_refuses_an_existing_layer(self):
        with self.assertRaises(ValueError) as ctx:
            self.dlg._publish_layer_from_values(
                {"workspace": "topp", "datastore": "pg", "table": "tasmania_roads"}
            )
        self.assertIn("already exists", str(ctx.exception))
        self.assertEqual(self.dlg.gs.created, [])  # upsert never reached

    def test_dialog_combos_cascade_from_the_workspace(self):
        from unittest.mock import patch

        from qgis.PyQt.QtWidgets import QDialog

        from geoserver_manager.gui import tab_layers
        from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

        opened = []

        class Recording(ResourceFormDialog):
            def exec(self):
                opened.append(self)
                return QDialog.DialogCode.Rejected

        with patch.object(tab_layers, "ResourceFormDialog", Recording):
            self.dlg._publish_layer()

        form = opened[0]
        ws, ds, table = (
            form.get_widget(k) for k in ("workspace", "datastore", "table")
        )
        self.assertEqual([ws.itemText(i) for i in range(ws.count())], ["topp", "empty"])
        self.assertEqual([ds.itemText(i) for i in range(ds.count())], ["taz_shapes"])
        self.assertEqual(
            [table.itemText(i) for i in range(table.count())],
            ["another", "plugin_demo"],
        )
        # switching to a workspace with no datastores empties both dependants
        ws.setCurrentText("empty")
        self.assertEqual(ds.count(), 0)
        self.assertEqual(table.count(), 0)


class TestSetLayerStyle(unittest.TestCase):
    """The default style is read from the layer and written through the library."""

    def setUp(self):
        self.dlg = SyncDialog()
        outer = self
        self.set_calls = []

        class LayerModel:
            def asdict(inner):
                return {"name": "tasmania_roads", "defaultStyle": "simple_roads"}

        class Rest:
            def get_layer(inner, ws, name):
                return (LayerModel(), 200)

        class GS(FakeGS):
            rest_service = Rest()

            def get_styles(inner, workspace_name=None):
                if workspace_name is None:
                    return ([{"name": "population"}, {"name": "simple_roads"}], 200)
                return ([{"name": "roads_ws"}], 200)

            def set_default_layer_style(inner, layer_name, workspace_name, style):
                outer.set_calls.append((layer_name, workspace_name, style))
                return ("", 200)

        self.dlg.gs = GS()
        self.dlg.show_error_message = lambda t: self.fail(t)
        self.dlg.show_success_message = lambda t: None

    def test_choices_are_global_plus_qualified_workspace_styles(self):
        self.assertEqual(
            self.dlg._style_choices("topp"),
            ["population", "simple_roads", "topp:roads_ws"],
        )

    def test_current_default_is_read_from_the_layer(self):
        self.assertEqual(
            self.dlg._layer_default_style("topp", "tasmania_roads"), "simple_roads"
        )

    def test_dialog_preselects_the_current_style(self):
        from unittest.mock import patch

        from qgis.PyQt.QtWidgets import QDialog

        from geoserver_manager.gui import tab_layers
        from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

        opened = []

        class Recording(ResourceFormDialog):
            def exec(self):
                opened.append(self)
                return QDialog.DialogCode.Rejected

        with patch.object(tab_layers, "ResourceFormDialog", Recording):
            self.dlg._set_layer_style(
                ["tasmania_roads", "topp", "taz_shapes", "EPSG:4326", "True"]
            )
        combo = opened[0].get_widget("style")
        self.assertEqual(combo.currentText(), "simple_roads")
        self.assertEqual(
            [combo.itemText(i) for i in range(combo.count())],
            ["population", "simple_roads", "topp:roads_ws"],
        )
        self.assertEqual(self.set_calls, [])  # cancelled: nothing written

    def test_choosing_another_style_writes_it(self):
        from unittest.mock import patch

        from qgis.PyQt.QtWidgets import QDialog

        from geoserver_manager.gui import tab_layers
        from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

        class Choosing(ResourceFormDialog):
            def exec(self):
                self.get_widget("style").setCurrentText("population")
                return QDialog.DialogCode.Accepted

        with patch.object(tab_layers, "ResourceFormDialog", Choosing):
            self.dlg._set_layer_style(
                ["tasmania_roads", "topp", "taz_shapes", "EPSG:4326", "True"]
            )
        self.assertEqual(self.set_calls, [("tasmania_roads", "topp", "population")])

    def test_style_action_sits_between_add_and_delete(self):
        self.dlg.show_warning_message = lambda t: None
        self.dlg._load_layers()
        self.assertEqual(
            [action[1] for action in self.dlg._row_actions],
            [
                "Add to QGIS",
                "Preview in a browser",
                "Set style",
                "Style from QGIS",
                "Delete",
            ],
        )


# ############################################################################
# ###### Style from QGIS #########
# ################################


class StyleFakeGS(FakeGS):
    """Records the style calls the push makes."""

    def __init__(self):
        super().__init__()
        self.style_calls = []
        outer = self

        class Response:
            status_code = 200
            text = ""

            def json(inner):
                return {}

        class Client:
            def put(inner, path, **kwargs):
                outer.style_calls.append(("PUT", path, kwargs))
                return Response()

        class Endpoints:
            base_url = "/rest"

            def style(inner, style_name, workspace_name=None, format="json"):
                base = (
                    f"/rest/workspaces/{workspace_name}/styles/{style_name}"
                    if workspace_name
                    else f"/rest/styles/{style_name}"
                )
                return f"{base}.{format}"

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

        self.rest_service = Rest()

    def create_style_definition(self, name, filename, workspace_name=None):
        self.style_calls.append(("definition", name, filename, workspace_name))
        return ("", 201)

    def set_default_layer_style(self, layer_name, workspace_name, style):
        self.style_calls.append(("set_default", layer_name, workspace_name, style))
        return ("", 200)


class TestStyleFromQgis(unittest.TestCase):
    def setUp(self):
        from qgis.core import QgsProject

        self.project = QgsProject.instance()
        self.project.removeAllMapLayers()
        self.dlg = SyncDialog()
        self.dlg.gs = StyleFakeGS()
        self.messages = {"warning": [], "success": []}
        self.dlg.show_warning_message = self.messages["warning"].append
        self.dlg.show_success_message = self.messages["success"].append
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        self.dlg._reload_current_tab = lambda: None

    def tearDown(self):
        self.project.removeAllMapLayers()

    def add_layer(self, name, colour="#ff0000"):
        from tests.qgis.test_sld import point_layer

        layer = point_layer(name, colour=colour)
        self.project.addMapLayer(layer)
        return layer

    def push(self, row_data, **edits):
        from geoserver_manager.gui import tab_layers

        class Accepting(ResourceFormDialog):
            def exec(inner):
                for key, value in edits.items():
                    widget = inner.get_widget(key)
                    if hasattr(widget, "setChecked"):
                        widget.setChecked(value)
                    elif hasattr(widget, "setCurrentText"):
                        widget.setCurrentText(value)
                    else:
                        widget.setText(value)
                return QDialog.DialogCode.Accepted

        with patch.object(tab_layers, "ResourceFormDialog", Accepting):
            self.dlg._style_from_qgis(row_data)

    def test_the_matching_project_layer_is_found_by_name(self):
        from tests.qgis.test_sld import point_layer

        # a layer added by this plugin keeps GeoServer's "workspace:layer" name
        layers = [
            ("topp:roads  (vector)", point_layer("topp:roads")),
            ("Rivers  (vector)", point_layer("Rivers")),
        ]
        # matched ignoring case and any workspace prefix on either side
        self.assertEqual(
            self.dlg._matching_project_layer("roads", layers), "topp:roads  (vector)"
        )
        self.assertEqual(
            self.dlg._matching_project_layer("topp:rivers", layers),
            "Rivers  (vector)",
        )
        self.assertIsNone(self.dlg._matching_project_layer("nothing", layers))

    def test_the_push_creates_the_style_and_assigns_it_qualified(self):
        self.add_layer("tasmania_roads")
        self.push(["tasmania_roads", "topp", "taz_shapes", "EPSG:4326", "True"])

        self.assertEqual(
            self.dlg.gs.style_calls[0],
            ("definition", "tasmania_roads", "tasmania_roads.sld", "topp"),
        )
        verb, path, kwargs = self.dlg.gs.style_calls[1]
        self.assertEqual(
            (verb, path), ("PUT", "/rest/workspaces/topp/styles/tasmania_roads.sld")
        )
        self.assertEqual(
            kwargs["headers"]["Content-Type"], "application/vnd.ogc.se+xml"
        )
        self.assertIn(b"ff0000", kwargs["data"].lower())
        # a workspace style is referenced as "workspace:style"; a bare name
        # would resolve to a global style of the same name
        self.assertEqual(
            self.dlg.gs.style_calls[2],
            ("set_default", "tasmania_roads", "topp", "topp:tasmania_roads"),
        )

    def test_the_style_name_is_the_layers_and_can_be_changed(self):
        self.add_layer("tasmania_roads")
        self.push(
            ["tasmania_roads", "topp", "taz_shapes", "EPSG:4326", "True"],
            style="roads_from_qgis",
        )
        self.assertEqual(
            self.dlg.gs.style_calls[0],
            ("definition", "roads_from_qgis", "roads_from_qgis.sld", "topp"),
        )
        self.assertEqual(self.dlg.gs.style_calls[-1][3], "topp:roads_from_qgis")

    def test_unticking_the_default_uploads_without_assigning(self):
        self.add_layer("tasmania_roads")
        self.push(
            ["tasmania_roads", "topp", "taz_shapes", "EPSG:4326", "True"],
            set_default=False,
        )
        self.assertFalse(
            [call for call in self.dlg.gs.style_calls if call[0] == "set_default"]
        )
        self.assertIn("uploaded", self.messages["success"][0])

    def test_an_empty_project_is_a_banner_not_a_dialog(self):
        from geoserver_manager.gui import tab_layers

        class Recording(ResourceFormDialog):
            opened = []

            def exec(inner):
                Recording.opened.append(inner)
                return QDialog.DialogCode.Rejected

        with patch.object(tab_layers, "ResourceFormDialog", Recording):
            self.dlg._style_from_qgis(["tasmania_roads", "topp", "x", "", ""])
        self.assertEqual(Recording.opened, [])
        self.assertIn("no vector or raster layer", self.messages["warning"][0])


# ############################################################################
# ##### Publish from QGIS ########
# ################################


class GpkgPublishFakeGS(StyleFakeGS):
    """Adds what the GeoPackage publish path touches."""

    def __init__(self, datastore_exists=False, layer_exists=False):
        super().__init__()
        self.datastore_exists = datastore_exists
        self.layer_exists = layer_exists
        outer = self

        class Response:
            status_code = 200
            text = ""

            def json(inner):
                return {}

        class Client:
            def put(inner, path, **kwargs):
                outer.style_calls.append(("PUT", path, kwargs))
                if path.endswith("file.gpkg"):
                    # GeoServer creates the datastore from the uploaded file
                    outer.datastore_exists = True
                return Response()

        class Endpoints:
            base_url = "/rest"

            def style(inner, style_name, workspace_name=None, format="json"):
                base = (
                    f"/rest/workspaces/{workspace_name}/styles/{style_name}"
                    if workspace_name
                    else f"/rest/styles/{style_name}"
                )
                return f"{base}.{format}"

            def featuretype(inner, workspace_name, datastore_name, name):
                return (
                    f"/rest/workspaces/{workspace_name}/datastores/"
                    f"{datastore_name}/featuretypes/{name}.json"
                )

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

        self.rest_service = Rest()

    def get_datastore(self, workspace_name, name):
        if not self.datastore_exists:
            return ("not found", 404)
        return (
            {
                "name": name,
                "type": "GeoPackage",
                "enabled": True,
                "connectionParameters": {
                    "entry": {"database": f"/data/{name}.gpkg", "dbtype": "geopkg"}
                },
            },
            200,
        )

    def get_feature_type(self, workspace_name, datastore_name, name):
        return ({"name": name}, 200 if self.layer_exists else 404)

    def create_datastore(self, **kwargs):
        self.style_calls.append(("create_datastore", kwargs))
        return ("", 200)


class TestPublishQgisLayer(unittest.TestCase):
    """Uploading a project layer as a GeoPackage datastore."""

    def setUp(self):
        from qgis.core import QgsProject

        self.project = QgsProject.instance()
        self.project.removeAllMapLayers()
        self.dlg = SyncDialog()
        self.dlg.gs = GpkgPublishFakeGS()
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        self.dlg.show_success_message = lambda text: None
        self.dlg.show_warning_message = lambda text: None

    def tearDown(self):
        self.project.removeAllMapLayers()

    def add_layer(self, name="Roads (2024)", colour="#ff0000"):
        from tests.qgis.test_sld import point_layer

        layer = point_layer(name, colour=colour)
        self.project.addMapLayer(layer)
        return layer

    def values(self, **overrides):
        base = {
            "source": "A layer from this QGIS project",
            "workspace": "topp",
            "qgis_layer": "Roads (2024)  (vector)",
            "name": "Roads (2024)",
            "replace": False,
            "with_style": False,
            "title": "",
            "abstract": "",
            "keywords": "",
        }
        base.update(overrides)
        return base

    def sent(self, verb):
        return [call for call in self.dlg.gs.style_calls if call[0] == verb]

    def test_the_geopackage_is_put_under_the_normalised_name(self):
        self.add_layer()
        self.dlg._publish_layer_from_values(self.values())

        verb, path, kwargs = self.sent("PUT")[0]
        # "Roads (2024)" is not a WFS type name; "Roads_2024" is
        self.assertEqual(path, "/rest/workspaces/topp/datastores/Roads_2024/file.gpkg")
        self.assertEqual(kwargs["params"], {"update": "overwrite"})
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/x-sqlite3")
        self.assertTrue(kwargs["data"].startswith(b"SQLite format 3"))

    def test_the_uploaded_store_is_made_read_only_by_merging(self):
        self.add_layer()
        self.dlg._publish_layer_from_values(self.values())

        # the store exists because the upload created it
        kwargs = self.sent("create_datastore")[0][1]
        params = kwargs["connection_parameters"]
        self.assertEqual(params["read_only"], "true")
        # the server's own parameters are kept, not replaced by a template
        self.assertEqual(params["dbtype"], "geopkg")
        self.assertEqual(params["database"], "/data/Roads_2024.gpkg")
        self.assertEqual(kwargs["datastore_type"], "GeoPackage")

    def test_metadata_is_merged_onto_what_geoserver_computed(self):
        self.add_layer()
        self.dlg._publish_layer_from_values(
            self.values(title="Roads", abstract="Main roads", keywords="roads, 2024")
        )
        feature_type_puts = [
            call for call in self.sent("PUT") if "featuretypes" in call[1]
        ]
        _verb, path, kwargs = feature_type_puts[0]
        self.assertIn("/datastores/Roads_2024/featuretypes/Roads_2024.json", path)
        payload = kwargs["json"]["featureType"]
        self.assertEqual(payload["title"], "Roads")
        self.assertEqual(payload["abstract"], "Main roads")
        self.assertEqual(payload["keywords"], {"string": ["roads", "2024"]})
        # a partial PUT merges, so nothing else may be sent
        self.assertEqual(set(payload), {"title", "abstract", "keywords"})

    def test_no_metadata_means_no_extra_request(self):
        self.add_layer()
        self.dlg._publish_layer_from_values(self.values())
        self.assertEqual(
            [call for call in self.sent("PUT") if "featuretypes" in call[1]], []
        )

    def test_the_symbology_can_travel_with_the_data(self):
        self.add_layer(colour="#00aa44")
        self.dlg._publish_layer_from_values(self.values(with_style=True))
        style_puts = [call for call in self.sent("PUT") if "/styles/" in call[1]]
        self.assertEqual(
            style_puts[0][1], "/rest/workspaces/topp/styles/Roads_2024.sld"
        )
        self.assertIn(b"00aa44", style_puts[0][2]["data"].lower())
        self.assertIn(
            ("set_default", "Roads_2024", "topp", "topp:Roads_2024"),
            self.dlg.gs.style_calls,
        )

    def test_an_existing_datastore_is_refused_unless_replace_is_ticked(self):
        self.add_layer()
        self.dlg.gs = GpkgPublishFakeGS(datastore_exists=True)
        with self.assertRaises(ValueError) as caught:
            self.dlg._publish_layer_from_values(self.values())
        self.assertIn("Roads_2024", str(caught.exception))
        self.assertIn("Replace", str(caught.exception))
        self.assertEqual(self.sent("PUT"), [])

        self.dlg._publish_layer_from_values(self.values(replace=True))
        self.assertTrue(self.sent("PUT"))

    def test_an_existing_layer_is_refused_too(self):
        self.add_layer()
        self.dlg.gs = GpkgPublishFakeGS(layer_exists=True)
        with self.assertRaises(ValueError):
            self.dlg._publish_layer_from_values(self.values())

    def test_nothing_is_left_in_the_temporary_folder(self):
        import glob
        import tempfile

        self.add_layer()
        self.dlg._publish_layer_from_values(self.values())
        self.assertEqual(glob.glob(f"{tempfile.gettempdir()}/gsm_publish_*"), [])

    def test_a_table_source_still_goes_the_old_way(self):
        # the dispatch must not disturb the datastore-table path
        self.dlg.gs = PublishFakeGS()
        self.dlg._publish_layer_from_values(
            {
                "source": "A table in a datastore",
                "workspace": "topp",
                "datastore": "taz_shapes",
                "table": "plugin_demo",  # the fake's unpublished table
                "epsg": 4326,
                "title": "",
                "abstract": "",
                "keywords": "",
            }
        )
        self.assertEqual(self.dlg.gs.created[-1]["layer_name"], "plugin_demo")


class TestPublishForm(unittest.TestCase):
    """The publish dialog only shows the fields of the chosen source."""

    def setUp(self):
        from qgis.core import QgsProject

        QgsProject.instance().removeAllMapLayers()
        from tests.qgis.test_sld import point_layer

        QgsProject.instance().addMapLayer(point_layer("Roads (2024)"))
        self.dlg = SyncDialog()
        self.dlg.gs = GpkgPublishFakeGS()

    def tearDown(self):
        from qgis.core import QgsProject

        QgsProject.instance().removeAllMapLayers()

    def form(self):
        return ResourceFormDialog(title="t", fields=self.dlg._publish_fields(["topp"]))

    def test_the_table_source_hides_the_qgis_fields(self):
        form = self.form()
        self.dlg._on_publish_source_changed(form, "A table in a datastore")
        for key in ("datastore", "table", "epsg"):
            self.assertNotIn(key, form._hidden_keys)
        for key in ("qgis_layer", "name", "replace", "with_style"):
            self.assertIn(key, form._hidden_keys)

    def test_the_qgis_source_hides_the_table_fields_and_suggests_a_name(self):
        form = self.form()
        self.dlg._on_publish_source_changed(form, "A layer from this QGIS project")
        for key in ("datastore", "table", "epsg"):
            self.assertIn(key, form._hidden_keys)
        for key in ("qgis_layer", "name", "replace", "with_style"):
            self.assertNotIn(key, form._hidden_keys)
        # the name is filled in already, normalised, and still editable
        self.assertEqual(form.get_widget("name").text(), "Roads_2024")
        self.assertTrue(form.get_widget("name").isEnabled())

    def test_a_name_the_user_typed_is_not_overwritten(self):
        form = self.form()
        form.get_widget("name").setText("my_choice")
        self.dlg._prefill_publish_name(form, "Roads (2024)  (vector)")
        self.assertEqual(form.get_widget("name").text(), "my_choice")


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()


# ############################################################################
# ###### Preview in a browser ####
# ################################


class TestPreviewInBrowser(unittest.TestCase):
    """GeoServer's own OpenLayers page, on the layer's extent, in the browser."""

    def url(self, **kwargs):
        from geoserver_manager.gui.tab_layers import LayerTabMixin

        return LayerTabMixin._preview_url("http://gs/geoserver/", **kwargs)

    def test_a_workspace_layer_goes_through_its_virtual_service(self):
        url = self.url(
            qualified_name="topp:states",
            bbox=(0.0, 0.0, 4.0, 2.0),
            srs="EPSG:4326",
            workspace="topp",
        )
        self.assertTrue(url.startswith("http://gs/geoserver/topp/wms?"), url)
        for part in (
            "service=WMS",
            "version=1.1.0",
            "request=GetMap",
            "layers=topp:states",
            "bbox=0.0,0.0,4.0,2.0",
            "width=768",
            "height=384",
            "srs=EPSG:4326",
            "styles=",
            "format=application/openlayers",
        ):
            self.assertIn(part, url)

    def test_a_tall_extent_caps_the_height_instead(self):
        url = self.url(
            qualified_name="topp:states",
            bbox=(0.0, 0.0, 2.0, 4.0),
            srs="EPSG:4326",
            workspace="topp",
        )
        self.assertIn("width=384", url)
        self.assertIn("height=768", url)

    def test_a_global_group_has_no_workspace_anywhere(self):
        url = self.url(
            qualified_name="tasmania",
            bbox=(143.0, -44.0, 149.0, -40.0),
            srs="EPSG:4326",
        )
        self.assertTrue(url.startswith("http://gs/geoserver/wms?"), url)
        self.assertIn("layers=tasmania&", url)

    def test_without_an_extent_the_world(self):
        for bbox in (None, (1.0, 1.0, 1.0, 1.0)):
            url = self.url(
                qualified_name="x:y", bbox=bbox, srs="EPSG:2154", workspace="x"
            )
            self.assertIn("bbox=-180.0,-90.0,180.0,90.0", url)
            self.assertIn("srs=EPSG:4326", url)
            self.assertIn("width=768&height=384", url)

    def test_bbox_from_geoservers_shapes(self):
        from geoserver_manager.gui.tab_layers import LayerTabMixin

        box = {
            "minx": -124.731422,
            "maxx": -66.969849,
            "miny": 24.955967,
            "maxy": 49.371735,
            "crs": "EPSG:4326",
        }
        self.assertEqual(
            LayerTabMixin._bbox_from(box),
            ((-124.731422, 24.955967, -66.969849, 49.371735), "EPSG:4326"),
        )
        box["crs"] = {"@class": "projected", "$": "EPSG:2154"}
        self.assertEqual(LayerTabMixin._bbox_from(box)[1], "EPSG:2154")
        self.assertEqual(LayerTabMixin._bbox_from({"minx": 1}), (None, None))
        self.assertEqual(LayerTabMixin._bbox_from(None), (None, None))

    def test_the_row_action_opens_the_layers_own_extent(self):
        from geoserver_manager.gui import tab_layers

        class BboxGS(FakeGS):
            def get_feature_type(self, workspace_name, datastore_name, name):
                detail, status = super().get_feature_type(
                    workspace_name, datastore_name, name
                )
                detail["latLonBoundingBox"] = {
                    "minx": -124.731422,
                    "maxx": -66.969849,
                    "miny": 24.955967,
                    "maxy": 49.371735,
                    "crs": "EPSG:4326",
                }
                return detail, status

        class Settings:
            geoserver_url = "http://gs/geoserver"

        class Prefs:
            def get_plg_settings(self):
                return Settings()

        dlg = SyncDialog()
        dlg.gs = BboxGS()
        dlg.plg_settings = Prefs()
        opened = []
        with patch.object(
            tab_layers.QDesktopServices,
            "openUrl",
            lambda url: opened.append(url.toString()) or True,
        ):
            dlg._preview_layer_in_browser(
                ["states", "topp", "states_shapefile", "EPSG:4326", "True"]
            )
        self.assertEqual(len(opened), 1, opened)
        self.assertTrue(opened[0].startswith("http://gs/geoserver/topp/wms?"), opened)
        self.assertIn("layers=topp:states", opened[0])
        self.assertIn("bbox=-124.731422,24.955967,-66.969849,49.371735", opened[0])

    def test_a_browser_that_does_not_open_is_a_warning(self):
        from geoserver_manager.gui import tab_layers

        dlg = SyncDialog()
        warnings = []
        dlg.show_warning_message = warnings.append
        with patch.object(tab_layers.QDesktopServices, "openUrl", lambda url: False):
            dlg._open_in_browser("http://gs/geoserver/wms")
        self.assertEqual(len(warnings), 1)
        self.assertIn("http://gs/geoserver/wms", warnings[0])

    def test_the_action_sits_next_to_add_to_qgis_and_warns_about_the_login(self):
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        dlg.show_warning_message = lambda t: None
        dlg._load_layers()
        labels = [action[1] for action in dlg._row_actions]
        self.assertEqual(labels[:2], ["Add to QGIS", "Preview in a browser"])
        self.assertIn("log in", dlg._row_actions[1][3])
