#! python3  # noqa E265

"""
The CRS half of publishing: what is refused, what is reprojected.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_qgis_export
"""

import shutil
import tempfile
from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
)
from qgis.testing import start_app, unittest

from geoserver_manager.toolbelt.qgis_export import (
    export_to_geopackage,
    reprojection_target,
    require_crs,
)

start_app()


def point_layer(crs="EPSG:4326", x=10.0, y=20.0):
    layer = QgsVectorLayer(f"Point?crs={crs}", "spot", "memory")
    feature = QgsFeature()
    feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    layer.dataProvider().addFeatures([feature])
    return layer


CUSTOM = QgsCoordinateReferenceSystem.fromProj(
    "+proj=tmerc +lat_0=0 +lon_0=9 +k=1 +x_0=500000 +y_0=0 +ellps=WGS84 +units=m +no_defs"
)


class TestRequireCrs(unittest.TestCase):
    def test_a_layer_without_a_crs_is_refused_by_name(self):
        layer = QgsVectorLayer("Point", "orphan", "memory")
        layer.setCrs(QgsCoordinateReferenceSystem())  # a memory layer gets a default
        self.assertFalse(layer.crs().isValid())
        with self.assertRaises(ValueError) as caught:
            require_crs(layer)
        self.assertIn("orphan", str(caught.exception))
        self.assertIn("CRS", str(caught.exception))

    def test_a_layer_with_a_crs_passes_silently(self):
        self.assertIsNone(require_crs(point_layer()))


class TestReprojectionTarget(unittest.TestCase):
    def test_an_epsg_crs_needs_nothing(self):
        self.assertIsNone(reprojection_target(point_layer("EPSG:2056")))

    def test_a_crs_without_an_epsg_code_goes_to_4326(self):
        layer = point_layer()
        layer.setCrs(CUSTOM)
        self.assertFalse(layer.crs().authid().startswith("EPSG:"))
        self.assertEqual(reprojection_target(layer).authid(), "EPSG:4326")


class TestExportToGeopackage(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="gsm_test_"))

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def written(self, path, table):
        layer = QgsVectorLayer(f"{path}|layername={table}", table, "ogr")
        self.assertTrue(layer.isValid())
        point = next(layer.getFeatures()).geometry().asPoint()
        return layer.crs().authid(), point

    def test_without_a_target_the_layers_own_crs_is_kept(self):
        path = export_to_geopackage(point_layer(), self.folder / "a.gpkg", "spot")
        authid, point = self.written(path, "spot")
        self.assertEqual(authid, "EPSG:4326")
        self.assertAlmostEqual(point.x(), 10.0, places=6)

    def test_a_target_crs_reprojects_the_geometries_and_the_table(self):
        path = export_to_geopackage(
            point_layer(),
            self.folder / "b.gpkg",
            "spot",
            target_crs=QgsCoordinateReferenceSystem("EPSG:3857"),
        )
        authid, point = self.written(path, "spot")
        self.assertEqual(authid, "EPSG:3857")
        # lon 10, lat 20 in Web Mercator
        self.assertAlmostEqual(point.x(), 1113194.91, places=1)
        self.assertAlmostEqual(point.y(), 2273030.93, places=1)

    def test_the_reprojection_target_of_a_custom_crs_yields_a_publishable_table(self):
        layer = point_layer()
        layer.setCrs(CUSTOM)  # an override: the coordinates are now "in" CUSTOM
        path = export_to_geopackage(
            layer, self.folder / "c.gpkg", "spot", target_crs=reprojection_target(layer)
        )
        authid, _point = self.written(path, "spot")
        self.assertEqual(authid, "EPSG:4326")


if __name__ == "__main__":
    unittest.main()
