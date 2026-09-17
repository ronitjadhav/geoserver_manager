#! python3  # noqa: E265

"""
Layers tab — list, view and delete feature types.

Used as a mixin for GeoServerMainDialog.
"""

from qgis.core import QgsDataSourceUri, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

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
        """List every feature type on the server, with its SRS and enabled flag."""

        def load():
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
                ("mActionDeleteSelected.svg", self.tr("Delete"), self._delete_layer),
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

            # Three levels: workspaces -> datastores -> feature types, then one
            # detail GET per feature type for the SRS and enabled columns (the
            # list endpoint only returns names). Each level is fanned out and
            # tolerant, so one unreadable parent costs a warning, not the table.
            failures = []
            stores = []
            ws_names = self._get_workspace_names()
            for ws_name, (ds_names, error) in zip(
                ws_names, self._fan_out(self._datastore_names, ws_names)
            ):
                if error:
                    failures.append((ws_name, error))
                    continue
                stores.extend((ws_name, ds_name) for ds_name in ds_names)

            layers = []
            for (ws_name, ds_name), (names, error) in zip(
                stores, self._fan_out(lambda store: self._layer_names(*store), stores)
            ):
                if error:
                    failures.append((f"{ws_name}/{ds_name}", error))
                    continue
                layers.extend((ws_name, ds_name, name) for name in names)

            summaries = self._fan_out(lambda layer: self._layer_summary(*layer), layers)
            rows = []
            for (ws_name, ds_name, name), (summary, error) in zip(layers, summaries):
                if error:
                    failures.append((f"{ws_name}/{ds_name}/{name}", error))
                srs, enabled = summary or ("—", "—")
                rows.append([name, ws_name, ds_name, srs, enabled])

            self._populate_rows(rows)
            self._report_partial_failures(failures)

        self._run_action(load, self.tr("Failed to load layers"))

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
