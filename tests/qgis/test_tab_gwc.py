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

# The same states layer as GET .xml writes it: the form an edit round-trips
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
    cached broken:layer cannot be read. topp:roads, sf:archsites, the global
    group spearfish and topp's own group topp:overview are published but not
    cached."""

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

    def get_workspaces(self):
        return ([{"name": "topp"}, {"name": "sf"}], 200)

    def get_layer_groups(self, workspace_name=None):
        groups = {"topp": [{"name": "overview"}], "sf": []}
        return (groups.get(workspace_name, []), 200)

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
BROKEN_ROW = ["broken:layer", "broken", "-", "-", "-"]


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
        self.assertEqual(self.dlg._gwc_layer_summary(None), ("-", "-", "-"))
        # GWC writes an empty collection as "" and a single entry bare
        self.assertEqual(
            self.dlg._gwc_layer_summary(
                {
                    "enabled": True,
                    "gridSubsets": {"gridSetName": "EPSG:4326"},
                    "mimeFormats": "",
                }
            ),
            ("Yes", "EPSG:4326", "-"),
        )

    def test_gridsets_and_uncached_layers_come_from_the_server(self):
        self.assertEqual(self.dlg._gridset_names(), sorted(GRIDSETS))
        self.assertEqual(
            self.dlg._uncached_layer_names(),
            ["sf:archsites", "spearfish", "topp:overview", "topp:roads"],
        )


class TestDocument(unittest.TestCase):
    """The XML round trip an edit needs: read the form from it, write it back."""

    def test_form_values_read_the_document(self):
        self.assertEqual(
            GwcTabMixin._gwc_form_values(STATES_XML),
            {
                "name": "topp:states",
                "enabled": True,
                # The first gridset has published zoom levels 0-12.
                "gridsets": "EPSG:4326 = 0-12\nEPSG:900913",
                "formats": "image/png\nimage/jpeg",
                "meta_width": 4,
                "meta_height": 4,
                "expire_cache": 0,
                "expire_clients": 0,
                "gutter": 0,
                "filters": (
                    "<styleParameterFilter>\n  <key>STYLES</key>\n"
                    "  <defaultValue />\n</styleParameterFilter>"
                ),
            },
        )

    def test_saving_rewrites_only_what_the_form_owns(self):
        values = {
            "enabled": False,
            "gridsets": "EPSG:4326 = 0-12\nWebMercatorQuad\n\nEPSG:4326",
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
        # the kept gridset keeps its zoom bounds (the first line naming it
        # wins); the new one is bare
        self.assertEqual(root.find("gridSubsets/gridSubset").findtext("zoomStop"), "12")
        self.assertIsNone(root.findall("gridSubsets/gridSubset")[1].find("zoomStop"))
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

    def test_a_zoom_range_is_written_and_a_plain_line_clears_it(self):
        base = {"formats": "image/png"}
        root = ElementTree.fromstring(
            GwcTabMixin._gwc_xml_with_values(
                STATES_XML, dict(base, gridsets="EPSG:4326 = 3-9\nEPSG:900913 = 0-18")
            )
        )
        subsets = root.findall("gridSubsets/gridSubset")
        self.assertEqual(
            [(s.findtext("zoomStart"), s.findtext("zoomStop")) for s in subsets],
            [("3", "9"), ("0", "18")],
        )
        root = ElementTree.fromstring(
            GwcTabMixin._gwc_xml_with_values(
                STATES_XML, dict(base, gridsets="EPSG:4326")
            )
        )
        self.assertIsNone(root.find("gridSubsets/gridSubset/zoomStart"))

    def test_a_bad_zoom_range_is_refused(self):
        for line in ("EPSG:4326 = 12", "EPSG:4326 = 9-3", "EPSG:4326 = a-b"):
            with self.assertRaises(ValueError, msg=line):
                GwcTabMixin._gwc_xml_with_values(
                    STATES_XML, {"formats": "image/png", "gridsets": line}
                )

    def test_parameter_filters_are_replaced_from_their_xml(self):
        values = {
            "gridsets": "EPSG:4326",
            "formats": "image/png",
            "filters": (
                "<stringParameterFilter><key>CQL_FILTER</key><defaultValue/>"
                "<values><string>A=1</string></values></stringParameterFilter>"
            ),
        }
        root = ElementTree.fromstring(
            GwcTabMixin._gwc_xml_with_values(STATES_XML, values)
        )
        self.assertEqual(
            [f.tag for f in root.find("parameterFilters")], ["stringParameterFilter"]
        )
        with self.assertRaises(ValueError):
            GwcTabMixin._gwc_xml_with_values(
                STATES_XML, dict(values, filters="<stringParameterFilter>")
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
            ["sf:archsites", "spearfish", "topp:overview", "topp:roads"],
        )
        values = form.get_values()
        self.assertEqual(values["gridsets"], "EPSG:4326\nEPSG:900913")
        # the template's STYLES filter shows, so an untouched form keeps it
        self.assertIn("<key>STYLES</key>", values["filters"])
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
            "topp:overview",
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
        self.assertEqual(values["gridsets"], "EPSG:4326 = 0-12\nEPSG:900913")
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


class TestSeed(unittest.TestCase):
    """Measured on 2.28.5: POST /gwc/rest/seed/{layer}.json starts the task;
    GET lists [done, total, seconds left, id, state] per task."""

    VALUES = {
        "type": "Truncate",
        "gridset": "EPSG:4326",
        "format": "image/png",
        "zoom_start": 2,
        "zoom_stop": 6,
        "threads": 3,
        "bounds": "",
        "parameters": "",
    }

    def test_the_request_names_everything_gwc_needs(self):
        request = GwcTabMixin._seed_request("topp:states", self.VALUES)
        self.assertEqual(
            request,
            {
                "seedRequest": {
                    "name": "topp:states",
                    "gridSetId": "EPSG:4326",
                    "format": "image/png",
                    "type": "truncate",
                    "zoomStart": 2,
                    "zoomStop": 6,
                    "threadCount": 3,
                }
            },
        )

    def test_an_area_and_parameters_narrow_the_task(self):
        values = dict(
            self.VALUES, bounds="-125, 24 -66,50", parameters="STYLES = population"
        )
        request = GwcTabMixin._seed_request("topp:states", values)["seedRequest"]
        self.assertEqual(request["bounds"], {"coords": {"double": [-125, 24, -66, 50]}})
        self.assertEqual(
            request["parameters"], {"entry": [{"string": ["STYLES", "population"]}]}
        )

    def test_a_bad_area_or_zoom_order_is_refused(self):
        for bad in (
            {"bounds": "1, 2, 3"},
            {"bounds": "5, 0, 1, 1"},
            {"bounds": "a, b, c, d"},
            {"zoom_start": 7, "zoom_stop": 3},
        ):
            with self.assertRaises(ValueError, msg=bad):
                GwcTabMixin._seed_request("topp:states", dict(self.VALUES, **bad))

    def test_the_task_list_reads_as_sentences(self):
        text = GwcTabMixin._seed_tasks_text(
            {"long-array-array": [[656, 992290, 860, 4, 1], [-1, 130, -1, 1, 0]]}
        )
        self.assertEqual(
            text.splitlines(),
            [
                "Task 4: running, 656 of 992290 tiles, about 860 s left",
                "Task 1: pending, counting the tiles",
            ],
        )
        self.assertEqual(
            GwcTabMixin._seed_tasks_text({"long-array-array": []}),
            "No task running for this layer.",
        )

    def test_the_form_starts_the_task_then_opens_the_monitor(self):
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        values = dict(self.VALUES, type="Seed")

        class Accepting(ResourceFormDialog):
            def exec(inner):
                return QDialog.DialogCode.Accepted

            def get_values(inner):
                return values

        with (
            patch.object(tab_gwc, "ResourceFormDialog", Accepting),
            patch.object(dlg, "_show_seed_tasks") as monitor,
        ):
            dlg._seed_gwc_layer(STATES_ROW)
        posts = [call for call in dlg.gs.calls if call[0] == "POST"]
        self.assertEqual(posts[0][1], "/gwc/rest/seed/topp:states.json")
        self.assertEqual(posts[0][2]["json"]["seedRequest"]["type"], "seed")
        monitor.assert_called_once_with(STATES_ROW)

    def test_a_failed_read_is_shown_in_the_monitor_not_raised(self):
        dlg = SyncDialog()

        class Client:
            def get(inner, path, **kwargs):
                return Response("boom", 500, text="boom")

        self.assertEqual(
            dlg._read_seed_tasks(Client(), "/gwc/rest/seed/x.json"), "HTTP 500: boom"
        )
