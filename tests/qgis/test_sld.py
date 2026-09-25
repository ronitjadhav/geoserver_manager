#! python3  # noqa E265

"""
The QGIS half of the SLD helpers: exporting a layer's symbology, loading one
back, and listing what a project can style.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_sld
"""

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsGeometry,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)
from qgis.testing import start_app, unittest

from geoserver_manager.toolbelt.sld import (
    apply_sld_to_layer,
    layer_to_sld,
    sld_version,
    styleable_project_layers,
)

start_app()


def point_layer(name, colour="#3388ff"):
    """A two-feature point layer with a single-symbol renderer."""
    layer = QgsVectorLayer("Point?crs=EPSG:4326&field=kind:string", name, "memory")
    provider = layer.dataProvider()
    for kind, x, y in (("city", 1, 1), ("village", 2, 2)):
        feature = QgsFeature(layer.fields())
        feature.setAttributes([kind])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        provider.addFeature(feature)
    layer.updateExtents()
    layer.setRenderer(
        QgsSingleSymbolRenderer(
            QgsMarkerSymbol.createSimple({"color": colour, "size": "3"})
        )
    )
    return layer


class TestLayerToSld(unittest.TestCase):
    def test_a_qgis_export_is_sld_1_1(self):
        """The fact the upload's content type hangs on."""
        sld = layer_to_sld(point_layer("towns"))
        self.assertEqual(sld_version(sld), "1.1.0")
        self.assertIn("StyledLayerDescriptor", sld)

    def test_the_symbology_is_actually_in_there(self):
        layer = point_layer("towns", colour="#ff0000")
        sld = layer_to_sld(layer)
        self.assertIn("ff0000", sld.lower())

    def test_categories_survive_the_export(self):
        layer = point_layer("towns")
        layer.setRenderer(
            QgsCategorizedSymbolRenderer(
                "kind",
                [
                    QgsRendererCategory(
                        "city",
                        QgsMarkerSymbol.createSimple({"color": "red"}),
                        "City",
                    ),
                    QgsRendererCategory(
                        "village",
                        QgsMarkerSymbol.createSimple({"color": "blue"}),
                        "Village",
                    ),
                ],
            )
        )
        sld = layer_to_sld(layer)
        self.assertIn("City", sld)
        self.assertIn("Village", sld)
        self.assertIn("kind", sld)  # the filter references the attribute

    def test_no_temporary_file_is_left_behind(self):
        import glob
        import tempfile

        layer_to_sld(point_layer("towns"))
        leftovers = glob.glob(f"{tempfile.gettempdir()}/gsm_sld_*")
        self.assertEqual(leftovers, [])


class TestApplySldToLayer(unittest.TestCase):
    def test_a_style_exported_from_one_layer_lands_on_another(self):
        source = point_layer("source", colour="#ff0000")
        target = point_layer("target", colour="#0000ff")
        ok, message = apply_sld_to_layer(target, layer_to_sld(source))
        self.assertTrue(ok, message)
        colour = target.renderer().symbol().color().name()
        self.assertEqual(colour, "#ff0000")

    def test_nonsense_is_reported_not_raised(self):
        layer = point_layer("towns")
        ok, message = apply_sld_to_layer(layer, "<not-a-style/>")
        self.assertFalse(ok)
        self.assertTrue(message)  # QGIS explains itself

    def test_no_temporary_file_is_left_behind(self):
        import glob
        import tempfile

        apply_sld_to_layer(point_layer("towns"), layer_to_sld(point_layer("other")))
        self.assertEqual(glob.glob(f"{tempfile.gettempdir()}/gsm_sld_*"), [])


class TestStyleableProjectLayers(unittest.TestCase):
    def setUp(self):
        QgsProject.instance().removeAllMapLayers()

    def tearDown(self):
        QgsProject.instance().removeAllMapLayers()

    def test_lists_the_vector_and_raster_layers(self):
        layer = point_layer("towns")
        QgsProject.instance().addMapLayer(layer)
        self.assertEqual(styleable_project_layers(), [layer])

    def test_an_empty_project_is_an_empty_list(self):
        self.assertEqual(styleable_project_layers(), [])


# ############################################################################
# ##### GeoPackage export ########
# ################################


class TestExportToGeopackage(unittest.TestCase):
    """The upload's payload: one table, named as the layer will be."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        self.folder = Path(tempfile.mkdtemp(prefix="gsm_test_"))

    def tearDown(self):
        import shutil

        shutil.rmtree(self.folder, ignore_errors=True)

    def test_the_table_is_named_as_asked_and_holds_the_features(self):
        from qgis.core import QgsVectorLayer

        from geoserver_manager.toolbelt.qgis_export import export_to_geopackage

        package = self.folder / "towns.gpkg"
        export_to_geopackage(point_layer("towns  weird name"), package, "towns")

        self.assertTrue(package.exists())
        written = QgsVectorLayer(f"{package}|layername=towns", "check", "ogr")
        self.assertTrue(written.isValid(), "the asked-for table name is not there")
        self.assertEqual(written.featureCount(), 2)
        self.assertEqual(written.crs().authid(), "EPSG:4326")
        self.assertIn("kind", written.fields().names())

    def test_an_unwritable_path_is_a_runtime_error_with_qgis_words(self):
        from geoserver_manager.toolbelt.qgis_export import export_to_geopackage

        with self.assertRaises(RuntimeError) as caught:
            export_to_geopackage(
                point_layer("towns"), self.folder / "no" / "such" / "dir.gpkg", "towns"
            )
        self.assertIn("towns", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
