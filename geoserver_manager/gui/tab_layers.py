#! python3  # noqa: E265

"""
Layers tab — every published layer, whatever its type: list, inspect,
preview, style, add to QGIS, delete.

Used as a mixin for GeoServerMainDialog.
"""

import re
from urllib.parse import quote, unquote, urlencode

from qgis.core import Qgis, QgsDataSourceUri, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_preview import LayerPreviewDialog
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.toolbelt.qgis_export import export_to_geopackage, geoserver_name
from geoserver_manager.toolbelt.sld import layer_to_sld, styleable_project_layers

# How a GeoServer layer can be brought into QGIS. WFS gives the actual features
# (editable, stylable in QGIS); WMS/WMTS give rendered images. WMTS goes through
# GeoWebCache, which caches EPSG:900913 and EPSG:4326 for every layer by default.
PROTOCOLS = ("WMS", "WFS", "WMTS")

# Where the new layer's data comes from, in the publish form.
_SOURCE_TABLE = "A table in a datastore"
_SOURCE_QGIS = "A layer from this QGIS project"

# Fields that belong to one source only.
_SOURCE_FIELDS = {
    _SOURCE_TABLE: ("datastore", "table", "epsg"),
    _SOURCE_QGIS: ("qgis_layer", "name", "replace", "with_style"),
}
_WMTS_TILE_MATRIX_SET = "EPSG:900913"
# GeoServer's own Layer Preview page renders at 768 px on the long side.
_PREVIEW_SIZE = 768

# GeoServer's layer types, as /rest/layers writes them. The Type column
# carries them verbatim: they decide which resource a row's actions talk to.
VECTOR, RASTER, WMS, WMTS = "VECTOR", "RASTER", "WMS", "WMTS"


# Every user-visible string in this file goes through translate() with this
# file's own class as the context. self.tr() cannot: pylupdate extracts it
# under LayerTabMixin, but at runtime self.tr is QObject.tr with the context of the
# *instance's* class, GeoServerMainDialog — QDialog precedes the mixins in the
# MRO — so every lookup would miss. A wrapper function would not be extracted
# at all (pylupdate only understands a literal context), hence the repetition.
translate = QCoreApplication.translate


