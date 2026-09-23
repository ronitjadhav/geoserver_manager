#! python3  # noqa E265

"""
The GeoServer Manager submenu of the layer tree's context menu.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_layer_tree
"""

from unittest.mock import patch

from qgis.core import Qgis, QgsLayerTreeModel, QgsProject, QgsVectorLayer
from qgis.gui import QgsLayerTreeView
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QIcon, QPalette
from qgis.PyQt.QtWidgets import QApplication, QDialog, QMainWindow, QMenu
from qgis.testing import start_app, unittest

from geoserver_manager.gui import layer_tree
from geoserver_manager.gui.layer_tree import LayerTreeMenu
from geoserver_manager.plugin_main import GeoServerManagerPlugin
from tests.qgis.sync_dialog import SyncDialog

start_app()

BASE = "http://gs.example.org/geoserver"


class FakeBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, title, text, level=None, duration=None):  # noqa: N802
        self.messages.append((text, level))


class FakeIface:
    """A real layer tree view over the project, and a recording message bar."""

    def __init__(self):
        self.model = QgsLayerTreeModel(QgsProject.instance().layerTreeRoot())
        self.view = QgsLayerTreeView()
        self.view.setModel(self.model)
        self.bar = FakeBar()
        self.help_menu = QMenu()

    def layerTreeView(self):  # noqa: N802
        return self.view

    def messageBar(self):  # noqa: N802
        return self.bar

    def mainWindow(self):  # noqa: N802
        return None

    def pluginHelpMenu(self):  # noqa: N802
        return self.help_menu

    def __getattr__(self, name):
        # registerOptionsWidgetFactory, addToolBarIcon, …: nothing to do here.
        return lambda *args, **kwargs: None


class FakeEndpoints:
    base_url = f"{BASE}/rest"

    def style(self, style_name, workspace_name=None, format="json"):
        if workspace_name:
            return f"{self.base_url}/workspaces/{workspace_name}/styles/{style_name}.{format}"
        return f"{self.base_url}/styles/{style_name}.{format}"


class FakeLayerModel:
    """What rest_service.get_layer answers: geoservercloud.models.layer.Layer."""

    def __init__(self, default, others):
        self.default_style_name = default
        self.styles = [{"name": name} for name in others]


class FakeRestService:
    def __init__(self, styles_by_layer):
        self.rest_endpoints = FakeEndpoints()
        self.styles_by_layer = styles_by_layer

    def get_layer(self, workspace_name, layer_name):
        entry = self.styles_by_layer.get(f"{workspace_name}:{layer_name}")
        if entry is None:
            return ("no such layer", 404)
        return (FakeLayerModel(*entry), 200)


class FakeGS:
    url = BASE

    def __init__(self, layers, styles_by_layer=None, formats=None):
        self.layers = list(layers)
        self.rest_service = FakeRestService(styles_by_layer or {})
        self.formats = formats or {}

    def get_style_definition(self, style_name, workspace_name=None):
        return (
            {"name": style_name, "format": self.formats.get(style_name, "sld")},
            200,
        )


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload


def connected_dialog(layers, styles_by_layer=None, formats=None):
    """The real dialog with a fake client, recording what the menu asks of it."""
    dlg = SyncDialog()
    dlg.gs = FakeGS(layers, styles_by_layer, formats)
    dlg.requests = []
    dlg.pushed = []

    def raw_rest(method, path, **kwargs):
        dlg.requests.append((method, path))
        if path.endswith("/layers.json"):
            names = [{"name": name} for name in dlg.gs.layers]
            return FakeResponse({"layers": {"layer": names}})
        return FakeResponse(content=b"<StyledLayerDescriptor/>")

    dlg._raw_rest = raw_rest
    dlg._push_qgis_style = lambda *args: dlg.pushed.append(args) or True
    return dlg


class FakeForm:
    """ResourceFormDialog stand-in: records the fields, answers preset values."""

    opened = []
    values = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeForm.opened.append(self)

    def exec(self):
        return QDialog.DialogCode.Accepted

    def get_values(self):
        return dict(FakeForm.values)


class Source:
    """Only what server_layer_from_source reads off a layer."""

    def __init__(self, source, provider, name="states"):
        self._source, self._provider, self._name = source, provider, name

    def source(self):
        return self._source

    def providerType(self):  # noqa: N802
        return self._provider

    def name(self):
        return self._name


