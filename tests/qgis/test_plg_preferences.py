#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    # for whole tests
    python -m unittest tests.qgis.test_plg_preferences
    # for specific test
    python -m unittest tests.qgis.test_plg_preferences.TestPlgPreferences.test_plg_preferences_structure
"""

# standard library
import os
from unittest.mock import patch

from qgis.testing import unittest

# project
from geoserver_manager.__about__ import __version__
from geoserver_manager.toolbelt.preferences import (
    PREFIX_ENV_VARIABLE,
    PlgOptionsManager,
    PlgSettingsStructure,
)

# ############################################################################
# ########## Classes #############
# ################################


class TestPlgPreferences(unittest.TestCase):
    def test_plg_preferences_structure(self):
        """Test settings types and default values."""
        settings = PlgSettingsStructure()

        # global
        self.assertTrue(hasattr(settings, "debug_mode"))
        self.assertIsInstance(settings.debug_mode, bool)
        self.assertEqual(settings.debug_mode, False)

        self.assertTrue(hasattr(settings, "version"))
        self.assertIsInstance(settings.version, str)
        self.assertEqual(settings.version, __version__)

        # TLS verification defaults to on: nothing is silently insecure
        self.assertIs(settings.geoserver_verify_tls, True)

    def test_bool_env_variable(self):
        """Test settings with environment value."""
        manager = PlgOptionsManager()
        with patch.dict(
            os.environ, {f"{PREFIX_ENV_VARIABLE}DEBUG_MODE": "true"}, clear=True
        ):
            settings = manager.get_plg_settings()
            self.assertEqual(settings.debug_mode, True)

        with patch.dict(
            os.environ, {f"{PREFIX_ENV_VARIABLE}DEBUG_MODE": "false"}, clear=True
        ):
            settings = manager.get_plg_settings()
            self.assertEqual(settings.debug_mode, False)

        with patch.dict(
            os.environ, {f"{PREFIX_ENV_VARIABLE}DEBUG_MODE": "on"}, clear=True
        ):
            settings = manager.get_plg_settings()
            self.assertEqual(settings.debug_mode, True)

        with patch.dict(
            os.environ, {f"{PREFIX_ENV_VARIABLE}DEBUG_MODE": "off"}, clear=True
        ):
            settings = manager.get_plg_settings()
            self.assertEqual(settings.debug_mode, False)

        with patch.dict(
            os.environ, {f"{PREFIX_ENV_VARIABLE}DEBUG_MODE": "1"}, clear=True
        ):
            settings = manager.get_plg_settings()
            self.assertEqual(settings.debug_mode, True)

        with patch.dict(
            os.environ, {f"{PREFIX_ENV_VARIABLE}DEBUG_MODE": "0"}, clear=True
        ):
            settings = manager.get_plg_settings()
            self.assertEqual(settings.debug_mode, False)

        with patch.dict(
            os.environ,
            {f"{PREFIX_ENV_VARIABLE}DEBUG_MODE": "invalid_value"},
            clear=True,
        ):
            settings = manager.get_plg_settings()
            self.assertEqual(settings.debug_mode, False)


class TestServerProfiles(unittest.TestCase):
    """Saved connections (#47), stored in this test profile's QgsSettings."""

    KEYS = (
        "geoserver_url",
        "geoserver_auth_cfg_id",
        "geoserver_verify_tls",
        "profiles",
        "active_profile",
    )

    def setUp(self):
        from qgis.core import QgsSettings

        from geoserver_manager.__about__ import __title__

        self.settings = QgsSettings()
        self.group = __title__
        self.kept = {k: self.settings.value(f"{__title__}/{k}") for k in self.KEYS}
        for key in self.KEYS:
            self.settings.remove(f"{__title__}/{key}")
        self.addCleanup(self.restore)

    def restore(self):
        for key, value in self.kept.items():
            self.settings.remove(f"{self.group}/{key}")
            if value is not None:
                self.settings.setValue(f"{self.group}/{key}", value)

    def test_nothing_saved_means_no_profile(self):
        self.assertEqual(PlgOptionsManager.get_profiles(), [])
        self.assertEqual(PlgOptionsManager.active_profile_name(), "")

    def test_a_connection_saved_before_profiles_becomes_the_first(self):
        old = PlgSettingsStructure(
            geoserver_url="https://gs.example.org/geoserver",
            geoserver_auth_cfg_id="abc1234",
            geoserver_verify_tls=False,
        )
        PlgOptionsManager.save_from_object(old)
        self.assertEqual(
            PlgOptionsManager.get_profiles(),
            [
                {
                    "name": "gs.example.org",
                    "url": "https://gs.example.org/geoserver",
                    "auth_cfg_id": "abc1234",
                    "verify_tls": False,
                }
            ],
        )
        self.assertEqual(PlgOptionsManager.active_profile_name(), "gs.example.org")

    def test_activating_a_profile_is_what_everything_else_reads(self):
        dev = {
            "name": "dev",
            "url": "http://localhost:8080/geoserver",
            "auth_cfg_id": "dev0001",
            "verify_tls": True,
        }
        prod = {
            "name": "prod",
            "url": "https://prod.example.org/geoserver",
            "auth_cfg_id": "prd0001",
            "verify_tls": False,
        }
        PlgOptionsManager.save_profiles([dev, prod])
        PlgOptionsManager.activate_profile(prod)

        current = PlgOptionsManager.get_plg_settings()
        self.assertEqual(current.geoserver_url, prod["url"])
        self.assertEqual(current.geoserver_auth_cfg_id, "prd0001")
        self.assertIs(current.geoserver_verify_tls, False)
        self.assertEqual(PlgOptionsManager.active_profile_name(), "prod")
        self.assertEqual(
            [p["name"] for p in PlgOptionsManager.get_profiles()], ["dev", "prod"]
        )

    def test_no_active_profile_is_not_configured(self):
        PlgOptionsManager.activate_profile(None)
        current = PlgOptionsManager.get_plg_settings()
        self.assertFalse(current.has_credentials())
        self.assertEqual(PlgOptionsManager.active_profile_name(), "")

    def test_a_damaged_list_reads_as_empty_instead_of_raising(self):
        PlgOptionsManager.set_value_from_key("profiles", "[{not json")
        self.assertEqual(PlgOptionsManager.get_profiles(), [])


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
