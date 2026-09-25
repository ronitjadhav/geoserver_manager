#! python3  # noqa: E265

"""
Plugin settings.
"""

# standard
import json
from dataclasses import asdict, dataclass, fields
from urllib.parse import urlparse

# PyQGIS
from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

# package
import geoserver_manager.toolbelt.log_handler as log_hdlr
from geoserver_manager.__about__ import __title__, __version__
from geoserver_manager.toolbelt.env_var_parser import EnvVarParser

# ############################################################################
# ########## Classes ###############
# ##################################

# Every setting can be overridden by an environment variable of this prefix
# and its upper-cased name: QGIS_GEOSERVER_MANAGER_DEBUG_MODE=true.
PREFIX_ENV_VARIABLE = "QGIS_GEOSERVER_MANAGER_"


@dataclass
class PlgSettingsStructure:
    """Plugin settings structure and defaults values."""

    # global
    debug_mode: bool = False
    version: str = __version__

    # geoserver connection
    geoserver_url: str = ""
    geoserver_auth_cfg_id: str = ""
    # Off only for a private-CA / self-signed server you trust: the usual
    # on-prem case; default on so nothing is silently insecure.
    geoserver_verify_tls: bool = True

    def has_credentials(self) -> bool:
        """Check if GeoServer URL and auth config are set."""
        return bool(self.geoserver_url and self.geoserver_auth_cfg_id)

    def get_credentials(self) -> tuple:
        """Retrieve username and password from QgsAuthManager.

        :return: (username, password) tuple, empty strings if unavailable.
        """
        if not self.geoserver_auth_cfg_id:
            return ("", "")
        auth_mgr = QgsApplication.authManager()
        auth_cfg = QgsAuthMethodConfig()
        if auth_mgr.loadAuthenticationConfig(
            self.geoserver_auth_cfg_id, auth_cfg, True
        ):
            config_map = auth_cfg.configMap()
            return (
                config_map.get("username", ""),
                config_map.get("password", ""),
            )
        return ("", "")

    def save_credentials(self, username: str, password: str) -> str:
        """Store username/password in QgsAuthManager (encrypted).

        Creates a new auth config or updates the existing one.

        :param username: GeoServer username.
        :param password: GeoServer password.
        :return: the auth config ID, or an empty string if the auth database
            refused the write (e.g. the master password was not entered).
        """
        auth_mgr = QgsApplication.authManager()
        auth_cfg = QgsAuthMethodConfig()

        if self.geoserver_auth_cfg_id:
            # Try to load and update existing config
            if auth_mgr.loadAuthenticationConfig(
                self.geoserver_auth_cfg_id, auth_cfg, True
            ):
                auth_cfg.setConfig("username", username)
                auth_cfg.setConfig("password", password)
                if not auth_mgr.updateAuthenticationConfig(auth_cfg):
                    return ""
                return self.geoserver_auth_cfg_id

        # Create a new auth config
        auth_cfg.setName("GeoServer Manager")
        auth_cfg.setMethod("Basic")
        auth_cfg.setConfig("username", username)
        auth_cfg.setConfig("password", password)
        if not auth_mgr.storeAuthenticationConfig(auth_cfg):
            return ""
        return auth_cfg.id()

    def remove_credentials(self) -> None:
        """Remove the auth config from QgsAuthManager."""
        if self.geoserver_auth_cfg_id:
            auth_mgr = QgsApplication.authManager()
            auth_mgr.removeAuthenticationConfig(self.geoserver_auth_cfg_id)
            self.geoserver_auth_cfg_id = ""


