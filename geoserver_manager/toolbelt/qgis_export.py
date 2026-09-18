#! python3  # noqa: E265

"""
Turning a QGIS layer into something GeoServer can ingest: a name it can carry
and a GeoPackage it can read.

`geoserver_name` imports nothing from QGIS, so the naming rules — the part that
is easy to get subtly wrong — are tested in an interpreter without QGIS, like
the CI unit job. `export_to_geopackage` reads a live layer and must run on the
GUI thread (invariant 9 in CLAUDE.md).
"""

import re
import unicodedata

# A published layer's name ends up in XML element positions (a WFS type name is
# an XML NCName) and in URLs, so only these characters are safe.
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_RUNS = re.compile(r"_{2,}")


def geoserver_name(text):
    """A GeoServer-safe name derived from `text` — a QGIS layer name, usually.

    Accents are folded ("Rivière" → "Riviere"), anything else outside
    [A-Za-z0-9_.-] becomes an underscore, and runs of underscores collapse.
    Separators at either end go, so "  Roads (2024) " is "Roads_2024" rather
    than "_Roads_2024_" — except a leading underscore the caller actually
    typed, which is kept. A name left starting with a digit gets one
    underscore in front: an NCName may start with an underscore, so the digit
    does not have to be thrown away.
    """
    text = text or ""
    folded = "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    cleaned = _RUNS.sub("_", _UNSAFE.sub("_", folded)).strip("_-.")
    if not cleaned:
        return "layer"
    if text.startswith("_"):
        cleaned = f"_{cleaned}"
    elif cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def export_to_geopackage(layer, path, table_name):
    """Write one QGIS vector layer into a single-table GeoPackage.

    GUI thread only. The table name becomes the published layer's name, because
    GeoServer configures a feature type per table when the file is uploaded.
    Raises RuntimeError with QGIS's own message when the write fails.
    """
    from qgis.core import QgsCoordinateTransformContext, QgsVectorFileWriter

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = table_name
    options.actionOnExistingFile = (
        QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
    )
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, str(path), QgsCoordinateTransformContext(), options
    )
    # (error code, message, …) — the tuple grew across QGIS versions.
    if result[0] != QgsVectorFileWriter.WriterError.NoError:
        detail = next(
            (item for item in result[1:] if isinstance(item, str) and item), ""
        )
        raise RuntimeError(
            f"QGIS could not write '{layer.name()}' as a GeoPackage: "
            f"{detail or result[0]}"
        )
    return path
