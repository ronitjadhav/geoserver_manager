#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_tab_gwc
"""

import xml.etree.ElementTree as ElementTree
from unittest.mock import patch

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
from qgis.testing import start_app, unittest

from geoserver_manager.gui import tab_gwc
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_gwc import GwcTabMixin
from tests.qgis.sync_dialog import SyncDialog

start_app()

# A cached layer as GET /gwc/rest/layers/topp:states.json hands it back on 2.28.5
STATES = {
    "GeoServerLayer": {
        "expireClients": 0,
        "gutter": 0,
        "expireCache": 0,
        "parameterFilters": [{"defaultValue": "", "key": "STYLES"}],
        "metaWidthHeight": [4, 4],
        "cacheWarningSkips": [],
        "name": "topp:states",
        "mimeFormats": ["image/png", "image/jpeg"],
        "id": "LayerInfoImpl--570ae188:124761b8d78:-7fc0",
        "gridSubsets": [{"gridSetName": "EPSG:4326"}, {"gridSetName": "EPSG:900913"}],
        "enabled": True,
    }
}

# A global layer group, cached under its bare name, one gridset, disabled
TASMANIA = {
    "GeoServerLayer": {
        "name": "tasmania",
        "id": "LayerGroupInfoImpl--570ae188:124761b8d78:-7fac",
        "enabled": False,
        "mimeFormats": ["image/png"],
        "gridSubsets": [{"gridSetName": "EPSG:4326"}],
        "metaWidthHeight": [4, 4],
        "parameterFilters": [],
    }
}

# The same states layer as GET .xml writes it — the form an edit round-trips
STATES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<GeoServerLayer>
  <id>LayerInfoImpl--570ae188:124761b8d78:-7fc0</id>
  <enabled>true</enabled>
  <name>topp:states</name>
  <mimeFormats>
    <string>image/png</string>
    <string>image/jpeg</string>
  </mimeFormats>
  <gridSubsets>
    <gridSubset>
      <gridSetName>EPSG:4326</gridSetName>
      <zoomStart>0</zoomStart>
      <zoomStop>12</zoomStop>
    </gridSubset>
    <gridSubset>
      <gridSetName>EPSG:900913</gridSetName>
    </gridSubset>
  </gridSubsets>
  <metaWidthHeight>
    <int>4</int>
    <int>4</int>
  </metaWidthHeight>
  <expireCache>0</expireCache>
  <expireClients>0</expireClients>
  <gutter>0</gutter>
  <parameterFilters>
    <styleParameterFilter>
      <key>STYLES</key>
      <defaultValue></defaultValue>
    </styleParameterFilter>
  </parameterFilters>
</GeoServerLayer>
"""

GRIDSETS = ["EPSG:900913", "EPSG:4326", "WebMercatorQuad"]


class Response:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or str(payload)

    def json(self):
        if isinstance(self._payload, (dict, list)):
            return self._payload
        raise ValueError("not JSON")


class FakeGS:
    """GeoWebCache caches topp:states and the global group tasmania; the
    cached broken:layer cannot be read. topp:roads, sf:archsites and the
    group spearfish are published but not cached."""

    def __init__(self, cached=("broken:layer", "tasmania", "topp:states")):
        self.cached = list(cached)
        self.calls = []
        outer = self

        class Gwc:
            base_url = "/gwc/rest"

            def layers(inner, workspace_name):
                return "/gwc/rest/layers.json"

            def layer(inner, workspace_name, layer_name):
                return f"/gwc/rest/layers/{workspace_name}:{layer_name}.json"

            def gridsets(inner):
                return "/gwc/rest/gridsets.json"

        class Rest:
            base_url = "/rest"

        class Client:
            def get(inner, path, **kwargs):
                outer.calls.append(("GET", path, kwargs))
                return outer.answer(path)

            def put(inner, path, **kwargs):
                outer.calls.append(("PUT", path, kwargs))
                return Response(text="layer saved")

            def post(inner, path, **kwargs):
                outer.calls.append(("POST", path, kwargs))
                return Response(text="")

            def delete(inner, path, **kwargs):
                outer.calls.append(("DELETE", path, kwargs))
                return Response(text="deleted")

        class Service:
            rest_client = Client()
            gwc_endpoints = Gwc()
            rest_endpoints = Rest()

            def resource_exists(inner, path):
                outer.calls.append(("EXISTS", path))
                return outer.answer(path).status_code == 200

        self.rest_service = Service()

    def answer(self, path):
        if path == "/gwc/rest/layers.json":
            return Response(list(self.cached))
        if path == "/gwc/rest/layers/tasmania.json":
            return Response(TASMANIA)
        if path == "/gwc/rest/layers/topp:states.xml":
            return Response(text=STATES_XML)
        if path == "/gwc/rest/gridsets.json":
            return Response(list(GRIDSETS))
        if path == "/rest/layers.json":
            return Response(
                {
                    "layers": {
                        "layer": [
                            {"name": "topp:states", "href": "…"},
                            {"name": "topp:roads", "href": "…"},
                            {"name": "sf:archsites", "href": "…"},
                        ]
                    }
                }
            )
        if path == "/rest/layergroups.json":
            return Response(
                {
                    "layerGroups": {
                        "layerGroup": [
                            {"name": "tasmania", "href": "…"},
                            {"name": "spearfish", "href": "…"},
                        ]
                    }
                }
            )
        return Response("Unknown layer", 404, text="Unknown layer")

    def get_gwc_layer(self, workspace_name, layer):
        self.calls.append(("get_gwc_layer", workspace_name, layer))
        if (workspace_name, layer) == ("topp", "states"):
            return (STATES, 200)
        if workspace_name == "broken":
            raise RuntimeError("HTTP 500: boom")
        return ("Unknown layer", 404)

    def delete_gwc_layer(self, workspace_name, layer):
        self.calls.append(("delete_gwc_layer", workspace_name, layer))
        return (f"{workspace_name}:{layer} deleted", 200)


