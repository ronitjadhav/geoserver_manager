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
from qgis.core import Qgis
from qgis.gui import QgsOptionsPageWidget, QgsOptionsWidgetFactory
from qgis.PyQt import uic
from qgis.PyQt.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

# project
from geoserver_manager.__about__ import (
    __title__,
    __uri_homepage__,
    __uri_tracker__,
    __version__,
)
from geoserver_manager.gui.icons import icon
from geoserver_manager.gui.theme import hint_colour, status_colour
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
        self._icon_refresh_timer = QTimer(self)
        self._icon_refresh_timer.setSingleShot(True)
        self._icon_refresh_timer.timeout.connect(self._refresh_icons)
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
        self._refresh_icons()
        self.btn_help.pressed.connect(
            partial(QDesktopServices.openUrl, QUrl(__uri_homepage__))
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

        self.btn_reset.pressed.connect(self.on_reset_settings)

        self.btn_test_connection.clicked.connect(self.test_connection)
        self._build_profile_row()
        # A result describes the fields as they were; editing any of them ends it.
        for field in (self.txt_gs_url, self.txt_gs_username, self.txt_gs_password):
            field.textChanged.connect(self.lbl_test_result.clear)
        self.opt_verify_tls.toggled.connect(self.lbl_test_result.clear)

        # load previously saved settings
        self.load_settings()

    def _refresh_icons(self):
        self.btn_help.setIcon(icon("help", self.btn_help.palette()))
        self.btn_report.setIcon(icon("report-issue", self.btn_report.palette()))
        self.btn_reset.setIcon(icon("reset-settings", self.btn_reset.palette()))
        for button in (self.btn_help, self.btn_report, self.btn_reset):
            button.setIconSize(QSize(20, 20))

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange):
            if hasattr(self, "_icon_refresh_timer"):
                self._icon_refresh_timer.start(0)

    @staticmethod
    def _password_travels_in_clear(url: str, username: str, password: str) -> bool:
        """True when saving these would put a password on the wire unencrypted.

        The plugin authenticates with HTTP Basic, so over `http://` the
        password is readable by anything on the path. Loopback is exempt:
        those requests never leave the machine, and a warning on every local
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

        self._commit_fields()
        # Profiles edited but not shown: their connection and credentials,
        # through the same checks as the shown one.
        for profile in self._profiles:
            name = profile["name"]
            if name == self._shown or not self._is_dirty(name):
                continue
            stored = PlgSettingsStructure(
                geoserver_url=profile["url"],
                geoserver_auth_cfg_id=profile["auth_cfg_id"],
                geoserver_verify_tls=profile["verify_tls"],
            )
            self._store_connection(stored, profile=name, **self._buffers[name])
            self._keep(profile, stored)
        # The shown profile goes through `settings`, the connection everything
        # reads, so it becomes the active one: with its own auth config, never
        # the one of the profile that was active before.
        shown = self._profile(self._shown)
        if shown is not None:
            settings.geoserver_url = shown["url"]
            settings.geoserver_auth_cfg_id = shown["auth_cfg_id"]
        elif self._profile(self.plg_settings.active_profile_name()) is None and (
            self.plg_settings.active_profile_name()
        ):
            # The active profile was removed, and no other is shown: nothing is
            # left to connect with.
            settings.geoserver_url = ""
            settings.geoserver_auth_cfg_id = ""
        self._store_connection(
            settings,
            profile=shown["name"] if shown else None,
            url=self.txt_gs_url.text(),
            username=self.txt_gs_username.text(),
            password=self.txt_gs_password.text(),
            verify_tls=self.opt_verify_tls.isChecked(),
        )

        # dump settings into QgsSettings
        self.plg_settings.save_from_object(settings)
        if shown is None and settings.geoserver_url:
            # No profile yet: the first save makes one, named after the host.
            shown = {"name": urlparse(settings.geoserver_url).netloc or "GeoServer"}
            self._profiles.append(shown)
        if shown is not None:
            self._keep(shown, settings)
        for auth_cfg_id in self._removed_auth:
            PlgSettingsStructure(geoserver_auth_cfg_id=auth_cfg_id).remove_credentials()
        self._removed_auth = []
        self.plg_settings.save_profiles(self._profiles)
        self.plg_settings.set_value_from_key(
            "active_profile", shown["name"] if shown else ""
        )

        if __debug__:
            self.log(
                message="DEBUG - Settings successfully saved.",
                log_level=Qgis.MessageLevel.NoLevel,
            )

    def _store_connection(
        self, settings, url, username, password, verify_tls, profile=None
    ):
        """Validate one profile's URL and store its credentials, into `settings`.

        `settings` is the active connection for the shown profile, or a
        stand-in built for another edited one; both are updated in place.
        With more than one profile, every warning says which one it is about.
        """
        log = self.log
        if profile and len(self._profiles) > 1:
            self.log = lambda message="", **kwargs: log(
                message=self.tr("Profile '{}': {}").format(profile, message), **kwargs
            )
        try:
            self._store_one_connection(settings, url, username, password, verify_tls)
        finally:
            self.log = log

    def _store_one_connection(self, settings, url, username, password, verify_tls):
        """The checks and the credential write of _store_connection."""
        settings.geoserver_verify_tls = verify_tls

        # geoserver URL (not sensitive, stored in QgsSettings)
        url = url.strip()
        problem = self._url_problem(url) if url else None
        if problem:
            # apply() cannot stop the options dialog from closing, so keep the
            # previous URL and warn: dropping out here would also discard the
            # credentials the user just typed.
            self.log(
                message=f"{problem} {self.tr('URL not saved.')}",
                log_level=Qgis.MessageLevel.Warning,
                push=True,
            )
        else:
            settings.geoserver_url = url

        # credentials (sensitive, stored encrypted in QgsAuthManager)
        if not (username or password) and settings.geoserver_auth_cfg_id:
            # Both blanked on purpose: forget the stored credentials rather
            # than keep them behind empty fields.
            settings.remove_credentials()
            settings.geoserver_auth_cfg_id = ""
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

    def _warn_if_password_travels_in_clear(
        self, url: str, username: str, password: str
    ) -> None:
        """Say once, while saving, that HTTP Basic over http:// is readable.

        Informs rather than refuses: apply() cannot stop the options dialog
        from closing, and a plain-HTTP server on a trusted network is a
        legitimate setup: the settings are saved either way.
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

    def _url_problem(self, url):
        """What is wrong with a GeoServer URL, or None. One check, two callers
        (Save and Test connection), so their messages cannot drift apart."""
        if not url.startswith(("http://", "https://")):
            return self.tr("The GeoServer URL must start with http:// or https://.")
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            # user:pass@host would surface in the window title, the status
            # line, every error banner and the persistent QGIS log.
            return self.tr(
                "Take the user name and password out of the URL: the fields "
                "below carry them."
            )
        return None

    def test_connection(self) -> None:
        """Probe the server with the fields as typed, saved or not."""
        url = self.txt_gs_url.text().strip()
        problem = self._url_problem(url)
        if problem:
            self._show_test_result(problem, "error")
            return
        auth = (self.txt_gs_username.text(), self.txt_gs_password.text())
        self._show_test_result(self.tr("Testing…"), "busy")
        QApplication.processEvents()  # paint the line before the blocking probe
        # ponytail: blocks the Options dialog for up to PROBE_TIMEOUT (10 s)
        # against a dead host; QgsTask.fromFunction plus a deleted-widget guard
        # if that ever hurts.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            problem = probe(url, auth, self.opt_verify_tls.isChecked())
        finally:
            QApplication.restoreOverrideCursor()
        if problem is None:
            self._show_test_result(self.tr("Connected. GeoServer answered."), "ok")
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

        # Profiles: edits are kept per profile until Save (or dropped by
        # Cancel); a removed profile's credentials go only on Save.
        self._profiles = [dict(profile) for profile in self.plg_settings.get_profiles()]
        self._buffers, self._loaded, self._removed_auth = {}, {}, []
        active = self.plg_settings.active_profile_name()
        self._shown = None
        self._fill_profile_combo(
            active or (self._profiles[0]["name"] if self._profiles else None)
        )

    def on_reset_settings(self) -> None:
        """Reset settings to default values, every profile included."""
        count = len(self.plg_settings.get_profiles())
        if count and not self._confirm_reset(count):
            return
        for profile in self.plg_settings.get_profiles():
            PlgSettingsStructure(
                geoserver_auth_cfg_id=profile.get("auth_cfg_id", "")
            ).remove_credentials()
        # Remove the auth config if it exists
        current = self.plg_settings.get_plg_settings()
        current.remove_credentials()

        default_settings: PlgSettingsStructure = PlgSettingsStructure()
        self.plg_settings.save_from_object(default_settings)
        self.plg_settings.save_profiles([])
        self.plg_settings.set_value_from_key("active_profile", "")
        self.load_settings()

    def _confirm_reset(self, count) -> bool:
        """Reset saves at once: Cancel on the options dialog cannot undo it."""
        answer = QMessageBox.question(
            self,
            self.tr("Reset settings"),
            self.tr(
                "Remove %n saved profile(s) and their stored passwords? "
                "This cannot be undone.",
                None,
                count,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    # -- Server profiles (#47) -------------------------------------------------

    def _build_profile_row(self) -> None:
        """A Profile row above the URL: pick, add, remove."""
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        self.cmb_profile = QComboBox(row)
        self.cmb_profile.setToolTip(
            self.tr(
                "The server connection shown below. Saving makes it the active one."
            )
        )
        self.btn_profile_add = QPushButton(self.tr("Add…"), row)
        self.btn_profile_remove = QPushButton(self.tr("Remove"), row)
        layout.addWidget(self.cmb_profile, 1)
        layout.addWidget(self.btn_profile_add)
        layout.addWidget(self.btn_profile_remove)
        self.btn_profile_remove.setToolTip(
            self.tr("Removes the shown profile when you save. Cancel keeps it.")
        )
        self.formLayout.insertRow(0, QLabel(self.tr("Profile"), self), row)
        # Which profile the dialog connects to, and what Save changes: the list
        # alone does not say, and saving another one switches servers.
        self.lbl_profile_note = QLabel(self)
        self.lbl_profile_note.setWordWrap(True)
        self.lbl_profile_note.setStyleSheet(f"color: {hint_colour(self.palette())};")
        self.formLayout.insertRow(1, self.lbl_profile_note)
        self.cmb_profile.currentTextChanged.connect(self._on_profile_changed)
        self.btn_profile_add.clicked.connect(self._add_profile)
        self.btn_profile_remove.clicked.connect(self._remove_profile)

    def _profile(self, name):
        return next((p for p in self._profiles if p["name"] == name), None)

    def _fields(self) -> dict:
        return {
            "url": self.txt_gs_url.text(),
            "username": self.txt_gs_username.text(),
            "password": self.txt_gs_password.text(),
            "verify_tls": self.opt_verify_tls.isChecked(),
        }

    def _commit_fields(self) -> None:
        """Keep what the fields say for the profile they show."""
        if self._shown is not None:
            self._buffers[self._shown] = self._fields()

    def _is_dirty(self, name) -> bool:
        return name in self._buffers and self._buffers[name] != self._loaded.get(name)

    @staticmethod
    def _keep(profile, settings) -> None:
        """Copy a saved connection back into its profile entry."""
        profile.update(
            url=settings.geoserver_url,
            auth_cfg_id=settings.geoserver_auth_cfg_id,
            verify_tls=bool(settings.geoserver_verify_tls),
        )

    def _fill_profile_combo(self, select) -> None:
        self.cmb_profile.blockSignals(True)
        self.cmb_profile.clear()
        self.cmb_profile.addItems([p["name"] for p in self._profiles])
        if not self._profiles:
            # What an empty list means. Qt 5's combo placeholder does not
            # render in every style, so it is an item, disabled with the combo;
            # no profile has this name, so nothing can select or save it.
            self.cmb_profile.addItem(self.tr("None yet. Saving creates one."))
        self.cmb_profile.setEnabled(bool(self._profiles))
        self.cmb_profile.setCurrentText(select or "")
        self.cmb_profile.blockSignals(False)
        self.btn_profile_remove.setEnabled(bool(self._profiles))
        self._show_profile(select if self._profile(select) else None)

    def _show_profile(self, name) -> None:
        """Fill the fields from a profile's edits, else from what is stored."""
        self._shown = name
        profile = self._profile(name)
        if name in self._buffers:
            values = self._buffers[name]
        elif profile is not None:
            username, password = PlgSettingsStructure(
                geoserver_auth_cfg_id=profile.get("auth_cfg_id", "")
            ).get_credentials()
            values = {
                "url": profile.get("url", ""),
                "username": username,
                "password": password,
                "verify_tls": bool(profile.get("verify_tls", True)),
            }
            self._loaded[name] = dict(values)
        else:
            values = {"url": "", "username": "", "password": "", "verify_tls": True}
        self.txt_gs_url.setText(values["url"])
        self.txt_gs_username.setText(values["username"])
        self.txt_gs_password.setText(values["password"])
        self.opt_verify_tls.setChecked(values["verify_tls"])
        note = self._profile_note(name)
        self.lbl_profile_note.setText(note)
        self.lbl_profile_note.setVisible(bool(note))  # no blank row without one

    def _profile_note(self, shown) -> str:
        active = self.plg_settings.active_profile_name()
        if shown is None:
            return ""
        if shown == active:
            return self.tr("The active profile: the dialog connects to it.")
        if active and self._profile(active) is not None:
            return self.tr("Active: {}. Saving makes '{}' active instead.").format(
                active, shown
            )
        return self.tr("Saving makes '{}' the active profile.").format(shown)

    def _on_profile_changed(self, name) -> None:
        self._commit_fields()
        self._show_profile(name if self._profile(name) else None)

    def _add_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, self.tr("Add a Profile"), self.tr("Name of the new profile:")
        )
        name = name.strip()
        if not ok or not name:
            return
        if self._profile(name) is not None:
            QMessageBox.warning(
                self,
                self.tr("Add a Profile"),
                self.tr("A profile named '{}' already exists.").format(name),
            )
            return
        typed = self._fields() if self._shown is None else None
        self._commit_fields()
        self._profiles.append(
            {"name": name, "url": "", "auth_cfg_id": "", "verify_tls": True}
        )
        if typed is not None:
            # No profile yet: what was typed is this first profile's, and
            # naming it must not blank the fields.
            self._buffers[name] = typed
        self._fill_profile_combo(name)

    def _remove_profile(self) -> None:
        """Drop the shown profile; its credentials go when the page is saved."""
        profile = self._profile(self._shown)
        if profile is None:
            return
        self._profiles.remove(profile)
        self._buffers.pop(profile["name"], None)
        if profile.get("auth_cfg_id"):
            self._removed_auth.append(profile["auth_cfg_id"])
        self._shown = None
        # Keep the active profile on screen (Save makes the shown one active),
        # so removing another one does not quietly switch servers.
        active = self.plg_settings.active_profile_name()
        if self._profile(active) is None:
            active = self._profiles[0]["name"] if self._profiles else None
        self._fill_profile_combo(active)


class PlgOptionsFactory(QgsOptionsWidgetFactory):
    """Factory for options widget."""

    def __init__(self) -> None:
        super().__init__()

    def icon(self) -> QIcon:
        return icon("plugin")

    def createWidget(self, parent: QWidget) -> ConfigOptionsPage:  # noqa: N802
        return ConfigOptionsPage(parent)

    def title(self) -> str:
        return __title__

    def helpId(self) -> str:  # noqa: N802
        return __uri_homepage__
