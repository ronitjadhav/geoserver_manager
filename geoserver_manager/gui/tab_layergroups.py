#! python3  # noqa: E265

"""
Layer Groups tab: list, view, create, delete layer groups.

Used as a mixin for GeoServerMainDialog. `_layer_uri()` comes from LayerTabMixin
through the shared dialog class; the global-or-workspace scope is `gui.scope`.
"""

from urllib.parse import quote

from qgis.core import QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.scope import GLOBAL, scope
from geoserver_manager.toolbelt.payload import bbox_text, unwrap

# GeoServer's LayerGroupInfo.Mode enum. Spelled out rather than imported from
# geoservercloud.models: the bundled wheels only reach sys.path once the plugin
# has run ensure_dependencies(). test_tab_layergroups asserts it still matches
# LayerGroup.modes.
MODES = ("SINGLE", "OPAQUE_CONTAINER", "NAMED", "CONTAINER", "EO")

# First entry of the layer picker. Picking a layer always *changes* the combo's
# text this way, so the same layer can be appended twice in a row.
_PICK = "(pick a layer)"


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
                "add-to-qgis",
                translate("LayerGroupTabMixin", "Add to QGIS"),
                self._add_group_to_qgis,
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

        # Mode and size are only in the group itself, so one GET per group.
        rows = []
        for (name, ws_label), (summary, error) in zip(
            groups,
            self._fan_out(lambda group: self._group_summary(*group), groups, task),
        ):
            if error:
                failures.append((f"{ws_label}/{name}", error))
                continue
            mode, layer_count = summary
            rows.append([name, ws_label, mode, str(layer_count)])
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
        if workspace_name:
            return endpoints.layergroup(workspace_name, name)
        # quote(): a "/" or "?" in a name would otherwise change the path
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

    # -- View ------------------------------------------------------------------

    @staticmethod
    def _as_text(value):
        """A GeoServer text field, which may be internationalised, as one line."""
        if isinstance(value, dict):
            return "; ".join(f"{lang}: {text}" for lang, text in value.items())
        return "" if value is None else str(value)

    @classmethod
    def _group_form_values(cls, detail, name, workspace_label):
        """Prefill for the detail dialog. Pure, so it is unit-testable."""
        styles = cls._group_styles(detail)
        lines = []
        for index, (layer_name, kind) in enumerate(cls._group_layers(detail)):
            notes = [] if kind == "layer" else [kind]
            style = styles[index] if index < len(styles) else ""
            if style:
                notes.append(f"style {style}")
            lines.append(layer_name + (f"  ({', '.join(notes)})" if notes else ""))

        return {
            "name": name,
            "workspace": workspace_label,
            "mode": _mode_label(detail.get("mode", "")),
            "title": cls._as_text(
                detail.get("internationalTitle") or detail.get("title")
            ),
            # GeoServer stores the abstract under "abstractTxt".
            "abstract": cls._as_text(
                detail.get("internationalAbstract") or detail.get("abstractTxt")
            ),
            "layers": "\n".join(lines),
            "bounds": bbox_text(detail.get("bounds")),
        }

    def _group_info_fields(self):
        """Field definitions for the read-only detail dialog."""
        read_only_text = [
            ("name", translate("LayerGroupTabMixin", "Name")),
            ("workspace", translate("LayerGroupTabMixin", "Workspace")),
            ("mode", translate("LayerGroupTabMixin", "Mode")),
            ("title", translate("LayerGroupTabMixin", "Title")),
            ("bounds", translate("LayerGroupTabMixin", "Bounds")),
        ]
        fields = [
            {"key": key, "label": label, "type": "text", "read_only": True}
            for key, label in read_only_text
        ]
        fields.append(
            {
                "key": "abstract",
                "label": translate("LayerGroupTabMixin", "Abstract"),
                "type": "textarea",
                "read_only": True,
            }
        )
        fields.append(
            {
                "key": "layers",
                "label": translate("LayerGroupTabMixin", "Layers"),
                "type": "textarea",
                "read_only": True,
                "group": translate("LayerGroupTabMixin", "Layers"),
                "help": translate(
                    "LayerGroupTabMixin",
                    "In drawing order: the first line is at the bottom.",
                ),
            }
        )
        return fields

    def _show_layer_group_info(self, row_data):
        """Open a layer group, read-only."""
        name, workspace_label = row_data[0], row_data[1]
        detail = self._fetch(
            lambda: self._group_detail(name, scope(workspace_label)),
            translate("LayerGroupTabMixin", "Failed to load layer group '{}'").format(
                name
            ),
        )
        if detail is None:
            return

        dlg = ResourceFormDialog(
            title=translate("LayerGroupTabMixin", "Layer Group '{}'").format(name),
            description=translate(
                "LayerGroupTabMixin",
                "Read-only: to change a group, create it again or delete it.",
            ),
            fields=self._group_info_fields(),
            values=self._group_form_values(detail, name, workspace_label),
            parent=self,
        )
        dlg.get_widget("layers").setMaximumHeight(300)
        dlg.hide_save_button()
        dlg.exec()

    # -- Create ----------------------------------------------------------------

    def _group_fields(self, workspace_names, layer_names):
        """Field definitions for the create dialog."""
        return [
            {
                "key": "name",
                "label": translate("LayerGroupTabMixin", "Name"),
                "type": "text",
                "required": True,
            },
            {
                "key": "workspace",
                "label": translate("LayerGroupTabMixin", "Workspace"),
                "type": "combo",
                "options": [GLOBAL] + list(workspace_names),
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
                "key": "pick",
                "label": translate("LayerGroupTabMixin", "Add a layer"),
                "type": "combo",
                "options": [_PICK] + list(layer_names),
                "group": translate("LayerGroupTabMixin", "Layers"),
                "help": translate("LayerGroupTabMixin", "Appends to the list below"),
            },
            {
                "key": "layers",
                "label": translate("LayerGroupTabMixin", "Layers"),
                "type": "textarea",
                "required": True,
                "group": translate("LayerGroupTabMixin", "Layers"),
                "placeholder": (
                    "topp:tasmania_state_boundaries\ntopp:tasmania_roads = simple_roads"
                ),
                "help": translate(
                    "LayerGroupTabMixin",
                    "One layer per line, in drawing order: the first line is "
                    "drawn first, at the bottom. Reorder by editing the text. "
                    'Add "= style" to a line to publish that layer with a '
                    "style other than its own default.",
                ),
            },
        ]

    def _append_group_layer(self, dlg, choice):
        """Append the picked layer to the ordered list, then reset the picker."""
        if choice == _PICK:
            return
        dlg.get_widget("layers").appendPlainText(choice)
        dlg.get_widget("pick").setCurrentIndex(0)  # re-fires with _PICK, ignored above

    def _add_layer_group(self):
        """Create a layer group from picked or pasted layer names."""
        fetched = self._fetch(
            lambda: (self._get_workspace_names(), self._all_layer_names()),
            translate("LayerGroupTabMixin", "Failed to load the workspaces and layers"),
        )
        if fetched is None:
            return
        workspace_names, layer_names = fetched

        dlg = ResourceFormDialog(
            title=translate("LayerGroupTabMixin", "Create a Layer Group"),
            description=translate(
                "LayerGroupTabMixin",
                "Publish several layers as one. GeoServer computes the group's "
                "bounds from the layers it contains.",
            ),
            fields=self._group_fields(workspace_names, layer_names),
            parent=self,
            ok_label=translate("LayerGroupTabMixin", "Create"),
        )
        dlg.get_widget("pick").currentTextChanged.connect(
            lambda choice: self._append_group_layer(dlg, choice)
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._create_layer_group_from_values(values, layer_names),
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
    def _parse_group_layers(text, workspace_name):
        """Parse the ordered layer list into (layers, styles).

        One layer per line, `workspace:layer` or `workspace:layer = style`,
        the same `key = value` shape the datastore parameter editor uses. The
        styles are parallel to the layers, "" where the layer keeps its own
        default style, and a bare layer name takes the group's workspace.
        """
        layers, styles = [], []
        for line in text.splitlines():
            if not line.strip():
                continue
            name, _, style = line.partition("=")
            name = name.strip()
            if ":" not in name and workspace_name:
                name = f"{workspace_name}:{name}"
            layers.append(name)
            styles.append(style.strip())
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

    def _create_layer_group_from_values(self, values, known_layers=None):
        """POST a new layer group, refusing to overwrite an existing one.

        :param known_layers: the server's layer names, as the form's picker
            listed them; a typed line naming none of them is refused here,
            by line, instead of coming back as GeoServer's HTTP error.

        TODO(#50): upstream: create_layer_group() cannot express any of this:
        it has no global scope, it qualifies every layer with the group's own
        workspace (so no group spanning workspaces, and no nested group), it
        replaces the bounds with a world bbox read from a three-entry EPSG
        table (a KeyError for any other code), and it sends the abstract under
        "abstract", which GeoServer silently drops.
        """
        name = values["name"]
        self._require_safe_name(name)
        workspace_name = scope(values["workspace"])
        layers, styles = self._parse_group_layers(values["layers"], workspace_name)
        if not layers:
            raise ValueError(
                translate("LayerGroupTabMixin", "List at least one layer.")
            )
        if known_layers is not None:
            unknown = [layer for layer in layers if layer not in known_layers]
            if unknown:
                raise ValueError(
                    translate(
                        "LayerGroupTabMixin",
                        "No layer named '{}' on the server. Pick it from the list, "
                        "or qualify it as workspace:layer.",
                    ).format(unknown[0])
                )
        self._check_styles_exist(styles)
        if self.gs.rest_service.resource_exists(self._group_path(name, workspace_name)):
            raise ValueError(
                translate(
                    "LayerGroupTabMixin", "Layer group '{}' already exists in {}."
                ).format(name, values["workspace"] or GLOBAL)
            )

        group = {
            "name": name,
            "mode": _mode_from_label(values["mode"]),
            "publishables": {
                "published": [{"@type": "layer", "name": layer} for layer in layers]
            },
        }
        if workspace_name:
            group["workspace"] = {"name": workspace_name}
        if values.get("title"):
            group["title"] = values["title"]
        if values.get("abstract"):
            group["abstractTxt"] = values["abstract"]
        if any(styles):
            # "" is how GeoServer itself spells "this layer's own default style".
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

        def add():
            settings = self.plg_settings.get_plg_settings()
            uri, provider = self._layer_uri(
                "WMS",
                settings.geoserver_url,
                qualified,
                settings.geoserver_auth_cfg_id,
            )
            layer = QgsRasterLayer(uri, name, provider)
            if not layer.isValid():
                raise RuntimeError(
                    layer.error().message()
                    or translate("LayerGroupTabMixin", "layer is not valid")
                )
            QgsProject.instance().addMapLayer(layer)

        if self._run_action(
            add,
            translate("LayerGroupTabMixin", "Could not add '{}' to QGIS").format(name),
        ):
            self.show_success_message(
                translate(
                    "LayerGroupTabMixin", "'{}' added to the project as WMS."
                ).format(name)
            )

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
                    f"{row[1]}/{row[0]}",
                    lambda name=row[0], ws=scope(row[1]): self._do_delete_group(
                        name, ws
                    ),
                )
                for row in selected_rows
            ],
            self._load_layer_groups,
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
            self._check(self.gs.delete_layer_group(workspace_name, name))
        else:
            self._raw_rest("delete", self._group_path(name, None))
