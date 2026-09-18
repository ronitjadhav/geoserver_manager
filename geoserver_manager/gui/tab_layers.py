#! python3  # noqa: E265

"""
Layers tab — list, view and delete feature types.

Used as a mixin for GeoServerMainDialog.
"""

from qgis.core import QgsDataSourceUri, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.toolbelt.sld import layer_to_sld, styleable_project_layers

# How a GeoServer layer can be brought into QGIS. WFS gives the actual features
# (editable, stylable in QGIS); WMS/WMTS give rendered images. WMTS goes through
# GeoWebCache, which caches EPSG:900913 and EPSG:4326 for every layer by default.
PROTOCOLS = ("WMS", "WFS", "WMTS")
_WMTS_TILE_MATRIX_SET = "EPSG:900913"


class LayerTabMixin:
    """Mixin that adds feature-type methods to the main dialog.

    ponytail: same translation caveat as WorkspaceTabMixin — self.tr() here is
    extracted under this class but resolved against the host dialog's context.
    """

    def _load_layers(self):
        """Arm the Layers tab, then fetch its rows in the background."""
        self._setup_add_button(
            self.tr("Publish a Table"),
            self.tr("Publish a table of a datastore as a new layer"),
            self._publish_layer,
        )
        self._setup_delete_selected_button(self._delete_selected_layers)
        self._name_click_callback = self._show_layer_info
        self._extra_click_callbacks = {
            self.tr("Workspace"): self._open_workspace_from_row
        }
        self._row_actions = [
            (
                "mActionAddLayer.svg",
                self.tr("Add to QGIS"),
                self._add_layer_to_qgis,
            ),
            (
                "mActionStyleManager.svg",
                self.tr("Set style"),
                self._set_layer_style,
            ),
            (
                "mActionSharingExport.svg",
                self.tr("Style from QGIS"),
                self._style_from_qgis,
            ),
            (
                "mActionDeleteSelected.svg",
                self.tr("Delete"),
                self._delete_layer,
            ),
        ]
        self._setup_table(
            [
                self.tr("Layer Name"),
                self.tr("Workspace"),
                self.tr("Datastore"),
                self.tr("SRS"),
                self.tr("Enabled"),
                self.tr("Actions"),
            ]
        )
        self._start_load(self.tr("Failed to load layers"), self._fetch_layer_rows)

    def _fetch_layer_rows(self, task=None):
        """(rows, failures) for the Layers table. Runs in a worker thread.

        Three levels: workspaces -> datastores -> feature types, then one
        detail GET per feature type for the SRS and enabled columns (the list
        endpoint only returns names). Each level is fanned out and tolerant, so
        one unreadable parent costs a warning, not the table.
        """
        failures = []
        stores = []
        ws_names = self._get_workspace_names()
        for ws_name, (ds_names, error) in zip(
            ws_names, self._fan_out(self._datastore_names, ws_names, task)
        ):
            if error:
                failures.append((ws_name, error))
                continue
            stores.extend((ws_name, ds_name) for ds_name in ds_names)

        layers = []
        for (ws_name, ds_name), (names, error) in zip(
            stores,
            self._fan_out(lambda store: self._layer_names(*store), stores, task),
        ):
            if error:
                failures.append((f"{ws_name}/{ds_name}", error))
                continue
            layers.extend((ws_name, ds_name, name) for name in names)

        summaries = self._fan_out(
            lambda layer: self._layer_summary(*layer), layers, task
        )
        rows = []
        for (ws_name, ds_name, name), (summary, error) in zip(layers, summaries):
            if error:
                failures.append((f"{ws_name}/{ds_name}/{name}", error))
            srs, enabled = summary or ("—", "—")
            rows.append([name, ws_name, ds_name, srs, enabled])
        return rows, failures

    def _layer_names(self, workspace_name, datastore_name):
        """Feature-type names in one datastore. Raises on HTTP errors."""
        return [
            self._name_of(ft)
            for ft in self._fetch_list(
                self.gs.get_feature_types, workspace_name, datastore_name
            )
        ]

    def _layer_summary(self, workspace_name, datastore_name, name):
        """(srs, enabled) for the list view. Raises on HTTP errors."""
        detail = self._check(
            self.gs.get_feature_type(workspace_name, datastore_name, name)
        )
        if not isinstance(detail, dict):
            return ("—", "—")
        return (detail.get("srs", "—"), str(detail.get("enabled", True)))

    @staticmethod
    def _layer_form_values(row_data, detail):
        """Prefill for the detail view, from what GeoServer returned.

        A feature type carries far more than the plugin can safely edit (see
        _show_layer_info), so this is a view: the interesting fields, flattened
        for display.
        """
        name, ws_name, ds_name = row_data[0], row_data[1], row_data[2]
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
            ("name", self.tr("Layer Name")),
            ("native_name", self.tr("Native Name")),
            ("workspace", self.tr("Workspace")),
            ("datastore", self.tr("Datastore")),
            ("srs", self.tr("SRS")),
            ("projection_policy", self.tr("Projection Policy")),
            ("title", self.tr("Title")),
            ("abstract", self.tr("Abstract")),
            ("keywords", self.tr("Keywords")),
        ]
        fields = [
            {"key": key, "label": label, "type": "text", "read_only": True}
            for key, label in text
        ]
        fields += [
            {
                "key": "enabled",
                "label": self.tr("Enabled"),
                "type": "checkbox",
                "read_only": True,
            },
            {
                "key": "advertised",
                "label": self.tr("Advertised"),
                "type": "checkbox",
                "read_only": True,
            },
            {
                "key": "bbox",
                "label": self.tr("Native Bounding Box"),
                "type": "text",
                "read_only": True,
                "group": self.tr("Data"),
            },
            {
                "key": "attributes",
                "label": self.tr("Attributes"),
                "type": "textarea",
                "read_only": True,
                "group": self.tr("Data"),
            },
        ]
        return fields

    def _show_layer_info(self, row_data):
        """Open a read-only view of one feature type.

        View-only on purpose: the library's create_feature_type upserts from a
        handful of arguments, so saving through it would drop everything the
        form does not model (projection policy, bounding boxes, attributes) —
        exactly the destruction the datastore merge exists to avoid. Editing
        needs an update_feature_type that merges; tracked in #50.
        """
        detail = self._fetch(
            lambda: self._check(
                self.gs.get_feature_type(row_data[1], row_data[2], row_data[0])
            ),
            self.tr("Failed to load layer details"),
        )
        if detail is None:
            return

        dlg = ResourceFormDialog(
            title=self.tr("Layer '{}'").format(row_data[0]),
            description=self.tr(
                "Published from {ws}/{ds}. Read-only here — GeoServer's web UI can "
                "change it."
            ).format(ws=row_data[1], ds=row_data[2]),
            fields=self._layer_fields(),
            values=self._layer_form_values(row_data, detail),
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
                "key": "workspace",
                "label": self.tr("Workspace"),
                "type": "combo",
                "options": workspace_names,
                "required": True,
            },
            {
                "key": "datastore",
                "label": self.tr("Datastore"),
                "type": "combo",
                "options": [],
                "required": True,
                "help": self.tr("Datastores of the selected workspace"),
            },
            {
                "key": "table",
                "label": self.tr("Table"),
                "type": "combo",
                "options": [],
                "required": True,
                "help": self.tr(
                    "Tables in the datastore that are not published yet. The layer "
                    "takes the table's name."
                ),
            },
            {
                "key": "epsg",
                "label": self.tr("Declared SRS (EPSG)"),
                "type": "spinbox",
                "default": 4326,
                "min": 1,
                "max": 999999,
                "group": self.tr("Metadata"),
                "help": self.tr(
                    "The SRS GeoServer declares for the layer. Use the table's own "
                    "SRS — a wrong value misplaces the data."
                ),
            },
            {
                "key": "title",
                "label": self.tr("Title"),
                "type": "text",
                "group": self.tr("Metadata"),
                "placeholder": self.tr("Optional"),
            },
            {
                "key": "abstract",
                "label": self.tr("Abstract"),
                "type": "textarea",
                "group": self.tr("Metadata"),
                "placeholder": self.tr("Optional"),
            },
            {
                "key": "keywords",
                "label": self.tr("Keywords"),
                "type": "text",
                "group": self.tr("Metadata"),
                "placeholder": self.tr("Optional, comma-separated"),
            },
        ]

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
                self.tr("No workspaces available. Create a workspace first.")
            )
            return

        dlg = ResourceFormDialog(
            title=self.tr("Publish a Table"),
            description=self.tr(
                "Publish a database table as a new layer. Only tables not "
                "published yet are offered."
            ),
            fields=self._publish_fields(workspace_names),
            parent=self,
        )
        dlg.get_widget("workspace").currentTextChanged.connect(
            lambda ws: self._refill_publish_combos(dlg, workspace=ws)
        )
        dlg.get_widget("datastore").currentTextChanged.connect(
            lambda ds: self._refill_publish_combos(dlg, datastore=ds)
        )
        self._refill_publish_combos(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._publish_layer_from_values(values),
            self.tr("Failed to publish '{}'").format(values["table"]),
        ):
            self.show_success_message(
                self.tr("Layer '{}' published.").format(values["table"])
            )
            self._load_layers()

    def _publish_layer_from_values(self, values):
        """Publish one table as a feature type through the library."""
        ws_name, ds_name, table = (
            values["workspace"],
            values["datastore"],
            values["table"],
        )
        # create_feature_type upserts, so an existing layer would be overwritten
        if self._resource_exists(self.gs.get_feature_type, ws_name, ds_name, table):
            raise ValueError(
                self.tr("Layer '{}' already exists in {}/{}.").format(
                    table, ws_name, ds_name
                )
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
            self.tr("Failed to load styles for '{}'").format(name),
        )
        if fetched is None:
            return
        choices, current = fetched
        if current and current not in choices:
            choices.insert(0, current)

        dlg = ResourceFormDialog(
            title=self.tr("Default style for '{}'").format(name),
            description=self.tr(
                "Global styles and the styles of workspace '{}'. Other styles the "
                "layer may use stay as they are."
            ).format(ws_name),
            fields=[
                {
                    "key": "style",
                    "label": self.tr("Default style"),
                    "type": "combo",
                    "options": choices,
                    "default": current,
                    "required": True,
                }
            ],
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        style = dlg.get_values()["style"]
        if style == current:
            return
        if self._run_action(
            lambda: self._check(self.gs.set_default_layer_style(name, ws_name, style)),
            self.tr("Failed to set the style of '{}'").format(name),
        ):
            self.show_success_message(
                self.tr("'{}' now uses style '{}'.").format(name, style)
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
                self.tr(
                    "This QGIS project has no vector or raster layer to take a style from."
                )
            )
            return
        match = self._matching_project_layer(name, layers)

        dlg = ResourceFormDialog(
            title=self.tr("Style '{}' from QGIS").format(name),
            description=self.tr(
                "The layer's symbology is exported as SLD and uploaded to "
                "workspace '{}'. A style of that name there is replaced — that "
                "is how you push a change you just made in QGIS."
            ).format(ws_name),
            fields=[
                {
                    "key": "qgis_layer",
                    "label": self.tr("QGIS layer"),
                    "type": "combo",
                    "options": [label for label, _layer in layers],
                    "default": match,
                    "required": True,
                    "help": (
                        None
                        if match
                        else self.tr("No project layer matches '{}' by name.").format(
                            name
                        )
                    ),
                },
                {
                    "key": "style",
                    "label": self.tr("Style name"),
                    "type": "text",
                    "default": name,
                    "required": True,
                },
                {
                    "key": "set_default",
                    "label": self.tr("Make it the layer's default style"),
                    "type": "checkbox",
                    "default": True,
                },
            ],
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        # The export reads a live QGIS layer, so it happens here on the GUI
        # thread, before the upload (invariant 9).
        layer = self._picked_layer(values)
        sld = self._fetch(
            lambda: layer_to_sld(layer),
            self.tr("Could not export the symbology of '{}'").format(layer.name()),
        )
        if sld is None:
            return

        style_name = values["style"]
        if self._run_action(
            lambda: self._push_qgis_style(
                style_name, ws_name, sld, name, values["set_default"]
            ),
            self.tr("Failed to upload the style of '{}'").format(layer.name()),
        ):
            self.show_success_message(
                self.tr("'{}' styled from '{}'.").format(name, layer.name())
                if values["set_default"]
                else self.tr("Style '{}' uploaded to '{}'.").format(style_name, ws_name)
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

    def _add_layer_to_qgis(self, row_data):
        """Ask which protocol, then add the layer to the current QGIS project."""
        name, ws_name = row_data[0], row_data[1]
        dlg = ResourceFormDialog(
            title=self.tr("Add '{}' to QGIS").format(name),
            description=self.tr(
                "WFS loads the features themselves (editable, styled in QGIS); WMS "
                "and WMTS load rendered images. Credentials come from the plugin's "
                "saved connection, not from the layer."
            ),
            fields=[
                {
                    "key": "protocol",
                    "label": self.tr("Load as"),
                    "type": "combo",
                    "options": list(PROTOCOLS),
                    "default": "WMS",
                    "required": True,
                }
            ],
            parent=self,
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
                    layer.error().message() or self.tr("layer is not valid")
                )
            QgsProject.instance().addMapLayer(layer)

        if self._run_action(add, self.tr("Could not add '{}' to QGIS").format(name)):
            self.show_success_message(
                self.tr("'{}' added to the project as {}.").format(name, protocol)
            )

    def _delete_layer(self, row_data):
        """Delete a single feature type after confirmation."""
        self._delete_selected_layers([row_data])

    def _delete_selected_layers(self, selected_rows):
        """Delete one or more feature types after confirmation."""
        self._delete_many(
            self.tr("layer"),
            [
                (
                    f"{row[1]}/{row[2]}/{row[0]}",
                    lambda ws=row[1], ds=row[2], name=row[0]: self._check(
                        self.gs.delete_feature_type(ws, ds, name)
                    ),
                )
                for row in selected_rows
            ],
            self._load_layers,
            # delete_feature_type sends recurse=true, which removes the
            # published layer — but GeoServer refuses outright while a layer
            # group still references it (verified against 2.28.5).
            cascade=self.tr(
                "The published layer goes too; the table or file behind it is not "
                "touched. GeoServer refuses if a layer group still uses the "
                "layer — remove it from the group first.\n\n"
            ),
        )