STATES_ROW = [
    "topp:states",
    "topp",
    "Yes",
    "EPSG:4326, EPSG:900913",
    "image/png, image/jpeg",
]
TASMANIA_ROW = ["tasmania", "(global)", "No", "EPSG:4326", "image/png"]
BROKEN_ROW = ["broken:layer", "broken", "—", "—", "—"]


class Recording(ResourceFormDialog):
    opened = []

    def exec(self):
        Recording.opened.append(self)
        return QDialog.DialogCode.Rejected


def confirm_yes(kind, labels, cascade="", **kwargs):
    return True


class TestListing(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = self.dlg.gs = FakeGS()
        self.dlg.show_warning_message = lambda text: None

    def test_rows_carry_every_cached_layer_and_a_broken_one_is_reported_not_fatal(
        self,
    ):
        rows, failures = self.dlg._fetch_gwc_rows()
        self.assertEqual(rows, [BROKEN_ROW, TASMANIA_ROW, STATES_ROW])
        self.assertEqual([label for label, _ in failures], ["broken:layer"])
        # workspace layers go through the library, a global group cannot
        self.assertIn(("get_gwc_layer", "topp", "states"), self.gs.calls)
        self.assertIn(("GET", "/gwc/rest/layers/tasmania.json", {}), self.gs.calls)

    def test_the_whole_loader_renders_them(self):
        self.dlg._load_gwc_layers()
        self.assertEqual(self.dlg._all_rows, [BROKEN_ROW, TASMANIA_ROW, STATES_ROW])
        self.assertEqual(self.dlg.resultsTable.columnCount(), 6)
        self.assertEqual(self.dlg.btn_add.text(), "Add a Layer to the Cache")

    def test_the_workspace_column_links_except_for_a_global_group(self):
        opened = []
        self.dlg._show_workspace_info = lambda row: opened.append(row)
        self.dlg._open_workspace_from_row(TASMANIA_ROW)
        self.assertEqual(opened, [])
        self.dlg._open_workspace_from_row(STATES_ROW)
        self.assertEqual(opened, [["topp"]])

    def test_a_layer_whose_get_failed_shows_dashes(self):
        self.assertEqual(self.dlg._gwc_layer_summary(None), ("—", "—", "—"))
        # GWC writes an empty collection as "" and a single entry bare
        self.assertEqual(
            self.dlg._gwc_layer_summary(
                {
                    "enabled": True,
                    "gridSubsets": {"gridSetName": "EPSG:4326"},
                    "mimeFormats": "",
                }
            ),
            ("Yes", "EPSG:4326", "—"),
        )

    def test_gridsets_and_uncached_layers_come_from_the_server(self):
        self.assertEqual(self.dlg._gridset_names(), sorted(GRIDSETS))
        self.assertEqual(
            self.dlg._uncached_layer_names(),
            ["sf:archsites", "spearfish", "topp:roads"],
        )


class TestDocument(unittest.TestCase):
    """The XML round trip an edit needs: read the form from it, write it back."""

    def test_form_values_read_the_document(self):
        self.assertEqual(
            GwcTabMixin._gwc_form_values(STATES_XML),
            {
                "name": "topp:states",
                "enabled": True,
                "gridsets": "EPSG:4326\nEPSG:900913",
                "formats": "image/png\nimage/jpeg",
                "meta_width": 4,
                "meta_height": 4,
                "expire_cache": 0,
                "expire_clients": 0,
                "gutter": 0,
            },
        )

    def test_saving_rewrites_only_what_the_form_owns(self):
        values = {
            "enabled": False,
            "gridsets": "EPSG:4326\nWebMercatorQuad\n\nEPSG:4326",
            "formats": "image/png",
            "meta_width": 3,
            "meta_height": 3,
            "expire_cache": 3600,
            "expire_clients": 0,
            "gutter": 5,
        }
        root = ElementTree.fromstring(
            GwcTabMixin._gwc_xml_with_values(STATES_XML, values)
        )
        self.assertEqual(root.findtext("enabled"), "false")
        self.assertEqual(
            [s.findtext("gridSetName") for s in root.findall("gridSubsets/gridSubset")],
            ["EPSG:4326", "WebMercatorQuad"],
        )
        # the kept gridset keeps its zoom bounds; the new one is bare
        self.assertEqual(root.find("gridSubsets/gridSubset").findtext("zoomStop"), "12")
        self.assertEqual(
            [s.text for s in root.findall("mimeFormats/string")], ["image/png"]
        )
        self.assertEqual(
            [i.text for i in root.findall("metaWidthHeight/int")], ["3", "3"]
        )
        self.assertEqual(root.findtext("expireCache"), "3600")
        self.assertEqual(root.findtext("gutter"), "5")
        # what the form does not model stays as GeoServer wrote it
        self.assertEqual(
            root.findtext("id"), "LayerInfoImpl--570ae188:124761b8d78:-7fc0"
        )
        self.assertEqual(
            root.findtext("parameterFilters/styleParameterFilter/key"), "STYLES"
        )

    def test_an_empty_gridset_or_format_list_is_refused(self):
        values = {"gridsets": "", "formats": "image/png"}
        with self.assertRaises(ValueError):
            GwcTabMixin._gwc_xml_with_values(STATES_XML, values)
        values = {"gridsets": "EPSG:4326", "formats": "  \n"}
        with self.assertRaises(ValueError):
            GwcTabMixin._gwc_xml_with_values(STATES_XML, values)


class TestActions(unittest.TestCase):
    def setUp(self):
        Recording.opened.clear()
        self.dlg = SyncDialog()
        self.gs = self.dlg.gs = FakeGS()
        self.dlg.show_warning_message = lambda text: None
        self.dlg.show_error_message = lambda text: None
        self.dlg.show_success_message = lambda text: None
        self.warnings = []
        self.dlg.show_warning_message = self.warnings.append

    def puts(self):
        return [
            (path, kwargs)
            for verb, path, kwargs in [c for c in self.gs.calls if c[0] == "PUT"]
        ]

    def test_saving_puts_the_xml_document_back(self):
        values = GwcTabMixin._gwc_form_values(STATES_XML)
        values["enabled"] = False
        self.dlg._save_gwc_layer("topp:states", STATES_XML, values)
        [(path, kwargs)] = self.puts()
        self.assertEqual(path, "/gwc/rest/layers/topp:states.xml")
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/xml"})
        self.assertIn("<enabled>false</enabled>", kwargs["data"].decode())

    def test_creating_puts_a_complete_document(self):
        values = {
            "layer": "topp:roads",
            "enabled": True,
            "gridsets": "EPSG:4326\nEPSG:900913",
            "formats": "image/png\nimage/jpeg",
            "meta_width": 4,
            "meta_height": 4,
            "expire_cache": 0,
            "expire_clients": 0,
            "gutter": 0,
        }
        self.dlg._create_gwc_layer_from_values(values)
        [(path, kwargs)] = self.puts()
        self.assertEqual(path, "/gwc/rest/layers/topp:roads.xml")
        root = ElementTree.fromstring(kwargs["data"])
        self.assertEqual(root.findtext("name"), "topp:roads")
        self.assertEqual(len(root.findall("gridSubsets/gridSubset")), 2)
        self.assertEqual(len(root.findall("mimeFormats/string")), 2)
        self.assertEqual(
            [i.text for i in root.findall("metaWidthHeight/int")], ["4", "4"]
        )
        # the STYLES filter GeoServer itself configures: one tile set per style
        self.assertEqual(
            root.findtext("parameterFilters/styleParameterFilter/key"), "STYLES"
        )

    def test_creating_refuses_a_layer_that_is_cached_already(self):
        values = {
            "layer": "topp:states",
            "gridsets": "EPSG:4326",
            "formats": "image/png",
        }
        with self.assertRaises(ValueError):
            self.dlg._create_gwc_layer_from_values(values)
        self.assertIn(("get_gwc_layer", "topp", "states"), self.gs.calls)
        self.assertEqual(self.puts(), [])

    def test_truncate_asks_first_then_mass_truncates(self):
        self.dlg._confirm_delete = lambda kind, labels, cascade="", **kwargs: False
        self.dlg._truncate_gwc_layer(STATES_ROW)
        self.assertEqual([c for c in self.gs.calls if c[0] == "POST"], [])

        self.dlg._confirm_delete = confirm_yes
        self.dlg._truncate_gwc_layer(STATES_ROW)
        [(_verb, path, kwargs)] = [c for c in self.gs.calls if c[0] == "POST"]
        self.assertEqual(path, "/gwc/rest/masstruncate")
        self.assertEqual(
            kwargs["data"],
            "<truncateLayer><layerName>topp:states</layerName></truncateLayer>",
        )
        # GWC's mass-truncate rejects application/xml with a 400
        self.assertEqual(kwargs["headers"], {"Content-Type": "text/xml"})

    def test_remove_uses_the_library_for_a_workspace_layer_and_raw_for_a_group(self):
        cascades = []

        def confirm(kind, labels, cascade="", **kwargs):
            cascades.append((kind, labels, cascade))
            return True

        self.dlg._confirm_delete = confirm
        self.dlg._remove_selected_gwc_layers([STATES_ROW, TASMANIA_ROW])
        self.assertIn(("delete_gwc_layer", "topp", "states"), self.gs.calls)
        self.assertIn(("DELETE", "/gwc/rest/layers/tasmania.json", {}), self.gs.calls)
        [(kind, labels, cascade)] = cascades
        self.assertEqual(labels, ["topp:states", "tasmania"])
        self.assertIn("layer itself stays", cascade)

    def test_the_add_dialog_offers_the_uncached_layers_with_geoservers_defaults(self):
        with patch.object(tab_gwc, "ResourceFormDialog", Recording):
            self.dlg._add_gwc_layer()
        form = Recording.opened[-1]
        self.assertEqual(form.windowTitle(), "Add a Layer to the Cache")
        ok = QDialogButtonBox.StandardButton.Ok
        self.assertEqual(form._button_box.button(ok).text(), "Create")
        combo = form.get_widget("layer")
        self.assertEqual(
            [combo.itemText(i) for i in range(combo.count())],
            ["sf:archsites", "spearfish", "topp:roads"],
        )
        values = form.get_values()
        self.assertEqual(values["gridsets"], "EPSG:4326\nEPSG:900913")
        self.assertEqual(values["formats"], "image/png\nimage/jpeg")
        self.assertEqual((values["meta_width"], values["meta_height"]), (4, 4))
        # the picker appends to the textarea and resets itself
        form.get_widget("add_gridset").setCurrentText("WebMercatorQuad")
        self.assertEqual(
            form.get_values()["gridsets"], "EPSG:4326\nEPSG:900913\nWebMercatorQuad"
        )
        self.assertEqual(form.get_widget("add_gridset").currentText(), "")

    def test_nothing_to_add_is_a_warning_not_an_empty_dialog(self):
        self.gs.cached = [
            "topp:states",
            "topp:roads",
            "sf:archsites",
            "tasmania",
            "spearfish",
        ]
        with patch.object(tab_gwc, "ResourceFormDialog", Recording):
            self.dlg._add_gwc_layer()
        self.assertEqual(Recording.opened, [])
        self.assertTrue(self.warnings and "cached already" in self.warnings[0])

    def test_the_edit_dialog_is_prefilled_from_the_xml_document(self):
        with patch.object(tab_gwc, "ResourceFormDialog", Recording):
            self.dlg._show_gwc_layer_info(STATES_ROW)
        form = Recording.opened[-1]
        self.assertEqual(form.windowTitle(), "Tile cache of 'topp:states'")
        values = form.get_values()
        self.assertEqual(values["name"], "topp:states")
        self.assertEqual(values["gridsets"], "EPSG:4326\nEPSG:900913")
        self.assertTrue(values["enabled"])
        ok = QDialogButtonBox.StandardButton.Ok
        self.assertEqual(form._button_box.button(ok).text(), "Save")  # an edit


if __name__ == "__main__":
    unittest.main()


class TestNamesInPaths(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()

    def test_a_cached_layer_path_is_quoted_but_keeps_its_colon(self):
        self.assertEqual(
            self.dlg._gwc_layer_path("topp:a b", "xml"),
            "/gwc/rest/layers/topp:a%20b.xml",
        )
        self.assertEqual(self.dlg._gwc_layer_path("a#b"), "/gwc/rest/layers/a%23b.json")

    def test_a_name_the_paths_cannot_carry_is_refused_before_any_request(self):
        with self.assertRaises(ValueError):
            self.dlg._create_gwc_layer_from_values(
                {"layer": "topp/roads", "gridsets": "EPSG:4326", "formats": "image/png"}
            )
        self.assertEqual([c for c in self.dlg.gs.calls if c[0] == "PUT"], [])
