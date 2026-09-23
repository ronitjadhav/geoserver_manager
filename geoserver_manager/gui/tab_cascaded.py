#! python3  # noqa: E265

"""
Cascaded Stores tab: WMS and WMTS stores that proxy another server, and the
remote layers published through them.

Used as a mixin for GeoServerMainDialog.
"""

from urllib.parse import quote

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.toolbelt.payload import bbox_text, keyword_list

# GeoServer's own `type` values. The Type column carries them, and every
# action reads the row's type to pick the WMS or the WMTS endpoint.
WMS = "WMS"
WMTS = "WMTS"

# (collection key, entry key) of the store and layer collections, per type.
_STORE_KEYS = {WMS: ("wmsStores", "wmsStore"), WMTS: ("wmtsStores", "wmtsStore")}
_LAYER_KEYS = {WMS: ("wmsLayers", "wmsLayer"), WMTS: ("wmtsLayers", "wmtsLayer")}


# Every user-visible string in this file goes through translate() with this
# file's own class as the context. self.tr() cannot: pylupdate extracts it
# under CascadedStoreTabMixin, but at runtime self.tr is QObject.tr with the
# context of the *instance's* class, GeoServerMainDialog. QDialog precedes the
# mixins in the MRO, so every lookup would miss. A wrapper function would not
# be extracted at all (pylupdate only understands a literal context), hence
# the repetition.
translate = QCoreApplication.translate


def _q(segment):
    """A URL path segment. TODO(#50): the library's `RestEndpoints` builders
    interpolate names raw and `requests` sends `stores/a#b.json` as `stores/a`;
    pre-quoting what they receive is the smallest fix, to drop once the
    library quotes itself (or `%` doubles)."""
    return quote(str(segment), safe="")


