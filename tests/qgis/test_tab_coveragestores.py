#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    python -m unittest tests.qgis.test_tab_coveragestores
"""

# standard library
from unittest.mock import patch

from qgis.PyQt.QtWidgets import QDialog
from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui import tab_coveragestores
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_coveragestores import (
    COG,
    GEOTIFF,
    MOSAIC_DIRECTORY,
    MOSAIC_ZIP,
    CoverageStoreTabMixin,
)
from tests.qgis.sync_dialog import SyncDialog

start_app()

# A store and a coverage as GeoServer really answers them: the store carries a
# description the library's model drops, the coverage a bounding box and
# keywords its model drops, and a single band is not wrapped in a list.
SFDEM_STORE = {
    "name": "sfdem",
    "description": "Digital elevation model for Spearfish.",
    "type": "GeoTIFF",
    "enabled": True,
    "workspace": {"name": "sf"},
    "url": "file:data/sf/sfdem.tif",
}

SFDEM_COVERAGE = {
    "name": "sfdem",
    "nativeName": "sfdem",
    "title": "Spearfish elevation",
    "description": "Elevation in metres.",
    "keywords": {"string": ["WCS", "sfdem"]},
    "srs": "EPSG:26713",
    "nativeFormat": "GeoTIFF",
    "enabled": True,
    "nativeBoundingBox": {
        "minx": 589980,
        "maxx": 609000,
        "miny": 4913700,
        "maxy": 4928010,
        "crs": {"@class": "projected", "$": "EPSG:26713"},
    },
    "grid": {"@dimension": 2, "range": {"low": "0 0", "high": "634 477"}},
    "dimensions": {
        "coverageDimension": {"name": "GRAY_INDEX", "range": {"min": -100, "max": 2000}}
    },
}


# ############################################################################
# ########## Fakes ###############
# ################################


class FakeGS:
    """Two workspaces: sf has one GeoTIFF store, nurc an unpublished mosaic."""

    def __init__(self, broken_workspace=None, exists=False):
        self.broken_workspace = broken_workspace
        self.exists = exists
        self.calls = []
        outer = self

        class Response:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200
                self.text = str(payload)

            def json(self):
                return self._payload

        class Client:
            def get(inner, path, **kwargs):
                outer.calls.append(("GET", path, kwargs))
                return Response(outer.payload_for(path, kwargs.get("params") or {}))

        class Endpoints:
            base_url = "/rest"

            def coveragestores(inner, workspace_name):
                return f"/rest/workspaces/{workspace_name}/coveragestores.json"

            def coveragestore(
                inner, workspace_name, name, method=None, store_type=None
            ):
                base = f"/rest/workspaces/{workspace_name}/coveragestores/{name}"
                if method is None and store_type is None:
                    return f"{base}.json"
                return f"{base}/{method}.{store_type}"

            def coverages(inner, workspace_name, store_name):
                return (
                    f"/rest/workspaces/{workspace_name}"
                    f"/coveragestores/{store_name}/coverages.json"
                )

            def coverage(inner, workspace_name, store_name, name):
                return (
                    f"/rest/workspaces/{workspace_name}"
                    f"/coveragestores/{store_name}/coverages/{name}.json"
                )

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

        self.rest_service = Rest()

    # -- payloads -----------------------------------------------------------

    STORES = {"sf": ["sfdem"], "nurc": ["mosaic"], "empty": []}
    PUBLISHED = {"sfdem": ["sfdem"], "mosaic": []}  # the mosaic has none yet

    def payload_for(self, path, params):
        if path.endswith("/coveragestores.json"):
            workspace_name = path.split("/workspaces/")[1].split("/")[0]
            if workspace_name == self.broken_workspace:
                raise RuntimeError("HTTP 500: boom")
            names = self.STORES.get(workspace_name, [])
            if not names:
                return {"coverageStores": ""}  # how GeoServer spells "none"
            return {"coverageStores": {"coverageStore": [{"name": n} for n in names]}}
        if path.endswith("/coverages.json"):
            store_name = path.split("/coveragestores/")[1].split("/")[0]
            names = (
                self.PUBLISHED[store_name]
                if params.get("list") == "configured"
                else ["mosaic"]
            )
            if not names:
                return {"coverages": ""}
            return {"coverages": {"coverage": [{"name": n} for n in names]}}
        if "/coverages/" in path:
            return {"coverage": SFDEM_COVERAGE}
        if "/coveragestores/" in path:
            name = path.rsplit("/", 1)[1].removesuffix(".json")
            store = dict(SFDEM_STORE, name=name)
            if name == "mosaic":
                store.update(type="ImageMosaic", workspace={"name": "nurc"})
            return {"coverageStore": store}
        raise AssertionError(f"unexpected GET {path}")

    # -- library calls ------------------------------------------------------

    def get_workspaces(self):
        return ([{"name": "sf"}, {"name": "nurc"}, {"name": "empty"}], 200)

    def get_coverage_store(self, workspace_name, name):
        self.calls.append(("get_coverage_store", workspace_name, name))
        return ({"name": name}, 200 if self.exists else 404)

    def get_coverages(self, workspace_name, store_name):
        # The library answers list=all: everything the store can expose.
        return ([{"name": "mosaic"}, {"name": "extra"}], 200)

    def create_coverage_store(
        self, workspace_name, name, url, type=None, metadata=None
    ):
        self.calls.append(
            ("create_coverage_store", workspace_name, name, url, type, metadata)
        )
        return ("", 201)

    def create_imagemosaic_store_from_directory(self, workspace_name, name, directory):
        self.calls.append(("from_directory", workspace_name, name, directory))
        return (name, 201)

    def create_imagemosaic_store_from_properties_zip(self, workspace_name, name, blob):
        self.calls.append(("from_zip", workspace_name, name, blob))
        return ("", 201)

    def create_coverage(
        self, workspace_name, store_name, name, title=None, native_name=None
    ):
        self.calls.append(
            ("create_coverage", workspace_name, store_name, name, title, native_name)
        )
        return ("", 201)

    def delete_coverage_store(self, workspace_name, name):
        self.calls.append(("delete_coverage_store", workspace_name, name))
        return ("", 200)


class Recording(ResourceFormDialog):
    opened = []

    def exec(self):
        Recording.opened.append(self)
        return QDialog.DialogCode.Rejected


# ############################################################################
# ########## Tests ###############
# ################################


class TestCoverageStoresTab(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.warnings = []
        self.dlg.show_warning_message = self.warnings.append
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        self.dlg.show_success_message = lambda text: None
        Recording.opened.clear()

    def test_registered_as_a_tab(self):
        loaders = {label: loader for label, _icon, loader in self.dlg.TABS}
        self.assertEqual(loaders["Coverage Stores"], "_load_coverage_stores")
        self.assertTrue(hasattr(self.dlg, "_load_coverage_stores"))

    def test_lists_stores_with_their_type_and_published_count(self):
        rows, failures = self.dlg._fetch_coverage_store_rows()
        self.assertEqual(
            rows,
            [  # workspace order, as get_workspaces gives them
                ["sfdem", "sf", "GeoTIFF", "1"],
                ["mosaic", "nurc", "ImageMosaic", "0"],  # created, nothing published
            ],
        )
        self.assertEqual(failures, [])

    def test_a_workspace_without_stores_is_not_a_failure(self):
        # GeoServer answers {"coverageStores": ""} — not a list, not an error.
        self.assertEqual(self.dlg._coverage_store_names("empty"), [])

    def test_one_unreadable_workspace_keeps_the_rest(self):
        self.dlg.gs = FakeGS(broken_workspace="nurc")
        self.dlg._load_coverage_stores()
        self.assertEqual([row[0] for row in self.dlg._all_rows], ["sfdem"])
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("nurc", self.warnings[0])

    def test_published_and_available_are_asked_for_separately(self):
        self.dlg._published_coverage_names("sf", "sfdem")
        _verb, path, kwargs = self.dlg.gs.calls[-1]
        # The library hardcodes list=all, which would count unpublished ones too
        self.assertEqual(kwargs["params"], {"list": "configured"})
        self.assertIn("/coveragestores/sfdem/coverages.json", path)

    def test_publish_candidates_are_the_unpublished_ones(self):
        # get_coverages (list=all) answers mosaic + extra; mosaic is published
        self.dlg.gs.PUBLISHED = {"mosaic": ["mosaic"]}
        self.assertEqual(self.dlg._publishable_coverages("nurc", "mosaic"), ["extra"])


class TestStoreAndCoverageDetail(unittest.TestCase):
    """The detail views read what GeoServer stores, not what the models keep."""

    def setUp(self):
        Recording.opened.clear()  # class-level: order must not matter

    def test_store_prefill_keeps_the_description(self):
        values = CoverageStoreTabMixin._coverage_store_form_values(
            SFDEM_STORE, ["sfdem"]
        )
        # CoverageStore.from_get_response_payload() drops "description": this
        # would be empty if the detail came from the library's model.
        self.assertEqual(
            values["description"], "Digital elevation model for Spearfish."
        )
        self.assertEqual(values["type"], "GeoTIFF")
        self.assertEqual(values["workspace"], "sf")
        self.assertEqual(values["url"], "file:data/sf/sfdem.tif")
        self.assertEqual(values["coverages"], "sfdem")

    def test_store_without_published_coverages_says_so(self):
        values = CoverageStoreTabMixin._coverage_store_form_values(SFDEM_STORE, [])
        self.assertEqual(values["coverages"], "—")

    def test_coverage_prefill_keeps_the_bbox_keywords_and_bands(self):
        values = CoverageStoreTabMixin._coverage_form_values(SFDEM_COVERAGE)
        # Coverage.asdict() drops all three of these.
        self.assertIn("589980, 4913700 → 609000, 4928010", values["bounds"])
        self.assertIn("EPSG:26713", values["bounds"])  # crs arrives as {"$": …}
        self.assertEqual(values["keywords"], "WCS, sfdem")
        self.assertEqual(values["bands"], "GRAY_INDEX  (-100 … 2000)")
        # GeoServer's grid "high" is the exclusive bound: this file is 634 x 477
        # (checked with gdalinfo on the demo data's sfdem.tif)
        self.assertEqual(values["size"], "634 × 477")
        self.assertEqual(values["title"], "Spearfish elevation")
        self.assertEqual(values["srs"], "EPSG:26713")

    def test_a_coverage_without_grid_or_bands_still_renders(self):
        values = CoverageStoreTabMixin._coverage_form_values({"name": "bare"})
        self.assertEqual(values["size"], "")
        self.assertEqual(values["bounds"], "")
        self.assertEqual(values["bands"], "—")

    def test_the_store_dialog_is_read_only(self):
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        with patch.object(tab_coveragestores, "ResourceFormDialog", Recording):
            dlg._show_coverage_store_info(["sfdem", "sf"])
        form = Recording.opened[-1]
        self.assertFalse(form.get_widget("url").isEnabled())
        self.assertTrue(form.get_widget("description").isReadOnly())

    def test_the_coverage_viewer_fills_itself_from_the_picked_coverage(self):
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        dlg.show_warning_message = lambda text: None
        with patch.object(tab_coveragestores, "ResourceFormDialog", Recording):
            dlg._show_coverages(["sfdem", "sf"])
        form = Recording.opened[-1]
        self.assertEqual(form.get_widget("coverage").currentText(), "sfdem")
        self.assertEqual(form.get_widget("srs").text(), "EPSG:26713")
        self.assertIn("609000", form.get_widget("bounds").text())
        self.assertIn("GRAY_INDEX", form.get_widget("bands").toPlainText())

    def test_a_store_with_nothing_published_says_so_instead_of_an_empty_dialog(self):
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        warnings = []
        dlg.show_warning_message = warnings.append
        with patch.object(tab_coveragestores, "ResourceFormDialog", Recording):
            dlg._show_coverages(["mosaic", "nurc"])
        self.assertEqual(Recording.opened, [])
        self.assertIn("no published coverage", warnings[0])


class TestCreateCoverageStore(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()

    def test_geotiff_goes_through_the_library_with_no_cog_metadata(self):
        self.dlg._create_coverage_store_from_values(
            {
                "name": "dem",
                "workspace": "sf",
                "type": GEOTIFF,
                "url": "file:data/sf/sfdem.tif",
            }
        )
        self.assertEqual(
            self.dlg.gs.calls[-1],
            (
                "create_coverage_store",
                "sf",
                "dem",
                "file:data/sf/sfdem.tif",
                "GeoTIFF",
                None,
            ),
        )

    def test_cog_is_a_geotiff_store_plus_the_cog_settings(self):
        self.dlg._create_coverage_store_from_values(
            {
                "name": "cog",
                "workspace": "sf",
                "type": COG,
                "url": "https://example.org/dem.tif",
            }
        )
        _call, _ws, _name, url, store_type, metadata = self.dlg.gs.calls[-1]
        self.assertEqual((url, store_type), ("https://example.org/dem.tif", "GeoTIFF"))
        self.assertEqual(metadata, {"cogSettings": {"rangeReaderSettings": "HTTP"}})

    def test_a_mosaic_directory_uses_the_directory_call(self):
        self.dlg._create_coverage_store_from_values(
            {
                "name": "mos",
                "workspace": "nurc",
                "type": MOSAIC_DIRECTORY,
                "directory": "/opt/geoserver_data/coverages/mos",
            }
        )
        self.assertEqual(
            self.dlg.gs.calls[-1],
            ("from_directory", "nurc", "mos", "/opt/geoserver_data/coverages/mos"),
        )

    def test_a_properties_zip_is_read_and_uploaded(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as handle:
            handle.write(b"PK\x03\x04 pretend")
            path = handle.name
        self.dlg._create_coverage_store_from_values(
            {"name": "mos", "workspace": "nurc", "type": MOSAIC_ZIP, "zip": path}
        )
        self.assertEqual(
            self.dlg.gs.calls[-1], ("from_zip", "nurc", "mos", b"PK\x03\x04 pretend")
        )

    def test_a_server_that_drops_the_cog_settings_is_reported(self):
        """GeoServer silently ignores store metadata it does not understand."""
        warnings = []
        self.dlg.show_warning_message = warnings.append
        self.dlg.show_success_message = lambda text: None

        class Accepting(ResourceFormDialog):
            def exec(inner):
                inner.get_widget("name").setText("cog")
                inner.get_widget("type").setCurrentText(COG)
                inner.get_widget("url").setText("https://example.org/dem.tif")
                return QDialog.DialogCode.Accepted

        self.dlg._load_coverage_stores = lambda: None
        with patch.object(tab_coveragestores, "ResourceFormDialog", Accepting):
            self.dlg._add_coverage_store()  # the fake store has no metadata
        self.assertEqual(len(warnings), 1)
        self.assertIn("COG extension", warnings[0])

    def test_a_server_that_keeps_them_says_nothing(self):
        kept = FakeGS()
        original = kept.payload_for

        def with_metadata(path, params):
            payload = original(path, params)
            if "coverageStore" in payload:
                payload["coverageStore"]["metadata"] = {
                    "entry": {"@key": "CogSettings.Key"}
                }
            return payload

        kept.payload_for = with_metadata
        self.dlg.gs = kept
        warnings = []
        self.dlg.show_warning_message = warnings.append
        self.dlg._warn_if_cog_settings_dropped(
            {"type": COG, "name": "cog", "workspace": "sf"}
        )
        self.assertEqual(warnings, [])

    def test_the_zip_help_warns_that_a_granule_is_required(self):
        """GeoServer's upload validator refuses a properties-only archive."""
        field = [
            f for f in self.dlg._coverage_store_fields(["sf"]) if f["key"] == "zip"
        ][0]
        self.assertIn("at least one granule", field["help"])

    def test_an_existing_name_is_refused_before_anything_is_sent(self):
        self.dlg.gs = FakeGS(exists=True)
        with self.assertRaises(ValueError):
            self.dlg._create_coverage_store_from_values(
                {"name": "sfdem", "workspace": "sf", "type": GEOTIFF, "url": "file:x"}
            )
        self.assertFalse(
            [call for call in self.dlg.gs.calls if call[0].startswith("create")]
        )

    def test_the_type_combo_shows_only_that_type_s_source_field(self):
        dlg = ResourceFormDialog(
            title="t", fields=self.dlg._coverage_store_fields(["sf", "nurc"])
        )
        dlg.get_widget("type").currentTextChanged.connect(
            lambda store_type: self.dlg._on_store_type_changed(dlg, store_type)
        )
        self.dlg._on_store_type_changed(dlg, GEOTIFF)
        self.assertNotIn("url", dlg._hidden_keys)
        self.assertIn("directory", dlg._hidden_keys)
        self.assertIn("zip", dlg._hidden_keys)

        dlg.get_widget("type").setCurrentText(MOSAIC_ZIP)
        self.assertIn("url", dlg._hidden_keys)
        self.assertIn("directory", dlg._hidden_keys)
        self.assertNotIn("zip", dlg._hidden_keys)


