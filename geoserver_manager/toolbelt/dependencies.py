#! python3  # noqa: E265

"""
Dependency management module.
Ensures geoservercloud and its deps are available in the QGIS Python env.

QGIS's Python often does not include system site-packages, so transitive
dependencies like xmltodict may be missing. We bundle all required WHL
files in extras/ and add them to sys.path at plugin startup.
"""

# standard
import importlib
import sys

# PyQGIS
from qgis.core import Qgis
from qgis.PyQt.QtWidgets import QMessageBox

# project
from geoserver_manager.__about__ import DIR_PLUGIN_ROOT
from geoserver_manager.toolbelt.log_handler import PlgLogger

# All bundled WHLs — order matters: deps first, then geoservercloud
EXTRAS_DIR = DIR_PLUGIN_ROOT / "extras"
BUNDLED_WHLS = [
    EXTRAS_DIR / "xmltodict-1.0.4-py3-none-any.whl",
    EXTRAS_DIR / "geoservercloud-0.8.5-py3-none-any.whl",
]


def _add_whls_to_path(logger=None):
    """Add all bundled WHLs to sys.path if not already present."""
    for whl in BUNDLED_WHLS:
        whl_str = str(whl)
        if not whl.exists():
            if logger:
                logger(
                    f"Bundled WHL not found: {whl}",
                    log_level=Qgis.MessageLevel.Warning,
                )
            continue
        if whl_str not in sys.path:
            sys.path.insert(0, whl_str)
            if logger:
                logger(
                    f"Added to sys.path: {whl.name}",
                    log_level=Qgis.MessageLevel.Info,
                )

    # Also register with pkg_resources if available
    try:
        import pkg_resources

        for whl in BUNDLED_WHLS:
            if whl.exists():
                dist = pkg_resources.Distribution.from_location(
                    str(whl), whl.name
                )
                pkg_resources.working_set.add(dist)
    except Exception:
        pass  # non-fatal


def _try_import(logger=None) -> bool:
    """Invalidate import caches and try importing geoservercloud."""
    importlib.invalidate_caches()
    try:
        import geoservercloud  # noqa: F401

        return True
    except Exception as e:
        if logger:
            import traceback

            tb = traceback.format_exc()
            logger(
                f"geoservercloud import error: {e}\n"
                f"Traceback:\n{tb}",
                log_level=Qgis.MessageLevel.Warning,
            )
        return False


def ensure_dependencies() -> bool:
    """Ensure geoservercloud is installed and importable.

    Strategy:
    1. Direct import — already available, done.
    2. Add bundled WHLs (deps + geoservercloud) to sys.path.
    3. Show error dialog and return False.

    :return: True if dependency is available, False otherwise.
    """
    logger = PlgLogger().log

    # 1. Already importable?
    if _try_import():
        logger(
            "'geoservercloud' already available.",
            log_level=Qgis.MessageLevel.Info,
        )
        return True

    logger(
        "'geoservercloud' not found. Loading bundled WHLs...",
        log_level=Qgis.MessageLevel.Warning,
    )

    # 2. Add all bundled WHLs to sys.path
    _add_whls_to_path(logger)

    if _try_import(logger):
        logger(
            "Successfully loaded geoservercloud from bundled WHLs.",
            log_level=Qgis.MessageLevel.Success,
        )
        return True

    # 3. All methods failed
    logger(
        "Could not import geoservercloud even after adding WHLs.",
        log_level=Qgis.MessageLevel.Critical,
    )
    error_msg = (
        "<b>GeoServer Manager Plugin Error</b><br><br>"
        "Failed to load the required 'geoservercloud' library.<br><br>"
        "Please install it manually by running in a terminal:<br>"
        "<code>pip install geoservercloud</code><br><br>"
        "The plugin will not work until this library is available."
    )
    QMessageBox.critical(
        None, "GeoServer Manager - Missing Dependency", error_msg
    )
    return False
