#! python3  # noqa: E265

"""
SLD helpers shared by the Styles and Layers tabs: what version a document is,
which content type and encoding GeoServer wants for it, and how to move a
style between a QGIS layer and an SLD string.

Nothing here imports `qgis` at module level, so `sld_version` and
`sld_content_type` (the part with the rules worth pinning) are testable in an
interpreter without QGIS, like the CI unit job. The functions that do touch a
QGIS layer import it when called, and must run on the GUI thread: they read and
write live layer objects (see invariant 9 in docs/development/invariants.md).
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
# An XML declaration up to its encoding's name, which a rewrite replaces.
_DECLARATION = re.compile(
    r"^(\ufeff?\s*<\?xml\b[^>]*?\bencoding\s*=\s*[\"'])([\w.:-]+)"
)
_RASTER = re.compile(r"<\s*(?:\w+:)?RasterSymbolizer\b")
_HREF = re.compile(
    r"<\s*(?:\w+:)?OnlineResource\b[^>]*?\b(?:\w+:)?href\s*=\s*[\"']([^\"']+)[\"']"
)
# A path from the root, or a URI of any scheme but "file:" without a slash.
_ABSOLUTE = re.compile(r"^(?:[/\\]|file:/|(?!file:)[A-Za-z][\w+.-]*:)", re.IGNORECASE)


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


def style_text(data):
    """A style body as text: UTF-8, else the encoding its XML declaration names.

    GeoServer reads a style as UTF-8, whatever its declaration says. A file
    put in the data directory by hand is served byte for byte, and a Latin-1
    one is no valid UTF-8: it is decoded as it declares.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    match = _DECLARATION.match(data[:200].decode("latin-1"))
    try:
        return data.decode(match.group(2) if match else "utf-8", errors="replace")
    except LookupError:  # an encoding Python does not know, or not a text one
        return data.decode("utf-8", errors="replace")


def utf8_sld(sld):
    """An SLD, text or bytes, as UTF-8 bytes under a declaration that says so.

    GeoServer reads an SLD body as UTF-8 whatever its declaration names
    (measured on 2.28.5): an ISO-8859-1 SLD 1.0 was stored with replacement
    characters, and an SLD 1.1 one, stored as sent, was read with them.
    """
    text = style_text(sld) if isinstance(sld, bytes) else sld
    match = _DECLARATION.match(text)
    if match and match.group(2).upper() not in ("UTF-8", "UTF8"):
        text = match.group(1) + "UTF-8" + text[match.end() :]
    return text.encode("utf-8")


def has_raster_symbolizer(sld):
    """Whether an SLD draws a raster: GetLegendGraphic then needs a raster layer."""
    return _RASTER.search(sld or "") is not None


def relative_hrefs(sld):
    """The files an SLD points to beside itself, once each, in order.

    GeoServer resolves a relative OnlineResource href (an ExternalGraphic's
    icon, a fill image) against the style's own folder on the server.
    """
    found = [href for href in _HREF.findall(sld or "") if not _ABSOLUTE.match(href)]
    return list(dict.fromkeys(found))


def styleable_project_layers():
    """The project's layers that can carry an SLD: its vector and raster ones.

    QGIS reads and writes SLD for those, and a mesh or point-cloud layer would
    just fail later with a worse message. The forms' layer pickers filter the
    same two kinds.
    """
    from qgis.core import QgsMapLayer, QgsProject

    kinds = (QgsMapLayer.LayerType.VectorLayer, QgsMapLayer.LayerType.RasterLayer)
    return [
        layer
        for layer in QgsProject.instance().mapLayers().values()
        if layer.type() in kinds
    ]


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
        from qgis.PyQt.QtCore import QCoreApplication

        raise RuntimeError(
            QCoreApplication.translate(
                "Sld",
                "QGIS exported no SLD for '{}'. Its symbology may have no SLD "
                "equivalent.",
            ).format(layer.name())
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
        # QGIS reads the file in the encoding its declaration names.
        path.write_bytes(utf8_sld(sld))
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