class PlgOptionsManager:
    @staticmethod
    def get_plg_settings() -> PlgSettingsStructure:
        """Load and return plugin settings as a dictionary. \
        Useful to get user preferences across plugin logic.

        :return: plugin settings
        :rtype: PlgSettingsStructure
        """
        # retrieve settings from QGIS/Qt
        settings = QgsSettings()
        settings.beginGroup(__title__)

        # map settings values to preferences object, the environment winning
        li_settings_values = [
            EnvVarParser.get_env_var(
                f"{PREFIX_ENV_VARIABLE}{i.name}".upper(),
                settings.value(key=i.name, defaultValue=i.default, type=i.type),
            )
            for i in fields(PlgSettingsStructure)
        ]

        # instanciate new settings object
        options = PlgSettingsStructure(*li_settings_values)

        settings.endGroup()

        return options

    @staticmethod
    def get_value_from_key(key: str, default=None, exp_type=None):
        """Load and return a single plugin QSettings value by key.

        :return: plugin settings value matching key
        """
        settings = QgsSettings()
        settings.beginGroup(__title__)

        try:
            out_value = settings.value(key=key, defaultValue=default, type=exp_type)
        except Exception as err:
            log_hdlr.PlgLogger.log(
                message="Error occurred trying to get settings: {}.Trace: {}".format(
                    key, err
                )
            )
            out_value = None

        settings.endGroup()

        return out_value

    @classmethod
    def set_value_from_key(cls, key: str, value) -> bool:
        """Set plugin QSettings value using the key.

        :param key: QSettings key
        :type key: str
        :param value: value to set
        :type value: depending on the settings
        :return: operation status
        :rtype: bool
        """
        settings = QgsSettings()
        settings.beginGroup(__title__)

        try:
            settings.setValue(key, value)
            out_value = True
        except Exception as err:
            log_hdlr.PlgLogger.log(
                message="Error occurred trying to set settings: {}.Trace: {}".format(
                    key, err
                )
            )
            out_value = False

        settings.endGroup()

        return out_value

    @classmethod
    def save_from_object(cls, plugin_settings_obj: PlgSettingsStructure):
        """Save plugin settings from a dataclass object to QgsSettings.

        :param plugin_settings_obj: settings object to persist.
        """
        for k, v in asdict(plugin_settings_obj).items():
            cls.set_value_from_key(k, v)

    # -- Server profiles (#47) -----------------------------------------------
    # A profile is {"name", "url", "auth_cfg_id", "verify_tls"}, one auth
    # config each in QgsAuthManager. The list is JSON under "profiles". The
    # active one is also copied into geoserver_url / geoserver_auth_cfg_id /
    # geoserver_verify_tls, which is all the rest of the plugin reads, so only
    # the settings page and the dialog's switcher know that profiles exist.

    @classmethod
    def get_profiles(cls) -> list:
        """The saved profiles, in order. A connection saved before profiles
        existed comes back as the first one, named after its host."""
        raw = cls.get_value_from_key("profiles", "", str) or ""
        try:
            profiles = json.loads(raw) if raw else []
        except ValueError:
            profiles = []
        profiles = [
            profile
            for profile in profiles
            if isinstance(profile, dict) and profile.get("name")
        ]
        if not profiles:
            current = cls.get_plg_settings()
            if current.geoserver_url:
                profiles = [
                    {
                        "name": urlparse(current.geoserver_url).netloc
                        or current.geoserver_url,
                        "url": current.geoserver_url,
                        "auth_cfg_id": current.geoserver_auth_cfg_id,
                        "verify_tls": bool(current.geoserver_verify_tls),
                    }
                ]
        return profiles

    @classmethod
    def save_profiles(cls, profiles: list) -> bool:
        """Store the profile list as it is, active one included."""
        return cls.set_value_from_key("profiles", json.dumps(profiles))

    @classmethod
    def active_profile_name(cls) -> str:
        """The name of the profile the dialog connects to, or ""."""
        name = cls.get_value_from_key("active_profile", "", str) or ""
        profiles = cls.get_profiles()
        if not name and profiles:
            # Migrated from a single connection: that one is what is active.
            current = cls.get_plg_settings()
            if profiles[0]["url"] == current.geoserver_url:
                name = profiles[0]["name"]
        return name if any(p["name"] == name for p in profiles) else ""

    @classmethod
    def activate_profile(cls, profile) -> None:
        """Make `profile` the connection everything reads; None clears it,
        which the dialog shows as "Not configured"."""
        settings = cls.get_plg_settings()
        settings.geoserver_url = profile["url"] if profile else ""
        settings.geoserver_auth_cfg_id = profile["auth_cfg_id"] if profile else ""
        settings.geoserver_verify_tls = (
            bool(profile.get("verify_tls", True)) if profile else True
        )
        cls.save_from_object(settings)
        cls.set_value_from_key("active_profile", profile["name"] if profile else "")
