#! python3  # noqa: E265

"""
Layer Groups tab — list, view, create, delete layer groups.

Used as a mixin for GeoServerMainDialog. Two things come from its siblings on
that class: `_scope()` and the `GLOBAL` label (StyleTabMixin — layer groups have
the same global-or-workspace scope as styles) and `_layer_uri()` (LayerTabMixin).
"""

from qgis.core import QgsProject, QgsRasterLayer
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_styles import GLOBAL

# GeoServer's LayerGroupInfo.Mode enum. Spelled out rather than imported from
# geoservercloud.models: the bundled wheels only reach sys.path once the plugin
# has run ensure_dependencies(). test_tab_layergroups asserts it still matches
# LayerGroup.modes.
MODES = ("SINGLE", "OPAQUE_CONTAINER", "NAMED", "CONTAINER", "EO")

# First entry of the layer picker. Picking a layer always *changes* the combo's
# text this way, so the same layer can be appended twice in a row.
_PICK = "— pick a layer —"


class LayerGroupTabMixin:
    """Mixin that adds layer-group methods to the main dialog.

    ponytail: same translation caveat as the other tab mixins — self.tr() here
    is extracted under this class but resolved against the host dialog.
    """

    # -- Listing ---------------------------------------------------------------

    def _load_layer_groups(self):
        """List the global layer groups and every workspace's."""

        def load():
            self._setup_add_button(
                self.tr("Create a Layer Group"),
                self.tr("Publish several layers as one"),
                self._add_layer_group,
            )
            self._setup_delete_selected_button(self._delete_selected_layer_groups)
            self._name_click_callback = self._show_layer_group_info
            self._extra_click_callbacks = {
                self.tr("Workspace"): self._open_workspace_from_group_row
            }
            self._row_actions = [
                (
                    "mActionAddLayer.svg",
                    self.tr("Add to QGIS"),
                    self._add_group_to_qgis,
                ),
                (
                    "mActionDeleteSelected.svg",
                    self.tr("Delete"),
                    self._delete_layer_group,
                ),
            ]
            self._setup_table(
                [
                    self.tr("Layer Group"),
                    self.tr("Workspace"),
                    self.tr("Mode"),
                    self.tr("Layers"),
                    self.tr("Actions"),
                ]
            )

            groups = [(name, GLOBAL) for name in self._global_group_names()]
            failures = []
            ws_names = self._get_workspace_names()
            for ws_name, (names, error) in zip(
                ws_names,
                self._fan_out(
                    lambda ws: self._fetch_list(self.gs.get_layer_groups, ws), ws_names
                ),
            ):
                if error:
                    failures.append((ws_name, error))
                    continue
                groups.extend((self._name_of(group), ws_name) for group in names)

            # Mode and size are only in the group itself, so one GET per group.
            rows = []
            for (name, ws_label), (summary, error) in zip(
                groups, self._fan_out(lambda group: self._group_summary(*group), groups)
            ):
                if error:
                    failures.append((f"{ws_label}/{name}", error))
                    continue
                mode, layer_count = summary
                rows.append([name, ws_label, mode, str(layer_count)])
            self._populate_rows(rows)
            self._report_partial_failures(failures)

        self._run_action(load, self.tr("Failed to load layer groups"))

    def _open_workspace_from_group_row(self, row_data):
        """The Workspace column links to the workspace — not for global groups."""
        if self._scope(row_data[1]) is not None:
            self._show_workspace_info([row_data[1]])

    def _global_group_names(self):
        """Names of the layer groups that live outside any workspace.

        TODO(#50): upstream — every layer-group call in the library takes a
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
        detail = self._group_detail(name, self._scope(workspace_label))
        return detail.get("mode", ""), len(self._group_layers(detail))

    # -- One group -------------------------------------------------------------

    def _group_detail(self, name, workspace_name):
        """One layer group, as GeoServer stores it.

        TODO(#50): upstream — get_layer_group() exists, but its model drops the
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
        return f"{endpoints.base_url}/layergroups/{name}.json"

    @staticmethod
    def _unwrap(payload, list_key, item_key):
        """Entries of a GeoServer collection payload, always as a list.

        An empty collection comes back as `{"layerGroups": ""}` and a
        single-entry one wraps a bare object instead of a one-item list.
        """
        container = payload.get(list_key) or {}
        items = container.get(item_key) or [] if isinstance(container, dict) else []
        return [items] if isinstance(items, dict) else items

    @classmethod
    def _group_layers(cls, detail):
        """The group's publishables in drawing order, as (name, @type) pairs."""
        return [
            (item.get("name", ""), item.get("@type", "layer"))
            for item in cls._unwrap(detail, "publishables", "published")
            if isinstance(item, dict)
        ]

    @classmethod
    def _group_styles(cls, detail):
        """The style of each publishable; "" where the layer's default is used."""
        styles = cls._unwrap(detail, "styles", "style")
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

        bounds = detail.get("bounds") or {}
        bounds_text = (
            "{minx}, {miny} → {maxx}, {maxy}  ({crs})".format(**bounds)
            if {"minx", "miny", "maxx", "maxy", "crs"} <= set(bounds)
            else ""
        )
        return {
            "name": name,
            "workspace": workspace_label,
            "mode": detail.get("mode", ""),
            "title": cls._as_text(
                detail.get("internationalTitle") or detail.get("title")
            ),
            # GeoServer stores the abstract under "abstractTxt".
            "abstract": cls._as_text(
                detail.get("internationalAbstract") or detail.get("abstractTxt")
            ),
            "layers": "\n".join(lines),
            "bounds": bounds_text,
        }

    def _group_info_fields(self):
        """Field definitions for the read-only detail dialog."""
        read_only_text = [
            ("name", self.tr("Layer Group")),
            ("workspace", self.tr("Workspace")),
            ("mode", self.tr("Mode")),
            ("title", self.tr("Title")),
            ("bounds", self.tr("Bounds")),
        ]
        fields = [
            {"key": key, "label": label, "type": "text", "read_only": True}
            for key, label in read_only_text
        ]
        fields.append(
            {
                "key": "abstract",
                "label": self.tr("Abstract"),
                "type": "textarea",
                "read_only": True,
            }
        )
        fields.append(
            {
                "key": "layers",
                "label": self.tr("Layers"),
                "type": "textarea",
                "read_only": True,
                "group": self.tr("Layers"),
                "help": self.tr("In drawing order: the first line is at the bottom."),
            }
        )
        return fields

    def _show_layer_group_info(self, row_data):
        """Open a layer group, read-only."""
        name, workspace_label = row_data[0], row_data[1]
        detail = self._fetch(
            lambda: self._group_detail(name, self._scope(workspace_label)),
            self.tr("Failed to load layer group '{}'").format(name),
        )
        if detail is None:
            return

        dlg = ResourceFormDialog(
            title=self.tr("Layer Group '{}'").format(name),
            description=self.tr(
                "Read-only: to change a group, create it again or delete it."
            ),
            fields=self._group_info_fields(),
            values=self._group_form_values(detail, name, workspace_label),
            parent=self,
        )
        dlg.get_widget("layers").setMaximumHeight(300)
        dlg.hide_save_button()
        dlg.exec()

    # -- Create ----------------------------------------------------------------

    def _all_layer_names(self):
        """Every published layer on the server, qualified as "workspace:layer".

        TODO(#50): upstream as get_layers() — the library lists feature types
        per datastore and coverages per coverage store, so the one call that
        lists everything publishable, rasters included, is missing. Workaround:
        GET /rest/layers.json.
        """
        path = f"{self.gs.rest_service.rest_endpoints.base_url}/layers.json"
        payload = self._raw_rest("get", path).json()
        return sorted(
            self._name_of(layer) for layer in self._unwrap(payload, "layers", "layer")
        )

    def _group_fields(self, workspace_names, layer_names):
        """Field definitions for the create dialog."""
        return [
            {
                "key": "name",
                "label": self.tr("Layer Group"),
                "type": "text",
                "required": True,
            },
            {
                "key": "workspace",
                "label": self.tr("Workspace"),
                "type": "combo",
                "options": [GLOBAL] + list(workspace_names),
                "help": self.tr(
                    "A global group can mix layers from several workspaces"
                ),
            },
            {
                "key": "mode",
                "label": self.tr("Mode"),
                "type": "combo",
                "options": list(MODES),
                "default": "SINGLE",
                "help": self.tr(
                    "SINGLE publishes the group as one layer; NAMED also keeps "
                    "its layers addressable; CONTAINER and EO only group them"
                ),
            },
            {"key": "title", "label": self.tr("Title"), "type": "text"},
            {"key": "abstract", "label": self.tr("Abstract"), "type": "textarea"},
            {
                "key": "pick",
                "label": self.tr("Add a layer"),
                "type": "combo",
                "options": [_PICK] + list(layer_names),
                "group": self.tr("Layers"),
                "help": self.tr("Appends to the list below"),
            },
            {
                "key": "layers",
                "label": self.tr("Layers"),
                "type": "textarea",
                "required": True,
                "group": self.tr("Layers"),
                "placeholder": "topp:tasmania_state_boundaries\ntopp:tasmania_roads",
                "help": self.tr(
                    "One layer per line, in drawing order — the first line is "
                    "drawn first, at the bottom. Reorder by editing the text."
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
            self.tr("Failed to load the workspaces and layers"),
        )
        if fetched is None:
            return
        workspace_names, layer_names = fetched

        dlg = ResourceFormDialog(
            title=self.tr("Create a Layer Group"),
            description=self.tr(
                "Publish several layers as one. GeoServer computes the group's "
                "bounds from the layers it contains."
            ),
            fields=self._group_fields(workspace_names, layer_names),
            parent=self,
        )
        dlg.get_widget("pick").currentTextChanged.connect(
            lambda choice: self._append_group_layer(dlg, choice)
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._create_layer_group_from_values(values),
            self.tr("Failed to create layer group '{}'").format(values["name"]),
        ):
            self.show_success_message(
                self.tr("Layer group '{}' created.").format(values["name"])
            )
            self._load_layer_groups()

    @staticmethod
    def _parse_group_layers(text, workspace_name):
        """One "workspace:layer" per line; a bare name takes the group's workspace."""
        layers = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if ":" not in line and workspace_name:
                line = f"{workspace_name}:{line}"
            layers.append(line)
        return layers

    def _create_layer_group_from_values(self, values):
        """POST a new layer group, refusing to overwrite an existing one.

        TODO(#50): upstream — create_layer_group() cannot express any of this:
        it has no global scope, it qualifies every layer with the group's own
        workspace (so no group spanning workspaces, and no nested group), it
        replaces the bounds with a world bbox read from a three-entry EPSG
        table (a KeyError for any other code), and it sends the abstract under
        "abstract", which GeoServer silently drops.
        """
        name = values["name"]
        workspace_name = self._scope(values["workspace"])
        layers = self._parse_group_layers(values["layers"], workspace_name)
        if not layers:
            raise ValueError(self.tr("List at least one layer."))
        if self.gs.rest_service.resource_exists(self._group_path(name, workspace_name)):
            raise ValueError(
                self.tr("Layer group '{}' already exists in {}.").format(
                    name, values["workspace"] or GLOBAL
                )
            )

        group = {
            "name": name,
            "mode": values["mode"],
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
        # No "bounds": GeoServer then computes the union of the layers' extents.
        # No "styles": every layer keeps its own default style.
        self._raw_rest(
            "post", self._groups_path(workspace_name), json={"layerGroup": group}
        )

    # -- Add to QGIS -----------------------------------------------------------

    def _add_group_to_qgis(self, row_data):
        """Add the group to the current QGIS project as one WMS layer.

        WMS only: a group has no feature type to fetch over WFS, and it reaches
        GeoWebCache only once someone caches it there.
        """
        name, workspace_name = row_data[0], self._scope(row_data[1])
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
                    layer.error().message() or self.tr("layer is not valid")
                )
            QgsProject.instance().addMapLayer(layer)

        if self._run_action(add, self.tr("Could not add '{}' to QGIS").format(name)):
            self.show_success_message(
                self.tr("'{}' added to the project as WMS.").format(name)
            )

    # -- Delete ----------------------------------------------------------------

    def _delete_layer_group(self, row_data):
        """Delete a single layer group after confirmation."""
        self._delete_selected_layer_groups([row_data])

    def _delete_selected_layer_groups(self, selected_rows):
        """Delete one or more layer groups after confirmation."""
        self._delete_many(
            self.tr("layer group"),
            [
                (
                    f"{row[1]}/{row[0]}",
                    lambda name=row[0], ws=self._scope(row[1]): self._do_delete_group(
                        name, ws
                    ),
                )
                for row in selected_rows
            ],
            self._load_layer_groups,
            cascade=self.tr(
                "Only the group goes away — the layers it published stay. "
                "GeoServer refuses if another layer group contains this one.\n\n"
            ),
        )

    def _do_delete_group(self, name, workspace_name):
        """DELETE one layer group; the library covers the workspace scope only.

        TODO(#50): see _global_group_names — delete_layer_group() requires a
        workspace_name, so a global group needs the raw path.
        """
        if workspace_name:
            self._check(self.gs.delete_layer_group(workspace_name, name))
        else:
            self._raw_rest("delete", self._group_path(name, None))