class MenuCase(unittest.TestCase):
    def setUp(self):
        self.iface = FakeIface()
        self.dlg = None
        self.opened = []
        self.keep = []
        self.layer = QgsVectorLayer("Point?crs=epsg:4326", "states", "memory")
        QgsProject.instance().addMapLayer(self.layer)
        self.iface.view.setCurrentLayer(self.layer)
        self.menu = LayerTreeMenu(
            self.iface,
            dialog=lambda: self.dlg,
            open_dialog=lambda: self.opened.append(True),
        )
        FakeForm.opened.clear()
        FakeForm.values = {}

    def tearDown(self):
        self.menu.unload()
        QgsProject.instance().removeAllMapLayers()

    def build(self):
        menu = QMenu()
        self.keep.append(menu)  # the submenu is its child: it dies with it
        self.iface.view.contextMenuAboutToShow.emit(menu)
        return menu

    @staticmethod
    def submenu(menu):
        for action in menu.actions():
            if action.menu() is not None:
                return action.menu()
        return None

    def texts(self):
        return [message for message, _level in self.iface.bar.messages]


class TestWhereTheMenuAppears(MenuCase):
    def test_a_map_layer_gets_the_submenu_with_both_entries(self):
        submenu = self.submenu(self.build())
        self.assertIsNotNone(submenu)
        self.assertEqual(submenu.title(), "GeoServer Manager")
        labels = [action.text() for action in submenu.actions() if action.text()]
        self.assertEqual(labels[0], "Push style to GeoServer…")
        self.assertEqual(labels[1], "Apply style from GeoServer…")
        self.assertEqual(labels[2], "Publish to GeoServer…")

    def test_a_group_gets_nothing(self):
        group = QgsProject.instance().layerTreeRoot().addGroup("a group")
        self.iface.view.setCurrentIndex(self.iface.view.node2index(group))
        self.assertIsNone(self.submenu(self.build()))

    def test_no_current_layer_gets_nothing(self):
        self.iface.view.setCurrentLayer(None)
        self.assertIsNone(self.submenu(self.build()))

    def test_unload_takes_the_hook_out(self):
        self.menu.unload()
        self.assertIsNone(self.submenu(self.build()))
        self.menu.unload()  # a second time is harmless


class TestNotConnected(MenuCase):
    def test_entries_are_disabled_and_say_why(self):
        submenu = self.submenu(self.build())
        push, pull, publish = [a for a in submenu.actions() if a.text()][:3]
        self.assertFalse(push.isEnabled())
        self.assertFalse(pull.isEnabled())
        self.assertFalse(publish.isEnabled())
        self.assertIn("Open GeoServer Manager first", push.toolTip())

    def test_an_entry_opens_the_plugin_instead(self):
        submenu = self.submenu(self.build())
        connect = submenu.actions()[-1]
        self.assertIn("Open GeoServer Manager", connect.text())
        self.assertTrue(connect.isEnabled())
        connect.trigger()
        self.assertEqual(self.opened, [True])

    def test_a_dialog_without_a_client_counts_as_not_connected(self):
        self.dlg = SyncDialog()  # gs is None until the probe lands
        submenu = self.submenu(self.build())
        self.assertFalse(submenu.actions()[0].isEnabled())

    def test_triggering_after_the_connection_dropped_warns(self):
        self.dlg = SyncDialog()
        self.menu.push_style(self.layer)
        self.menu.apply_style(self.layer)
        self.menu.publish(self.layer)
        self.assertEqual(len(self.texts()), 3)
        self.assertIn("Not connected", self.texts()[0])

    def test_entries_are_live_once_connected(self):
        self.dlg = connected_dialog(["topp:states"])
        submenu = self.submenu(self.build())
        entries = [action for action in submenu.actions() if action.text()]
        self.assertEqual(len(entries), 3)
        self.assertTrue(all(action.isEnabled() for action in entries))

    def test_a_multi_selection_offers_to_publish_them_all(self):
        self.dlg = connected_dialog(["topp:states"])
        other = QgsVectorLayer("Point?crs=epsg:4326", "rivers", "memory")
        QgsProject.instance().addMapLayer(other)
        self.iface.view.setCurrentLayer(self.layer)
        for node in (self.layer, other):
            index = self.iface.view.node2index(
                QgsProject.instance().layerTreeRoot().findLayer(node)
            )
            self.iface.view.selectionModel().select(
                index, self.iface.view.selectionModel().SelectionFlag.Select
            )
        batches = []
        self.dlg._publish_layers = batches.append
        self.dlg._on_nav_changed = lambda index: None

        submenu = self.submenu(self.build())
        publish = [a for a in submenu.actions() if a.text()][2]
        self.assertEqual(publish.text(), "Publish 2 layer(s) to GeoServer…")
        publish.trigger()
        self.assertEqual(len(batches), 1)
        self.assertEqual({layer.name() for layer in batches[0]}, {"states", "rivers"})
        self.dlg.hide()

    def test_publish_brings_the_dialog_up_on_the_layers_tab(self):
        """The upload reports into the dialog, so the dialog must be showing,
        and on the tab where the published layer will appear.
        """
        self.dlg = connected_dialog(["topp:states"])
        self.dlg.navList.setCurrentRow(0)
        opened_with = []
        self.dlg._publish_layer = lambda layer=None: opened_with.append(layer)
        self.dlg._on_nav_changed = lambda index: None  # no load in this test

        self.menu.publish(self.layer)

        self.assertTrue(self.dlg.isVisible())
        self.assertEqual(self.dlg.navList.currentItem().text(), "Layers")
        self.assertEqual(opened_with, [self.layer])
        self.dlg.hide()