class LayerTabMixin:
    """Mixin that adds the Layers tab: every published layer, of any type."""

    def _load_layers(self):
        """Arm the Layers tab, then fetch its rows in the background."""
        self._setup_add_button(
            translate("LayerTabMixin", "Publish a Layer"),
            translate(
                "LayerTabMixin",
                "Publish a table of a datastore, or a layer of this QGIS project",
            ),
            self._publish_layer,
        )
        self._setup_delete_selected_button(self._delete_selected_layers)
        self._name_click_callback = self._show_layer_info
        self._extra_click_callbacks = {
            translate("LayerTabMixin", "Workspace"): self._open_workspace_from_row
        }
        self._row_actions = [
            (
                "mActionAddLayer.svg",
                translate("LayerTabMixin", "Add to QGIS"),
                self._add_layer_to_qgis,
            ),
            (
                "mIconWms.svg",
                translate("LayerTabMixin", "Preview in a browser"),
                self._preview_layer_in_browser,
                translate(
                    "LayerTabMixin",
                    "Preview in a browser — GeoServer's own OpenLayers page. A "
                    "secured server will ask the browser to log in.",
                ),
            ),
            (
                "mActionZoomToLayer.svg",
                translate("LayerTabMixin", "Preview"),
                self._preview_layer,
                translate(
                    "LayerTabMixin",
                    "Preview on a map inside QGIS — click the map for the feature "
                    "info at that point. Nothing is added to the project.",
                ),
            ),
            (
                "mActionStyleManager.svg",
                translate("LayerTabMixin", "Set style"),
                self._set_layer_style,
            ),
            (
                "mActionSharingExport.svg",
                translate("LayerTabMixin", "Style from QGIS"),
                self._style_from_qgis,
            ),
            (
                "mActionDeleteSelected.svg",
                translate("LayerTabMixin", "Delete"),
                self._delete_layer,
            ),
        ]
        self._setup_table(
            [
                translate("LayerTabMixin", "Layer Name"),
                translate("LayerTabMixin", "Workspace"),
                translate("LayerTabMixin", "Type"),
                translate("LayerTabMixin", "Store"),
                translate("LayerTabMixin", "Default style"),
                self.actions_column_label(),
            ]
        )
        self._start_load(
            translate("LayerTabMixin", "Failed to load layers"), self._fetch_layer_rows
        )

    def _fetch_layer_rows(self, task=None):
        """(rows, failures) for the Layers table. Runs in a worker thread.

        GeoServer's own layer list first — every published layer, whatever its
        type: vector, raster, cascaded WMS or WMTS — then one GET per layer,
        fanned out, for the type, the store and the default style. A layer
        whose detail cannot be read still gets a row, with placeholders, and
        a warning names it.
        """
        names = self._all_layer_names()
        rows, failures = [], []
        for qualified, (summary, error) in zip(
            names, self._fan_out(self._layer_summary, names, task)
        ):
            workspace, _, name = qualified.rpartition(":")
            if error:
                failures.append((qualified, error))
            kind, store, style = summary or ("—", "—", "—")
            rows.append([name, workspace, kind, store, style])
        return rows, failures

    def _layers_url(self, qualified_name=None):
        """/rest/layers.json, or one layer's own document under it."""
        base = self.gs.rest_service.rest_endpoints.base_url
        if qualified_name is None:
            return f"{base}/layers.json"
        return f"{base}/layers/{quote(qualified_name, safe=':')}.json"

    def _all_layer_names(self):
        """Every layer's qualified name ("workspace:layer"), from GeoServer's
        own list. Raises on HTTP errors.

        TODO(#50): row 39 — the facade has no get_layers(). Walking the
        datastores instead, as this tab did, misses every raster and cascaded
        layer; the workspace-less list is the one place they all appear.
        """
        payload = self._raw_rest("get", self._layers_url()).json()
        layers = payload.get("layers") if isinstance(payload, dict) else None
        layers = layers.get("layer") if isinstance(layers, dict) else None
        if isinstance(layers, dict):  # a single layer is not a list
            layers = [layers]
        return sorted(self._name_of(layer) for layer in layers or [])

    def _layer_summary(self, qualified_name):
        """(type, store, default style) of one layer. Raises on HTTP errors.

        TODO(#50): rest_service.get_layer() exists, but its Layer model keeps
        only the resource's *name* — not its class or href, which is where the
        store comes from — so this reads GeoServer's payload itself.
        """
        payload = self._raw_rest("get", self._layers_url(qualified_name)).json()
        layer = payload.get("layer") if isinstance(payload, dict) else None
        layer = layer if isinstance(layer, dict) else {}
        kind = layer.get("type") or "—"
        store = self._store_from_href((layer.get("resource") or {}).get("href"))
        if store is None and kind == WMTS:
            # GeoServer 2.28.5 writes no href for a wmtsLayer resource, so the
            # store has to be found among the workspace's WMTS stores.
            workspace, _, name = qualified_name.rpartition(":")
            store = self._wmts_store_of(workspace, name)
        style = (layer.get("defaultStyle") or {}).get("name") or "—"
        return kind, store or "—", style

    @staticmethod
    def _store_from_href(href):
        """The store in a resource href — .../workspaces/{ws}/{kind}stores/
        {store}/... — whatever host GeoServer wrote it with (behind a proxy it
        is not the one the plugin talks to, which is why the href is parsed
        and never followed). None when there is no such segment."""
        match = re.search(
            r"/workspaces/[^/]+/(?:data|coverage|wms|wmts)stores/([^/]+)/", href or ""
        )
        return unquote(match.group(1)) if match else None

    def _wmts_store_of(self, workspace_name, layer_name):
        """The WMTS store holding this cascaded layer, or None (helpers of the
        Cascaded Stores tab, reached through the shared dialog class)."""
        for store, kind in self._cascaded_store_names(workspace_name):
            if kind == WMTS and layer_name in self._cascaded_layer_names(
                workspace_name, store, kind
            ):
                return store
        return None

    @staticmethod
    def _layer_form_values(row_data, detail):
        """Prefill for the detail view, from what GeoServer returned.

        A feature type carries far more than the plugin can safely edit (see
        _show_layer_info), so this is a view: the interesting fields, flattened
        for display.
        """
        # A row is [name, workspace, type, store, default style].
        name, ws_name, ds_name = row_data[0], row_data[1], row_data[3]
        detail = detail if isinstance(detail, dict) else {}

        # The library's FeatureType.asdict() normalises keywords to a list and
        # attributes to a list; raw REST wraps them ({"string": […]},
        # {"attribute": […]}). Accept both — a live server showed the difference.
        keywords = detail.get("keywords") or []
        if isinstance(keywords, dict):
            keywords = keywords.get("string") or []
        if isinstance(keywords, str):
            keywords = [keywords]

        bbox = detail.get("nativeBoundingBox") or {}
        bbox_text = (
            ", ".join(
                f"{key} {bbox[key]}"
                for key in ("minx", "miny", "maxx", "maxy", "crs")
                if key in bbox
            )
            or "—"
        )

        attributes = detail.get("attributes") or []
        if isinstance(attributes, dict):
            attributes = attributes.get("attribute") or []
        if isinstance(attributes, dict):  # a single attribute is not a list
            attributes = [attributes]
        attribute_text = (
            "\n".join(
                "{} : {}".format(
                    a.get("name"), str(a.get("binding") or "").rsplit(".", 1)[-1]
                )
                for a in attributes
                if isinstance(a, dict)
            )
            or "—"
        )

        def as_text(value):
            """title/abstract are a string, or a dict of translations."""
            if isinstance(value, dict):
                return "; ".join(f"{k}: {v}" for k, v in sorted(value.items()))
            return value or ""

        return {
            "name": name,
            "native_name": detail.get("nativeName", ""),
            "workspace": ws_name,
            "datastore": ds_name,
            "srs": detail.get("srs", ""),
            "projection_policy": detail.get("projectionPolicy", ""),
            "enabled": bool(detail.get("enabled", True)),
            "advertised": bool(detail.get("advertised", True)),
            "title": as_text(detail.get("title")),
            "abstract": as_text(detail.get("abstract")),
            "keywords": ", ".join(str(k) for k in keywords),
            "bbox": bbox_text,
            "attributes": attribute_text,
        }

    def _layer_fields(self):
        """Field definitions for the feature-type detail view (all read-only)."""
        text = [
            ("name", translate("LayerTabMixin", "Layer Name")),
            ("native_name", translate("LayerTabMixin", "Native Name")),
            ("workspace", translate("LayerTabMixin", "Workspace")),
            ("datastore", translate("LayerTabMixin", "Datastore")),
            ("srs", translate("LayerTabMixin", "SRS")),
            ("projection_policy", translate("LayerTabMixin", "Projection Policy")),
            ("title", translate("LayerTabMixin", "Title")),
            ("abstract", translate("LayerTabMixin", "Abstract")),
            ("keywords", translate("LayerTabMixin", "Keywords")),
        ]
        fields = [
            {"key": key, "label": label, "type": "text", "read_only": True}
            for key, label in text
        ]
        fields += [
            {
                "key": "enabled",
                "label": translate("LayerTabMixin", "Enabled"),
                "type": "checkbox",
                "read_only": True,
            },
            {
                "key": "advertised",
                "label": translate("LayerTabMixin", "Advertised"),
                "type": "checkbox",
                "read_only": True,
            },
            {
                "key": "bbox",
                "label": translate("LayerTabMixin", "Native Bounding Box"),
                "type": "text",
                "read_only": True,
                "group": translate("LayerTabMixin", "Data"),
            },
            {
                "key": "attributes",
                "label": translate("LayerTabMixin", "Attributes"),
                "type": "textarea",
                "read_only": True,
                "group": translate("LayerTabMixin", "Data"),
            },
        ]
        return fields

    def _layer_resource(self, row_data):
        """The resource behind a layer row, as GeoServer stores it: a feature
        type, a coverage or a cascaded layer — by the row's type and store."""
        name, ws_name, kind, store = row_data[0], row_data[1], row_data[2], row_data[3]
        if kind == VECTOR:
            return self._check(self.gs.get_feature_type(ws_name, store, name))
        if kind == RASTER:
            return self._coverage_detail(ws_name, store, name)
        if kind in (WMS, WMTS):
            return self._cascaded_layer_detail(ws_name, store, kind, name)
        raise ValueError(
            translate("LayerTabMixin", "Unsupported layer type '{}'").format(kind)
        )

    def _show_layer_info(self, row_data):
        """Open a read-only view of one layer's resource, whatever its type.

        The vector view is this tab's own; the coverage and cascaded-layer
        views are borrowed from the Coverage Stores and Cascaded Stores tabs,
        minus their picker. View-only on purpose: the library's create_*
        helpers upsert from a handful of arguments, so saving through them
        would drop everything the form does not model — exactly the
        destruction the datastore merge exists to avoid. Editing needs an
        update that merges; tracked in #50.
        """
        detail = self._fetch(
            lambda: self._layer_resource(row_data),
            translate("LayerTabMixin", "Failed to load layer details"),
        )
        if detail is None:
            return
        detail = detail if isinstance(detail, dict) else {}
        name, ws_name, kind, store = row_data[0], row_data[1], row_data[2], row_data[3]
        if kind == RASTER:
            fields = [f for f in self._coverage_fields([]) if f["key"] != "coverage"]
            values = self._coverage_form_values(detail)
            origin = translate("LayerTabMixin", "Coverage of store {ws}/{store}.")
        elif kind in (WMS, WMTS):
            fields = [f for f in self._cascaded_layer_fields([]) if f["key"] != "layer"]
            values = self._cascaded_layer_form_values(detail)
            origin = translate(
                "LayerTabMixin", "Cascaded through {type} store {ws}/{store}."
            )
        else:
            fields = self._layer_fields()
            values = self._layer_form_values(row_data, detail)
            origin = translate("LayerTabMixin", "Published from {ws}/{store}.")

        dlg = ResourceFormDialog(
            title=translate("LayerTabMixin", "Layer '{}'").format(name),
            description=origin.format(ws=ws_name, store=store, type=kind)
            + " "
            + translate(
                "LayerTabMixin", "Read-only here — GeoServer's web UI can change it."
            ),
            fields=fields,
            values=values,
            parent=self,
        )
        dlg.hide_save_button()
        dlg.exec()

    # -- Publish --------------------------------------------------------------

    def _available_tables(self, workspace_name, datastore_name):
        """Tables of a datastore that are not published as layers yet.

        TODO(#50): upstream as get_available_feature_types(ws, ds) — the
        library has no call for GeoServer's ?list=available. Workaround: GET
        the featuretypes path with that query.
        """
        path = self.gs.rest_service.rest_endpoints.featuretypes(
            workspace_name, datastore_name
        )
        payload = self._raw_rest("get", path, params={"list": "available"}).json()
        listing = payload.get("list") if isinstance(payload, dict) else None
        names = listing.get("string") if isinstance(listing, dict) else []
        if isinstance(names, str):  # a single table comes back unwrapped
            names = [names]
        return sorted(names or [])

    def _publish_fields(self, workspace_names):
        """Field definitions for the publish form; combos cascade at runtime."""
        return [
            {
                "key": "source",
                "label": translate("LayerTabMixin", "Source"),
                "type": "combo",
                "options": [_SOURCE_TABLE, _SOURCE_QGIS],
            },
            {
                "key": "workspace",
                "label": translate("LayerTabMixin", "Workspace"),
                "type": "combo",
                "options": workspace_names,
                "required": True,
            },
            {
                "key": "datastore",
                "label": translate("LayerTabMixin", "Datastore"),
                "type": "combo",
                "options": [],
                "required": True,
                "help": translate(
                    "LayerTabMixin", "Datastores of the selected workspace"
                ),
            },
            {
                "key": "table",
                "label": translate("LayerTabMixin", "Table"),
                "type": "combo",
                "options": [],
                "required": True,
                "help": translate(
                    "LayerTabMixin",
                    "Tables in the datastore that are not published yet. The layer "
                    "takes the table's name.",
                ),
            },
            {
                "key": "epsg",
                "label": translate("LayerTabMixin", "Declared SRS (EPSG)"),
                "type": "spinbox",
                "default": 4326,
                "min": 1,
                "max": 999999,
                "group": translate("LayerTabMixin", "Metadata"),
                "help": translate(
                    "LayerTabMixin",
                    "The SRS GeoServer declares for the layer. Use the table's own "
                    "SRS — a wrong value misplaces the data.",
                ),
            },
            {
                "key": "title",
                "label": translate("LayerTabMixin", "Title"),
                "type": "text",
                "group": translate("LayerTabMixin", "Metadata"),
                "placeholder": translate("LayerTabMixin", "Optional"),
            },
            {
                "key": "abstract",
                "label": translate("LayerTabMixin", "Abstract"),
                "type": "textarea",
                "group": translate("LayerTabMixin", "Metadata"),
                "placeholder": translate("LayerTabMixin", "Optional"),
            },
            {
                "key": "keywords",
                "label": translate("LayerTabMixin", "Keywords"),
                "type": "text",
                "group": translate("LayerTabMixin", "Metadata"),
                "placeholder": translate("LayerTabMixin", "Optional, comma-separated"),
            },
            {
                "key": "qgis_layer",
                "label": translate("LayerTabMixin", "QGIS layer"),
                "type": "combo",
                "options": [label for label, _layer in styleable_project_layers()],
                "required": True,
                "visible": False,
                "help": translate(
                    "LayerTabMixin",
                    "The layer is written to a GeoPackage and uploaded, so the "
                    "data is copied to the server, not linked.",
                ),
            },
            {
                "key": "name",
                "label": translate("LayerTabMixin", "Layer name"),
                "type": "text",
                "required": True,
                "visible": False,
                "help": translate(
                    "LayerTabMixin",
                    "Also the name of the datastore and of the table inside it. "
                    "Anything a WFS type name cannot carry is replaced.",
                ),
            },
            {
                "key": "replace",
                "label": translate("LayerTabMixin", "Replace it if it already exists"),
                "type": "checkbox",
                "default": False,
                "visible": False,
            },
            {
                "key": "with_style",
                "label": translate(
                    "LayerTabMixin", "Upload its symbology as the layer's style"
                ),
                "type": "checkbox",
                "default": True,
                "visible": False,
            },
        ]

    def _on_publish_source_changed(self, dlg, source):
        """Show the fields of the chosen source only."""
        wanted = _SOURCE_FIELDS.get(source, ())
        for key in (
            "datastore",
            "table",
            "epsg",
            "qgis_layer",
            "name",
            "replace",
            "with_style",
        ):
            dlg.set_field_visible(key, key in wanted)
        if source == _SOURCE_QGIS:
            self._prefill_publish_name(dlg, dlg.get_widget("qgis_layer").currentText())

    @staticmethod
    def _prefill_publish_name(dlg, label):
        """Suggest the GeoServer-safe form of the picked layer's name."""
        widget = dlg.get_widget("name")
        if label and not widget.text().strip():
            widget.setText(geoserver_name(label.rsplit("  (", 1)[0]))

    def _refill_publish_combos(self, dlg, workspace=None, datastore=None):
        """Cascade: workspace -> its datastores -> the store's unpublished tables.

        A fetch that fails leaves its combo empty (and logs why); the required
        check then stops Save with the empty combo highlighted.
        """
        ws_combo = dlg.get_widget("workspace")
        ds_combo = dlg.get_widget("datastore")
        table_combo = dlg.get_widget("table")
        workspace = workspace or ws_combo.currentText()

        if datastore is None:
            ds_combo.blockSignals(True)  # the table refill below is explicit
            ds_combo.clear()
            try:
                ds_combo.addItems(self._datastore_names(workspace))
            except Exception as e:
                self.log(f"Could not list datastores of {workspace}: {e}")
            ds_combo.blockSignals(False)
            datastore = ds_combo.currentText()

        table_combo.clear()
        if workspace and datastore:
            try:
                table_combo.addItems(self._available_tables(workspace, datastore))
            except Exception as e:
                self.log(f"Could not list tables of {workspace}/{datastore}: {e}")

    def _publish_layer(self):
        """Open the publish form: pick workspace, datastore and table."""
        workspace_names = self._get_workspace_names()
        if not workspace_names:
            self.show_warning_message(
                translate(
                    "LayerTabMixin",
                    "No workspaces available. Create a workspace first.",
                )
            )
            return

        dlg = ResourceFormDialog(
            title=translate("LayerTabMixin", "Publish a Layer"),
            description=translate(
                "LayerTabMixin",
                "Publish a table of a datastore, or a layer of this QGIS "
                "project — that one is uploaded to the server as a GeoPackage.",
            ),
            fields=self._publish_fields(workspace_names),
            parent=self,
            ok_label=translate("LayerTabMixin", "Publish"),
        )
        dlg.get_widget("workspace").currentTextChanged.connect(
            lambda ws: self._refill_publish_combos(dlg, workspace=ws)
        )
        dlg.get_widget("datastore").currentTextChanged.connect(
            lambda ds: self._refill_publish_combos(dlg, datastore=ds)
        )
        dlg.get_widget("source").currentTextChanged.connect(
            lambda source: self._on_publish_source_changed(dlg, source)
        )
        dlg.get_widget("qgis_layer").currentTextChanged.connect(
            lambda label: self._prefill_publish_name(dlg, label)
        )
        self._refill_publish_combos(dlg)
        self._on_publish_source_changed(dlg, _SOURCE_TABLE)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        published = (
            geoserver_name(values["name"])
            if values.get("source") == _SOURCE_QGIS
            else values["table"]
        )
        if self._run_action(
            lambda: self._publish_layer_from_values(values),
            translate("LayerTabMixin", "Failed to publish '{}'").format(published),
        ):
            self.show_success_message(
                translate("LayerTabMixin", "Layer '{}' published.").format(published)
            )
            self._load_layers()

    def _publish_layer_from_values(self, values):
        """Publish from whichever source the form was filled for."""
        if values.get("source") == _SOURCE_QGIS:
            return self._publish_qgis_layer(values)
        return self._publish_table(values)

    def _publish_qgis_layer(self, values):
        """Upload a QGIS layer as a GeoPackage datastore and publish it.

        One store per published layer, named after it, which is also the name
        of the table inside the GeoPackage — GeoServer configures a feature
        type per table when the file lands, so this publishes the layer in one
        request. The data is copied: later edits in QGIS do not reach it, and
        deleting the store leaves the uploaded file in the data directory.

        TODO(#50): upstream as create_datastore_from_file(ws, name, path) — the
        library can only create datastores from connection parameters, so the
        upload is a raw PUT of .../datastores/{name}/file.gpkg.
        """
        import tempfile
        from pathlib import Path

        ws_name = values["workspace"]
        name = geoserver_name(values["name"])
        layer = self._picked_layer(values)
        if not values.get("replace"):
            for exists, message in (
                (
                    self._resource_exists(self.gs.get_datastore, ws_name, name),
                    translate(
                        "LayerTabMixin", "Datastore '{}' already exists in '{}'."
                    ),
                ),
                (
                    self._resource_exists(
                        self.gs.get_feature_type, ws_name, name, name
                    ),
                    translate("LayerTabMixin", "Layer '{}' already exists in '{}'."),
                ),
            ):
                if exists:
                    raise ValueError(
                        message.format(name, ws_name)
                        + " "
                        + translate("LayerTabMixin", "Tick Replace to overwrite it.")
                    )

        # The export reads a live QGIS layer, so it happens here, before any
        # request: this action runs on the GUI thread (invariant 9).
        folder = Path(tempfile.mkdtemp(prefix="gsm_publish_"))
        package = folder / f"{name}.gpkg"
        try:
            export_to_geopackage(layer, package, name)
            path = (
                f"{self.gs.rest_service.rest_endpoints.base_url}"
                f"/workspaces/{ws_name}/datastores/{name}/file.gpkg"
            )
            self._raw_rest(
                "put",
                path,
                params={"update": "overwrite"},
                data=package.read_bytes(),
                headers={"Content-Type": "application/x-sqlite3"},
            )
        finally:
            if package.exists():
                package.unlink()
            folder.rmdir()

        # Best effort: the data is published at this point, so a failure to set
        # a performance flag belongs in the log, not in the user's face.
        try:
            self._make_datastore_read_only(ws_name, name)
        except Exception as error:
            self.log(
                f"Could not mark '{ws_name}:{name}' read-only: {error}",
                log_level=Qgis.MessageLevel.Warning,
            )
        self._set_feature_type_metadata(ws_name, name, values)
        if values.get("with_style"):
            self._push_qgis_style(name, ws_name, layer_to_sld(layer), name, True)

    def _make_datastore_read_only(self, workspace_name, name):
        """Mark an uploaded GeoPackage store read-only.

        Nothing writes to a GeoPackage the plugin has just uploaded, and a
        read-only file store is the recommended setting for that case — it
        lets GeoServer serve it without taking write locks (not measured
        here). Merged onto the server's own parameters, never sent as a
        template (invariant 3).
        """
        detail = self._check(self.gs.get_datastore(workspace_name, name))
        params = dict(self._connection_params(detail))
        if params.get("read_only") == "true":
            return
        params["read_only"] = "true"
        self._check(
            self.gs.create_datastore(
                workspace_name=workspace_name,
                datastore_name=name,
                datastore_type=detail.get("type") or "GeoPackage",
                connection_parameters=params,
                enabled=bool(detail.get("enabled", True)),
            )
        )

    def _set_feature_type_metadata(self, workspace_name, name, values):
        """Add the form's title, abstract and keywords to a published layer.

        A partial feature-type PUT merges (verified on GeoServer 2.28.5), so
        the SRS, bounding box and attributes GeoServer computed from the upload
        survive — which create_feature_type() would overwrite with a template.
        """
        keywords = [
            keyword.strip()
            for keyword in (values.get("keywords") or "").split(",")
            if keyword.strip()
        ]
        metadata = {}
        if values.get("title"):
            metadata["title"] = values["title"]
        if values.get("abstract"):
            metadata["abstract"] = values["abstract"]
        if keywords:
            metadata["keywords"] = {"string": keywords}
        if not metadata:
            return
        path = self.gs.rest_service.rest_endpoints.featuretype(
            workspace_name, name, name
        )
        self._raw_rest("put", path, json={"featureType": metadata})

    def _publish_table(self, values):
        """Publish one table as a feature type through the library."""
        ws_name, ds_name, table = (
            values["workspace"],
            values["datastore"],
            values["table"],
        )
        # create_feature_type upserts, so an existing layer would be overwritten
        if self._resource_exists(self.gs.get_feature_type, ws_name, ds_name, table):
            raise ValueError(
                translate(
                    "LayerTabMixin", "Layer '{}' already exists in {}/{}."
                ).format(table, ws_name, ds_name)
            )
        keywords = [k.strip() for k in (values.get("keywords") or "").split(",")]
        self._check(
            self.gs.create_feature_type(
                layer_name=table,
                workspace_name=ws_name,
                datastore_name=ds_name,
                title=values.get("title") or None,
                abstract=values.get("abstract") or None,
                epsg=int(values.get("epsg") or 4326),
                keywords=[k for k in keywords if k],
            )
        )

    # -- Default style --------------------------------------------------------

    def _layer_default_style(self, workspace_name, name):
        """The layer's current default style name, or None if unreadable.

        TODO(#50): upstream — the facade has set_default_layer_style() but no
        get_layer(); rest_service.get_layer() exists and is used here directly.
        """
        try:
            layer = self._check(self.gs.rest_service.get_layer(workspace_name, name))
        except Exception:
            return None
        info = layer.asdict() if hasattr(layer, "asdict") else layer
        return info.get("defaultStyle") if isinstance(info, dict) else None

    def _style_choices(self, workspace_name):
        """Styles a layer in this workspace may use: global ones and its workspace's.

        A workspace style is referenced by its qualified name, "ws:style".
        """
        choices = [self._name_of(st) for st in self._fetch_list(self.gs.get_styles)]
        choices += [
            f"{workspace_name}:{self._name_of(st)}"
            for st in self._fetch_list(self.gs.get_styles, workspace_name)
        ]
        return sorted(choices)

    def _set_layer_style(self, row_data):
        """Pick the default style for one layer."""
        name, ws_name = row_data[0], row_data[1]
        fetched = self._fetch(
            lambda: (
                self._style_choices(ws_name),
                self._layer_default_style(ws_name, name),
            ),
            translate("LayerTabMixin", "Failed to load styles for '{}'").format(name),
        )
        if fetched is None:
            return
        choices, current = fetched
        if current and current not in choices:
            choices.insert(0, current)

        dlg = ResourceFormDialog(
            title=translate("LayerTabMixin", "Default style for '{}'").format(name),
            description=translate(
                "LayerTabMixin",
                "Global styles and the styles of workspace '{}'. Other styles the "
                "layer may use stay as they are.",
            ).format(ws_name),
            fields=[
                {
                    "key": "style",
                    "label": translate("LayerTabMixin", "Default style"),
                    "type": "combo",
                    "options": choices,
                    "default": current,
                    "required": True,
                }
            ],
            parent=self,
            ok_label=translate("LayerTabMixin", "Set style"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        style = dlg.get_values()["style"]
        if style == current:
            return
        if self._run_action(
            lambda: self._check(self.gs.set_default_layer_style(name, ws_name, style)),
            translate("LayerTabMixin", "Failed to set the style of '{}'").format(name),
        ):
            self.show_success_message(
                translate("LayerTabMixin", "'{}' now uses style '{}'.").format(
                    name, style
                )
            )

    # -- Style from QGIS -------------------------------------------------------

    @staticmethod
    def _matching_project_layer(layer_name, layers):
        """The label of the project layer that looks like this GeoServer layer.

        Matched on the name, ignoring case and any "workspace:" prefix, because
        that is how a layer added by this plugin (or by QGIS's own browser)
        comes into a project.
        """
        wanted = layer_name.split(":")[-1].casefold()
        for label, layer in layers:
            if layer.name().split(":")[-1].casefold() == wanted:
                return label
        return None

    def _style_from_qgis(self, row_data):
        """Upload a QGIS layer's symbology as this layer's style."""
        name, ws_name = row_data[0], row_data[1]
        layers = styleable_project_layers()
        if not layers:
            self.show_warning_message(
                translate(
                    "LayerTabMixin",
                    "This QGIS project has no vector or raster layer to take a style from.",
                )
            )
            return
        match = self._matching_project_layer(name, layers)

        dlg = ResourceFormDialog(
            title=translate("LayerTabMixin", "Style '{}' from QGIS").format(name),
            description=translate(
                "LayerTabMixin",
                "The layer's symbology is exported as SLD and uploaded to "
                "workspace '{}'. A style of that name there is replaced — that "
                "is how you push a change you just made in QGIS.",
            ).format(ws_name),
            fields=[
                {
                    "key": "qgis_layer",
                    "label": translate("LayerTabMixin", "QGIS layer"),
                    "type": "combo",
                    "options": [label for label, _layer in layers],
                    "default": match,
                    "required": True,
                    "help": (
                        None
                        if match
                        else translate(
                            "LayerTabMixin", "No project layer matches '{}' by name."
                        ).format(name)
                    ),
                },
                {
                    "key": "style",
                    "label": translate("LayerTabMixin", "Style name"),
                    "type": "text",
                    "default": geoserver_name(name),
                    "required": True,
                },
                {
                    "key": "set_default",
                    "label": translate(
                        "LayerTabMixin", "Make it the layer's default style"
                    ),
                    "type": "checkbox",
                    "default": True,
                },
            ],
            parent=self,
            ok_label=translate("LayerTabMixin", "Upload"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        # The export reads a live QGIS layer, so it happens here on the GUI
        # thread, before the upload (invariant 9).
        layer = self._picked_layer(values)
        sld = self._fetch(
            lambda: layer_to_sld(layer),
            translate("LayerTabMixin", "Could not export the symbology of '{}'").format(
                layer.name()
            ),
        )
        if sld is None:
            return

        style_name = geoserver_name(values["style"])
        if self._run_action(
            lambda: self._push_qgis_style(
                style_name, ws_name, sld, name, values["set_default"]
            ),
            translate("LayerTabMixin", "Failed to upload the style of '{}'").format(
                layer.name()
            ),
        ):
            self.show_success_message(
                translate("LayerTabMixin", "'{}' styled from '{}'.").format(
                    name, layer.name()
                )
                if values["set_default"]
                else translate("LayerTabMixin", "Style '{}' uploaded to '{}'.").format(
                    style_name, ws_name
                )
            )
            self._reload_current_tab()

    def _push_qgis_style(
        self, style_name, workspace_name, sld, layer_name, set_default
    ):
        """Create or replace the style in the layer's workspace, then assign it.

        Workspace styles are referenced by their qualified name, so the layer's
        defaultStyle gets "workspace:style" — a bare name there would resolve
        to a global style of the same name instead.
        """
        self._check(
            self.gs.create_style_definition(
                style_name, f"{style_name}.sld", workspace_name
            )
        )
        self._put_sld_body(style_name, workspace_name, sld)
        if set_default:
            self._check(
                self.gs.set_default_layer_style(
                    layer_name, workspace_name, f"{workspace_name}:{style_name}"
                )
            )

    # -- Add to QGIS ----------------------------------------------------------

    @staticmethod
    def _layer_uri(protocol, base_url, qualified_name, authcfg=""):
        """Provider URI for one GeoServer layer. Returns (uri, provider_key).

        Credentials never go in the URI: `authcfg` is the id of the QGIS
        authentication config the plugin already stores, and the providers
        resolve it themselves — so a saved project holds no password.
        """
        base = base_url.rstrip("/")
        auth = f"&authcfg={authcfg}" if authcfg else ""
        if protocol == "WMS":
            return (
                f"crs=EPSG:4326&format=image/png&layers={qualified_name}&styles="
                f"&url={base}/ows{auth}",
                "wms",
            )
        if protocol == "WMTS":
            return (
                f"crs=EPSG:4326&format=image/png&layers={qualified_name}&styles="
                f"&tileMatrixSet={_WMTS_TILE_MATRIX_SET}"
                f"&url={base}/gwc/service/wmts?REQUEST=GetCapabilities{auth}",
                "wms",
            )
        if protocol == "WFS":
            uri = QgsDataSourceUri()
            uri.setParam("url", f"{base}/ows")
            uri.setParam("typename", qualified_name)
            uri.setParam("version", "auto")
            uri.setParam("srsname", "EPSG:4326")
            uri.setParam("pagingEnabled", "true")
            if authcfg:
                uri.setAuthConfigId(authcfg)
            return (uri.uri(False), "WFS")
        raise ValueError(f"Unknown protocol: {protocol}")

    # -- Preview in a browser --------------------------------------------------

    @staticmethod
    def _bbox_from(box):
        """((minx, miny, maxx, maxy), crs) from a GeoServer bounding box, else
        (None, None) when it is missing or incomplete."""
        box = box or {}
        if not {"minx", "miny", "maxx", "maxy"} <= set(box):
            return None, None
        try:
            bbox = tuple(float(box[key]) for key in ("minx", "miny", "maxx", "maxy"))
        except (TypeError, ValueError):
            return None, None
        crs = box.get("crs")
        if isinstance(crs, dict):
            # A projected CRS comes as {"@class": "projected", "$": "EPSG:…"}.
            crs = crs.get("$")
        return bbox, str(crs or "EPSG:4326")

    @staticmethod
    def _preview_url(base_url, qualified_name, bbox=None, srs=None, workspace=None):
        """GeoServer's own OpenLayers preview page for a layer or a layer group.

        A URL for the browser, not a request from the plugin — the browser's
        session is not the plugin's, so a secured server asks it to log in.
        Without a usable bbox the map opens on the world. 768 px on the long
        side and the other from the bbox's aspect, as GeoServer's own Layer
        Preview page computes them.
        """
        base = base_url.rstrip("/")
        service = f"{base}/{workspace}/wms" if workspace else f"{base}/wms"
        if not bbox or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            bbox, srs = (-180.0, -90.0, 180.0, 90.0), "EPSG:4326"
        width = height = _PREVIEW_SIZE
        ratio = (bbox[3] - bbox[1]) / (bbox[2] - bbox[0])
        if ratio <= 1:
            height = max(1, round(_PREVIEW_SIZE * ratio))
        else:
            width = max(1, round(_PREVIEW_SIZE / ratio))
        query = urlencode(
            {
                "service": "WMS",
                "version": "1.1.0",
                "request": "GetMap",
                "layers": qualified_name,
                "bbox": ",".join(str(value) for value in bbox),
                "width": width,
                "height": height,
                "srs": srs or "EPSG:4326",
                "styles": "",
                "format": "application/openlayers",
            },
            safe=":/,",
        )
        return f"{service}?{query}"

    def _open_in_browser(self, url):
        """Hand a URL to the system browser; say so when nothing opens."""
        if not QDesktopServices.openUrl(QUrl(url)):
            self.show_warning_message(
                translate("LayerTabMixin", "Could not open a browser for {}").format(
                    url
                )
            )

    def _preview_layer_in_browser(self, row_data):
        """Open GeoServer's own preview of the layer, on its extent."""
        name, ws_name = row_data[0], row_data[1]
        detail = self._fetch(
            lambda: self._layer_resource(row_data),
            translate("LayerTabMixin", "Failed to load layer details"),
        )
        if detail is None:
            return
        detail = detail if isinstance(detail, dict) else {}
        bbox, srs = self._bbox_from(detail.get("latLonBoundingBox"))
        self._open_in_browser(
            self._preview_url(
                self.plg_settings.get_plg_settings().geoserver_url,
                f"{ws_name}:{name}" if ws_name else name,
                bbox,
                srs,
                workspace=ws_name or None,
            )
        )

    # -- Preview inside QGIS ---------------------------------------------------

    def _preview_layer(self, row_data):
        """Show the layer on a map of its own, with the feature info on click.

        The map layer is built like *Add to QGIS* builds one — credentials as
        the auth config id — but it lives in the preview window only: nothing
        reaches the project.
        """
        name, ws_name = row_data[0], row_data[1]
        detail = self._fetch(
            lambda: self._layer_resource(row_data),
            translate("LayerTabMixin", "Failed to load layer details"),
        )
        if detail is None:
            return
        detail = detail if isinstance(detail, dict) else {}
        # latLonBoundingBox is EPSG:4326 by definition, which is the map's CRS.
        bbox, _srs = self._bbox_from(detail.get("latLonBoundingBox"))
        qualified = f"{ws_name}:{name}" if ws_name else name

        def build():
            settings = self.plg_settings.get_plg_settings()
            uri, provider = self._layer_uri(
                "WMS", settings.geoserver_url, qualified, settings.geoserver_auth_cfg_id
            )
            # Reading the capabilities is a request. An invalid layer is not
            # an error here: the window explains it in place of the map.
            return QgsRasterLayer(uri, qualified, provider)

        layer = self._fetch(
            build,
            translate("LayerTabMixin", "Could not build the preview of '{}'").format(
                name
            ),
        )
        if layer is None:
            return
        LayerPreviewDialog(qualified, layer, bbox, parent=self).show()

    def _add_layer_to_qgis(self, row_data):
        """Ask which protocol, then add the layer to the current QGIS project."""
        name, ws_name, kind = row_data[0], row_data[1], row_data[2]
        if kind == VECTOR:
            protocols = list(PROTOCOLS)
            description = translate(
                "LayerTabMixin",
                "WFS loads the features themselves (editable, styled in QGIS); WMS "
                "and WMTS load rendered images. Credentials come from the plugin's "
                "saved connection, not from the layer.",
            )
        else:
            # A raster or a cascaded layer has no features to serve over WFS.
            protocols = [protocol for protocol in PROTOCOLS if protocol != "WFS"]
            description = translate(
                "LayerTabMixin",
                "WMS and WMTS load rendered images — this layer has no features to "
                "serve over WFS. Credentials come from the plugin's saved "
                "connection, not from the layer.",
            )
        dlg = ResourceFormDialog(
            title=translate("LayerTabMixin", "Add '{}' to QGIS").format(name),
            description=description,
            fields=[
                {
                    "key": "protocol",
                    "label": translate("LayerTabMixin", "Load as"),
                    "type": "combo",
                    "options": protocols,
                    "default": "WMS",
                    "required": True,
                }
            ],
            parent=self,
            ok_label=translate("LayerTabMixin", "Add"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        protocol = dlg.get_values()["protocol"]

        def add():
            settings = self.plg_settings.get_plg_settings()
            uri, provider = self._layer_uri(
                protocol,
                settings.geoserver_url,
                f"{ws_name}:{name}",
                settings.geoserver_auth_cfg_id,
            )
            layer_class = QgsVectorLayer if provider == "WFS" else QgsRasterLayer
            layer = layer_class(uri, name, provider)
            if not layer.isValid():
                # Build first and check, instead of iface.addRasterLayer(), so an
                # unreachable layer becomes our banner rather than QGIS's modal.
                raise RuntimeError(
                    layer.error().message()
                    or translate("LayerTabMixin", "layer is not valid")
                )
            QgsProject.instance().addMapLayer(layer)

        if self._run_action(
            add, translate("LayerTabMixin", "Could not add '{}' to QGIS").format(name)
        ):
            self.show_success_message(
                translate("LayerTabMixin", "'{}' added to the project as {}.").format(
                    name, protocol
                )
            )

    def _delete_layer(self, row_data):
        """Delete a single layer, with its resource, after confirmation."""
        self._delete_selected_layers([row_data])

    def _delete_layer_resource(self, workspace_name, kind, store, name):
        """Remove the resource behind a layer — the published layer goes with it."""
        if kind == VECTOR:
            self._check(self.gs.delete_feature_type(workspace_name, store, name))
        elif kind == RASTER:
            # TODO(#50): no delete_coverage() in the library, only
            # delete_coverage_store(). Workaround: DELETE the coverage with
            # recurse=true, which removes the layer and keeps the store.
            path = self.gs.rest_service.rest_endpoints.coverage(
                workspace_name, store, name
            )
            self._raw_rest("delete", path, params={"recurse": "true"})
        elif kind in (WMS, WMTS):
            self._delete_cascaded_layer(workspace_name, store, kind, name)
        else:
            raise ValueError(
                translate("LayerTabMixin", "Unsupported layer type '{}'").format(kind)
            )

    def _delete_selected_layers(self, selected_rows):
        """Delete one or more layers, each through its own resource type."""
        self._delete_many(
            translate("LayerTabMixin", "layer"),
            [
                (
                    f"{row[1]}:{row[0]}" if row[1] else row[0],
                    lambda row=row: self._delete_layer_resource(
                        row[1], row[2], row[3], row[0]
                    ),
                )
                for row in selected_rows
            ],
            self._load_layers,
            # Every resource delete sends recurse=true, which removes the
            # published layer — but GeoServer refuses outright while a layer
            # group still references it (verified against 2.28.5).
            cascade=translate(
                "LayerTabMixin",
                "The published layer goes too; the table, file or remote layer "
                "behind it is not touched. GeoServer refuses if a layer group "
                "still uses the layer — remove it from the group first.\n\n",
            ),
        )
