#! python3  # noqa: E265

"""
The *GeoServer Manager* submenu of the layer tree's context menu.

Two actions a cartographer repeats all day, put where the layer already is:
push this layer's symbology to GeoServer as the matching layer's style, and
apply the server's style to it. Both need the main dialog's connection and a
GeoServer layer to talk about. Without a connection the entries are disabled
and say why, next to an entry that opens the plugin; without a matching layer
the click explains itself in the message bar. Neither ever overwrites
silently: pushing confirms the target and the style name in the same small
form the Layers tab uses, and pulling asks which style when the layer has
several.

The hook is `QgsLayerTreeView.contextMenuAboutToShow`, connected in `initGui`
and disconnected in `unload()`. A hook left behind survives a plugin reload and
fires into the dead plugin, and plugin_reloader is how this repo is developed.
"""

from urllib.parse import parse_qs, urlparse

from qgis.core import Qgis, QgsDataSourceUri, QgsMapLayer
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QApplication, QDialog

from geoserver_manager.__about__ import __title__
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.icons import icon
from geoserver_manager.toolbelt.log_handler import PlgLogger
from geoserver_manager.toolbelt.qgis_export import geoserver_name
from geoserver_manager.toolbelt.sld import apply_sld_to_layer, layer_to_sld

# Not a QObject, so self.tr() is not available; the context is this class.
translate = QCoreApplication.translate

_STYLEABLE = (QgsMapLayer.LayerType.VectorLayer, QgsMapLayer.LayerType.RasterLayer)