class TestReadsAndMessages(MenuCase):
    """The menu's server reads and its message bar (review of 2026-09-23)."""

    def test_a_server_read_runs_in_a_worker(self):
        import threading

        self.dlg = connected_dialog(["topp:states"])
        ok, where = self.menu._read(self.dlg, threading.current_thread, "failed")
        self.assertTrue(ok)
        self.assertIsNot(where, threading.main_thread())

    def test_cancelling_the_wait_reports_nothing(self):
        from geoserver_manager.gui.dlg_main import _Abandoned

        self.dlg = connected_dialog(["topp:states"])

        def abandon(_fn):
            raise _Abandoned()

        self.dlg._wait_for = abandon
        self.assertEqual(self.menu._read(self.dlg, lambda: 1, "failed"), (False, None))
        self.assertEqual(self.iface.bar.messages, [])

    def test_warnings_and_errors_stay_until_closed(self):
        durations = []
        self.iface.bar.pushMessage = lambda title, text, level, duration: (
            durations.append((level, duration))
        )
        self.menu._say("gone", Qgis.MessageLevel.Critical)
        self.menu._say("careful", Qgis.MessageLevel.Warning)
        self.menu._say("done", Qgis.MessageLevel.Success)
        self.assertEqual(
            durations,
            [
                (Qgis.MessageLevel.Critical, 0),
                (Qgis.MessageLevel.Warning, 0),
                (Qgis.MessageLevel.Success, 8),
            ],
        )


class TestWhichServerLayer(unittest.TestCase):
    """Pure: the target comes from the layer's source, else from its name."""

    def test_a_wfs_layer_from_this_server_names_its_layer(self):
        uri, provider = SyncDialog._layer_uri("WFS", BASE, "topp:states", "cfg1")
        found = LayerTreeMenu.server_layer_from_source(Source(uri, provider), BASE)
        self.assertEqual(found, "topp:states")

    def test_a_wms_layer_from_this_server_names_its_layer(self):
        uri, provider = SyncDialog._layer_uri("WMS", BASE, "topp:states", "cfg1")
        found = LayerTreeMenu.server_layer_from_source(Source(uri, provider), BASE)
        self.assertEqual(found, "topp:states")

    def test_a_layer_from_another_server_is_not_a_target(self):
        uri, provider = SyncDialog._layer_uri(
            "WFS", "http://other.example.org/geoserver", "topp:states"
        )
        self.assertIsNone(
            LayerTreeMenu.server_layer_from_source(Source(uri, provider), BASE)
        )

    def test_a_local_layer_names_nothing(self):
        for source, provider in (
            ("Point?crs=epsg:4326&field=id:integer", "memory"),
            ("/data/states.shp|layername=states", "ogr"),
        ):
            self.assertIsNone(
                LayerTreeMenu.server_layer_from_source(Source(source, provider), BASE)
            )

    def test_name_match_ignores_case_and_workspace_prefix(self):
        server = ["topp:states", "nurc:States", "sf:roads", "unqualified"]
        self.assertEqual(
            LayerTreeMenu.matching_server_layers("Topp:STATES", server),
            ["topp:states", "nurc:States"],
        )
        self.assertEqual(
            LayerTreeMenu.matching_server_layers("roads", server), ["sf:roads"]
        )
        self.assertEqual(LayerTreeMenu.matching_server_layers("nothing", server), [])


