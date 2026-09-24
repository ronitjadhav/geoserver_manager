#! python3  # noqa: E265

"""
Layer Groups tab: list, create, edit, delete layer groups.

Used as a mixin for GeoServerMainDialog. `_layer_uri()` comes from LayerTabMixin
through the shared dialog class; the global-or-workspace scope is `gui.scope`.
"""

from urllib.parse import quote

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_preview import LayerPreviewDialog
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.scope import GLOBAL, PENDING, global_label, scope
from geoserver_manager.toolbelt.payload import bbox_text, text_of, unwrap

# GeoServer's LayerGroupInfo.Mode enum. Spelled out rather than imported from
# geoservercloud.models: the bundled wheels only reach sys.path once the plugin
# has run ensure_dependencies(). test_tab_layergroups asserts it still matches
# LayerGroup.modes.
MODES = ("SINGLE", "OPAQUE_CONTAINER", "NAMED", "CONTAINER", "EO")

# First entry of the layer picker. Picking a layer always *changes* the combo's
# text this way, so the same layer can be appended twice in a row.

# The collection of each layer type's resources, reachable by workspace alone.
_RESOURCE_COLLECTIONS = {
    "VECTOR": "featuretypes",
    "RASTER": "coverages",
    "WMS": "wmslayers",
    "WMTS": "wmtslayers",
}


# Every user-visible string in this file goes through translate() with this
# file's own class as the context. self.tr() cannot: pylupdate extracts it
# under LayerGroupTabMixin, but at runtime self.tr is QObject.tr with the context of the
# *instance's* class, GeoServerMainDialog. QDialog precedes the mixins in the
# MRO, so every lookup would miss. A wrapper function would not be extracted
# at all (pylupdate only understands a literal context), hence the repetition.
translate = QCoreApplication.translate


def _mode_label(mode):
    """GeoServer's web-admin words for a LayerGroupInfo.Mode; the enum when unknown."""
    labels = {
        "SINGLE": translate("LayerGroupTabMixin", "Single"),
        "OPAQUE_CONTAINER": translate("LayerGroupTabMixin", "Opaque Container"),
        "NAMED": translate("LayerGroupTabMixin", "Named Tree"),
        "CONTAINER": translate("LayerGroupTabMixin", "Container Tree"),
        "EO": translate("LayerGroupTabMixin", "Earth Observation Tree"),
    }
    return labels.get(mode, mode)


def _mode_from_label(label):
    """The enum behind a label, or the value itself when it already is one."""
    for mode in MODES:
        if label in (mode, _mode_label(mode)):
            return mode
    return label


