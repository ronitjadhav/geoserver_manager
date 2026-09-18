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

    def test_lists_project_layers_with_their_kind_sorted(self):
        QgsProject.instance().addMapLayer(point_layer("zebra"))
        QgsProject.instance().addMapLayer(point_layer("Alpha"))
        labels = [label for label, _layer in styleable_project_layers()]
        self.assertEqual(labels, ["Alpha  (vector)", "zebra  (vector)"])

    def test_an_empty_project_is_an_empty_list(self):
        self.assertEqual(styleable_project_layers(), [])

    def test_the_layer_objects_come_back_with_the_labels(self):
        layer = point_layer("towns")
        QgsProject.instance().addMapLayer(layer)
        ((label, found),) = styleable_project_layers()
        self.assertEqual(label, "towns  (vector)")
        self.assertIs(found, layer)


if __name__ == "__main__":
    unittest.main()