class TestPush(MenuCase):
    def setUp(self):
        super().setUp()
        self.dlg = connected_dialog(["topp:states", "sf:roads"])

    def push(self, **values):
        FakeForm.values = {"style": "states", "set_default": True, **values}
        with (
            patch.object(layer_tree, "ResourceFormDialog", FakeForm),
            patch.object(layer_tree, "layer_to_sld", lambda layer: "<sld/>"),
        ):
            self.menu.push_style(self.layer)

    def test_the_symbology_goes_to_the_matching_server_layer(self):
        self.push()
        self.assertEqual(
            self.dlg.pushed, [("states", "topp", "<sld/>", "states", True)]
        )
        self.assertIn("topp:states", self.texts()[-1])
        # one confirmation, and it named the target
        self.assertEqual(len(FakeForm.opened), 1)
        self.assertIn("topp", FakeForm.opened[0].kwargs["description"])
        self.assertEqual(FakeForm.opened[0].kwargs["ok_label"], "Upload")

    def test_the_style_name_is_made_geoserver_safe(self):
        self.push(style="états unis", set_default=False)
        self.assertEqual(self.dlg.pushed[0][0], "etats_unis")
        self.assertEqual(self.dlg.pushed[0][4], False)

    def test_several_matches_ask_which_one(self):
        self.dlg.gs.layers = ["topp:states", "nurc:states"]
        self.push(target="nurc:states")
        self.assertEqual(self.dlg.pushed[0][1], "nurc")
        picker = FakeForm.opened[0]
        self.assertEqual(picker.kwargs["fields"][0]["key"], "target")
        self.assertEqual(
            picker.kwargs["fields"][0]["options"], ["topp:states", "nurc:states"]
        )

    def test_no_match_is_said_and_nothing_is_asked(self):
        self.dlg.gs.layers = ["sf:roads"]
        self.push()
        self.assertEqual(self.dlg.pushed, [])
        self.assertEqual(FakeForm.opened, [])
        self.assertIn("No layer on the server is named like 'states'", self.texts()[0])

    def test_a_layer_loaded_from_the_server_needs_no_lookup(self):
        uri, provider = SyncDialog._layer_uri("WFS", BASE, "sf:archsites", "cfg1")
        self.layer = Source(uri, provider, name="whatever the user renamed it to")
        self.push()
        self.assertEqual(
            self.dlg.pushed[0][1:2] + self.dlg.pushed[0][3:4], ("sf", "archsites")
        )
        self.assertEqual(self.dlg.requests, [])  # no /layers.json GET

    def test_a_kept_style_is_said_not_claimed_as_uploaded(self):
        self.dlg._push_qgis_style = (
            lambda *args: False
        )  # the user kept the existing one
        self.push()
        text, level = self.iface.bar.messages[-1]
        self.assertIn("left as it is", text)
        self.assertEqual(level, Qgis.MessageLevel.Info)

    def test_a_failing_upload_lands_in_the_message_bar(self):
        def boom(*args):
            raise RuntimeError("HTTP 500: boom")

        self.dlg._push_qgis_style = boom
        self.push()
        text, level = self.iface.bar.messages[-1]
        self.assertIn("boom", text)
        self.assertEqual(level, Qgis.MessageLevel.Critical)


class TestApply(MenuCase):
    def setUp(self):
        super().setUp()
        self.applied = []
        self.styles_by_layer = {"topp:states": ("population", [])}
        self.formats = {}

    def apply(self, **values):
        self.dlg = connected_dialog(
            ["topp:states", "sf:roads"], self.styles_by_layer, self.formats
        )
        FakeForm.values = dict(values)

        def record(layer, sld):
            self.applied.append((layer, sld))
            return True, ""

        with (
            patch.object(layer_tree, "ResourceFormDialog", FakeForm),
            patch.object(layer_tree, "apply_sld_to_layer", record),
        ):
            self.menu.apply_style(self.layer)

    def test_the_only_style_is_applied_without_asking(self):
        self.apply()
        self.assertEqual(self.applied, [(self.layer, "<StyledLayerDescriptor/>")])
        self.assertEqual(FakeForm.opened, [])
        self.assertTrue(
            self.dlg.requests[-1][1].endswith("/styles/population.sld"),
            self.dlg.requests,
        )
        self.assertIn("population", self.texts()[-1])

    def test_several_styles_are_offered_default_first(self):
        self.styles_by_layer = {"topp:states": ("population", ["topp:pophatch"])}
        self.apply(style="topp:pophatch")
        picker = FakeForm.opened[0]
        self.assertEqual(
            picker.kwargs["fields"][0]["options"], ["population", "topp:pophatch"]
        )
        self.assertEqual(picker.kwargs["fields"][0]["default"], "population")
        # a workspace style is fetched from its workspace
        self.assertTrue(
            self.dlg.requests[-1][1].endswith("/workspaces/topp/styles/pophatch.sld")
        )

    def test_a_css_style_arrives_as_geoservers_own_sld(self):
        # GET .sld on a CSS style returns GeoServer's conversion (2.28.5).
        self.formats = {"population": "css"}
        self.apply()
        self.assertEqual(self.applied, [(self.layer, "<StyledLayerDescriptor/>")])
        self.assertTrue(self.dlg.requests[-1][1].endswith("/styles/population.sld"))

    def test_a_layer_without_styles_is_said(self):
        self.styles_by_layer = {"topp:states": (None, [])}
        self.apply()
        self.assertEqual(self.applied, [])
        self.assertIn("has no style", self.texts()[-1])


