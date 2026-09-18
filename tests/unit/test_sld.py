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
    sld_content_type,
    sld_version,
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


if __name__ == "__main__":
    unittest.main()
