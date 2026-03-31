#! python3  # noqa: E265

# ----------------------------------------------------------
# Copyright (C) 2015 Martin Dobias
# ----------------------------------------------------------
# Licensed under the terms of GNU GPL 2
# --------------------------------------------------------------------


def classFactory(iface):
    """Load the plugin class.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    import os
    import sys

    this_dir = os.path.dirname(__file__)

    # Order matters: load transitive deps first, then geoservercloud
    whls = [
        os.path.join(this_dir, "extras", "xmltodict-1.0.4-py3-none-any.whl"),
        os.path.join(this_dir, "extras", "geoservercloud-0.8.5-py3-none-any.whl"),
    ]

    for whl_path in whls:
        if os.path.exists(whl_path) and whl_path not in sys.path:
            sys.path.insert(0, whl_path)

    # Register with pkg_resources if available
    try:
        import geoservercloud  # noqa: F401
    except ImportError:
        try:
            import pkg_resources

            for whl_path in whls:
                if os.path.exists(whl_path):
                    whl_name = os.path.basename(whl_path)
                    dist = pkg_resources.Distribution.from_location(
                        whl_path, whl_name
                    )
                    pkg_resources.working_set.add(dist)
        except Exception:
            pass

    from .plugin_main import GeoServerManagerPlugin

    return GeoServerManagerPlugin(iface)
