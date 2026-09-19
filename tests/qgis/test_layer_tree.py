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
from qgis.PyQt.QtWidgets import QDialog, QMenu
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
        push, pull = submenu.actions()[0], submenu.actions()[1]
        self.assertFalse(push.isEnabled())
        self.assertFalse(pull.isEnabled())
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
        self.assertEqual(len(self.texts()), 2)
        self.assertIn("Not connected", self.texts()[0])

    def test_entries_are_live_once_connected(self):
        self.dlg = connected_dialog(["topp:states"])
        submenu = self.submenu(self.build())
        self.assertTrue(submenu.actions()[0].isEnabled())
        self.assertTrue(submenu.actions()[1].isEnabled())
        self.assertEqual(len(submenu.actions()), 2)


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

    def test_a_css_style_is_refused_before_qgis_chokes_on_it(self):
        self.formats = {"population": "css"}
        self.apply()
        self.assertEqual(self.applied, [])
        self.assertIn("QGIS can only read SLD", self.texts()[-1])

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
