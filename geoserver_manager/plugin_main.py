#! python3  # noqa: E265

"""Main plugin module."""

# standard
from functools import partial
from pathlib import Path

# PyQGIS
from qgis.core import Qgis, QgsSettings
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QCoreApplication, QLocale, QTimer, QTranslator, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QAction, QApplication, QMessageBox

# project
from geoserver_manager.__about__ import (
    DIR_PLUGIN_ROOT,
    __title__,
    __uri_homepage__,
)
from geoserver_manager.gui.dlg_main import GeoServerMainDialog
from geoserver_manager.gui.dlg_settings import PlgOptionsFactory
from geoserver_manager.gui.icons import icon
from geoserver_manager.gui.layer_tree import LayerTreeMenu
from geoserver_manager.toolbelt.log_handler import PlgLogger
from geoserver_manager.toolbelt.preferences import PlgOptionsManager

# ############################################################################
# ########## Classes ###############
# ##################################


class GeoServerManagerPlugin:
    def __init__(self, iface: QgisInterface) -> None:
        """Constructor.

        :param iface: An interface instance that will be passed to this class which \
        provides the hook by which you can manipulate the QGIS application at run time.
        :type iface: QgsInterface
        """
        self.iface = iface
        self.log = PlgLogger().log
        self.plg_settings = PlgOptionsManager()
        self.main_dialog = None
        self.layer_tree_menu = None

        # translation
        # initialize the locale
        self.locale: str = QgsSettings().value("locale/userLocale", QLocale().name())[
            0:2
        ]
        # A locale the plugin has no translation for falls back to English's:
        # its plural forms, without which "%n layer(s)" read "(s)".
        candidates = [
            DIR_PLUGIN_ROOT / "resources" / "i18n" / f"{DIR_PLUGIN_ROOT.name}_{code}.qm"
            for code in (self.locale, "en")
        ]
        locale_path: Path = next(
            (path for path in candidates if path.exists()), candidates[0]
        )
        self.log(
            message=f"Translation: {self.locale}, {locale_path}",
            log_level=Qgis.MessageLevel.NoLevel,
        )
        self.translator = None
        if locale_path.exists():
            self.translator = QTranslator()
            self.translator.load(str(locale_path.resolve()))
            QCoreApplication.installTranslator(self.translator)

        # Ensure dependencies are available
        from geoserver_manager.toolbelt.dependencies import ensure_dependencies

        self.dependencies_available = ensure_dependencies()

    def initGui(self) -> None:  # noqa: N802
        """Set up plugin UI elements."""

        # settings page within the QGIS preferences menu
        self.options_factory = PlgOptionsFactory()
        self.iface.registerOptionsWidgetFactory(self.options_factory)

        # -- Actions
        self.action_help = QAction(
            icon("help", for_menu=True),
            self.tr("Help"),
            self.iface.mainWindow(),
        )
        self.action_help.triggered.connect(
            partial(QDesktopServices.openUrl, QUrl(__uri_homepage__))
        )

        self.action_settings = QAction(
            icon("settings", for_menu=True),
            self.tr("Settings"),
            self.iface.mainWindow(),
        )
        self.action_settings.triggered.connect(
            lambda: self.iface.showOptionsDialog(
                currentPage="mOptionsPage{}".format(__title__)
            )
        )

        self.action_main = QAction(
            icon("plugin"),
            self.tr(__title__),
            self.iface.mainWindow(),
        )
        self.action_main.triggered.connect(self.run)

        # -- Toolbar
        self.iface.addToolBarIcon(self.action_main)

        # -- Menu
        self.iface.addPluginToMenu(__title__, self.action_main)
        self.iface.addPluginToMenu(__title__, self.action_settings)
        self.iface.addPluginToMenu(__title__, self.action_help)

        # -- Help menu

        # documentation
        self._help_separator = self.iface.pluginHelpMenu().addSeparator()
        self.action_help_plugin_menu_documentation = QAction(
            icon("plugin", for_menu=True),
            f"{__title__} - Documentation",
            self.iface.mainWindow(),
        )
        self.action_help_plugin_menu_documentation.triggered.connect(
            partial(QDesktopServices.openUrl, QUrl(__uri_homepage__))
        )

        self.iface.pluginHelpMenu().addAction(
            self.action_help_plugin_menu_documentation
        )

        self._icon_refresh_timer = QTimer(self.iface.mainWindow())
        self._icon_refresh_timer.setSingleShot(True)
        self._icon_refresh_timer.timeout.connect(self._refresh_menu_icons)
        QApplication.instance().paletteChanged.connect(self._queue_menu_icon_refresh)
        self._refresh_menu_icons()

        # -- Layer tree context menu: push / apply the clicked layer's style.
        # The connection is the main dialog's, which exists once run() has
        # opened it; until then the entries are disabled and say so.
        self.layer_tree_menu = LayerTreeMenu(
            self.iface, dialog=lambda: self.main_dialog, open_dialog=self.run
        )

    def _queue_menu_icon_refresh(self, _palette):
        # QApplication emits before the main window inherits the new palette.
        self._icon_refresh_timer.start(0)

    def _refresh_menu_icons(self):
        window = self.iface.mainWindow()
        palette = window.palette() if window is not None else QApplication.palette()
        self.action_main.setIcon(icon("plugin", palette))
        self.action_help.setIcon(icon("help", palette, for_menu=True))
        self.action_settings.setIcon(icon("settings", palette, for_menu=True))
        self.action_help_plugin_menu_documentation.setIcon(
            icon("plugin", palette, for_menu=True)
        )

    def tr(self, message: str) -> str:
        """Get the translation for a string using Qt translation API.

        :param message: string to be translated.
        :type message: str

        :returns: Translated version of message.
        :rtype: str
        """
        return QCoreApplication.translate(self.__class__.__name__, message)

    def unload(self) -> None:
        """Cleans up when plugin is disabled/uninstalled."""
        QApplication.instance().paletteChanged.disconnect(self._queue_menu_icon_refresh)
        self._icon_refresh_timer.stop()
        self._icon_refresh_timer.deleteLater()
        # -- The layer-tree hook first: left connected, it would fire into a
        # dead plugin after the next reload.
        if self.layer_tree_menu:
            self.layer_tree_menu.unload()
            self.layer_tree_menu = None

        # -- Close and destroy the main dialog (it is a child of the QGIS main
        # window, so dropping the reference alone would keep it alive)
        if self.main_dialog:
            self.main_dialog.close()
            self.main_dialog.deleteLater()
            self.main_dialog = None

        # -- Clean up menu and toolbar
        self.iface.removeToolBarIcon(self.action_main)
        self.iface.removePluginMenu(__title__, self.action_main)
        self.iface.removePluginMenu(__title__, self.action_help)
        self.iface.removePluginMenu(__title__, self.action_settings)

        # -- Clean up preferences panel in QGIS settings
        self.iface.unregisterOptionsWidgetFactory(self.options_factory)

        # remove from QGIS help/extensions menu
        if self.action_help_plugin_menu_documentation:
            self.iface.pluginHelpMenu().removeAction(
                self.action_help_plugin_menu_documentation
            )
        if self._help_separator:
            self.iface.pluginHelpMenu().removeAction(self._help_separator)
        if self.translator:
            QCoreApplication.removeTranslator(self.translator)

        # remove actions
        del self.action_main
        del self.action_settings
        del self.action_help

    def run(self):
        """Open the main plugin dialog."""
        if not self.dependencies_available:
            # Try again, and say why once more: the explanation was shown once
            # at QGIS startup, and a toolbar click that does nothing says less.
            from geoserver_manager.toolbelt.dependencies import ensure_dependencies

            self.dependencies_available = ensure_dependencies()
            if not self.dependencies_available:
                return

        settings = self.plg_settings.get_plg_settings()

        if not settings.has_credentials():
            QMessageBox.information(
                self.iface.mainWindow(),
                self.tr("GeoServer Manager: first connection"),
                self.tr(
                    "Welcome to GeoServer Manager.\n\n"
                    "Enter your GeoServer's URL, user name and password on the "
                    "settings page that opens next; Test connection tells you "
                    "whether they work before you save."
                ),
            )
            self.iface.showOptionsDialog(currentPage=f"mOptionsPage{__title__}")

            # Re-check in case they cancelled
            settings = self.plg_settings.get_plg_settings()
            if not settings.has_credentials():
                return

        if not self.main_dialog:
            self.main_dialog = GeoServerMainDialog(self.iface.mainWindow(), self.iface)

        # refresh_ui only starts the connection probe. It runs in a QgsTask
        # and calls back when it lands, so the window paints straight away
        # even against a host that swallows the SYN (VPN down, firewall DROP).
        self.main_dialog.show()
        self.main_dialog.refresh_ui()
