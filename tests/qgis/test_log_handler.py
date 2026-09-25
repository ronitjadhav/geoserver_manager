#! python3  # noqa E265

"""
The plugin's logger: what it keeps, and what it reads to decide.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_log_handler
"""

from unittest.mock import patch

from qgis.core import Qgis
from qgis.testing import start_app, unittest

from geoserver_manager.toolbelt import preferences
from geoserver_manager.toolbelt.log_handler import PlgLogger

start_app()


class TestLogGate(unittest.TestCase):
    def test_a_warning_is_kept_without_reading_the_settings(self):
        # Every call read the whole settings block (QgsSettings and the
        # environment) to learn debug_mode, even for a message kept anyway.
        reads = []

        def read_settings():
            reads.append(1)
            return preferences.PlgSettingsStructure()

        with patch.object(
            preferences.PlgOptionsManager, "get_plg_settings", read_settings
        ):
            PlgLogger.log("kept", log_level=Qgis.MessageLevel.Warning)
            PlgLogger.log("kept", log_level=Qgis.MessageLevel.Critical)
            self.assertEqual(reads, [])
            PlgLogger.log(
                "dropped without debug mode", log_level=Qgis.MessageLevel.Info
            )
            self.assertEqual(reads, [1])


if __name__ == "__main__":
    unittest.main()
