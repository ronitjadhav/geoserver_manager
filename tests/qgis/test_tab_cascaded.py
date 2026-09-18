#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_tab_cascaded
"""

from unittest.mock import patch

from qgis.PyQt.QtWidgets import QDialog
from qgis.testing import start_app, unittest

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_cascaded import WMS, WMTS, CascadedStoreTabMixin
from tests.qgis.sync_dialog import SyncDialog

start_app()

CAPS = "http://remote.example.org/geoserver/wms?service=WMS&request=GetCapabilities"
TILES = "http://remote.example.org/geoserver/gwc/service/wmts?REQUEST=GetCapabilities"

# A cascaded WMS layer as the library's get_wms_layer() hands it back (asdict)
STATES_DETAIL = {
    "name": "states",
    "nativeName": "topp:states",
    "store": {"name": "topp:remote"},
    "namespace": {"name": "topp"},
    "title": "USA Population",
    "abstract": "Census data on the states.",
    "latLonBoundingBox": {
        "minx": -124.73,
        "maxx": -66.97,
        "miny": 24.96,
        "maxy": 49.37,
        "crs": "EPSG:4326",
    },
    "srs": "EPSG:4326",
    "keywords": ["census", "states"],
    "enabled": True,
}

# The same through a raw GET of a WMTS layer: keywords and CRS are wrapped
RAW_TILES_DETAIL = {
    "wmtsLayer": {
        "name": "states",
        "nativeName": "topp:states",
        "title": "USA Population",
        "srs": "EPSG:4326",
        "enabled": True,
        "keywords": {"string": "census"},
        "latLonBoundingBox": {
            "minx": -124.73,
            "maxx": -66.97,
            "miny": 24.96,
            "maxy": 49.37,
            "crs": {"@class": "projected", "$": "EPSG:4326"},
        },
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
    """topp has a WMS store `remote` publishing `states`; sf a WMTS store
    `tiles` publishing nothing yet; `broken` cannot be listed at all."""

    PAYLOADS = {
        "/rest/workspaces/topp/wmsstores.json": {
            "wmsStores": {"wmsStore": [{"name": "remote", "href": "…"}]}
        },
        "/rest/workspaces/topp/wmtsstores.json": {"wmtsStores": ""},
        "/rest/workspaces/sf/wmsstores.json": {"wmsStores": ""},
        # a one-entry collection: GeoServer writes the entry bare, not in a list
        "/rest/workspaces/sf/wmtsstores.json": {
            "wmtsStores": {"wmtsStore": {"name": "tiles", "href": "…"}}
        },
        "/rest/workspaces/sf/wmtsstores/tiles.json": {
            "wmtsStore": {
                "name": "tiles",
                "type": "WMTS",
                "enabled": False,
                "workspace": {"name": "sf"},
                "capabilitiesURL": TILES,
            }
        },
        "/rest/workspaces/topp/wmsstores/remote/wmslayers.json": {
            "wmsLayers": {"wmsLayer": [{"name": "states", "href": "…"}]}
        },
        "/rest/workspaces/sf/wmtsstores/tiles/layers.json": {"wmtsLayers": ""},
        "/rest/workspaces/sf/wmtsstores/tiles/layers/states.json": RAW_TILES_DETAIL,
    }
    AVAILABLE = {
        "/rest/workspaces/topp/wmsstores/remote/wmslayers.json": {
            "list": {"string": ["topp:states", "topp:roads"]}
        },
        # one advertised layer: a bare string, not a one-item list
        "/rest/workspaces/sf/wmtsstores/tiles/layers.json": {
            "list": {"string": "topp:states"}
        },
    }

    def __init__(self):
        self.calls = []
        outer = self

        class Endpoints:
            def wmsstores(inner, ws):
                return f"/rest/workspaces/{ws}/wmsstores.json"

            def wmsstore(inner, ws, name):
                return f"/rest/workspaces/{ws}/wmsstores/{name}.json"

            def wmtsstores(inner, ws):
                return f"/rest/workspaces/{ws}/wmtsstores.json"

            def wmtsstore(inner, ws, name):
                return f"/rest/workspaces/{ws}/wmtsstores/{name}.json"

            def wmslayers(inner, ws, store):
                return f"/rest/workspaces/{ws}/wmsstores/{store}/wmslayers.json"

            def wmslayer(inner, ws, store, layer):
                return f"/rest/workspaces/{ws}/wmsstores/{store}/wmslayers/{layer}.json"

            def wmtslayers(inner, ws, store):
                return f"/rest/workspaces/{ws}/wmtsstores/{store}/layers.json"

            def wmtslayer(inner, ws, store, layer):
                return f"/rest/workspaces/{ws}/wmtsstores/{store}/layers/{layer}.json"

        class Client:
            def get(inner, path, **kwargs):
                outer.calls.append(("GET", path, kwargs))
                return outer.answer(path, kwargs.get("params") or {})

            def post(inner, path, **kwargs):
                outer.calls.append(("POST", path, kwargs))
                return Response("created", 201)

            def delete(inner, path, **kwargs):
                outer.calls.append(("DELETE", path, kwargs))
                return Response("", 200)

        class Service:
            rest_client = Client()
            rest_endpoints = Endpoints()

            def resource_exists(inner, path):
                outer.calls.append(("EXISTS", path))
                return outer.answer(path, {}).status_code == 200

        self.rest_service = Service()

    def answer(self, path, params):
        if "/broken/" in path:
            raise RuntimeError("HTTP 500: boom")
        if params.get("list") == "available":
            return Response(self.AVAILABLE[path])
        if path in self.PAYLOADS:
            return Response(self.PAYLOADS[path])
        return Response("No such resource", 404)

    def get_workspaces(self):
        return ([{"name": "topp"}, {"name": "sf"}, {"name": "broken"}], 200)

    def get_wms_store(self, ws, name):
        self.calls.append(("get_wms_store", ws, name))
        if (ws, name) == ("topp", "remote"):
            return (
                {
                    "name": "remote",
                    "type": "WMS",
                    "workspace": "topp",
                    "capabilitiesURL": CAPS,
                    "enabled": True,
                    "_default": False,
                    "disableOnConnFailure": False,
                },
                200,
            )
        return ("No such wms store", 404)

    def create_wms_store(self, ws, name, url):
        self.calls.append(("create_wms_store", ws, name, url))
        return (name, 201)

    def create_wmts_store(self, ws, name, url):
        self.calls.append(("create_wmts_store", ws, name, url))
        return (name, 201)

    def delete_wms_store(self, ws, name):
        self.calls.append(("delete_wms_store", ws, name))
        return ("", 200)

    def delete_wmts_store(self, ws, name):
        self.calls.append(("delete_wmts_store", ws, name))
        return ("", 200)

    def get_wms_layer(self, ws, store, layer):
        self.calls.append(("get_wms_layer", ws, store, layer))
        if (ws, store, layer) == ("topp", "remote", "states"):
            return (STATES_DETAIL, 200)
        return ("No such cascaded wms", 404)

    def create_wms_layer(self, ws, store, native, published=None):
        self.calls.append(("create_wms_layer", ws, store, native, published))
        return (published, 201)

    def delete_wms_layer(self, ws, store, layer):
        self.calls.append(("delete_wms_layer", ws, store, layer))
        return ("", 200)


REMOTE_ROW = ["remote", "topp", WMS, "True", CAPS]
TILES_ROW = ["tiles", "sf", WMTS, "False", TILES]


class TestListing(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = self.dlg.gs = FakeGS()
        self.dlg.show_warning_message = lambda text: None

    def test_rows_carry_both_kinds_and_a_broken_workspace_is_reported_not_fatal(self):
        rows, failures = self.dlg._fetch_cascaded_store_rows()
        self.assertEqual(rows, [REMOTE_ROW, TILES_ROW])
        self.assertEqual([label for label, _ in failures], ["broken"])

    def test_the_whole_loader_renders_them(self):
        self.dlg._load_cascaded_stores()
        self.assertEqual(self.dlg._all_rows, [REMOTE_ROW, TILES_ROW])
        self.assertEqual(self.dlg.resultsTable.columnCount(), 6)
        self.assertEqual(self.dlg.btn_add.text(), "Add a Cascaded Store")

    def test_a_store_whose_get_fails_shows_dashes(self):
        self.assertEqual(
            CascadedStoreTabMixin._cascaded_store_summary(None), ("—", "—")
        )

    def test_layer_names_configured_and_advertised(self):
        self.assertEqual(
            self.dlg._cascaded_layer_names("topp", "remote", WMS), ["states"]
        )
        self.assertEqual(
            self.dlg._cascaded_layer_names("topp", "remote", WMS, available=True),
            ["topp:states", "topp:roads"],
        )
        # an empty collection, and a single advertised layer written bare
        self.assertEqual(self.dlg._cascaded_layer_names("sf", "tiles", WMTS), [])
        self.assertEqual(
            self.dlg._cascaded_layer_names("sf", "tiles", WMTS, available=True),
            ["topp:states"],
        )


class TestCreate(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = self.dlg.gs = FakeGS()

    def values(self, **overrides):
        values = {
            "workspace": "sf",
            "name": "new",
            "type": WMS,
            "capabilities_url": CAPS,
        }
        values.update(overrides)
        return values

    def creates(self):
        return [c for c in self.gs.calls if c[0].startswith("create_")]

    def test_create_routes_by_type(self):
        self.dlg._create_cascaded_store_from_values(self.values())
        self.dlg._create_cascaded_store_from_values(
            self.values(type=WMTS, capabilities_url=TILES)
        )
        self.assertEqual(
            self.creates(),
            [
                ("create_wms_store", "sf", "new", CAPS),
                ("create_wmts_store", "sf", "new", TILES),
            ],
        )

    def test_add_refuses_an_existing_name_of_either_kind(self):
        with self.assertRaises(ValueError):
            self.dlg._create_cascaded_store_from_values(
                self.values(workspace="topp", name="remote")
            )
        with self.assertRaises(ValueError):
            self.dlg._create_cascaded_store_from_values(
                self.values(name="tiles", type=WMTS)
            )
        self.assertEqual(self.creates(), [])

    def test_add_refuses_a_url_without_a_scheme(self):
        with self.assertRaises(ValueError):
            self.dlg._create_cascaded_store_from_values(
                self.values(capabilities_url="remote.example.org/wms")
            )
        self.assertEqual(self.creates(), [])


class TestCascadedLayers(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = self.dlg.gs = FakeGS()
        self.messages = []
        self.dlg.show_success_message = self.messages.append
        self.dlg.show_warning_message = self.messages.append
        self.dlg.show_error_message = self.messages.append

    def test_publish_goes_through_the_library_for_wms_and_posts_for_wmts(self):
        self.dlg._create_cascaded_layer("topp", "remote", WMS, "topp:roads", "roads")
        self.dlg._create_cascaded_layer("sf", "tiles", WMTS, "topp:states", "usa")
        self.assertIn(
            ("create_wms_layer", "topp", "remote", "topp:roads", "roads"), self.gs.calls
        )
        posts = [c for c in self.gs.calls if c[0] == "POST"]
        self.assertEqual(
            posts,
            [
                (
                    "POST",
                    "/rest/workspaces/sf/wmtsstores/tiles/layers.json",
                    {
                        "json": {
                            "wmtsLayer": {"name": "usa", "nativeName": "topp:states"}
                        }
                    },
                )
            ],
        )

    def test_publish_refuses_a_name_that_is_already_published(self):
        with self.assertRaises(ValueError):
            self.dlg._create_cascaded_layer(
                "topp", "remote", WMS, "topp:states", "states"
            )
        self.assertFalse([c for c in self.gs.calls if c[0] == "create_wms_layer"])

    def test_the_publish_dialog_defaults_the_name_to_the_remote_name_unprefixed(self):
        with (
            patch.object(
                ResourceFormDialog, "exec", return_value=QDialog.DialogCode.Accepted
            ),
            patch.object(
                ResourceFormDialog,
                "get_values",
                return_value={"native_name": "topp:roads", "name": ""},
            ),
        ):
            self.dlg._publish_cascaded_layer(REMOTE_ROW)
        self.assertIn(
            ("create_wms_layer", "topp", "remote", "topp:roads", "roads"), self.gs.calls
        )
        self.assertIn("'topp:roads' published as layer 'roads'.", self.messages)

    def test_delete_sends_recurse_because_the_layer_references_the_resource(self):
        self.dlg._delete_cascaded_layer("topp", "remote", WMS, "states")
        self.dlg._delete_cascaded_layer("sf", "tiles", WMTS, "states")
        self.assertIn(("delete_wms_layer", "topp", "remote", "states"), self.gs.calls)
        self.assertIn(
            (
                "DELETE",
                "/rest/workspaces/sf/wmtsstores/tiles/layers/states.json",
                {"params": {"recurse": "true"}},
            ),
            self.gs.calls,
        )

    def test_layer_form_values_read_both_payload_shapes(self):
        from_library = CascadedStoreTabMixin._cascaded_layer_form_values(STATES_DETAIL)
        self.assertEqual(from_library["native_name"], "topp:states")
        self.assertEqual(from_library["keywords"], "census, states")
        self.assertEqual(
            from_library["bounds"], "-124.73 24.96 — -66.97 49.37 (EPSG:4326)"
        )
        raw = CascadedStoreTabMixin._cascaded_layer_form_values(
            RAW_TILES_DETAIL["wmtsLayer"]
        )
        self.assertEqual(raw["keywords"], "census")
        self.assertEqual(raw["bounds"], "-124.73 24.96 — -66.97 49.37 (EPSG:4326)")
        self.assertEqual(raw["abstract"], "")

    def test_the_layers_viewer_warns_when_nothing_is_published(self):
        self.dlg._show_cascaded_layers(TILES_ROW)
        self.assertEqual(len(self.messages), 1)
        self.assertIn("publishes no layer yet", self.messages[0])


class TestDelete(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = self.dlg.gs = FakeGS()
        self.dlg.show_success_message = lambda text: None
        self.asked = []

        def confirm(kind, labels, cascade=""):
            self.asked.append((kind, labels, cascade))
            return True

        self.dlg._confirm_delete = confirm

    def test_store_delete_names_the_cascade_and_uses_the_typed_library_call(self):
        self.dlg._delete_selected_cascaded_stores([REMOTE_ROW, TILES_ROW])
        kind, labels, cascade = self.asked[0]
        self.assertEqual(kind, "cascaded store")
        self.assertEqual(labels, ["topp/remote", "sf/tiles"])
        self.assertIn("cascaded layer", cascade)
        self.assertIn(("delete_wms_store", "topp", "remote"), self.gs.calls)
        self.assertIn(("delete_wmts_store", "sf", "tiles"), self.gs.calls)

    def test_store_form_values(self):
        values = CascadedStoreTabMixin._cascaded_store_form_values(
            {
                "name": "tiles",
                "type": "WMTS",
                "enabled": False,
                "capabilitiesURL": TILES,
            },
            "sf",
            WMTS,
            [],
        )
        self.assertEqual(values["capabilities_url"], TILES)
        self.assertEqual(values["enabled"], "False")
        self.assertEqual(values["layers"], "—")


if __name__ == "__main__":
    unittest.main()
