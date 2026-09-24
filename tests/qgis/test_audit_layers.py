#! python3  # noqa E265

"""
Audit follow-ups on the Layers and Coverage Stores tabs: names that would
change a URL's meaning are refused, path segments are quoted, and two project
layers named alike are two entries in the layer picker.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_audit_layers
"""

from qgis.core import QgsProject, QgsVectorLayer
from qgis.testing import start_app, unittest

from geoserver_manager.gui.dlg_main import GeoServerMainDialog
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from tests.qgis.sync_dialog import SyncDialog

start_app()


class RecordingGS:
    def __init__(self):
        self.created = []

    def get_coverage_store(self, workspace_name, name):
        return ("not found", 404)

    def create_coverage_store(self, *args, **kwargs):
        self.created.append(("store", args, kwargs))
        return ("", 201)

    def create_coverage(self, *args, **kwargs):
        self.created.append(("coverage", args, kwargs))
        return ("", 201)


class TestUnsafeNamesAreRefused(unittest.TestCase):
    """requests sends coveragestores/a#b.json as coveragestores/a, a different store."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = RecordingGS()

    def test_a_coverage_store_name_with_a_hash_never_reaches_the_server(self):
        with self.assertRaises(ValueError):
            self.dlg._create_coverage_store_from_values(
                {
                    "name": "dem#2",
                    "workspace": "sf",
                    "type": "GeoTIFF",
                    "url": "file:x.tif",
                }
            )
        self.assertEqual(self.dlg.gs.created, [])

    def test_a_safe_name_goes_through(self):
        self.dlg._create_coverage_store_from_values(
            {"name": "dem 2", "workspace": "sf", "type": "GeoTIFF", "url": "file:x.tif"}
        )
        self.assertEqual(self.dlg.gs.created[0][0], "store")


class TestQuotedPathSegments(unittest.TestCase):
    def test_the_browser_preview_quotes_the_workspace_segment(self):
        url = GeoServerMainDialog._preview_url(
            "http://gs/geoserver", "my ws:roads", (0, 0, 1, 1), "EPSG:4326", "my ws"
        )
        self.assertTrue(url.startswith("http://gs/geoserver/my%20ws/wms?"), url)


class TestLayersNamedAlike(unittest.TestCase):
    def setUp(self):
        self.project = QgsProject.instance()
        self.project.removeAllMapLayers()

    def tearDown(self):
        self.project.removeAllMapLayers()

    def test_two_layers_named_alike_are_two_entries_that_both_resolve(self):
        # A picker of labels handed the first layer to whoever picked the
        # second; QGIS's layer combo holds the layers themselves.
        first = QgsVectorLayer("Point?crs=EPSG:4326", "roads", "memory")
        second = QgsVectorLayer("Point?crs=EPSG:4326", "roads", "memory")
        self.project.addMapLayers([first, second])
        form = ResourceFormDialog(
            title="t", fields=[{"key": "layer", "label": "L", "type": "layer"}]
        )
        combo = form.get_widget("layer")
        self.assertEqual(combo.count(), 2)
        picked = set()
        for index in range(2):
            combo.setCurrentIndex(index)
            picked.add(form.get_values()["layer"].id())
        self.assertEqual(picked, {first.id(), second.id()})


if __name__ == "__main__":
    unittest.main()
