#! python3  # noqa E265

"""
The embedded layer preview: a map of one layer, feature info on click.

A file raster stands in for the WMS layer — the canvas, the click-or-pan tool
and the identify path are the same; only the provider differs, and QGIS's
GDAL provider answers `identify` without a server.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_dlg_preview
"""

import struct
import tempfile
from pathlib import Path

from osgeo import gdal, osr
from qgis.core import Qgis, QgsPointXY, QgsRasterLayer, QgsRectangle
from qgis.gui import QgsMapMouseEvent
from qgis.PyQt.QtCore import QEvent, QPoint, Qt
from qgis.testing import start_app, unittest

from geoserver_manager.gui.dlg_preview import LayerPreviewDialog

start_app()


def tiny_raster(path):
    """A 4×4 GeoTIFF over 0..4 / 0..4 (EPSG:4326); pixel value = row * 4 + col."""
    dataset = gdal.GetDriverByName("GTiff").Create(str(path), 4, 4, 1, gdal.GDT_Int16)
    dataset.SetGeoTransform((0, 1, 0, 4, 0, -1))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    dataset.SetProjection(srs.ExportToWkt())
    dataset.GetRasterBand(1).WriteRaster(0, 0, 4, 4, struct.pack("<16h", *range(16)))
    dataset.FlushCache()
    dataset = None
    return path


class TestLayerPreview(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.layer = QgsRasterLayer(
            str(tiny_raster(Path(self.folder.name) / "tiny.tif")), "tiny"
        )
        self.assertTrue(self.layer.isValid())

    def tearDown(self):
        self.folder.cleanup()

    def dialog(self, bbox=(0.0, 0.0, 4.0, 4.0)):
        dlg = LayerPreviewDialog("ws:tiny", self.layer, bbox)
        dlg.show()
        return dlg

    def test_opens_on_the_layers_extent(self):
        dlg = self.dialog()
        self.assertEqual(dlg.canvas.layers(), [self.layer])
        self.assertTrue(dlg.canvas.extent().contains(QgsRectangle(0, 0, 4, 4)))
        self.assertIn("ws:tiny", dlg.windowTitle())
        self.assertTrue(dlg.message.isHidden())
        dlg.close()

    def test_without_an_extent_the_world(self):
        self.assertEqual(
            LayerPreviewDialog.extent_for(None), QgsRectangle(-180, -90, 180, 90)
        )
        self.assertEqual(
            LayerPreviewDialog.extent_for((1.0, 1.0, 1.0, 1.0)),
            QgsRectangle(-180, -90, 180, 90),
        )
        self.assertEqual(
            LayerPreviewDialog.extent_for((0.0, 0.0, 4.0, 2.0)),
            QgsRectangle(0, 0, 4, 2),
        )

    def test_identify_puts_the_value_under_the_point_in_the_panel(self):
        dlg = self.dialog()
        dlg.identify(QgsPointXY(0.5, 3.5))  # top-left pixel
        self.assertIn("Band 1: 0", dlg.info.toPlainText())
        dlg.identify(QgsPointXY(3.5, 0.5))  # bottom-right pixel
        self.assertIn("Band 1: 15", dlg.info.toPlainText())
        self.assertIn("3.500000, 0.500000", dlg.info.toPlainText())
        dlg.close()

    def test_a_click_identifies_and_a_drag_pans(self):
        dlg = self.dialog()
        canvas = dlg.canvas
        tool = canvas.mapTool()
        identified = []
        dlg.identify = identified.append  # the tool calls through the dialog
        tool._on_click = dlg.identify

        def event(kind, x, y):
            return QgsMapMouseEvent(
                canvas,
                kind,
                QPoint(x, y),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

        # press and release in place: a click
        tool.canvasPressEvent(event(QEvent.Type.MouseButtonPress, 100, 100))
        tool.canvasReleaseEvent(event(QEvent.Type.MouseButtonRelease, 101, 100))
        self.assertEqual(len(identified), 1)
        self.assertIsInstance(identified[0], QgsPointXY)

        # press, move far, release: a pan — the map moves, nothing is identified
        before = canvas.extent().center()
        tool.canvasPressEvent(event(QEvent.Type.MouseButtonPress, 100, 100))
        tool.canvasMoveEvent(event(QEvent.Type.MouseMove, 160, 140))
        tool.canvasReleaseEvent(event(QEvent.Type.MouseButtonRelease, 160, 140))
        self.assertEqual(len(identified), 1)
        self.assertNotEqual(canvas.extent().center(), before)
        dlg.close()

    def test_the_format_is_the_richest_the_provider_offers(self):
        # a file raster answers values; GeoServer over WMS answers text
        self.assertEqual(
            LayerPreviewDialog.identify_format(self.layer.dataProvider()),
            Qgis.RasterIdentifyFormat.Value,
        )

        class Mute:
            def capabilities(self):
                return Qgis.RasterInterfaceCapabilities()

        self.assertIsNone(LayerPreviewDialog.identify_format(Mute()))

    def test_a_failed_identify_shows_the_providers_message(self):
        class Error:
            def message(self):
                return "GetFeatureInfo refused"

        class Result:
            def isValid(self):  # noqa: N802
                return False

            def error(self):
                return Error()

        text = LayerPreviewDialog.result_text(QgsPointXY(1, 2), Result())
        self.assertEqual(text, "GetFeatureInfo refused")

    def test_text_answers_are_shown_as_they_are(self):
        class Result:
            def isValid(self):  # noqa: N802
                return True

            def results(self):
                return {0: "Results for FeatureType 'sfdem':\nGRAY_INDEX = 1538.0"}

        text = LayerPreviewDialog.result_text(QgsPointXY(1, 2), Result())
        self.assertIn("GRAY_INDEX = 1538.0", text)
        self.assertNotIn("Band", text)

    def test_an_invalid_layer_is_explained_in_place_of_the_map(self):
        broken = QgsRasterLayer("", "broken", "wms")
        self.assertFalse(broken.isValid())
        dlg = LayerPreviewDialog("ws:broken", broken, None)
        self.assertFalse(dlg.message.isHidden())
        self.assertIn("did not load", dlg.message.text())
        self.assertEqual(dlg.canvas.layers(), [])
        dlg.identify(
            QgsPointXY(0, 0)
        )  # no crash: the provider is asked, answers nothing
        dlg.close()

    def test_closing_while_a_render_is_pending_is_fine(self):
        dlg = self.dialog()
        dlg.canvas.refresh()
        dlg.close()  # WA_DeleteOnClose: the window is gone, nothing to assert on


if __name__ == "__main__":
    unittest.main()