class LayerGroupTabMixin:
    """Mixin that adds layer-group methods to the main dialog."""

    # -- Listing ---------------------------------------------------------------

    def _load_layer_groups(self):
        """Arm the Layer Groups tab, then fetch its rows in the background."""
        self._setup_add_button(
            translate("LayerGroupTabMixin", "Create a Layer Group"),
            translate("LayerGroupTabMixin", "Publish several layers as one"),
            self._add_layer_group,
        )
        self._setup_delete_selected_button(self._delete_selected_layer_groups)
        self._name_click_callback = self._show_layer_group_info
        self._extra_click_callbacks = {
            translate("LayerGroupTabMixin", "Workspace"): self._open_workspace_from_row
        }
        self._row_actions = [
            (
                "preview-map",
                translate("LayerGroupTabMixin", "Preview"),
                self._preview_group,
                translate(
                    "LayerGroupTabMixin",
                    "The group on a map of its own, with feature info on a click; "
                    "the project is not touched",
                ),
            ),
            (
                "add-to-qgis",
                translate("LayerGroupTabMixin", "Add to QGIS"),
                self._add_group_to_qgis,
                translate(
                    "LayerGroupTabMixin",
                    "Add the group to this QGIS project as one WMS layer",
                ),
            ),
            (
                "preview-browser",
                translate("LayerGroupTabMixin", "Preview in a browser"),
                self._preview_group_in_browser,
                translate(
                    "LayerGroupTabMixin",
                    "Preview in a browser: GeoServer's own OpenLayers page. A "
                    "secured server will ask the browser to log in.",
                ),
            ),
            (
                "delete",
                translate("LayerGroupTabMixin", "Delete"),
                self._delete_layer_group,
                translate(
                    "LayerGroupTabMixin",
                    "Delete: remove the group; its layers stay (asks first).",
                ),
            ),
        ]
        self._setup_table(
            [
                translate("LayerGroupTabMixin", "Name"),
                translate("LayerGroupTabMixin", "Workspace"),
                translate("LayerGroupTabMixin", "Mode"),
                translate("LayerGroupTabMixin", "Layers"),
                self.actions_column_label(),
            ]
        )
        self._row_detail = lambda row: tuple(
            str(cell) for cell in self._group_summary(row[0], row[1])
        )
        self._detail_columns = (2, 3)
        self._start_load(
            translate("LayerGroupTabMixin", "Failed to load layer groups"),
            self._fetch_layer_group_rows,
        )

    def _fetch_layer_group_rows(self, task=None):
        """(rows, failures) for the Layer Groups table. Runs in a worker thread."""
        groups = [(name, GLOBAL) for name in self._global_group_names()]
        failures = []
        ws_names = self._get_workspace_names()
        for ws_name, (names, error) in zip(
            ws_names,
            self._fan_out(
                lambda ws: self._fetch_list(self.gs.get_layer_groups, ws),
                ws_names,
                task,
            ),
        ):
            if error:
                failures.append((ws_name, error))
                continue
            groups.extend((self._name_of(group), ws_name) for group in names)

        # Mode and size are only in the group itself: one GET per group, for
        # the page shown (#58). A group that cannot be read keeps its row.
        rows = [[name, ws_label, PENDING, PENDING] for name, ws_label in groups]
        return rows, failures

    def _global_group_names(self):
        """Names of the layer groups that live outside any workspace.

        TODO(#50): upstream: every layer-group call in the library takes a
        workspace_name, so groups in the global scope cannot be reached at all
        (GeoServer's own demo data has three). Workaround: GET the collection.
        """
        payload = self._raw_rest("get", self._groups_path(None)).json()
        return sorted(
            self._name_of(group)
            for group in self._unwrap(payload, "layerGroups", "layerGroup")
        )

    def _group_summary(self, name, workspace_label):
        """(mode, number of layers) for the list view. Raises on HTTP errors."""
        detail = self._group_detail(name, scope(workspace_label))
        return _mode_label(detail.get("mode", "")), len(self._group_layers(detail))

    # -- One group -------------------------------------------------------------

    def _group_detail(self, name, workspace_name):
        """One layer group, as GeoServer stores it.

        TODO(#50): upstream: get_layer_group() exists, but its model drops the
        abstract (GeoServer writes "abstractTxt" while the model reads
        "abstract") and the "@type" that tells a nested group from a layer, and
        it has no global scope. Workaround: GET the layer-group path.
        """
        payload = self._raw_rest("get", self._group_path(name, workspace_name)).json()
        return payload.get("layerGroup") or {}

    def _groups_path(self, workspace_name):
        """REST path of the layer-group collection, global or in a workspace."""
        endpoints = self.gs.rest_service.rest_endpoints
        if workspace_name:
            return endpoints.layergroups(workspace_name)
        return f"{endpoints.base_url}/layergroups.json"

    def _group_path(self, name, workspace_name):
        """REST path of one layer group, global or in a workspace."""
        endpoints = self.gs.rest_service.rest_endpoints
        # quote(): a "/", "?" or "#" in a name would otherwise change the path
        if workspace_name:
            return endpoints.layergroup(
                quote(workspace_name, safe=""), quote(name, safe="")
            )
        return f"{endpoints.base_url}/layergroups/{quote(name, safe='')}.json"

    @classmethod
    def _group_layers(cls, detail):
        """The group's publishables in drawing order, as (name, @type) pairs."""
        return [
            (item.get("name", ""), item.get("@type", "layer"))
            for item in unwrap(detail, "publishables", "published")
            if isinstance(item, dict)
        ]

    @classmethod
    def _group_styles(cls, detail):
        """The style of each publishable; "" where the layer's default is used."""
        styles = unwrap(detail, "styles", "style")
        return [
            style.get("name", "") if isinstance(style, dict) else (style or "")
            for style in styles
        ]

    # -- View and edit ---------------------------------------------------------

    @classmethod
    def _group_form_values(cls, detail, name, workspace_label):
        """Prefill for the edit dialog, in the form's own layer syntax. Pure."""
        styles = cls._group_styles(detail)
        rows = [
            [layer_name, styles[index] if index < len(styles) else ""]
            for index, (layer_name, _kind) in enumerate(cls._group_layers(detail))
        ]

        return {
            "name": name,
            "workspace": workspace_label,
            "mode": _mode_label(detail.get("mode", "")),
            "title": text_of(detail.get("internationalTitle") or detail.get("title")),
            # GeoServer stores the abstract under "abstractTxt".
            "abstract": text_of(
                detail.get("internationalAbstract") or detail.get("abstractTxt")
            ),
            # A group GeoServer has never re-saved has no flags: both default on.
            "enabled": detail.get("enabled", True) is not False,
            "advertised": detail.get("advertised", True) is not False,
            "layers": rows,
            "root_layer": (detail.get("rootLayer") or {}).get("name", ""),
            "root_style": (detail.get("rootLayerStyle") or {}).get("name", ""),
            "bounds": bbox_text(detail.get("bounds")),
        }

    def _show_layer_group_info(self, row_data):
        """Open a layer group to edit it."""
        name, workspace_label = row_data[0], row_data[1]
        fetched = self._fetch(
            lambda: (
                self._group_detail(name, scope(workspace_label)),
                self._all_layer_names(),
                self._all_group_names(),
                self._style_choices(scope(workspace_label)),
            ),
            translate("LayerGroupTabMixin", "Failed to load layer group '{}'").format(
                name
            ),
        )
        if fetched is None:
            return
        detail, layer_names, group_names, style_names = fetched
        before = self._group_form_values(detail, name, workspace_label)
        own = f"{scope(workspace_label)}:{name}" if scope(workspace_label) else name

        dlg = ResourceFormDialog(
            title=translate("LayerGroupTabMixin", "Layer Group '{}'").format(name),
            description=translate(
                "LayerGroupTabMixin",
                "GeoServer cannot rename a layer group. When the layers change, "
                "the plugin recomputes the group's bounds.",
            ),
            fields=self._group_fields(
                [workspace_label],
                self._same_workspace(
                    scope(workspace_label),
                    layer_names + [group for group in group_names if group != own],
                ),
                self._same_workspace(scope(workspace_label), layer_names),
                edit_mode=True,
                styles=style_names,
            ),
            values=before,
            parent=self,
            ok_label=translate("LayerGroupTabMixin", "Save"),
            validate=lambda after: self._check_group_rows(
                after, scope(workspace_label), layer_names, group_names
            ),
        )
        self._wire_group_form(dlg)
        for key, international in (
            ("title", "internationalTitle"),
            ("abstract", "internationalAbstract"),
        ):
            if detail.get(international):
                # Shown as "en: …; fr: …", which a save would store as the
                # plain title, in every language. Kept read-only instead.
                widget = dlg.get_widget(key)
                widget.setReadOnly(True)
                widget.setToolTip(
                    translate(
                        "LayerGroupTabMixin",
                        "Translated in several languages: edit it in GeoServer's "
                        "web interface.",
                    )
                )
        if detail.get("mode") == "EO":
            # GeoServer refuses every way of clearing the root layer (measured
            # on 2.28.5), so an Earth Observation group cannot change mode.
            dlg.get_widget("mode").setEnabled(False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        after = dlg.get_values()
        saved = self._fetch(
            lambda: self._save_layer_group(
                name, scope(workspace_label), before, after, layer_names, group_names
            ),
            translate("LayerGroupTabMixin", "Failed to update layer group '{}'").format(
                name
            ),
        )
        if saved:
            self.show_success_message(
                translate("LayerGroupTabMixin", "Layer group '{}' saved.").format(name)
            )
            self._load_layer_groups()

    @staticmethod
    def _group_changes(before, after):
        """(body, layers changed) for a partial PUT of the edited fields. Pure.

        The layer list is only compared here: it needs the server's names to
        become publishables, see _save_layer_group.
        """
        body = {}
        for key, target in (
            ("title", "title"),
            ("abstract", "abstractTxt"),
            ("enabled", "enabled"),
            ("advertised", "advertised"),
        ):
            if after.get(key) != before.get(key):
                body[target] = after.get(key)
        if _mode_from_label(after["mode"]) != _mode_from_label(before["mode"]):
            body["mode"] = _mode_from_label(after["mode"])
        before_layers = LayerGroupTabMixin._parse_group_layers(before["layers"], None)
        after_layers = LayerGroupTabMixin._parse_group_layers(after["layers"], None)
        return body, before_layers != after_layers

    def _save_layer_group(
        self, name, workspace_name, before, after, known_layers, known_groups
    ):
        """PUT what changed. False when nothing did. Runs in a worker thread.

        TODO(#50): no update_layer_group() in the library (row 57). GeoServer
        merges a partial PUT, but a new layer list needs a style per entry,
        and it keeps the old bounds, so they are recomputed here.
        """
        body, layers_changed = self._group_changes(before, after)
        mode = _mode_from_label(after["mode"])
        if layers_changed:
            published, styles = self._group_publishables(
                after["layers"], workspace_name, known_layers, known_groups
            )
            body["publishables"] = {"published": published}
            # A new list with fewer styles than entries is refused.
            body["styles"] = {"style": [{"name": s} if s else "" for s in styles]}
            body["bounds"] = self._group_bounds(published)
        if mode == "EO" and (
            layers_changed
            or "mode" in body
            or (after["root_layer"], after["root_style"])
            != (before["root_layer"], before["root_style"])
        ):
            body.update(self._eo_root(after, known_layers))
        if not body:
            return False
        self._raw_rest(
            "put", self._group_path(name, workspace_name), json={"layerGroup": body}
        )
        return True

    @staticmethod
    def _same_workspace(workspace_name, names):
        """The names a group in this workspace may hold: all, for a global one."""
        if not workspace_name:
            return list(names)
        return [name for name in names if name.startswith(f"{workspace_name}:")]

    def _group_publishables(self, rows, workspace_name, known_layers, known_groups):
        """The layer list as GeoServer publishables, and the styles beside it.

        GeoServer drops a name it does not know, answering 200, so every line
        is checked here. A name is a layer first, then a group.
        ponytail: a group named like a layer cannot be listed; GeoServer allows
        it, add a marker to the syntax when someone needs it.
        """
        layers, styles = self._parse_group_layers(rows, workspace_name)
        if not layers:
            raise ValueError(
                translate("LayerGroupTabMixin", "List at least one layer.")
            )
        published = []
        for layer in layers:
            if workspace_name and not layer.startswith(f"{workspace_name}:"):
                # GeoServer answers a bare 500 for it, after the form closed.
                raise ValueError(
                    translate(
                        "LayerGroupTabMixin",
                        "'{}' is in another workspace. A group in '{}' can only "
                        "hold that workspace's layers and groups.",
                    ).format(layer, workspace_name)
                )
            if known_layers is None or layer in known_layers:
                published.append({"@type": "layer", "name": layer})
            elif layer in known_groups or layer.partition(":")[2] in known_groups:
                # A global group is listed bare, even from a workspace group.
                if layer not in known_groups:
                    layer = layer.partition(":")[2]
                published.append({"@type": "layerGroup", "name": layer})
            else:
                raise ValueError(
                    translate(
                        "LayerGroupTabMixin",
                        "No layer or group named '{}' on the server. Pick it from "
                        "the list, or qualify it as workspace:layer.",
                    ).format(layer)
                )
        self._check_styles_exist(styles)
        return published, styles

    def _eo_root(self, values, known_layers):
        """rootLayer and rootLayerStyle of an Earth Observation group.

        GeoServer requires both. A blank style takes the root layer's default.
        """
        root = (values.get("root_layer") or "").strip()
        if not root:
            raise ValueError(
                translate(
                    "LayerGroupTabMixin",
                    "An Earth Observation group needs a root layer.",
                )
            )
        if known_layers is not None and root not in known_layers:
            raise ValueError(
                translate(
                    "LayerGroupTabMixin", "No layer named '{}' on the server."
                ).format(root)
            )
        style = (values.get("root_style") or "").strip() or self._layer_summary(root)[2]
        if style == "-":  # _layer_summary's "none", a cascaded layer's case
            raise ValueError(
                translate(
                    "LayerGroupTabMixin",
                    "Root layer '{}' has no default style: type one.",
                ).format(root)
            )
        self._check_styles_exist([style])
        return {
            "rootLayer": {"@type": "layer", "name": root},
            "rootLayerStyle": {"name": style},
        }

    def _group_bounds(self, published):
        """The union of the publishables' extents, in EPSG:4326.

        GeoServer computes it on a create but never on a PUT (a new layer list
        keeps the old box, and "bounds": null stores a zero one). Layers give
        their lon/lat box; a nested group gives its own, in any CRS.
        """
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        total = None
        for item in published:
            if item["@type"] == "layerGroup":
                workspace_name, _, bare = item["name"].rpartition(":")
                box = self._group_detail(bare, workspace_name or None).get("bounds")
            else:
                box = self._layer_lonlat_box(item["name"])
            rect = self._box_in(box or {}, wgs84)
            if rect is None:
                continue
            if total is None:
                total = rect
            else:
                total.combineExtentWith(rect)
        if total is None:
            raise ValueError(
                translate(
                    "LayerGroupTabMixin",
                    "None of the layers has bounds, so the group would have none.",
                )
            )
        return {
            "minx": total.xMinimum(),
            "miny": total.yMinimum(),
            "maxx": total.xMaximum(),
            "maxy": total.yMaximum(),
            "crs": "EPSG:4326",
        }

    def _layer_lonlat_box(self, qualified_name):
        """A layer's latLonBoundingBox, read from its resource by workspace."""
        layer = self._raw_rest("get", self._layers_url(qualified_name)).json()
        layer = layer.get("layer") or {}
        collection = _RESOURCE_COLLECTIONS.get(layer.get("type"), "featuretypes")
        workspace_name, _, _ = qualified_name.rpartition(":")
        resource = (layer.get("resource") or {}).get("name") or qualified_name
        path = "{}/workspaces/{}/{}/{}.json".format(
            self.gs.rest_service.rest_endpoints.base_url,
            quote(workspace_name, safe=""),
            collection,
            quote(resource.rpartition(":")[2], safe=""),
        )
        payload = self._raw_rest("get", path).json()
        body = next(iter(payload.values()), {}) if isinstance(payload, dict) else {}
        return body.get("latLonBoundingBox")

    @staticmethod
    def _box_in(box, target):
        """A GeoServer bbox as a QgsRectangle in the target CRS; None if empty."""
        try:
            rect = QgsRectangle(
                float(box["minx"]),
                float(box["miny"]),
                float(box["maxx"]),
                float(box["maxy"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if rect.isEmpty():
            return None
        crs = box.get("crs")
        crs = crs.get("$") if isinstance(crs, dict) else crs
        source = QgsCoordinateReferenceSystem(crs or "EPSG:4326")
        if not source.isValid() or source == target:
            return rect
        return QgsCoordinateTransform(
            source, target, QgsProject.instance()
        ).transformBoundingBox(rect)

    # -- Create ----------------------------------------------------------------

    def _group_fields(
        self, workspace_names, pickable, root_layers=None, edit_mode=False, styles=()
    ):
        """Field definitions for the create and the edit dialog.

        :param pickable: what the picker offers: layers, then groups.
        :param root_layers: the layers an Earth Observation root can be;
            what the picker offers when not given.
        """
        fields = [
            {
                "key": "name",
                "label": translate("LayerGroupTabMixin", "Name"),
                "type": "text",
                "required": not edit_mode,
                "read_only": edit_mode,
            },
            {
                "key": "workspace",
                "label": translate("LayerGroupTabMixin", "Workspace"),
                "type": "text" if edit_mode else "combo",
                "read_only": edit_mode,
                "options": [(global_label(), GLOBAL)] + list(workspace_names),
                "help": translate(
                    "LayerGroupTabMixin",
                    "A global group can mix layers from several workspaces",
                ),
            },
            {
                "key": "mode",
                "label": translate("LayerGroupTabMixin", "Mode"),
                "type": "combo",
                "options": [_mode_label(mode) for mode in MODES],
                "default": _mode_label("SINGLE"),
                "help": translate(
                    "LayerGroupTabMixin",
                    "Single publishes the group as one layer; Opaque Container is "
                    "the same but hides its layers from the capabilities; Named "
                    "Tree also keeps the layers addressable on their own; Container "
                    "Tree and Earth Observation Tree only group them",
                ),
            },
            {
                "key": "title",
                "label": translate("LayerGroupTabMixin", "Title"),
                "type": "text",
            },
            {
                "key": "abstract",
                "label": translate("LayerGroupTabMixin", "Abstract"),
                "type": "textarea",
            },
            {
                "key": "layers",
                "label": translate("LayerGroupTabMixin", "Layers"),
                "type": "table",
                "ordered": True,
                "required": True,
                "wide": True,
                "group": translate("LayerGroupTabMixin", "Layers"),
                "choices": list(pickable),
                "columns": [
                    {"label": translate("LayerGroupTabMixin", "Layer or group")},
                    {
                        "label": translate("LayerGroupTabMixin", "Style"),
                        "type": "combo",
                        # Blank: the layer's own default style.
                        "options": [""] + list(styles),
                        "placeholder": translate("LayerGroupTabMixin", "(default)"),
                    },
                ],
                "help": translate(
                    "LayerGroupTabMixin",
                    "In drawing order: the first row is drawn first, at the "
                    "bottom. A blank style is the layer's own default.",
                ),
            },
            {
                "key": "root_layer",
                "label": translate("LayerGroupTabMixin", "Root layer"),
                "type": "combo",
                # No value: Save then says a root layer is needed.
                "options": [(translate("LayerGroupTabMixin", "(pick a layer)"), "")]
                + list(pickable if root_layers is None else root_layers),
                "visible": False,
                "group": translate("LayerGroupTabMixin", "Layers"),
                "help": translate(
                    "LayerGroupTabMixin",
                    "What an Earth Observation group draws when it is requested "
                    "as a whole",
                ),
            },
            {
                "key": "root_style",
                "label": translate("LayerGroupTabMixin", "Root layer style"),
                "type": "text",
                "visible": False,
                "group": translate("LayerGroupTabMixin", "Layers"),
                "placeholder": translate("LayerGroupTabMixin", "Its default style"),
            },
        ]
        if edit_mode:
            fields[3:3] = [
                {
                    "key": "enabled",
                    "label": translate("LayerGroupTabMixin", "Enabled"),
                    "type": "checkbox",
                    "default": True,
                },
                {
                    "key": "advertised",
                    "label": translate("LayerGroupTabMixin", "Advertised"),
                    "type": "checkbox",
                    "default": True,
                    "help": translate(
                        "LayerGroupTabMixin",
                        "Listed in the capabilities. Off, the group is still "
                        "served to whoever names it.",
                    ),
                },
            ]
            fields.append(
                {
                    "key": "bounds",
                    "label": translate("LayerGroupTabMixin", "Bounds"),
                    "type": "text",
                    "read_only": True,
                }
            )
        return fields

    def _wire_group_form(self, dlg):
        """Show the root fields for an Earth Observation group only."""

        def show_root(label):
            for key in ("root_layer", "root_style"):
                dlg.set_field_visible(key, _mode_from_label(label) == "EO")

        mode = dlg.get_widget("mode")
        mode.currentTextChanged.connect(show_root)
        show_root(mode.currentText())

    def _all_group_names(self):
        """Every group's name as a publishable spells it: bare when global,
        "workspace:group" otherwise. Raises on HTTP errors."""
        names = list(self._global_group_names())
        workspaces = self._get_workspace_names()
        # One workspace that cannot be listed (a name like "w#x") used to fail
        # Create and Edit for every group; now it only loses its own groups.
        for ws_name, (groups, error) in zip(
            workspaces,
            self._fan_out(
                lambda ws: self._fetch_list(
                    self.gs.get_layer_groups, quote(ws, safe="")
                ),
                workspaces,
            ),
        ):
            if error is None:
                names.extend(f"{ws_name}:{self._name_of(group)}" for group in groups)
        return names

    def _add_layer_group(self):
        """Create a layer group from picked or pasted layer names."""
        fetched = self._fetch(
            lambda: (
                self._get_workspace_names(),
                self._all_layer_names(),
                self._all_group_names(),
                self._style_choices(None),
            ),
            translate("LayerGroupTabMixin", "Failed to load the workspaces and layers"),
        )
        if fetched is None:
            return
        workspace_names, layer_names, group_names, style_names = fetched

        dlg = ResourceFormDialog(
            title=translate("LayerGroupTabMixin", "Create a Layer Group"),
            description=translate(
                "LayerGroupTabMixin",
                "Publish several layers as one. GeoServer computes the group's "
                "bounds from the layers it contains.",
            ),
            fields=self._group_fields(
                workspace_names,
                layer_names + group_names,
                layer_names,
                styles=style_names,
            ),
            parent=self,
            ok_label=translate("LayerGroupTabMixin", "Create"),
            validate=self._form_check(
                lambda values: self._check_new_layer_group(
                    values, layer_names, group_names
                )
            ),
        )
        self._wire_group_form(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._wait_for_save(
                lambda: self._create_layer_group_from_values(
                    values, layer_names, group_names
                )
            ),
            translate("LayerGroupTabMixin", "Failed to create layer group '{}'").format(
                values["name"]
            ),
        ):
            self.show_success_message(
                translate("LayerGroupTabMixin", "Layer group '{}' created.").format(
                    values["name"]
                )
            )
            self._load_layer_groups()

    @staticmethod
    def _parse_group_layers(rows, workspace_name):
        """The form's rows as (layers, styles), in drawing order.

        A row is [layer, style]; the styles are parallel to the layers, ""
        where the layer keeps its own default style, and a bare layer name
        takes the group's workspace.
        """
        layers, styles = [], []
        for row in rows or ():
            name = (row[0] or "").strip()
            if not name:
                continue
            if ":" not in name and workspace_name:
                name = f"{workspace_name}:{name}"
            layers.append(name)
            styles.append((row[1] if len(row) > 1 else "").strip())
        return layers, styles

    def _check_styles_exist(self, styles):
        """Refuse a style GeoServer would silently ignore.

        A layer group POST naming a style that does not exist answers 201 with
        the style simply dropped, so the group would quietly render with the
        layers' default styles and the plugin would report success.
        """
        for reference in sorted({style for style in styles if style}):
            workspace_name, _, name = reference.rpartition(":")
            if not self._resource_exists(
                self.gs.get_style_definition, name, workspace_name or None
            ):
                raise ValueError(
                    translate(
                        "LayerGroupTabMixin", "No style '{}' on the server."
                    ).format(reference)
                )

    def _check_group_rows(self, values, workspace_name, known_layers, known_groups):
        """Refuse layer rows GeoServer would drop or refuse. Pure: the form
        runs it before it closes."""
        self._group_publishables(
            values["layers"], workspace_name, known_layers, known_groups
        )
        if _mode_from_label(values["mode"]) == "EO":
            self._eo_root(values, known_layers)

    def _check_new_layer_group(self, values, known_layers, known_groups):
        """The rows, a name a URL would eat, a name taken. Reads only."""
        name, workspace_name = values["name"], scope(values["workspace"])
        self._require_safe_name(name)
        self._check_group_rows(values, workspace_name, known_layers, known_groups)
        if self.gs.rest_service.resource_exists(self._group_path(name, workspace_name)):
            raise ValueError(
                translate(
                    "LayerGroupTabMixin", "Layer group '{}' already exists in {}."
                ).format(name, values["workspace"] or GLOBAL)
            )

    def _create_layer_group_from_values(
        self, values, known_layers=None, known_groups=()
    ):
        """POST a new layer group, refusing to overwrite an existing one.

        :param known_layers: the server's layer names, as the form's picker
            listed them; a typed line naming none of them, or none of
            known_groups, is refused here, by line, instead of GeoServer
            dropping it.

        TODO(#50): upstream: create_layer_group() cannot express any of this:
        it has no global scope, it qualifies every layer with the group's own
        workspace (so no group spanning workspaces, and no nested group), it
        replaces the bounds with a world bbox read from a three-entry EPSG
        table (a KeyError for any other code), it sends the abstract under
        "abstract", which GeoServer silently drops, and it has no root layer.
        """
        name = values["name"]
        workspace_name = scope(values["workspace"])
        self._check_new_layer_group(values, known_layers, known_groups)
        published, styles = self._group_publishables(
            values["layers"], workspace_name, known_layers, known_groups
        )
        mode = _mode_from_label(values["mode"])
        root = self._eo_root(values, known_layers) if mode == "EO" else {}

        group = {"name": name, "mode": mode, "publishables": {"published": published}}
        group.update(root)
        if workspace_name:
            group["workspace"] = {"name": workspace_name}
        if values.get("title"):
            group["title"] = values["title"]
        if values.get("abstract"):
            group["abstractTxt"] = values["abstract"]
        if any(styles) or any(item["@type"] != "layer" for item in published):
            # "" is how GeoServer itself spells "this layer's own default style".
            # With a nested group and no styles, GeoServer fails (HTTP 500).
            group["styles"] = {
                "style": [{"name": style} if style else "" for style in styles]
            }
        # No "bounds": GeoServer then computes the union of the layers' extents.
        self._raw_rest(
            "post", self._groups_path(workspace_name), json={"layerGroup": group}
        )

    # -- Add to QGIS -----------------------------------------------------------

    def _add_group_to_qgis(self, row_data):
        """Add the group to the current QGIS project as one WMS layer.

        WMS only: a group has no feature type to fetch over WFS, and it reaches
        GeoWebCache only once someone caches it there.
        """
        name, workspace_name = row_data[0], scope(row_data[1])
        qualified = f"{workspace_name}:{name}" if workspace_name else name

        def build():
            settings = self.plg_settings.get_plg_settings()
            uri, provider = self._layer_uri(
                "WMS",
                settings.geoserver_url,
                qualified,
                settings.geoserver_auth_cfg_id,
            )
            # The constructor reads the capabilities: a request, so a worker's.
            layer = QgsRasterLayer(uri, name, provider)
            if not layer.isValid():
                raise RuntimeError(
                    layer.error().message()
                    or translate("LayerGroupTabMixin", "layer is not valid")
                )
            return layer

        layer = self._fetch(
            build,
            translate("LayerGroupTabMixin", "Could not add '{}' to QGIS").format(name),
        )
        if layer is not None:
            QgsProject.instance().addMapLayer(layer)
            self.show_success_message(
                translate(
                    "LayerGroupTabMixin", "'{}' added to the project as WMS."
                ).format(name)
            )

    def _preview_group(self, row_data):
        """Show the group on a map of its own, like the Layers tab's Preview.

        Nothing reaches the project. The map opens on the group's bounds,
        which GeoServer may store in a projected CRS: they are reprojected.
        """
        name, workspace_name = row_data[0], scope(row_data[1])
        qualified = f"{workspace_name}:{name}" if workspace_name else name
        detail = self._fetch(
            lambda: self._group_detail(name, workspace_name),
            translate("LayerGroupTabMixin", "Failed to load layer group '{}'").format(
                name
            ),
        )
        if detail is None:
            return
        rect = self._box_in(
            detail.get("bounds") or {}, QgsCoordinateReferenceSystem("EPSG:4326")
        )
        bbox = (
            (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())
            if rect is not None
            else None
        )

        def build():
            settings = self.plg_settings.get_plg_settings()
            uri, provider = self._layer_uri(
                "WMS", settings.geoserver_url, qualified, settings.geoserver_auth_cfg_id
            )
            # An invalid layer is not an error here: the window explains it.
            return QgsRasterLayer(uri, qualified, provider)

        layer = self._fetch(
            build,
            translate(
                "LayerGroupTabMixin", "Could not build the preview of '{}'"
            ).format(name),
        )
        if layer is not None:
            LayerPreviewDialog(qualified, layer, bbox, parent=self).show()

    def _preview_group_in_browser(self, row_data):
        """Open GeoServer's own preview of the group, on its bounds.

        The URL builder is LayerTabMixin._preview_url, reached through the
        dialog class like _layer_uri; a global group has no workspace in the
        path and no prefix on its name.
        """
        name, workspace_name = row_data[0], scope(row_data[1])
        detail = self._fetch(
            lambda: self._group_detail(name, workspace_name),
            translate("LayerGroupTabMixin", "Failed to load layer group '{}'").format(
                name
            ),
        )
        if detail is None:
            return
        bbox, srs = self._bbox_from(detail.get("bounds"))
        qualified = f"{workspace_name}:{name}" if workspace_name else name
        self._open_in_browser(
            self._preview_url(
                self.plg_settings.get_plg_settings().geoserver_url,
                qualified,
                bbox,
                srs,
                workspace=workspace_name,
            )
        )

    # -- Delete ----------------------------------------------------------------

    def _delete_layer_group(self, row_data):
        """Delete a single layer group after confirmation."""
        self._delete_selected_layer_groups([row_data])

    def _delete_selected_layer_groups(self, selected_rows):
        """Delete one or more layer groups after confirmation."""
        self._delete_many(
            translate("LayerGroupTabMixin", "layer group"),
            [
                (
                    # As the Layers tab names them; a global group has no prefix.
                    f"{scope(row[1])}:{row[0]}" if scope(row[1]) else row[0],
                    lambda name=row[0], ws=scope(row[1]): self._do_delete_group(
                        name, ws
                    ),
                )
                for row in selected_rows
            ],
            self._load_layer_groups,
            lambda n: translate("LayerGroupTabMixin", "%n layer group(s)", None, n),
            cascade=translate(
                "LayerGroupTabMixin",
                "Only the group goes away. The layers it published stay. "
                "GeoServer refuses if another layer group contains this one.",
            ),
        )

    def _do_delete_group(self, name, workspace_name):
        """DELETE one layer group; the library covers the workspace scope only.

        TODO(#50): see _global_group_names; delete_layer_group() requires a
        workspace_name, so a global group needs the raw path.
        """
        if workspace_name:
            # The library interpolates the names into the path as they are, so
            # "a#b" would delete "a": hand it the quoted segments.
            self._check(
                self.gs.delete_layer_group(
                    quote(workspace_name, safe=""), quote(name, safe="")
                )
            )
        else:
            self._raw_rest("delete", self._group_path(name, None))
