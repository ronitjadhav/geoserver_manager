#! python3  # noqa: E265

"""
Plugin settings form integrated into QGIS 'Options' menu.
"""

# standard
import ipaddress
import platform
from functools import partial
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlparse

# PyQGIS
from qgis.core import Qgis, QgsApplication
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QApplication, QWidget

# project
from geoserver_manager.__about__ import (
    __icon_path__,
    __title__,
    __uri_homepage__,
    __uri_tracker__,
    __version__,
)
from geoserver_manager.gui.theme import status_colour
from geoserver_manager.toolbelt.log_handler import PlgLogger
from geoserver_manager.toolbelt.preferences import (
    PlgOptionsManager,
    PlgSettingsStructure,
)
from geoserver_manager.toolbelt.probe import probe

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

        self.btn_test_connection.clicked.connect(self.test_connection)
        # A result describes the fields as they were; editing any of them ends it.
        for field in (self.txt_gs_url, self.txt_gs_username, self.txt_gs_password):
            field.textChanged.connect(self.lbl_test_result.clear)
        self.opt_verify_tls.toggled.connect(self.lbl_test_result.clear)

        # load previously saved settings
        self.load_settings()

    @staticmethod
    def _password_travels_in_clear(url: str, username: str, password: str) -> bool:
        """True when saving these would put a password on the wire unencrypted.

        The plugin authenticates with HTTP Basic, so over `http://` the
        password is readable by anything on the path. Loopback is exempt:
        those requests never leave the machine — and a warning on every local
        sandbox (this repo ships one) is a warning nobody reads.
        """
        if not (username or password):
            return False
        parsed = urlparse((url or "").strip())
        if parsed.scheme != "http":
            return False
        host = (parsed.hostname or "").casefold()
        if host == "localhost" or host.endswith(".localhost"):
            return False
        try:
            return not ipaddress.ip_address(host).is_loopback
        except ValueError:
            # A host name the plugin cannot resolve to a loopback address.
            return True

    def apply(self) -> None:
        """Save settings from UI to QgsSettings + QgsAuthManager."""
        settings: PlgSettingsStructure = self.plg_settings.get_plg_settings()

        # misc
        settings.debug_mode = self.opt_debug.isChecked()
        settings.version = __version__
        settings.geoserver_verify_tls = self.opt_verify_tls.isChecked()

        # geoserver URL (not sensitive — stored in QgsSettings)
        url = self.txt_gs_url.text().strip()
        if url and not url.startswith(("http://", "https://")):
            # apply() cannot stop the options dialog from closing, so keep the
            # previous URL and warn — dropping out here would also discard the
            # credentials the user just typed.
            self.log(
                message=self.tr(
                    "GeoServer URL must start with http:// or https:// — URL not saved."
                ),
                log_level=Qgis.MessageLevel.Warning,
                push=True,
            )
        else:
            settings.geoserver_url = url

        # credentials (sensitive — stored encrypted in QgsAuthManager)
        username = self.txt_gs_username.text()
        password = self.txt_gs_password.text()
        if username or password:
            auth_cfg_id = settings.save_credentials(username, password)
            if auth_cfg_id:
                settings.geoserver_auth_cfg_id = auth_cfg_id
            else:
                # Typically the user dismissed the master password prompt
                self.log(
                    message=self.tr(
                        "Could not store the credentials in the QGIS authentication "
                        "database. Check that the master password is set, then save again."
                    ),
                    log_level=Qgis.MessageLevel.Critical,
                    push=True,
                )

        self._warn_if_password_travels_in_clear(url, username, password)

        # dump settings into QgsSettings
        self.plg_settings.save_from_object(settings)

        if __debug__:
            self.log(
                message="DEBUG - Settings successfully saved.",
                log_level=Qgis.MessageLevel.NoLevel,
            )

    def _warn_if_password_travels_in_clear(
        self, url: str, username: str, password: str
    ) -> None:
        """Say once, while saving, that HTTP Basic over http:// is readable.

        Informs rather than refuses: apply() cannot stop the options dialog
        from closing, and a plain-HTTP server on a trusted network is a
        legitimate setup — the settings are saved either way.
        """
        if not self._password_travels_in_clear(url, username, password):
            return
        self.log(
            message=self.tr(
                "{url} is plain HTTP, so the password is sent unencrypted with every "
                "request. Use https:// where the server offers it."
            ).format(url=url),
            log_level=Qgis.MessageLevel.Warning,
            push=True,
        )

    def test_connection(self) -> None:
        """Probe the server with the fields as typed — saved or not."""
        url = self.txt_gs_url.text().strip()
        if not url.startswith(("http://", "https://")):
            self._show_test_result(
                self.tr("Enter a URL starting with http:// or https:// first."),
                "error",
            )
            return
        auth = (self.txt_gs_username.text(), self.txt_gs_password.text())
        # ponytail: blocks the Options dialog for up to PROBE_TIMEOUT (10 s)
        # against a dead host; QgsTask.fromFunction plus a deleted-widget guard
        # if that ever hurts.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            problem = probe(url, auth, self.opt_verify_tls.isChecked())
        finally:
            QApplication.restoreOverrideCursor()
        if problem is None:
            self._show_test_result(self.tr("Connected — GeoServer answered."), "ok")
        else:
            _status, message = problem
            self._show_test_result(message, "error")

    def _show_test_result(self, text: str, kind: str) -> None:
        """Show the outcome under the button, in a colour this theme can carry."""
        self.lbl_test_result.setText(text)
        colour = status_colour(kind, self.palette())
        self.lbl_test_result.setStyleSheet(f"color: {colour};" if colour else "")

    def load_settings(self) -> None:
        """Load options from QgsSettings + QgsAuthManager into UI form."""
        settings: PlgSettingsStructure = self.plg_settings.get_plg_settings()

        # global
        self.opt_debug.setChecked(settings.debug_mode)
        self.lbl_version_saved_value.setText(settings.version)

        # geoserver URL
        self.txt_gs_url.setText(settings.geoserver_url)
        self.opt_verify_tls.setChecked(settings.geoserver_verify_tls)

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
