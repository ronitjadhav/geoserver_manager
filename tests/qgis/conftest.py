"""pytest bootstrap for the QGIS suite.

Starts the QGIS application once and puts the bundled wheels on sys.path, so
tests may import `geoservercloud` and exercise the library contract the plugin
relies on — without a live server and without the modal error dialog that
`ensure_dependencies()` shows when the import fails.
"""

import sys

from qgis.testing import start_app

from geoserver_manager.toolbelt.dependencies import BUNDLED_WHLS

start_app()
for whl in BUNDLED_WHLS:
    if str(whl) not in sys.path:
        sys.path.insert(0, str(whl))
