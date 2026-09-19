#! python3  # noqa E265

"""
Audit follow-ups on the Layers and Coverage Stores tabs: names that would
change a URL's meaning are refused, path segments are quoted, and two project
layers named alike get distinct picker labels.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_audit_layers
"""

from qgis.core import QgsProject, QgsVectorLayer
from qgis.testing import start_app, unittest

from geoserver_manager.gui.dlg_main import GeoServerMainDialog
from geoserver_manager.toolbelt.qgis_export import unique_labels
from geoserver_manager.toolbelt.sld import (
    project_layer_by_label,
    styleable_project_layers,
)
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
    """requests sends coveragestores/a#b.json as coveragestores/a — a different store."""

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


class TestPickerLabelsAreUnique(unittest.TestCase):
    def setUp(self):
        self.project = QgsProject.instance()
        self.project.removeAllMapLayers()

    def tearDown(self):
        self.project.removeAllMapLayers()

    def test_two_layers_named_alike_get_two_labels_that_both_resolve(self):
        first = QgsVectorLayer("Point?crs=EPSG:4326", "roads", "memory")
        second = QgsVectorLayer("Point?crs=EPSG:4326", "roads", "memory")
        self.project.addMapLayers([first, second])
        labels = [label for label, _layer in styleable_project_layers()]
        self.assertEqual(len(set(labels)), 2, labels)
        self.assertTrue(all(label.startswith("roads  (vector) [") for label in labels))
        resolved = {project_layer_by_label(label).id() for label in labels}
        self.assertEqual(resolved, {first.id(), second.id()})

    def test_a_lone_layer_keeps_its_plain_label(self):
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "roads", "memory")
        self.project.addMapLayer(layer)
        self.assertEqual(
            [label for label, _l in styleable_project_layers()], ["roads  (vector)"]
        )

    def test_unique_labels_is_pure(self):
        class Layer:
            def __init__(self, identifier):
                self.identifier = identifier

            def id(self):
                return self.identifier

        entries = [
            ("b  (vector)", Layer("b_0001")),
            ("a  (vector)", Layer("a_1")),
            ("a  (vector)", Layer("a_2")),
        ]
        labels = [label for label, _layer in unique_labels(entries)]
        self.assertEqual(
            labels, ["a  (vector) [a_1]", "a  (vector) [a_2]", "b  (vector)"]
        )


if __name__ == "__main__":
    unittest.main()
