#! python3  # noqa: E265

"""
Plugin settings form integrated into QGIS 'Options' menu.
"""

# standard
import platform
from functools import partial
from pathlib import Path
from typing import Callable
from urllib.parse import quote

# PyQGIS
from qgis.core import Qgis, QgsApplication
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QWidget

# project
from geoserver_manager.__about__ import (
    __icon_path__,
    __title__,
    __uri_homepage__,
    __uri_tracker__,
    __version__,
)
from geoserver_manager.toolbelt import PlgLogger, PlgOptionsManager
from geoserver_manager.toolbelt.preferences import PlgSettingsStructure

# ############################################################################
# ########## Classes ###############
# ##################################


class ConfigOptionsPage(QgsOptionsPageWidget):
    """Settings form embedded into QGIS 'options' menu."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.log: Callable = PlgLogger().log
        self.plg_settings = PlgOptionsManager()

        # load UI and set objectName
        uic.loadUi(Path(__file__).parent / f"{Path(__file__).stem}.ui", self)
        self.setObjectName("mOptionsPage{}".format(__title__))
        self.initGui()

    def initGui(self) -> None:  # noqa: N802
        """Set up UI elements."""
        report_context_message: str = quote(
            "> Reported from plugin settings\n\n"
            f"- operating system: {platform.system()} "
            f"{platform.release()}_{platform.version()}\n"
            f"- QGIS: {Qgis.QGIS_VERSION}\n"
            f"- plugin version: {__version__}\n"
        )

        # header
        self.lbl_title.setText(f"{__title__} - Version {__version__}")

        # customization
        self.btn_help.setIcon(QIcon(QgsApplication.iconPath("mActionHelpContents.svg")))
        self.btn_help.pressed.connect(
            partial(QDesktopServices.openUrl, QUrl(__uri_homepage__))
        )

        self.btn_report.setIcon(
            QIcon(QgsApplication.iconPath("console/iconSyntaxErrorConsole.svg"))
        )
        self.btn_report.pressed.connect(
            partial(
                QDesktopServices.openUrl,
                QUrl(
                    f"{__uri_tracker__}new/?"
                    "template=10_bug_report.yml"
                    f"&about-info={report_context_message}"
                ),
            )
        )

        self.btn_reset.setIcon(QIcon(QgsApplication.iconPath("mActionUndo.svg")))
        self.btn_reset.pressed.connect(self.on_reset_settings)

        # load previously saved settings
        self.load_settings()

    def apply(self) -> None:
        """Save settings from UI to QgsSettings + QgsAuthManager."""
        settings: PlgSettingsStructure = self.plg_settings.get_plg_settings()

        # misc
        settings.debug_mode = self.opt_debug.isChecked()
        settings.version = __version__

        # geoserver URL (not sensitive — stored in QgsSettings)
        url = self.txt_gs_url.text().strip()
        if url and not url.startswith(("http://", "https://")):
            self.log(
                message="GeoServer URL must start with http:// or https://",
                log_level=Qgis.MessageLevel.Warning,
                push=True,
            )
            return
        settings.geoserver_url = url

        # credentials (sensitive — stored encrypted in QgsAuthManager)
        username = self.txt_gs_username.text()
        password = self.txt_gs_password.text()
        auth_cfg_id = settings.save_credentials(username, password)
        settings.geoserver_auth_cfg_id = auth_cfg_id

        # dump settings into QgsSettings
        self.plg_settings.save_from_object(settings)

        if __debug__:
            self.log(
                message="DEBUG - Settings successfully saved.",
                log_level=Qgis.MessageLevel.NoLevel,
            )

    def load_settings(self) -> None:
        """Load options from QgsSettings + QgsAuthManager into UI form."""
        settings: PlgSettingsStructure = self.plg_settings.get_plg_settings()

        # global
        self.opt_debug.setChecked(settings.debug_mode)
        self.lbl_version_saved_value.setText(settings.version)

        # geoserver URL
        self.txt_gs_url.setText(settings.geoserver_url)

        # credentials from encrypted store
        username, password = settings.get_credentials()
        self.txt_gs_username.setText(username)
        self.txt_gs_password.setText(password)

    def on_reset_settings(self) -> None:
        """Reset settings to default values."""
        # Remove the auth config if it exists
        current = self.plg_settings.get_plg_settings()
        current.remove_credentials()

        default_settings: PlgSettingsStructure = PlgSettingsStructure()
        self.plg_settings.save_from_object(default_settings)
        self.load_settings()


class PlgOptionsFactory(QgsOptionsWidgetFactory):
    """Factory for options widget."""

    def __init__(self) -> None:
        super().__init__()

    def icon(self) -> QIcon:
        return QIcon(str(__icon_path__))

    def createWidget(self, parent: QWidget) -> ConfigOptionsPage:  # noqa: N802
        return ConfigOptionsPage(parent)

    def title(self) -> str:
        return __title__

    def helpId(self) -> str:  # noqa: N802
        return __uri_homepage__