class CascadedStoreTabMixin:
    """Mixin that adds cascaded WMS / WMTS store methods to the main dialog."""

    # -- Load -----------------------------------------------------------------

    def _load_cascaded_stores(self):
        """Arm the Cascaded Stores tab, then fetch its rows in the background."""
        self._setup_add_button(
            translate("CascadedStoreTabMixin", "Add a Cascaded Store"),
            translate(
                "CascadedStoreTabMixin",
                "Proxy another server's WMS or WMTS through this GeoServer",
            ),
            self._add_cascaded_store,
        )
        self._setup_delete_selected_button(self._delete_selected_cascaded_stores)
        self._name_click_callback = self._show_cascaded_store_info
        self._extra_click_callbacks = {
            translate(
                "CascadedStoreTabMixin", "Workspace"
            ): self._open_workspace_from_row
        }
        self._row_actions = [
            (
                "browse-resources",
                translate("CascadedStoreTabMixin", "Cascaded layers"),
                self._show_cascaded_layers,
            ),
            (
                "publish-layer",
                translate("CascadedStoreTabMixin", "Publish a layer"),
                self._publish_cascaded_layer,
            ),
            (
                "delete",
                translate("CascadedStoreTabMixin", "Delete"),
                self._delete_cascaded_store,
            ),
        ]
        self._setup_table(
            [
                translate("CascadedStoreTabMixin", "Name"),
                translate("CascadedStoreTabMixin", "Workspace"),
                translate("CascadedStoreTabMixin", "Type"),
                translate("CascadedStoreTabMixin", "Enabled"),
                translate("CascadedStoreTabMixin", "GetCapabilities URL"),
                self.actions_column_label(),
            ]
        )
        self._start_load(
            translate("CascadedStoreTabMixin", "Failed to load cascaded stores"),
            self._fetch_cascaded_store_rows,
        )

    def _fetch_cascaded_store_rows(self, task=None):
        """(rows, failures) for the table. Runs in a worker thread."""
        ws_names = self._get_workspace_names()
        listed = self._fan_out(self._cascaded_store_names, ws_names, task)
        triples = [
            (ws_name, name, kind)
            for ws_name, (stores, error) in zip(ws_names, listed)
            if error is None
            for name, kind in stores
        ]
        details = self._fan_out(
            lambda triple: self._cascaded_store_detail(*triple), triples, task
        )
        rows = [
            [name, ws_name, kind, *self._cascaded_store_summary(detail)]
            for (ws_name, name, kind), (detail, _error) in zip(triples, details)
        ]
        failures = [(ws, err) for ws, (_stores, err) in zip(ws_names, listed) if err]
        failures += [
            (f"{ws}/{name}", err)
            for (ws, name, _kind), (_detail, err) in zip(triples, details)
            if err
        ]
        return rows, failures

    def _cascaded_store_summary(self, detail):
        """(enabled, capabilities URL) cells; a store whose GET failed shows dashes."""
        if not isinstance(detail, dict):
            return ("-", "-")
        return (
            self._yes_no(detail.get("enabled", True)),
            detail.get("capabilitiesURL") or "-",
        )

    def _cascaded_store_names(self, workspace_name):
        """[(name, type)] of one workspace's WMS and WMTS stores. Raises on HTTP errors.

        TODO(#50): upstream as get_wms_stores(ws) / get_wmts_stores(ws); the
        library gets, creates and deletes one store but never lists them.
        Workaround: GET the two collections.
        """
        endpoints = self.gs.rest_service.rest_endpoints
        stores = []
        for kind, path in (
            (WMS, endpoints.wmsstores(_q(workspace_name))),
            (WMTS, endpoints.wmtsstores(_q(workspace_name))),
        ):
            payload = self._raw_rest("get", path).json()
            stores += [
                (self._name_of(store), kind)
                for store in self._unwrap(payload, *_STORE_KEYS[kind])
            ]
        return sorted(stores)

    def _cascaded_store_detail(self, workspace_name, name, kind):
        """One store as GeoServer stores it: type, enabled, capabilitiesURL, …"""
        if kind == WMS:
            return self._check(self.gs.get_wms_store(workspace_name, name))
        # TODO(#50): the library has get_wms_store() but no get_wmts_store().
        # Workaround: GET the store path.
        path = self.gs.rest_service.rest_endpoints.wmtsstore(
            _q(workspace_name), _q(name)
        )
        return self._raw_rest("get", path).json().get("wmtsStore") or {}

    def _cascaded_store_exists(self, workspace_name, name, kind):
        """True when the store is already there (create_* would upsert it)."""
        if kind == WMS:
            return self._resource_exists(self.gs.get_wms_store, workspace_name, name)
        # TODO(#50): no get_wmts_store() to hand to _resource_exists; the
        # service layer's own existence check stands in.
        service = self.gs.rest_service
        return service.resource_exists(
            service.rest_endpoints.wmtsstore(_q(workspace_name), _q(name))
        )

    # -- Cascaded layers ------------------------------------------------------

    def _cascaded_layer_names(self, workspace_name, store_name, kind, available=False):
        """The store's cascaded layers, or, with available=True, every layer the
        remote capabilities advertise, under their remote names. Raises on HTTP
        errors.

        TODO(#50): upstream as get_wms_layers(ws, store, list=…) and a WMTS
        twin; the library's get_wms_layers() is this GeoServer's own WMS
        capabilities, not a store's cascaded layers. Workaround: GET the
        collection; `?list=available` answers `{"list": {"string": [...]}}`.
        """
        endpoints = self.gs.rest_service.rest_endpoints
        if kind == WMS:
            path = endpoints.wmslayers(_q(workspace_name), _q(store_name))
        else:
            path = endpoints.wmtslayers(_q(workspace_name), _q(store_name))
        if available:
            payload = self._raw_rest("get", path, params={"list": "available"}).json()
            # a one-entry list is a bare string; _unwrap knows
            return [str(name) for name in self._unwrap(payload, "list", "string")]
        payload = self._raw_rest("get", path).json()
        return sorted(
            self._name_of(layer) for layer in self._unwrap(payload, *_LAYER_KEYS[kind])
        )

    def _cascaded_layer_detail(self, workspace_name, store_name, kind, layer_name):
        """One cascaded layer: remote name, title, SRS, bounds, keywords, …"""
        if kind == WMS:
            return self._check(
                self.gs.get_wms_layer(workspace_name, store_name, layer_name)
            )
        # TODO(#50): no get_wmts_layer() in the library. Workaround: GET the path.
        path = self.gs.rest_service.rest_endpoints.wmtslayer(
            _q(workspace_name), _q(store_name), _q(layer_name)
        )
        return self._raw_rest("get", path).json().get("wmtsLayer") or {}

    def _cascaded_layer_exists(self, workspace_name, store_name, kind, layer_name):
        """True when a cascaded layer of that name is already published."""
        if kind == WMS:
            return self._resource_exists(
                self.gs.get_wms_layer, workspace_name, store_name, layer_name
            )
        service = self.gs.rest_service  # TODO(#50): as for the store
        return service.resource_exists(
            service.rest_endpoints.wmtslayer(
                _q(workspace_name), _q(store_name), _q(layer_name)
            )
        )

    def _create_cascaded_layer(self, workspace_name, store_name, kind, native, name):
        """Publish one remote layer under `name`. Raises when the name is taken."""
        self._require_safe_name(name)
        # create_wms_layer deletes and recreates an existing name, so refuse it first
        if self._cascaded_layer_exists(workspace_name, store_name, kind, name):
            raise ValueError(
                translate(
                    "CascadedStoreTabMixin", "Layer '{}' already exists in store '{}'."
                ).format(name, store_name)
            )
        if kind == WMS:
            self._check(
                self.gs.create_wms_layer(workspace_name, store_name, native, name)
            )
            return
        # TODO(#50): create_wmts_layer() fetches the remote capabilities from
        # *this* machine (the remote may be reachable from GeoServer only),
        # forces the SRS to EPSG:4326 and deletes an existing layer first.
        # GeoServer needs only the two names and reads title, abstract, SRS
        # and bounds from the capabilities itself. Workaround: POST them.
        path = self.gs.rest_service.rest_endpoints.wmtslayers(
            _q(workspace_name), _q(store_name)
        )
        self._raw_rest(
            "post", path, json={"wmtsLayer": {"name": name, "nativeName": native}}
        )

    def _delete_cascaded_layer(self, workspace_name, store_name, kind, layer_name):
        """Remove one cascaded layer.

        recurse=true is required: the resource is referenced by its layer, and
        without it GeoServer answers 403 "wms layer referenced by layer(s)".
        """
        if kind == WMS:
            self._check(
                self.gs.delete_wms_layer(workspace_name, store_name, layer_name)
            )
            return
        # TODO(#50): no delete_wmts_layer() in the library. Workaround: DELETE.
        path = self.gs.rest_service.rest_endpoints.wmtslayer(
            _q(workspace_name), _q(store_name), _q(layer_name)
        )
        self._raw_rest("delete", path, params={"recurse": "true"})

    def _cascaded_layer_form_values(self, detail):
        """Prefill for the layer viewer, from the library's dict or GeoServer's
        raw payload; the keywords differ in shape between the two."""
        keywords = keyword_list(detail.get("keywords"))
        return {
            "native_name": detail.get("nativeName", ""),
            "title": str(detail.get("title") or ""),
            "srs": detail.get("srs", ""),
            "enabled": self._yes_no(detail.get("enabled", True)),
            "bounds": bbox_text(detail.get("latLonBoundingBox")) or "-",
            "keywords": ", ".join(keywords) or "-",
            "abstract": str(detail.get("abstract") or ""),
        }

    def _cascaded_layer_fields(self, names):
        """Field definitions for the layer viewer: a picker plus its details."""
        fields = [
            {
                "key": "layer",
                "label": translate("CascadedStoreTabMixin", "Layer"),
                "type": "combo",
                "options": list(names),
            }
        ]
        fields += [
            {"key": key, "label": label, "type": "text", "read_only": True}
            for key, label in (
                ("native_name", translate("CascadedStoreTabMixin", "Remote layer")),
                ("title", translate("CascadedStoreTabMixin", "Title")),
                ("srs", translate("CascadedStoreTabMixin", "SRS")),
                ("enabled", translate("CascadedStoreTabMixin", "Enabled")),
                ("bounds", translate("CascadedStoreTabMixin", "Bounds")),
                ("keywords", translate("CascadedStoreTabMixin", "Keywords")),
            )
        ]
        fields.append(
            {
                "key": "abstract",
                "label": translate("CascadedStoreTabMixin", "Abstract"),
                "type": "textarea",
                "read_only": True,
            }
        )
        return fields

    def _refill_cascaded_layer_detail(
        self, dlg, workspace_name, store_name, kind, name
    ):
        """Show one cascaded layer's details in the viewer."""
        if not name:
            return
        detail = self._fetch(
            lambda: self._cascaded_layer_detail(workspace_name, store_name, kind, name),
            translate("CascadedStoreTabMixin", "Failed to load layer '{}'").format(
                name
            ),
        )
        for key, value in self._cascaded_layer_form_values(detail or {}).items():
            widget = dlg.get_widget(key)
            if hasattr(widget, "setPlainText"):
                widget.setPlainText(value)
            else:
                widget.setText(value)

    def _show_cascaded_layers(self, row_data):
        """List the store's cascaded layers and view one at a time."""
        store_name, ws_name, kind = row_data[0], row_data[1], row_data[2]
        names = self._fetch(
            lambda: self._cascaded_layer_names(ws_name, store_name, kind),
            translate(
                "CascadedStoreTabMixin", "Failed to load the layers of '{}'"
            ).format(store_name),
        )
        if names is None:
            return
        if not names:
            self.show_warning_message(
                translate(
                    "CascadedStoreTabMixin",
                    "'{}' publishes no layer yet. Use Publish a layer.",
                ).format(store_name)
            )
            return

        dlg = ResourceFormDialog(
            title=translate("CascadedStoreTabMixin", "Cascaded layers of '{}'").format(
                store_name
            ),
            description=translate(
                "CascadedStoreTabMixin",
                "What this store publishes from the remote server. To remove one, "
                "delete it from the Layers tab.",
            ),
            fields=self._cascaded_layer_fields(names),
            parent=self,
        )
        dlg.hide_save_button()
        dlg.get_widget("layer").currentTextChanged.connect(
            lambda name: self._refill_cascaded_layer_detail(
                dlg, ws_name, store_name, kind, name
            )
        )
        self._refill_cascaded_layer_detail(dlg, ws_name, store_name, kind, names[0])
        dlg.exec()

    def _publish_cascaded_layer(self, row_data):
        """Publish one of the remote server's layers through this store."""
        store_name, ws_name, kind = row_data[0], row_data[1], row_data[2]
        candidates = self._fetch(
            lambda: self._cascaded_layer_names(
                ws_name, store_name, kind, available=True
            ),
            translate(
                "CascadedStoreTabMixin", "Failed to list the remote layers of '{}'"
            ).format(store_name),
        )
        if candidates is None:
            return
        if not candidates:
            self.show_warning_message(
                translate(
                    "CascadedStoreTabMixin",
                    "The remote server behind '{}' advertises no layer. Check its "
                    "capabilities URL.",
                ).format(store_name)
            )
            return

        dlg = ResourceFormDialog(
            title=translate("CascadedStoreTabMixin", "Publish a layer of '{}'").format(
                store_name
            ),
            description=translate(
                "CascadedStoreTabMixin",
                "The remote layer becomes a layer of this GeoServer, fetched from "
                "the remote server on every request. Leave the name empty to reuse "
                "the remote name without its prefix.",
            ),
            fields=[
                {
                    "key": "native_name",
                    "label": translate("CascadedStoreTabMixin", "Remote layer"),
                    "type": "combo",
                    "options": candidates,
                    "required": True,
                },
                {
                    "key": "name",
                    "label": translate("CascadedStoreTabMixin", "Layer name"),
                    "type": "text",
                    "help": translate(
                        "CascadedStoreTabMixin", "As published here, in workspace '{}'."
                    ).format(ws_name),
                },
            ],
            parent=self,
            ok_label=translate("CascadedStoreTabMixin", "Publish"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        native = values["native_name"]
        name = (values.get("name") or "").strip() or native.rsplit(":", 1)[-1]
        if self._run_action(
            lambda: self._create_cascaded_layer(
                ws_name, store_name, kind, native, name
            ),
            translate("CascadedStoreTabMixin", "Failed to publish '{}'").format(native),
        ):
            self.show_success_message(
                translate(
                    "CascadedStoreTabMixin", "'{}' published as layer '{}'."
                ).format(native, name)
            )
            self._load_cascaded_stores()

    # -- Add ------------------------------------------------------------------

    def _cascaded_store_fields(self, workspace_names):
        """Field definitions for the create dialog."""
        return [
            {
                "key": "name",
                "label": translate("CascadedStoreTabMixin", "Name"),
                "type": "text",
                "required": True,
            },
            {
                "key": "workspace",
                "label": translate("CascadedStoreTabMixin", "Workspace"),
                "type": "combo",
                "options": list(workspace_names),
                "required": True,
            },
            {
                "key": "type",
                "label": translate("CascadedStoreTabMixin", "Type"),
                "type": "combo",
                "options": [WMS, WMTS],
                "required": True,
            },
            {
                "key": "capabilities_url",
                "label": translate("CascadedStoreTabMixin", "GetCapabilities URL"),
                "type": "text",
                "required": True,
                "placeholder": "https://example.org/geoserver/wms?service=WMS"
                "&version=1.3.0&request=GetCapabilities",
                "help": translate(
                    "CascadedStoreTabMixin",
                    "As GeoServer reaches it, from its own machine, not from yours.",
                ),
            },
        ]

    def _add_cascaded_store(self):
        """Open a form dialog to create a cascaded store."""
        workspace_names = self._fetch(
            self._get_workspace_names,
            translate("CascadedStoreTabMixin", "Failed to load the workspaces"),
        )
        if workspace_names is None:
            return
        if not workspace_names:
            self.show_warning_message(
                translate(
                    "CascadedStoreTabMixin",
                    "No workspaces available. Create a workspace first.",
                )
            )
            return

        dlg = ResourceFormDialog(
            title=translate("CascadedStoreTabMixin", "Add a Cascaded Store"),
            description=translate(
                "CascadedStoreTabMixin",
                "A cascaded store proxies another server's WMS or WMTS: its layers "
                "can then be published here, and are fetched from the remote server "
                "on every request.",
            ),
            fields=self._cascaded_store_fields(workspace_names),
            parent=self,
            ok_label=translate("CascadedStoreTabMixin", "Create"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._create_cascaded_store_from_values(values),
            translate(
                "CascadedStoreTabMixin", "Failed to create cascaded store '{}'"
            ).format(values["name"]),
        ):
            self.show_success_message(
                translate(
                    "CascadedStoreTabMixin", "Cascaded store '{}' created."
                ).format(values["name"])
            )
            self._load_cascaded_stores()

    def _create_cascaded_store_from_values(self, values):
        """Create the store the form describes. Raises on a taken name or a bad URL."""
        ws = values["workspace"]
        name = values["name"].strip()
        self._require_safe_name(name)
        kind = values["type"]
        url = values["capabilities_url"].strip()
        if not url.startswith(("http://", "https://")):
            # GeoServer accepts any string here and only fails later, when the
            # store's layers are listed. Say it now instead.
            raise ValueError(
                translate(
                    "CascadedStoreTabMixin",
                    "The GetCapabilities URL must start with http:// or https://.",
                )
            )
        # create_* upserts, so an existing name would reconfigure a live store
        if self._cascaded_store_exists(ws, name, kind):
            raise ValueError(
                translate(
                    "CascadedStoreTabMixin",
                    "Cascaded store '{}' already exists in workspace '{}'.",
                ).format(name, ws)
            )
        if kind == WMS:
            self._check(self.gs.create_wms_store(ws, name, url))
        else:
            self._check(self.gs.create_wmts_store(ws, name, url))

    # -- Info -----------------------------------------------------------------

    def _cascaded_store_info_fields(self):
        """Field definitions for the read-only store dialog."""
        fields = [
            {"key": key, "label": label, "type": "text", "read_only": True}
            for key, label in (
                ("name", translate("CascadedStoreTabMixin", "Name")),
                ("workspace", translate("CascadedStoreTabMixin", "Workspace")),
                ("type", translate("CascadedStoreTabMixin", "Type")),
                (
                    "capabilities_url",
                    translate("CascadedStoreTabMixin", "GetCapabilities URL"),
                ),
                ("enabled", translate("CascadedStoreTabMixin", "Enabled")),
            )
        ]
        fields.append(
            {
                "key": "layers",
                "label": translate("CascadedStoreTabMixin", "Cascaded layers"),
                "type": "textarea",
                "read_only": True,
                "group": translate("CascadedStoreTabMixin", "Layers"),
                "help": translate(
                    "CascadedStoreTabMixin",
                    "Open the Cascaded layers action for one layer's details.",
                ),
            }
        )
        return fields

    def _cascaded_store_form_values(self, detail, workspace_name, kind, published):
        """Prefill for the store dialog."""
        return {
            "name": detail.get("name", ""),
            "workspace": workspace_name,
            "type": detail.get("type") or kind,
            "capabilities_url": detail.get("capabilitiesURL", ""),
            "enabled": self._yes_no(detail.get("enabled", True)),
            "layers": "\n".join(published) or "-",
        }

    def _show_cascaded_store_info(self, row_data):
        """Open a cascaded store, read-only."""
        name, ws_name, kind = row_data[0], row_data[1], row_data[2]
        fetched = self._fetch(
            lambda: (
                self._cascaded_store_detail(ws_name, name, kind),
                self._cascaded_layer_names(ws_name, name, kind),
            ),
            translate(
                "CascadedStoreTabMixin", "Failed to load cascaded store '{}'"
            ).format(name),
        )
        if fetched is None:
            return
        detail, published = fetched

        dlg = ResourceFormDialog(
            title=translate("CascadedStoreTabMixin", "Cascaded Store '{}'").format(
                name
            ),
            description=translate(
                "CascadedStoreTabMixin",
                "Read-only. To point it at another server, delete it and create "
                "it again; its published layers go with it.",
            ),
            fields=self._cascaded_store_info_fields(),
            values=self._cascaded_store_form_values(detail, ws_name, kind, published),
            parent=self,
        )
        dlg.hide_save_button()
        dlg.exec()

    # -- Delete ---------------------------------------------------------------

    def _delete_cascaded_store(self, row_data):
        """Delete a single cascaded store after confirmation."""
        self._delete_selected_cascaded_stores([row_data])

    def _delete_selected_cascaded_stores(self, selected_rows):
        """Delete one or more cascaded stores after confirmation."""
        self._delete_many(
            translate("CascadedStoreTabMixin", "cascaded store"),
            [
                (
                    f"{row[1]}/{row[0]}",
                    lambda ws=row[1], name=row[0], kind=row[2]: (
                        self._do_delete_cascaded_store(ws, name, kind)
                    ),
                )
                for row in selected_rows
            ],
            self._load_cascaded_stores,
            lambda n: translate(
                "CascadedStoreTabMixin", "%n cascaded store(s)", None, n
            ),
            # both library deletes send recurse=true
            cascade=translate(
                "CascadedStoreTabMixin",
                "Every cascaded layer published from it is deleted too; the remote "
                "server is not touched.",
            ),
        )

    def _do_delete_cascaded_store(self, workspace_name, name, kind):
        """The library's deletes, which recurse into the store's layers."""
        delete = self.gs.delete_wms_store if kind == WMS else self.gs.delete_wmts_store
        self._check(delete(workspace_name, name))
