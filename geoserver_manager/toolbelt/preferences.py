#! python3  # noqa: E265

"""
Plugin settings.
"""

# standard
from dataclasses import asdict, dataclass, fields

# PyQGIS
from qgis.core import Qgis, QgsApplication, QgsAuthMethodConfig, QgsSettings

# package
import geoserver_manager.toolbelt.log_handler as log_hdlr
from geoserver_manager.__about__ import __title__, __version__
from geoserver_manager.toolbelt.env_var_parser import EnvVarParser

# ############################################################################
# ########## Classes ###############
# ##################################

PREFIX_ENV_VARIABLE = "QGIS_GEOSERVER_MANAGER_"


@dataclass
class PlgEnvVariableSettings:
    """Plugin settings from environnement variable"""

    def env_variable_used(self, attribute: str, default_from_name: bool = True) -> str:
        """Get environnement variable used for environnement variable settings

        :param attribute: attribute to check
        :type attribute: str
        :param default_from_name: define default environnement value from attribute name PREFIX_ENV_VARIABLE_<upper case attribute>
        :type default_from_name: bool
        :return: environnement variable used
        :rtype: str
        """
        settings_env_variable = asdict(self)
        env_variable = settings_env_variable.get(attribute, "")
        if not env_variable and default_from_name:
            env_variable = f"{PREFIX_ENV_VARIABLE}{attribute}".upper()
        return env_variable


@dataclass
class PlgSettingsStructure:
    """Plugin settings structure and defaults values."""

    # global
    debug_mode: bool = False
    version: str = __version__

    # geoserver connection
    geoserver_url: str = ""
    geoserver_auth_cfg_id: str = ""

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
        :return: the auth config ID.
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
                auth_mgr.updateAuthenticationConfig(auth_cfg)
                return self.geoserver_auth_cfg_id

        # Create a new auth config
        auth_cfg.setName("GeoServer Manager")
        auth_cfg.setMethod("Basic")
        auth_cfg.setConfig("username", username)
        auth_cfg.setConfig("password", password)
        auth_mgr.storeAuthenticationConfig(auth_cfg)
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
        # get dataclass fields definition
        settings_fields = fields(PlgSettingsStructure)
        env_variable_settings = PlgEnvVariableSettings()

        # retrieve settings from QGIS/Qt
        settings = QgsSettings()
        settings.beginGroup(__title__)

        # map settings values to preferences object
        li_settings_values = []
        for i in settings_fields:
            try:
                value = settings.value(key=i.name, defaultValue=i.default, type=i.type)
                # If environnement variable used, get value from environnement variable
                env_variable = env_variable_settings.env_variable_used(i.name)
                if env_variable:
                    value = EnvVarParser.get_env_var(env_variable, value)
                li_settings_values.append(value)
            except TypeError:
                li_settings_values.append(
                    settings.value(key=i.name, defaultValue=i.default)
                )

        # instanciate new settings object
        options = PlgSettingsStructure(*li_settings_values)

        settings.endGroup()

        return options

    @staticmethod
    def get_value_from_key(key: str, default=None, exp_type=None):
        """Load and return plugin settings as a dictionary. \
        Useful to get user preferences across plugin logic.

        :return: plugin settings value matching key
        """
        if not hasattr(PlgSettingsStructure, key):
            log_hdlr.PlgLogger.log(
                message="Bad settings key. Must be one of: {}".format(
                    ",".join(PlgSettingsStructure._fields)
                ),
                log_level=Qgis.MessageLevel.Warning,
            )
            return None

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
        if not hasattr(PlgSettingsStructure, key):
            log_hdlr.PlgLogger.log(
                message="Bad settings key. Must be one of: {}".format(
                    ",".join(PlgSettingsStructure._fields)
                ),
                log_level=Qgis.MessageLevel.Critical,
            )
            return False

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
        """Load and return plugin settings as a dictionary. \
        Useful to get user preferences across plugin logic.

        :return: plugin settings value matching key
        """
        settings = QgsSettings()
        settings.beginGroup(__title__)

        for k, v in asdict(plugin_settings_obj).items():
            cls.set_value_from_key(k, v)

        settings.endGroup()