class TestPluginWiring(unittest.TestCase):
    """initGui connects the hook, unload disconnects it."""

    def setUp(self):
        self.iface = FakeIface()
        self.layer = QgsVectorLayer("Point?crs=epsg:4326", "states", "memory")
        QgsProject.instance().addMapLayer(self.layer)
        self.iface.view.setCurrentLayer(self.layer)

    def tearDown(self):
        QgsProject.instance().removeAllMapLayers()

    def submenus(self):
        menu = QMenu()
        self.iface.view.contextMenuAboutToShow.emit(menu)
        return [action for action in menu.actions() if action.menu() is not None]

    def test_opening_without_the_library_explains_itself_again(self):
        """The failure was said once at startup; a later click was silent."""
        plugin = GeoServerManagerPlugin(self.iface)
        plugin.dependencies_available = False
        tried = []
        with patch(
            "geoserver_manager.toolbelt.dependencies.ensure_dependencies",
            lambda: tried.append(1) or False,
        ):
            plugin.run()
        self.assertEqual(tried, [1])
        self.assertIsNone(plugin.main_dialog)

    def test_menu_icons_follow_the_palette_and_disconnect_on_unload(self):
        app = QApplication.instance()
        original = QPalette(app.palette())
        self.addCleanup(QApplication.setPalette, original)
        receivers = app.receivers(app.paletteChanged)
        window = QMainWindow()
        self.addCleanup(window.deleteLater)
        self.iface.mainWindow = lambda: window
        plugin = GeoServerManagerPlugin(self.iface)
        plugin.initGui()
        try:
            self.assertEqual(app.receivers(app.paletteChanged), receivers + 1)
            before = plugin.action_help.icon().pixmap(QSize(20, 20)).toImage()
            changed = QPalette(original)
            changed.setColor(QPalette.ColorRole.Text, QColor("#526fa8"))
            QApplication.setPalette(changed)
            QApplication.processEvents()
            after = plugin.action_help.icon().pixmap(QSize(20, 20)).toImage()
            self.assertNotEqual(before, after)
        finally:
            plugin.unload()
        self.assertEqual(app.receivers(app.paletteChanged), receivers)

    def test_highlighted_menu_icons_keep_their_strokes_visible(self):
        plugin = GeoServerManagerPlugin(self.iface)
        plugin.initGui()
        try:
            image = (
                plugin.action_help.icon()
                .pixmap(QSize(20, 20), QIcon.Mode.Active)
                .toImage()
            )
            expected = QApplication.palette().color(QPalette.ColorRole.HighlightedText)
            visible = 0
            for x in range(image.width()):
                for y in range(image.height()):
                    pixel = image.pixelColor(x, y)
                    if pixel.alpha() > 128:
                        visible += 1
                        for actual, target in zip(
                            pixel.getRgb()[:3], expected.getRgb()[:3]
                        ):
                            self.assertLessEqual(abs(actual - target), 3)
            self.assertGreater(visible, 5)
            # The toolbar action also appears in a menu. Preserve its normal
            # brand colours on hover so it stays visible on a light toolbar.
            toolbar = plugin.action_main.icon()
            self.assertEqual(
                toolbar.pixmap(QSize(20, 20), QIcon.Mode.Normal).toImage(),
                toolbar.pixmap(QSize(20, 20), QIcon.Mode.Active).toImage(),
            )
        finally:
            plugin.unload()

    def test_the_hook_lives_from_init_gui_to_unload(self):
        plugin = GeoServerManagerPlugin(self.iface)
        self.assertEqual(self.submenus(), [])
        plugin.initGui()
        self.assertEqual(len(self.submenus()), 1)
        plugin.unload()
        self.assertEqual(self.submenus(), [])
        self.assertIsNone(plugin.layer_tree_menu)


if __name__ == "__main__":
    unittest.main()