class LayerTreeMenu:
    """Adds the plugin's entries to the layer tree's context menu.

    :param dialog: a callable returning the main dialog, or None before the
        plugin has been opened. The connection lives on that dialog.
    :param open_dialog: what the "open GeoServer Manager" entry calls.
    """

    def __init__(self, iface, dialog, open_dialog=None):
        self.iface = iface
        self._dialog = dialog
        self._open_dialog = open_dialog
        self.log = PlgLogger().log
        self._view = iface.layerTreeView()
        self._view.contextMenuAboutToShow.connect(self._populate)

    def unload(self):
        """Take the hook out again; the plugin is going away."""
        try:
            self._view.contextMenuAboutToShow.disconnect(self._populate)
        except TypeError:
            pass  # already disconnected

    # -- The menu --------------------------------------------------------------

    def _connected_dialog(self):
        """The main dialog while it holds a live client, else None."""
        dlg = self._dialog()
        return dlg if dlg is not None and getattr(dlg, "gs", None) else None

    def _populate(self, menu):
        """Add the submenu for the clicked layer, if it is one a style can go on."""
        layer = self._view.currentLayer()
        if layer is None or layer.type() not in _STYLEABLE:
            return
        submenu = menu.addMenu(icon("plugin", menu.palette(), for_menu=True), __title__)
        push = submenu.addAction(
            icon("push-style", submenu.palette(), for_menu=True),
            translate("LayerTreeMenu", "Push style to GeoServer…"),
        )
        pull = submenu.addAction(
            icon("apply-style", submenu.palette(), for_menu=True),
            translate("LayerTreeMenu", "Apply style from GeoServer…"),
        )
        submenu.addSeparator()
        publish = submenu.addAction(
            icon("publish-layer", submenu.palette(), for_menu=True),
            translate("LayerTreeMenu", "Publish to GeoServer…"),
        )
        if self._connected_dialog() is None:
            reason = translate(
                "LayerTreeMenu", "Not connected. Open GeoServer Manager first"
            )
            for action in (push, pull, publish):
                action.setEnabled(False)
                action.setToolTip(reason)
            submenu.addSeparator()
            connect = submenu.addAction(
                icon("plugin", submenu.palette(), for_menu=True),
                translate("LayerTreeMenu", "Open GeoServer Manager to connect…"),
            )
            if self._open_dialog is None:
                connect.setEnabled(False)
            else:
                connect.triggered.connect(lambda: self._open_dialog())
            return
        push.triggered.connect(lambda: self.push_style(layer))
        pull.triggered.connect(lambda: self.apply_style(layer))
        publish.triggered.connect(lambda: self.publish(layer))

    # -- Which server layer is this? -------------------------------------------

    @staticmethod
    def server_layer_from_source(layer, base_url):
        """'workspace:name' when the layer was loaded from *this* GeoServer.

        A layer the plugin (or QGIS's browser) added carries the answer in its
        data source: the WFS `typename`, or the WMS/WMTS `layers` parameter.
        Only trusted when the source's host is the configured server, so a
        layer from another GeoServer does not name a target here. Pure.
        """
        source = layer.source()
        if layer.providerType().casefold() == "wfs":
            uri = QgsDataSourceUri(source)
            url, name = uri.param("url"), uri.param("typename")
        else:
            params = parse_qs(source, keep_blank_values=True)
            url = (params.get("url") or [""])[0]
            name = (params.get("layers") or [""])[0]
        if ":" not in name or not url:
            return None
        if urlparse(url).netloc.casefold() != urlparse(base_url).netloc.casefold():
            return None
        return name

    @staticmethod
    def matching_server_layers(layer_name, server_layers):
        """The qualified server layers named like this project layer.

        Case-insensitive, and a "workspace:" prefix on either side is ignored:
        the same rule as LayerTabMixin._matching_project_layer, the other way
        round. Pure.
        """
        wanted = layer_name.split(":")[-1].casefold()
        return [
            name
            for name in server_layers
            if ":" in name and name.split(":")[-1].casefold() == wanted
        ]

    def _server_layers(self, dlg):
        """Every published layer's qualified name, in one GET.

        TODO(#50): the facade has no get_layers() and RestEndpoints no path for
        GeoServer's layer list (its layers() / layer() are GeoWebCache's), so
        this GETs /rest/layers.json like StyleTabMixin._legend_layer does.
        """
        base = dlg.gs.rest_service.rest_endpoints.base_url
        payload = dlg._raw_rest("get", f"{base}/layers.json").json()
        return [dlg._name_of(e) for e in dlg._unwrap(payload, "layers", "layer")]

    def _candidates(self, layer, dlg):
        """Qualified names this project layer may stand for; None if the
        server could not be asked (already reported)."""
        known = self.server_layer_from_source(layer, dlg.gs.url)
        if known:
            return [known]
        ok, names = self._run(
            dlg,
            lambda: self._server_layers(dlg),
            translate("LayerTreeMenu", "Could not list the layers of the server"),
        )
        if not ok:
            return None
        return self.matching_server_layers(layer.name(), names)

    def _target(self, layer, dlg, title):
        """The server layer to act on, asking when several match; None when
        there is none to act on (said in the message bar) or the user gave up."""
        candidates = self._candidates(layer, dlg)
        if candidates is None:
            return None
        if not candidates:
            self._say(
                translate(
                    "LayerTreeMenu",
                    "No layer on the server is named like '{}'. Publish it "
                    "first, from the Layers tab.",
                ).format(layer.name()),
                Qgis.MessageLevel.Warning,
            )
            return None
        if len(candidates) == 1:
            return candidates[0]
        form = ResourceFormDialog(
            title=title,
            description=translate(
                "LayerTreeMenu", "Several layers on the server are named like '{}'."
            ).format(layer.name()),
            fields=[
                {
                    "key": "target",
                    "label": translate("LayerTreeMenu", "GeoServer layer"),
                    "type": "combo",
                    "options": candidates,
                    "default": candidates[0],
                    "required": True,
                }
            ],
            parent=self.iface.mainWindow(),
            ok_label=translate("LayerTreeMenu", "Continue"),
        )
        if form.exec() != QDialog.DialogCode.Accepted:
            return None
        return form.get_values().get("target") or candidates[0]

    # -- Push --------------------------------------------------------------------

    def push_style(self, layer):
        """Upload the layer's symbology as the matching server layer's style."""
        dlg = self._connected_dialog()
        if dlg is None:
            return self._say_not_connected()
        title = translate(
            "LayerTreeMenu", "Push the style of '{}' to GeoServer"
        ).format(layer.name())
        target = self._target(layer, dlg, title)
        if target is None:
            return None
        workspace, name = target.split(":", 1)
        form = ResourceFormDialog(
            title=title,
            description=translate(
                "LayerTreeMenu",
                "The symbology of '{}' is exported as SLD and uploaded to workspace "
                "'{}' as the style of layer '{}'. A style of that name there is "
                "replaced, which is how you push a change you just made in QGIS.",
            ).format(layer.name(), workspace, name),
            fields=[
                {
                    "key": "style",
                    "label": translate("LayerTreeMenu", "Style name"),
                    "type": "text",
                    "default": geoserver_name(name),
                    "required": True,
                },
                {
                    "key": "set_default",
                    "label": translate(
                        "LayerTreeMenu", "Make it the layer's default style"
                    ),
                    "type": "checkbox",
                    "default": True,
                },
            ],
            parent=self.iface.mainWindow(),
            ok_label=translate("LayerTreeMenu", "Upload"),
        )
        if form.exec() != QDialog.DialogCode.Accepted:
            return None
        values = form.get_values()

        # The export reads a live QGIS layer: GUI thread, before any request.
        ok, sld = self._run(
            dlg,
            lambda: layer_to_sld(layer),
            translate("LayerTreeMenu", "Could not export the symbology of '{}'").format(
                layer.name()
            ),
        )
        if not ok:
            return None
        style_name = geoserver_name(values["style"])
        ok, pushed = self._run(
            dlg,
            lambda: dlg._push_qgis_style(
                style_name, workspace, sld, name, values["set_default"]
            ),
            translate("LayerTreeMenu", "Failed to upload the style of '{}'").format(
                layer.name()
            ),
        )
        if ok and not pushed:
            # The style exists and the user chose to keep it (the dialog asked).
            self._say(
                translate("LayerTreeMenu", "Style '{}' left as it is.").format(
                    style_name
                ),
                Qgis.MessageLevel.Info,
            )
        elif ok:
            self._say(
                (
                    translate(
                        "LayerTreeMenu", "'{}' on GeoServer now uses the style of '{}'."
                    ).format(target, layer.name())
                    if values["set_default"]
                    else translate(
                        "LayerTreeMenu", "Style '{}' uploaded to workspace '{}'."
                    ).format(style_name, workspace)
                ),
                Qgis.MessageLevel.Success,
            )
        return None

    # -- Pull --------------------------------------------------------------------

    @staticmethod
    def _layer_styles(dlg, workspace, name):
        """The server layer's styles, default first, as qualified-or-bare names.

        TODO(#50): the facade has set_default_layer_style() but no get_layer();
        rest_service.get_layer() answers a Layer model (a dict is tolerated
        too, in case that changes).
        """
        layer = dlg._check(dlg.gs.rest_service.get_layer(workspace, name))
        default = getattr(layer, "default_style_name", None)
        others = getattr(layer, "styles", None)
        if isinstance(layer, dict):
            default, others = layer.get("defaultStyle"), layer.get("styles")
        if isinstance(default, dict):
            default = default.get("name")
        if isinstance(others, dict):
            others = others.get("style") or []
        names = [dlg._name_of(item) for item in (others or [])]
        return ([default] if default else []) + [n for n in names if n != default]

    @staticmethod
    def _sld_body(dlg, style):
        """The SLD of a style named 'workspace:style' or 'style' (global)."""
        workspace, _, name = style.rpartition(":")
        workspace = workspace or None
        definition = dlg._check(dlg.gs.get_style_definition(name, workspace))
        style_format = str((definition or {}).get("format") or "sld").lower()
        if style_format != "sld":
            # QGIS reads SLD only; refuse here rather than let it fail later.
            raise ValueError(
                translate(
                    "LayerTreeMenu", "'{}' is a {} style. QGIS can only read SLD."
                ).format(style, style_format.upper())
            )
        return dlg._style_body(name, workspace, "sld")

    def apply_style(self, layer):
        """Load the matching server layer's style into this project layer."""
        dlg = self._connected_dialog()
        if dlg is None:
            return self._say_not_connected()
        title = translate("LayerTreeMenu", "Apply a GeoServer style to '{}'").format(
            layer.name()
        )
        target = self._target(layer, dlg, title)
        if target is None:
            return None
        workspace, name = target.split(":", 1)
        ok, styles = self._run(
            dlg,
            lambda: self._layer_styles(dlg, workspace, name),
            translate("LayerTreeMenu", "Failed to load the styles of '{}'").format(
                target
            ),
        )
        if not ok:
            return None
        if not styles:
            self._say(
                translate("LayerTreeMenu", "'{}' has no style on the server.").format(
                    target
                ),
                Qgis.MessageLevel.Warning,
            )
            return None
        style = styles[0]
        if len(styles) > 1:
            form = ResourceFormDialog(
                title=title,
                description=translate(
                    "LayerTreeMenu",
                    "'{}' has several styles on the server; the default comes "
                    "first. The style is applied to this project only.",
                ).format(target),
                fields=[
                    {
                        "key": "style",
                        "label": translate("LayerTreeMenu", "Style"),
                        "type": "combo",
                        "options": styles,
                        "default": style,
                        "required": True,
                    }
                ],
                parent=self.iface.mainWindow(),
                ok_label=translate("LayerTreeMenu", "Apply"),
            )
            if form.exec() != QDialog.DialogCode.Accepted:
                return None
            style = form.get_values()["style"]

        ok, sld = self._run(
            dlg,
            lambda: self._sld_body(dlg, style),
            translate("LayerTreeMenu", "Failed to load style '{}'").format(style),
        )
        if not ok:
            return None
        ok, outcome = self._run(
            dlg,
            lambda: apply_sld_to_layer(layer, sld),
            translate("LayerTreeMenu", "Failed to apply '{}' to '{}'").format(
                style, layer.name()
            ),
        )
        if not ok:
            return None
        applied, message = outcome
        layer.triggerRepaint()
        if applied:
            self._say(
                translate(
                    "LayerTreeMenu", "'{}' now uses the GeoServer style '{}'."
                ).format(layer.name(), style),
                Qgis.MessageLevel.Success,
            )
        else:
            # QGIS reads less SLD than it writes; say what it could not take.
            self._say(
                translate(
                    "LayerTreeMenu", "QGIS could not read all of '{}': {}"
                ).format(
                    style, message or translate("LayerTreeMenu", "no detail given")
                ),
                Qgis.MessageLevel.Warning,
            )
        return None

    # -- Publishing ---------------------------------------------------------------

    def publish(self, layer):
        """Open the main dialog's Publish form with this layer as the source.

        The dialog comes up on the Layers tab first. The upload reports its
        progress, its Cancel and its outcome there, and that is where the new
        layer appears; a form over a hidden dialog would report into nothing.
        """
        dlg = self._connected_dialog()
        if dlg is None:
            return self._say_not_connected()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        loaders = [loader for _label, _icon, loader in dlg.TABS]
        dlg.navList.setCurrentRow(loaders.index("_load_layers"))
        dlg._publish_layer(layer=layer)
        return None

    # -- Plumbing ----------------------------------------------------------------

    def _run(self, dlg, fn, failure_message):
        """fn() under a wait cursor. (True, result), or (False, None) once the
        failure is in the message bar and the QGIS log.

        Not the dialog's _run_action: its banners live in a window that may be
        hidden behind QGIS right now.
        """
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return True, fn()
        except Exception as error:  # noqa: BLE001 (anything, reported as text)
            detail = dlg._error_text(error)
            self._say(f"{failure_message}: {detail}", Qgis.MessageLevel.Critical)
            self.log(
                f"{failure_message}: {detail}", log_level=Qgis.MessageLevel.Critical
            )
            return False, None
        finally:
            QApplication.restoreOverrideCursor()

    def _say(self, text, level):
        self.iface.messageBar().pushMessage(__title__, text, level, 8)

    def _say_not_connected(self):
        self._say(
            translate(
                "LayerTreeMenu",
                "Not connected to GeoServer. Open GeoServer Manager and connect first.",
            ),
            Qgis.MessageLevel.Warning,
        )
        return None
