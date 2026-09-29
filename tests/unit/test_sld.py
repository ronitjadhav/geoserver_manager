#! python3  # noqa E265

"""
The SLD rules that do not need QGIS, so they are checked by the CI job that has
no QGIS at all.

Usage from the repo root folder:

.. code-block:: bash

    python -m unittest tests.unit.test_sld
"""

import unittest

from geoserver_manager.toolbelt.sld import (
    SLD_1_0,
    SLD_1_1,
    has_raster_symbolizer,
    relative_hrefs,
    sld_content_type,
    sld_version,
    style_text,
    utf8_sld,
)

# What QgsMapLayer.saveSldStyle() writes on QGIS 3.40: version 1.1.0, with
# Symbology Encoding elements.
QGIS_SLD = """<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor xmlns="http://www.opengis.net/sld"
 xmlns:se="http://www.opengis.net/se" version="1.1.0">
 <NamedLayer><se:Name>towns</se:Name></NamedLayer>
</StyledLayerDescriptor>"""

# What GeoServer's own demo styles look like.
GEOSERVER_SLD = """<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" version="1.0.0">
 <NamedLayer><Name>roads</Name></NamedLayer>
</StyledLayerDescriptor>"""


class TestSldVersion(unittest.TestCase):
    def test_reads_the_version_attribute(self):
        self.assertEqual(sld_version(QGIS_SLD), "1.1.0")
        self.assertEqual(sld_version(GEOSERVER_SLD), "1.0.0")

    def test_a_document_without_a_version_is_judged_by_its_namespace(self):
        se_only = '<StyledLayerDescriptor xmlns:se="http://www.opengis.net/se"/>'
        self.assertEqual(sld_version(se_only), "1.1.0")
        self.assertEqual(sld_version("<StyledLayerDescriptor/>"), "1.0.0")

    def test_symbology_encoding_elements_count_even_without_the_namespace(self):
        self.assertEqual(sld_version("<sld><se:Rule/></sld>"), "1.1.0")

    def test_a_1_1_1_style_document_is_still_1_1(self):
        self.assertEqual(
            sld_version('<StyledLayerDescriptor version="1.1.1"/>'), "1.1.0"
        )

    def test_nothing_at_all_is_not_a_crash(self):
        self.assertEqual(sld_version(""), "1.0.0")
        self.assertEqual(sld_version(None), "1.0.0")


class TestSldContentType(unittest.TestCase):
    """GeoServer picks its parser from the content type, not from the document."""

    def test_a_qgis_export_needs_the_symbology_encoding_content_type(self):
        self.assertEqual(sld_content_type(QGIS_SLD), SLD_1_1)
        self.assertEqual(SLD_1_1, "application/vnd.ogc.se+xml")

    def test_a_1_0_document_keeps_the_classic_content_type(self):
        self.assertEqual(sld_content_type(GEOSERVER_SLD), SLD_1_0)
        self.assertEqual(SLD_1_0, "application/vnd.ogc.sld+xml")


LATIN1 = (
    '<?xml version="1.0" encoding="ISO-8859-1"?>'
    '<StyledLayerDescriptor version="1.0.0"><Title>Caf\xe9</Title>'
    "</StyledLayerDescriptor>"
)
AS_UTF8 = LATIN1.replace("ISO-8859-1", "UTF-8").encode("utf-8")


class TestEncoding(unittest.TestCase):
    """GeoServer reads an SLD as UTF-8 whatever its declaration names
    (measured on 2.28.5), so every SLD goes as UTF-8, declared as such."""

    def test_a_latin1_body_reads_as_it_declares(self):
        # Decoded as UTF-8 with replacement, "Café" came back "Caf\ufffd".
        self.assertEqual(style_text(LATIN1.encode("latin-1")), LATIN1)

    def test_a_utf8_body_reads_as_utf8_whatever_it_declares(self):
        # GeoServer reads it so: the declaration of such a file is wrong.
        self.assertEqual(style_text(LATIN1.encode("utf-8")), LATIN1)

    def test_an_unknown_encoding_falls_back_to_utf8(self):
        data = b'<?xml version="1.0" encoding="x-nothing"?><a>\xe9</a>'
        self.assertEqual(
            style_text(data), '<?xml version="1.0" encoding="x-nothing"?><a>\ufffd</a>'
        )
        data = b'<?xml version="1.0" encoding="base64"?><a>\xe9</a>'
        self.assertIn("\ufffd", style_text(data))

    def test_latin1_bytes_or_text_go_as_utf8_under_their_declaration_rewritten(self):
        self.assertEqual(utf8_sld(LATIN1.encode("latin-1")), AS_UTF8)
        self.assertEqual(utf8_sld(LATIN1), AS_UTF8)
        self.assertEqual(utf8_sld(LATIN1.encode("utf-8")), AS_UTF8)

    def test_a_utf8_document_is_left_as_it_is(self):
        for document in (GEOSERVER_SLD, "<StyledLayerDescriptor/>"):
            self.assertEqual(
                utf8_sld(document.encode("utf-8")), document.encode("utf-8")
            )
        lower = GEOSERVER_SLD.replace("UTF-8", "utf-8")
        self.assertEqual(utf8_sld(lower), lower.encode("utf-8"))


class TestWhatAnSldHolds(unittest.TestCase):
    def test_a_raster_style_is_told_from_a_vector_one(self):
        # GetLegendGraphic needs a layer of the style's kind.
        self.assertTrue(has_raster_symbolizer("<sld:RasterSymbolizer><ColorMap/>"))
        self.assertTrue(has_raster_symbolizer("<se:RasterSymbolizer>"))
        self.assertFalse(has_raster_symbolizer(GEOSERVER_SLD))
        self.assertFalse(has_raster_symbolizer(None))

    def test_the_files_beside_the_style_are_its_relative_hrefs(self):
        sld = (
            '<OnlineResource xlink:type="simple" xlink:href="icons/pin.png"/>'
            "<se:OnlineResource xlink:href='fill.svg' xlink:type='simple'/>"
            '<OnlineResource xlink:href="icons/pin.png"/>'
            '<OnlineResource xlink:href="file:local.png"/>'
            '<OnlineResource xlink:href="http://example.org/far.png"/>'
            '<OnlineResource xlink:href="file:/data/abs.png"/>'
            '<OnlineResource xlink:href="/data/abs.png"/>'
        )
        self.assertEqual(
            relative_hrefs(sld), ["icons/pin.png", "fill.svg", "file:local.png"]
        )
        self.assertEqual(relative_hrefs(None), [])


if __name__ == "__main__":
    unittest.main()
