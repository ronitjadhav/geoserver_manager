#! python3  # noqa: E265

"""
SLD helpers shared by the Styles and Layers tabs: what version a document is,
which content type GeoServer wants for it, and how to move a style between a
QGIS layer and an SLD string.

Nothing here imports `qgis` at module level, so `sld_version` and
`sld_content_type` (the part with the rules worth pinning) are testable in an
interpreter without QGIS, like the CI unit job. The functions that do touch a
QGIS layer import it when called, and must run on the GUI thread: they read and
write live layer objects (see invariant 9 in AGENTS.md).
"""

import re
import tempfile
from pathlib import Path

# GeoServer chooses its SLD parser from the request's content type, not from the
# document. Send the wrong one and it stores the body under the wrong
# languageVersion: accepted, rendered, and mislabelled.
SLD_1_0 = "application/vnd.ogc.sld+xml"
SLD_1_1 = "application/vnd.ogc.se+xml"

_VERSION = re.compile(
    r"StyledLayerDescriptor[^>]*\bversion\s*=\s*[\"']([\d.]+)[\"']", re.IGNORECASE
)
# QGIS writes Symbology Encoding elements (se:PolygonSymbolizer, …) for SLD 1.1.
_SE_NAMESPACE = re.compile(r"xmlns:se\s*=|<\s*se:", re.IGNORECASE)


def sld_version(sld):
    """The SLD version of a document: "1.1.0" or "1.0.0".

    Reads the version attribute, and falls back to the Symbology Encoding
    namespace for documents that leave it out: an SE document is 1.1 whatever
    the root element says.
    """
    match = _VERSION.search(sld or "")
    if match:
        return "1.1.0" if match.group(1).startswith("1.1") else "1.0.0"
    return "1.1.0" if _SE_NAMESPACE.search(sld or "") else "1.0.0"


def sld_content_type(sld):
    """The content type GeoServer needs in order to parse this document."""
    return SLD_1_1 if sld_version(sld) == "1.1.0" else SLD_1_0


def styleable_project_layers():
    """The project's layers that can carry an SLD, as [(label, layer)].

    Vector and raster layers only: QGIS reads and writes SLD for those, and a
    mesh or point-cloud layer would just fail later with a worse message.
    """
    from qgis.core import QgsMapLayer, QgsProject

    kinds = {
        QgsMapLayer.LayerType.VectorLayer: "vector",
        QgsMapLayer.LayerType.RasterLayer: "raster",
    }
    from geoserver_manager.toolbelt.qgis_export import unique_labels

    layers = []
    for layer in QgsProject.instance().mapLayers().values():
        kind = kinds.get(layer.type())
        if kind:
            layers.append((f"{layer.name()}  ({kind})", layer))
    return unique_labels(layers)


def project_layer_by_label(label):
    """The project layer a `styleable_project_layers` label points at.

    Raises ValueError when it has left the project since the form was filled;
    a dialog can sit open for a long time.
    """
    for candidate, layer in styleable_project_layers():
        if candidate == label:
            return layer
    raise ValueError(f"Layer '{label}' is no longer in the project.")


def layer_to_sld(layer):
    """One QGIS layer's symbology as an SLD string. GUI thread only.

    Raises RuntimeError when QGIS writes nothing, which is what a renderer it
    cannot express in SLD looks like.
    """
    path = Path(tempfile.mkdtemp(prefix="gsm_sld_")) / "style.sld"
    try:
        # saveSldStyle's return value changed shape across QGIS versions
        # ((str, bool) on 3.40), so judge it by the file it wrote instead.
        layer.saveSldStyle(str(path))
        sld = path.read_text(encoding="utf-8") if path.exists() else ""
    finally:
        if path.exists():
            path.unlink()
        path.parent.rmdir()
    if not sld.strip():
        raise RuntimeError(
            f"QGIS exported no SLD for '{layer.name()}'. Its symbology may have "
            "no SLD equivalent."
        )
    return sld


def apply_sld_to_layer(layer, sld):
    """Load an SLD string into a QGIS layer. Returns (ok, message).

    GUI thread only. QGIS's SLD *reader* covers less than its writer, so a
    server style can come back "not applied" or applied in part; the message is
    QGIS's own and worth showing.
    """
    path = Path(tempfile.mkdtemp(prefix="gsm_sld_")) / "style.sld"
    try:
        path.write_text(sld, encoding="utf-8")
        result = layer.loadSldStyle(str(path))
    finally:
        if path.exists():
            path.unlink()
        path.parent.rmdir()

    # loadSldStyle answers (bool, str). Order and arity have moved between
    # QGIS releases, so accept whichever way round it comes.
    ok, message = True, ""
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, bool):
                ok = item
            elif isinstance(item, str):
                message = item
    elif isinstance(result, bool):
        ok = result
    if ok:
        layer.triggerRepaint()
    return ok, message