class TestPublishAndDelete(unittest.TestCase):
    def setUp(self):
        Recording.opened.clear()  # class-level: order must not matter
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.dlg._confirm_delete = lambda kind, labels, cascade="": True
        self.dlg._load_coverage_stores = lambda: None
        self.dlg.show_success_message = lambda text: None
        self.dlg.show_warning_message = lambda text: None
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")

    def test_publishing_sends_the_native_name_and_the_chosen_layer_name(self):
        class Accepting(ResourceFormDialog):
            def exec(inner):
                inner.get_widget("name").setText("mosaic_layer")
                return QDialog.DialogCode.Accepted

        with patch.object(tab_coveragestores, "ResourceFormDialog", Accepting):
            self.dlg._publish_coverage(["mosaic", "nurc"])
        self.assertEqual(
            self.dlg.gs.calls[-1],
            ("create_coverage", "nurc", "mosaic", "mosaic_layer", None, "mosaic"),
        )

    def test_an_empty_layer_name_reuses_the_coverage_name(self):
        class Accepting(ResourceFormDialog):
            def exec(inner):
                return QDialog.DialogCode.Accepted

        with patch.object(tab_coveragestores, "ResourceFormDialog", Accepting):
            self.dlg._publish_coverage(["mosaic", "nurc"])
        self.assertEqual(
            self.dlg.gs.calls[-1],
            ("create_coverage", "nurc", "mosaic", "mosaic", None, "mosaic"),
        )

    def test_nothing_left_to_publish_is_a_banner_not_a_dialog(self):
        self.dlg.gs.PUBLISHED = {"mosaic": ["mosaic", "extra"]}
        warnings = []
        self.dlg.show_warning_message = warnings.append
        with patch.object(tab_coveragestores, "ResourceFormDialog", Recording):
            self.dlg._publish_coverage(["mosaic", "nurc"])
        self.assertEqual(Recording.opened, [])
        self.assertIn("already published", warnings[0])

    def test_delete_goes_through_the_library_for_every_selected_store(self):
        self.dlg._delete_selected_coverage_stores(
            [["sfdem", "sf", "GeoTIFF", "1"], ["mosaic", "nurc", "ImageMosaic", "0"]]
        )
        self.assertEqual(
            [call for call in self.dlg.gs.calls if call[0] == "delete_coverage_store"],
            [
                ("delete_coverage_store", "sf", "sfdem"),
                ("delete_coverage_store", "nurc", "mosaic"),
            ],
        )

    def test_the_delete_confirmation_names_the_cascade(self):
        seen = {}

        def confirm(kind, labels, cascade=""):
            seen.update(kind=kind, cascade=cascade)
            return False

        self.dlg._confirm_delete = confirm
        self.dlg._delete_selected_coverage_stores([["sfdem", "sf", "GeoTIFF", "1"]])
        self.assertEqual(seen["kind"], "coverage store")
        self.assertIn("layers published from them", seen["cascade"])


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
