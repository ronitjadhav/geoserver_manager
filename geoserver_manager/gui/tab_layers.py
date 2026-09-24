#! python3  # noqa: E265

"""
Layers tab: every published layer, whatever its type: list, inspect,
preview, style, add to QGIS, delete.

Used as a mixin for GeoServerMainDialog.
"""

import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlencode

from qgis.core import Qgis, QgsDataSourceUri, QgsProject, QgsRasterLayer, QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QApplication, QDialog, QMessageBox

from geoserver_manager.gui.dlg_preview import LayerPreviewDialog
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.scope import PENDING
from geoserver_manager.toolbelt.payload import (
    bbox_text,
    keyword_list,
    text_of,
    unwrap,
    words,
)
from geoserver_manager.toolbelt.qgis_export import (
    export_to_geopackage,
    geoserver_name,
    reprojection_target,
    require_crs,
)
from geoserver_manager.toolbelt.sld import (
    layer_to_sld,
    styleable_project_layers,
)

# The projection policies GeoServer knows, as its REST API spells them.
_PROJECTION_POLICIES = ("FORCE_DECLARED", "REPROJECT_TO_DECLARED", "NONE")

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
# *instance's* class, GeoServerMainDialog. QDialog precedes the mixins in the
# MRO, so every lookup would miss. A wrapper function would not be extracted
# at all (pylupdate only understands a literal context), hence the repetition.
translate = QCoreApplication.translate


def _kind_label(kind):
    """A layer's type in words, as the Type column shows it (#91).

    The row keeps GeoServer's own ("VECTOR", "WMS"): the row actions read it.
    """
    return {
        VECTOR: translate("LayerTabMixin", "Vector"),
        RASTER: translate("LayerTabMixin", "Raster"),
        WMS: translate("LayerTabMixin", "Cascaded WMS"),
        WMTS: translate("LayerTabMixin", "Cascaded WMTS"),
    }.get(kind, kind)


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
        # Icon-only buttons: the tooltip is all the user reads, so each says
        # what it does and how it differs from its neighbour.
        self._row_actions = [
            (
                "add-to-qgis",
                translate("LayerTabMixin", "Add to QGIS"),
                self._add_layer_to_qgis,
                translate(
                    "LayerTabMixin",
                    "Add to QGIS: load the layer into this project as WFS, WMS or "
                    "WMTS (asks which).",
                ),
            ),
            (
                "preview-map",
                translate("LayerTabMixin", "Preview"),
                self._preview_layer,
                translate(
                    "LayerTabMixin",
                    "Preview on a map inside QGIS: click the map for the feature "
                    "info at that point. Nothing is added to the project.",
                ),
            ),
            (
                "preview-browser",
                translate("LayerTabMixin", "Preview in a browser"),
                self._preview_layer_in_browser,
                translate(
                    "LayerTabMixin",
                    "Preview in a browser: GeoServer's own OpenLayers page. A "
                    "secured server will ask the browser to log in.",
                ),
            ),
            (
                "styles",
                translate("LayerTabMixin", "Set style"),
                self._set_layer_style,
                translate(
                    "LayerTabMixin",
                    "Set style: pick one of the server's existing styles as this "
                    "layer's default.",
                ),
            ),
            (
                "push-style",
                translate("LayerTabMixin", "Push style from QGIS"),
                self._style_from_qgis,
                translate(
                    "LayerTabMixin",
                    "Push style from QGIS: upload a project layer's symbology as "
                    "a new server style and make it this layer's default.",
                ),
            ),
            (
                "update-from-source",
                translate("LayerTabMixin", "Update from the data"),
                self._update_layer_from_source,
                translate(
                    "LayerTabMixin",
                    "Update from the data: GeoServer re-reads the table or file "
                    "behind the layer (its columns, a replaced file) and "
                    "recomputes its bounds.",
                ),
            ),
            (
                "delete",
                translate("LayerTabMixin", "Delete"),
                self._delete_layer,
                translate(
                    "LayerTabMixin",
                    "Delete: remove the layer from GeoServer (asks first).",
                ),
            ),
        ]
        self._setup_table(
            [
                translate("LayerTabMixin", "Name"),
                translate("LayerTabMixin", "Workspace"),
                translate("LayerTabMixin", "Type"),
                translate("LayerTabMixin", "Store"),
                translate("LayerTabMixin", "Default style"),
                self.actions_column_label(),
            ]
        )
        self._path_columns = (0, 1, 3)  # the store is in the resource's path
        self._row_detail = lambda row: self._layer_summary(f"{row[1]}:{row[0]}")
        self._detail_columns = (2, 3, 4)
        self._cell_display = {2: _kind_label}
        self._start_load(
            translate("LayerTabMixin", "Failed to load layers"), self._fetch_layer_rows
        )

    def _fetch_layer_rows(self, task=None):
        """(rows, failures) for the Layers table. Runs in a worker thread.

        GeoServer's own layer list first: every published layer, whatever its
        type (vector, raster, cascaded WMS or WMTS), then one GET per layer,
        fanned out, for the type, the store and the default style. A layer
        whose detail cannot be read still gets a row, with placeholders, and
        a warning names it.
        """
        names = self._all_layer_names()
        # Type, store and style follow for the page shown (#58); a row action
        # fetches them first when they are still pending (_addressable).
        rows = []
        for qualified in names:
            workspace, _, name = qualified.rpartition(":")
            rows.append([name, workspace, PENDING, PENDING, PENDING])
        return rows, []

    def _layers_url(self, qualified_name=None):
        """/rest/layers.json, or one layer's own document under it."""
        base = self.gs.rest_service.rest_endpoints.base_url
        if qualified_name is None:
            return f"{base}/layers.json"
        return f"{base}/layers/{quote(qualified_name, safe=':')}.json"

    def _all_layer_names(self):
        """Every layer's qualified name ("workspace:layer"), from GeoServer's
        own list. Raises on HTTP errors.

        TODO(#50): row 39: the facade has no get_layers(). Walking the
        datastores instead, as this tab did, misses every raster and cascaded
        layer; the workspace-less list is the one place they all appear.
        """
        payload = self._raw_rest("get", self._layers_url()).json()
        return sorted(
            self._name_of(layer) for layer in self._unwrap(payload, "layers", "layer")
        )

    def _refuse_vector_clash(self, ws_name, name, values):
        """Refuse a vector upload onto a store or layer it would not own."""
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
        self._refuse_layer_clash(
            ws_name, name, values.get("replace"), "data", "GeoPackage"
        )

    def _refuse_layer_clash(self, ws_name, name, replace, kind, store_type):
        """Refuse an upload that would land on another store's layer.

        Measured on 2.28.5: a layer ws:name in another store makes GeoServer
        call the new one name1, and the style and metadata that follow went to
        the old ws:name, reported as "name published". With Replace, a store
        of the name that is not the plugin's own file store (a PostGIS one)
        had GeoServer import the file's tables into that database.

        :param kind: "data" or "coverage", the store collection.
        :param store_type: the only store type Replace may overwrite.
        """
        qualified = f"{ws_name}:{name}"
        if self.gs.rest_service.resource_exists(self._layers_url(qualified)):
            if not replace:
                raise ValueError(
                    translate(
                        "LayerTabMixin",
                        "Layer '{}' already exists. Tick Replace to overwrite it, "
                        "or pick another name.",
                    ).format(qualified)
                )
            _kind, store, _style = self._layer_summary(qualified)
            if store != name:
                raise ValueError(
                    translate(
                        "LayerTabMixin",
                        "Layer '{}' is published from store '{}', which this "
                        "upload would not replace. Pick another name.",
                    ).format(qualified, store)
                )
        if not replace:
            return
        path = "{}/workspaces/{}/{}stores/{}.json".format(
            self.gs.rest_service.rest_endpoints.base_url,
            quote(ws_name, safe=""),
            kind,
            quote(name, safe=""),
        )
        if not self.gs.rest_service.resource_exists(path):
            return
        payload = self._raw_rest("get", path).json()
        found = (next(iter(payload.values()), {}) or {}).get("type") or "-"
        if found != store_type:
            raise ValueError(
                translate(
                    "LayerTabMixin",
                    "Store '{}' is a {} store. Replace only overwrites a {} store "
                    "this plugin published; pick another name.",
                ).format(name, found, store_type)
            )

    def _layer_summary(self, qualified_name):
        """(type, store, default style) of one layer. Raises on HTTP errors.

        TODO(#50): rest_service.get_layer() exists, but its Layer model keeps
        only the resource's *name*, not its class or href, which is where the
        store comes from, so this reads GeoServer's payload itself.
        """
        payload = self._raw_rest("get", self._layers_url(qualified_name)).json()
        layer = payload.get("layer") if isinstance(payload, dict) else None
        layer = layer if isinstance(layer, dict) else {}
        kind = layer.get("type") or "-"
        store = self._store_from_href((layer.get("resource") or {}).get("href"))
        if store is None and kind == WMTS:
            # GeoServer 2.28.5 writes no href for a wmtsLayer resource, so the
            # store has to be found among the workspace's WMTS stores.
            workspace, _, name = qualified_name.rpartition(":")
            store = self._wmts_store_of(workspace, name)
        style = (layer.get("defaultStyle") or {}).get("name") or "-"
        return kind, store or "-", style

    @staticmethod
    def _store_from_href(href):
        """The store in a resource href: .../workspaces/{ws}/{kind}stores/
        {store}/..., whatever host GeoServer wrote it with (behind a proxy it
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

        The same for a feature type and a coverage: the fields the edit form
        shows, flattened, and the read-only details beside them.
        """
        # A row is [name, workspace, type, store, default style].
        name, ws_name, ds_name = row_data[0], row_data[1], row_data[3]
        detail = detail if isinstance(detail, dict) else {}

        # The library's FeatureType.asdict() normalises keywords to a list and
        # attributes to a list; raw REST wraps them ({"string": […]},
        # {"attribute": […]}). Accept both: a live server showed the difference.
        keywords = keyword_list(detail.get("keywords"))

        bounds = bbox_text(detail.get("nativeBoundingBox")) or "-"

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
            or "-"
        )

        return {
            "name": name,
            "native_name": detail.get("nativeName", ""),
            "workspace": ws_name,
            "datastore": ds_name,
            "srs": detail.get("srs", ""),
            "projection_policy": detail.get("projectionPolicy", ""),
            "enabled": bool(detail.get("enabled", True)),
            "advertised": bool(detail.get("advertised", True)),
            "title": text_of(detail.get("title")),
            "abstract": text_of(detail.get("abstract")),
            "keywords": [str(k) for k in keywords],
            "cql_filter": detail.get("cqlFilter") or "",
            "bbox": bounds,
            "attributes": attribute_text,
        }

    def _layer_fields(self, kind=VECTOR):
        """The layer edit form: what GeoServer lets a partial PUT change on the
        resource first, read-only details on the Data tab.

        Every field on the first tab was measured to merge on 2.28.5 (feature
        types and coverages alike); the CQL filter exists for vectors only.
        """
        data = translate("LayerTabMixin", "Data")
        fields = [
            {
                "key": "name",
                "label": translate("LayerTabMixin", "Layer name"),
                "type": "text",
                "required": True,
                "help": translate(
                    "LayerTabMixin",
                    "Renaming keeps the data: GeoServer updates the layer groups "
                    "and the tile cache that use it. Clients that ask for the old "
                    "name stop finding it.",
                ),
            },
            {
                "key": "title",
                "label": translate("LayerTabMixin", "Title"),
                "type": "text",
            },
            {
                "key": "abstract",
                "label": translate("LayerTabMixin", "Abstract"),
                "type": "textarea",
                "max_height": 72,
            },
            {
                "key": "keywords",
                "label": translate("LayerTabMixin", "Keywords"),
                "type": "list",
            },
            {
                "key": "srs",
                "label": translate("LayerTabMixin", "SRS (EPSG code)"),
                "type": "text",
                "required": True,
                "crs": True,
                "help": translate(
                    "LayerTabMixin",
                    "The SRS GeoServer declares for the layer. Changing it "
                    "recomputes the bounds.",
                ),
            },
            {
                "key": "projection_policy",
                "label": translate("LayerTabMixin", "Projection policy"),
                "type": "combo",
                "options": list(_PROJECTION_POLICIES),
                "help": translate(
                    "LayerTabMixin",
                    "FORCE_DECLARED uses the declared SRS as it is; "
                    "REPROJECT_TO_DECLARED reprojects from the data's own; NONE "
                    "keeps the data's own.",
                ),
            },
            {
                "key": "enabled",
                "label": translate("LayerTabMixin", "Enabled"),
                "type": "checkbox",
                "help": translate(
                    "LayerTabMixin",
                    "Off: GeoServer stops serving the layer, and keeps it.",
                ),
            },
            {
                "key": "advertised",
                "label": translate("LayerTabMixin", "Advertised"),
                "type": "checkbox",
                "help": translate(
                    "LayerTabMixin",
                    "Off: it is left out of the capabilities, but still served to "
                    "whoever names it.",
                ),
            },
        ]
        if kind == VECTOR:
            fields.append(
                {
                    "key": "cql_filter",
                    "label": translate("LayerTabMixin", "CQL filter"),
                    "type": "text",
                    "placeholder": translate(
                        "LayerTabMixin", "Optional, e.g. pop > 1000"
                    ),
                    "help": translate(
                        "LayerTabMixin",
                        "Only features matching it are served. Empty for all.",
                    ),
                }
            )
        details = [
            ("native_name", translate("LayerTabMixin", "Native name")),
            ("workspace", translate("LayerTabMixin", "Workspace")),
            ("datastore", translate("LayerTabMixin", "Store")),
            ("bbox", translate("LayerTabMixin", "Native bounding box")),
        ]
        if kind == RASTER:
            details += [
                ("native_format", translate("LayerTabMixin", "Native format")),
                ("size", translate("LayerTabMixin", "Size in pixels")),
            ]
        fields += [
            {
                "key": key,
                "label": label,
                "type": "text",
                "read_only": True,
                "group": data,
            }
            for key, label in details
        ]
        if kind in (VECTOR, RASTER):
            fields.append(
                {
                    "key": "attributes" if kind == VECTOR else "bands",
                    "label": (
                        translate("LayerTabMixin", "Attributes")
                        if kind == VECTOR
                        else translate("LayerTabMixin", "Bands")
                    ),
                    "type": "textarea",
                    "read_only": True,
                    "group": data,
                }
            )
        return fields

    def _layer_resource(self, row_data):
        """The resource behind a layer row, as GeoServer stores it: a feature
        type, a coverage or a cascaded layer, by the row's type and store."""
        name, ws_name, kind, store = row_data[0], row_data[1], row_data[2], row_data[3]
        if kind == VECTOR:
            return self._feature_type_detail(ws_name, store, name)
        if kind == RASTER:
            return self._coverage_detail(ws_name, store, name)
        if kind in (WMS, WMTS):
            return self._cascaded_layer_detail(ws_name, store, kind, name)
        raise ValueError(
            translate("LayerTabMixin", "Unsupported layer type '{}'").format(kind)
        )

    def _feature_type_detail(self, ws_name, store, name):
        """One feature type, as GeoServer stores it.

        TODO(#50): upstream: get_feature_type() exists, but FeatureType drops
        cqlFilter, and title when an internationalTitle is set (row 63). The
        edit form then showed an existing filter as empty, and emptying the
        field changed nothing. Workaround: GET the feature type path.
        """
        path = self.gs.rest_service.rest_endpoints.featuretype(ws_name, store, name)
        return self._raw_rest("get", path).json().get("featureType") or {}

    def _show_layer_info(self, row_data):
        """Open a layer: an edit form for a vector or a raster, a view for a
        cascaded layer.

        Save sends one partial PUT with only what changed: GeoServer merges it
        (measured on 2.28.5), so everything the form does not show stays as it
        is. A cascaded layer stays a view: GeoServer 2.28.5 answers any PUT on a
        cascaded WMS layer with UnsupportedOperationException, JSON, XML and
        the very document a GET returned alike.
        """
        detail = self._fetch(
            lambda: self._layer_resource(row_data),
            translate("LayerTabMixin", "Failed to load layer details"),
        )
        if detail is None:
            return
        detail = detail if isinstance(detail, dict) else {}
        name, ws_name, kind, store = row_data[0], row_data[1], row_data[2], row_data[3]
        if kind in (WMS, WMTS):
            dlg = ResourceFormDialog(
                title=translate("LayerTabMixin", "Layer '{}'").format(name),
                description=translate(
                    "LayerTabMixin",
                    "Cascaded through {type} store {ws}/{store}. Read-only: "
                    "GeoServer's REST API cannot change a cascaded layer, its web "
                    "UI can.",
                ).format(type=kind, ws=ws_name, store=store),
                fields=[
                    f for f in self._cascaded_layer_fields([]) if f["key"] != "layer"
                ],
                values=self._cascaded_layer_form_values(detail),
                parent=self,
            )
            dlg.hide_save_button()
            dlg.exec()
            return

        values = self._layer_form_values(row_data, detail)
        if kind == RASTER:
            coverage = self._coverage_form_values(detail)
            values.update(
                native_format=coverage.get("native_format", ""),
                size=coverage.get("size", ""),
                bands=coverage.get("bands", ""),
            )
        before = dict(values)
        dlg = ResourceFormDialog(
            title=translate("LayerTabMixin", "Layer '{}'").format(name),
            description=translate(
                "LayerTabMixin", "Published from {ws}/{store}."
            ).format(ws=ws_name, store=store),
            fields=self._layer_fields(kind),
            values=values,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        after = dlg.get_values()
        if self._layer_changes(before, after, kind)[0] is None:
            return  # nothing changed: no request
        if self._run_action(
            # In the worker, behind the waiting box: a slow server must not
            # freeze QGIS on Save either.
            lambda: self._wait_for_save(
                lambda: self._save_layer(row_data, before, after)
            ),
            translate("LayerTabMixin", "Failed to save layer '{}'").format(name),
        ):
            self.show_success_message(
                translate("LayerTabMixin", "Layer '{}' saved.").format(after["name"])
            )
            self._load_layers()

    @staticmethod
    def _layer_changes(before, after, kind):
        """(body, recalculate) for a partial resource PUT, or (None, False).

        Only the fields that changed go out, in GeoServer's own spelling; an
        emptied title, abstract, keyword list or filter is sent empty, which
        clears it (measured). A changed SRS or projection policy recomputes
        the bounds in the same request. Pure, so the mapping is testable.
        """

        def srs(text):
            code = str(text or "").strip().upper().removeprefix("EPSG:")
            return f"EPSG:{code}"

        body = {}
        for key, rest_key in (
            ("name", "name"),
            ("title", "title"),
            ("abstract", "abstract"),
            ("projection_policy", "projectionPolicy"),
            ("enabled", "enabled"),
            ("advertised", "advertised"),
        ):
            if after.get(key) != before.get(key):
                body[rest_key] = after.get(key)
        if kind == VECTOR and (after.get("cql_filter") or "") != (
            before.get("cql_filter") or ""
        ):
            body["cqlFilter"] = after.get("cql_filter") or ""
        if words(after.get("keywords")) != words(before.get("keywords")):
            body["keywords"] = {"string": words(after.get("keywords"))}
        if srs(after.get("srs")) != srs(before.get("srs")):
            body["srs"] = srs(after.get("srs"))
        recalculate = "srs" in body or "projectionPolicy" in body
        return (body or None), recalculate

    def _resource_path(self, workspace_name, kind, store, name):
        """REST path of the resource behind a vector or raster layer, quoted."""
        endpoints = self.gs.rest_service.rest_endpoints
        segments = [quote(part, safe="") for part in (workspace_name, store, name)]
        if kind == RASTER:
            return endpoints.coverage(*segments)
        return endpoints.featuretype(*segments)

    def _save_layer(self, row_data, before, after):
        """Validate, then PUT what changed on the layer's resource.

        TODO(#50): no update_feature_type() or update_coverage() in the
        library (row 53). create_feature_type() upserts by the *new* name, so a
        rename would POST a second layer, and it knows no cqlFilter; coverages
        have no update at all. Workaround: one merging PUT on the resource.
        """
        _name, ws_name, kind, store = row_data[0], row_data[1], row_data[2], row_data[3]
        body, recalculate = self._layer_changes(before, after, kind)
        if body is None:
            return
        if "name" in body:
            self._require_safe_name(body["name"])
            base = self.gs.rest_service.rest_endpoints.base_url
            qualified = "{}:{}".format(ws_name, body["name"])
            taken = f"{base}/layers/{quote(qualified, safe=':')}.json"
            try:
                self._raw_rest("get", taken)
            except RuntimeError:
                pass  # free (404)
            else:
                raise ValueError(
                    translate(
                        "LayerTabMixin", "Layer '{}' already exists in '{}'."
                    ).format(body["name"], ws_name)
                )
        if "srs" in body and not body["srs"].removeprefix("EPSG:").isdigit():
            raise ValueError(
                translate(
                    "LayerTabMixin",
                    "The SRS must be an EPSG code number, such as 3857 or 4326.",
                )
            )
        wrapper = "coverage" if kind == RASTER else "featureType"
        self._raw_rest(
            "put",
            self._resource_path(ws_name, kind, store, before["name"]),
            json={wrapper: body},
            params={"recalculate": "nativebbox,latlonbbox"} if recalculate else None,
        )

    def _update_layer_from_source(self, row_data):
        """Re-read the data behind a layer, then recompute its bounds.

        After the table gained a column or the file was replaced: GeoServer
        keeps the resource's schema cached until reset. TODO(#50): neither
        call is in the library (row 53): POST .../reset, then a PUT with
        ?recalculate=nativebbox,latlonbbox (both measured on 2.28.5).
        """
        name, ws_name, kind, store = row_data[0], row_data[1], row_data[2], row_data[3]
        if kind not in (VECTOR, RASTER):
            self.show_warning_message(
                translate(
                    "LayerTabMixin",
                    "'{}' is a cascaded layer: GeoServer's REST API cannot update "
                    "it, its web UI can.",
                ).format(name)
            )
            return
        path = self._resource_path(ws_name, kind, store, name)
        wrapper = "coverage" if kind == RASTER else "featureType"

        def update():
            self._raw_rest("post", path.removesuffix(".json") + "/reset")
            self._raw_rest(
                "put",
                path,
                json={wrapper: {"name": name}},
                params={"recalculate": "nativebbox,latlonbbox"},
            )

        if self._run_action(
            lambda: self._wait_for_save(update),
            translate("LayerTabMixin", "Failed to update '{}' from its data").format(
                name
            ),
        ):
            self.show_success_message(
                translate(
                    "LayerTabMixin", "'{}' re-read from its data, bounds recomputed."
                ).format(name)
            )

    # -- Publish --------------------------------------------------------------

    def _available_tables(self, workspace_name, datastore_name):
        """Tables of a datastore that are not published as layers yet.

        TODO(#50): upstream as get_available_feature_types(ws, ds); the
        library has no call for GeoServer's ?list=available. Workaround: GET
        the featuretypes path with that query.
        """
        path = self.gs.rest_service.rest_endpoints.featuretypes(
            workspace_name, datastore_name
        )
        payload = self._raw_rest("get", path, params={"list": "available"}).json()
        return sorted(self._unwrap(payload, "list", "string"))

    def _publish_fields(self, workspace_names):
        """Field definitions for the publish form; combos cascade at runtime."""
        return [
            {
                "key": "source",
                "label": translate("LayerTabMixin", "Source"),
                "type": "combo",
                "options": [
                    (
                        translate("LayerTabMixin", "A table in a datastore"),
                        _SOURCE_TABLE,
                    ),
                    (
                        translate("LayerTabMixin", "A layer from this QGIS project"),
                        _SOURCE_QGIS,
                    ),
                ],
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
                # Short: the longest label sets the width of the label column
                # for the whole form, and this one squeezed every combo.
                "label": translate("LayerTabMixin", "SRS (EPSG code)"),
                "type": "text",
                "required": True,
                "placeholder": translate("LayerTabMixin", "e.g. 3857"),
                "crs": True,
                # Required, so on the first tab: on Metadata it bounced the
                # user there after Publish.
                "help": translate(
                    "LayerTabMixin",
                    "The SRS GeoServer declares for the layer: the table's own, as "
                    "a bare EPSG number. A wrong value misplaces the data. Look it "
                    "up in the table's geometry column; GeoServer's web UI can "
                    "compute it.",
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
                "type": "list",
                "group": translate("LayerTabMixin", "Metadata"),
            },
            {
                "key": "qgis_layer",
                "label": translate("LayerTabMixin", "QGIS layer"),
                "type": "layer",
                "required": True,
                "visible": False,
                "help": translate(
                    "LayerTabMixin",
                    "A vector is written to a GeoPackage and becomes a datastore; "
                    "a raster to a GeoTIFF and becomes a coverage store. Either way "
                    "the data is copied to the server, not linked.",
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
                    "Also the name of the store it creates (and, for a vector, of "
                    "the table inside it). Anything a layer name cannot carry is "
                    "replaced.",
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
                "help": translate(
                    "LayerTabMixin",
                    "Vector layers only. A raster's symbology is not uploaded.",
                ),
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
            self._on_publish_layer_picked(
                dlg, dlg.get_widget("qgis_layer").currentLayer()
            )

    def _on_publish_layer_picked(self, dlg, layer):
        """Suggest the name, and hide what a raster ignores (its symbology)."""
        self._prefill_publish_name(dlg, layer)
        dlg.set_field_visible("with_style", not isinstance(layer, QgsRasterLayer))

    @staticmethod
    def _prefill_publish_name(dlg, layer):
        """Suggest the GeoServer-safe form of the picked layer's name."""
        widget = dlg.get_widget("name")
        if layer is not None and not widget.text().strip():
            widget.setText(geoserver_name(layer.name()))

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
                ds_combo.addItems(
                    self._wait_for(lambda: self._datastore_names(workspace))
                )
            except Exception as e:
                self.log(f"Could not list datastores of {workspace}: {e}")
            ds_combo.blockSignals(False)
            datastore = ds_combo.currentText()

        table_combo.clear()
        if workspace and datastore:
            try:
                table_combo.addItems(
                    self._wait_for(lambda: self._available_tables(workspace, datastore))
                )
            except Exception as e:
                self.log(f"Could not list tables of {workspace}/{datastore}: {e}")

    def _publish_layer(self, layer=None):
        """Open the publish form: pick workspace, datastore and table.

        :param layer: a project layer to preselect as the source, which is how
            the layer tree's *Publish to GeoServer* entry opens this form.
        """
        workspace_names = self._fetch(
            self._get_workspace_names,
            translate("LayerTabMixin", "Failed to load the workspaces"),
        )
        if workspace_names is None:
            return
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
                "project, uploaded as a GeoPackage (a vector becomes a datastore) "
                "or as a GeoTIFF (a raster becomes a coverage store).",
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
        dlg.on_value_changed(
            "source", lambda source: self._on_publish_source_changed(dlg, source)
        )
        dlg.get_widget("qgis_layer").layerChanged.connect(
            lambda layer: self._on_publish_layer_picked(dlg, layer)
        )
        self._refill_publish_combos(dlg)
        self._on_publish_source_changed(dlg, _SOURCE_TABLE)
        if layer is not None:
            # The layer first: switching the source prefills the name from
            # whichever layer the combo shows at that moment.
            dlg.get_widget("qgis_layer").setLayer(layer)
            dlg.set_values({"source": _SOURCE_QGIS})
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if values.get("source") == _SOURCE_QGIS:
            # The checks and the export raise here, under the wait cursor; the
            # upload then streams in a task and reports itself.
            self._run_action(
                lambda: self._publish_qgis_layer(values),
                translate("LayerTabMixin", "Failed to publish '{}'").format(
                    geoserver_name(values["name"])
                ),
            )
            return
        published = values["table"]
        if self._run_action(
            lambda: self._wait_for_save(lambda: self._publish_table(values)),
            translate("LayerTabMixin", "Failed to publish '{}'").format(published),
        ):
            self.show_success_message(
                translate("LayerTabMixin", "Layer '{}' published.").format(published)
            )
            self._load_layers()

    def _publish_layers(self, layers):
        """Publish several project layers into one workspace, one after another.

        One small form (workspace, Replace, style) for all of them; each layer
        keeps its own GeoServer-safe name. Only one upload runs at a time, so
        each layer starts when the previous one has ended. A layer refused
        before any request, or whose upload fails, is reported and skipped;
        Cancel stops the batch, and the summary names what was published and
        what was not.
        """
        names = [geoserver_name(layer.name()) for layer in layers]
        clashes = sorted({name for name in names if names.count(name) > 1})
        if clashes:
            # Published one after another, the second would replace the first
            # (with Replace) or be refused as existing (without it).
            self.show_warning_message(
                translate(
                    "LayerTabMixin",
                    "These layers would get the same GeoServer name: {}. "
                    "Rename them in QGIS first.",
                ).format(", ".join(clashes))
            )
            return
        if not self._upload_slot_free():
            return
        workspace_names = self._fetch(
            self._get_workspace_names,
            translate("LayerTabMixin", "Failed to load the workspaces"),
        )
        if workspace_names is None:
            return
        if not workspace_names:
            self.show_warning_message(
                translate(
                    "LayerTabMixin",
                    "No workspaces available. Create a workspace first.",
                )
            )
            return
        fields = [
            dict(field, visible=True)
            for field in self._publish_fields(workspace_names)
            if field["key"] in ("workspace", "replace", "with_style")
        ]
        listing = "\n".join(
            f"  • {layer.name()} → {name}" for layer, name in zip(layers, names)
        )
        dlg = ResourceFormDialog(
            title=translate("LayerTabMixin", "Publish %n Layer(s)", None, len(layers)),
            description=translate(
                "LayerTabMixin",
                "Each layer is uploaded on its own, under the name shown: a vector "
                "as a GeoPackage datastore, a raster as a GeoTIFF coverage store."
                "\n\n{}",
            ).format(listing),
            fields=fields,
            parent=self,
            ok_label=translate("LayerTabMixin", "Publish"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.get_values()
        queue = list(zip(layers, names))
        published, failed = [], []

        def summary(stopped):
            left = [name for _layer, name in queue]
            if not failed and not left:
                self.show_success_message(
                    translate(
                        "LayerTabMixin", "%n layer(s) published.", None, len(published)
                    )
                )
                return
            parts = [
                translate("LayerTabMixin", "Published: {}.").format(
                    ", ".join(published) or "-"
                )
            ]
            if failed:
                parts.append(
                    translate("LayerTabMixin", "Failed: {}.").format(", ".join(failed))
                )
            if stopped and left:
                parts.append(
                    translate("LayerTabMixin", "Not started: {}.").format(
                        ", ".join(left)
                    )
                )
            self.show_warning_message(" ".join(parts))

        def next_layer():
            if not queue:
                summary(stopped=False)
                return
            layer, name = queue.pop(0)

            def done(outcome):
                if outcome == "cancelled":
                    # The cancelled layer itself is reported by the upload.
                    summary(stopped=True)
                    return
                (published if outcome == "done" else failed).append(name)
                next_layer()

            started = []
            self._run_action(
                lambda: started.append(
                    self._publish_qgis_layer(
                        {
                            "workspace": values["workspace"],
                            "name": layer.name(),
                            "replace": values.get("replace"),
                            "with_style": values.get("with_style"),
                        },
                        layer=layer,
                        on_done=done,
                    )
                ),
                translate("LayerTabMixin", "Failed to publish '{}'").format(name),
            )
            if started != [True]:
                failed.append(name)
                next_layer()

        next_layer()

    def _publish_qgis_layer(self, values, layer=None, on_done=None):
        """Upload a QGIS layer and publish it: a GeoPackage datastore for a
        vector, a GeoTIFF coverage store for a raster.

        One store per published layer, named after it, which is also the name
        of the table inside the GeoPackage. GeoServer configures a feature
        type per table when the file lands, so this publishes the layer in one
        request. The data is copied: later edits in QGIS do not reach it, and
        deleting the store leaves the uploaded file in the data directory.

        The layer, its CRS, the name check, the export and the SLD happen here
        on the GUI thread (a live QGIS layer, invariant 9), and raise into the
        caller's _run_action; the PUT then streams in a task through
        _upload_file, with progress and Cancel, and the metadata and the style
        follow on the GUI thread once it lands. A raster goes down the Coverage
        Stores tab's path (_publish_qgis_raster), the same Replace semantics.

        `layer` overrides the form's pick (a batch hands each one in), and
        `on_done(outcome)` runs once the upload has ended however it ended.
        Returns True when an upload started, so a batch can tell a layer
        refused before any request from one still on its way.

        TODO(#50): upstream as create_datastore_from_file(ws, name, path); the
        library can only create datastores from connection parameters, so the
        upload is a raw PUT of .../datastores/{name}/file.gpkg (row 28).
        """
        if not self._upload_slot_free():
            return False
        ws_name = values["workspace"]
        name = geoserver_name(values["name"])
        if layer is None:
            layer = values["qgis_layer"]
        if isinstance(layer, QgsRasterLayer):
            return self._publish_qgis_raster(
                {
                    "workspace": ws_name,
                    "name": values["name"],
                    "replace": values.get("replace"),
                    "title": values.get("title", ""),
                    "abstract": values.get("abstract", ""),
                    "keywords": values.get("keywords", ""),
                },
                layer=layer,
                on_done=on_done,
            )
        require_crs(layer)
        # The checks are reads: off the GUI thread (the export below is not).
        self._wait_for(lambda: self._refuse_vector_clash(ws_name, name, values))

        # Before the export: a failure here used to leave the GeoPackage behind.
        sld = layer_to_sld(layer) if values.get("with_style") else None
        # A CRS without an EPSG code would be published as UNKNOWN: the export
        # reprojects it to one GeoServer can declare (reprojection_target).
        folder = Path(tempfile.mkdtemp(prefix="gsm_publish_"))
        package = folder / f"{name}.gpkg"
        try:
            export_to_geopackage(
                layer, package, name, target_crs=reprojection_target(layer)
            )
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        upload_path = (
            f"{self.gs.rest_service.rest_endpoints.base_url}"
            f"/workspaces/{quote(ws_name, safe='')}/datastores/{quote(name, safe='')}"
            "/file.gpkg"
        )
        failure = translate("LayerTabMixin", "Failed to publish '{}'").format(name)

        def published(_result):
            if self.gs is None:  # a Refresh dropped the client meanwhile
                self.show_warning_message(
                    translate(
                        "LayerTabMixin",
                        "Layer '{}' uploaded. Reconnect to finish its metadata "
                        "and style.",
                    ).format(name)
                )
                return

            def server_side():
                # Best effort: the data is published at this point, so a
                # failure to set a performance flag belongs in the log, not in
                # the user's face.
                try:
                    self._make_datastore_read_only(ws_name, name)
                except Exception as error:
                    self.log(
                        f"Could not mark '{ws_name}:{name}' read-only: {error}",
                        log_level=Qgis.MessageLevel.Warning,
                    )
                self._set_feature_type_metadata(ws_name, name, values)

            def finish():
                self._wait_for_save(server_side)  # requests, off the GUI thread
                if sld is not None:
                    self._push_qgis_style(name, ws_name, sld, name, True)

            done = translate(
                "LayerTabMixin",
                "Layer '{}' is published, but its title, keywords or style "
                "could not be set",
            ).format(name)
            if self._run_action(lambda: self._partly_saved(finish, done), failure):
                self.show_success_message(
                    translate("LayerTabMixin", "Layer '{}' published.").format(name)
                )
            # The user may have moved to another tab while it uploaded.
            self._reload_current_tab()

        return self._upload_file(
            failure,
            self.gs.rest_service.rest_client,
            upload_path,
            package,
            {"update": "overwrite"},
            {"Content-Type": "application/x-sqlite3"},
            published,
            lambda _task: self._report_cancelled_upload(
                translate("LayerTabMixin", "datastore"),
                translate("LayerTabMixin", "Datastores"),
                lambda: self._resource_exists(self.gs.get_datastore, ws_name, name),
                name,
            ),
            folder=folder,
            on_done=on_done,
        )

    def _make_datastore_read_only(self, workspace_name, name):
        """Mark an uploaded GeoPackage store read-only.

        Nothing writes to a GeoPackage the plugin has just uploaded, and a
        read-only file store is the recommended setting for that case; it
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
        survive, which create_feature_type() would overwrite with a template.
        """
        keywords = words(values.get("keywords"))
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
        epsg = str(values.get("epsg") or "").strip().upper().removeprefix("EPSG:")
        if not epsg.isdigit():
            raise ValueError(
                translate(
                    "LayerTabMixin",
                    "The SRS must be an EPSG code number, such as 3857 or 4326.",
                )
            )
        keywords = words(values.get("keywords"))
        # TODO(#50): the facade's create_feature_type(epsg=...) fills both
        # bounding boxes from utils.EPSG_BBOX, which knows 2056, 4326 and 3857
        # only: any other code raised KeyError before a request was sent, and
        # 4326 or 3857 published a world extent. The model without epsg_code
        # sends no box, and GeoServer computes both from the data (measured on
        # 2.28.5 with an EPSG:25832 table).
        from geoservercloud.models.featuretype import FeatureType

        self._check(
            self.gs.rest_service.create_feature_type(
                FeatureType(
                    name=table,
                    native_name=table,
                    workspace_name=ws_name,
                    store_name=ds_name,
                    srs=f"EPSG:{int(epsg)}",
                    projection_policy="FORCE_DECLARED",
                    title=values.get("title") or None,
                    abstract=values.get("abstract") or None,
                    keywords=keywords or None,
                )
            )
        )

    # -- Default style --------------------------------------------------------

    def _layer_styles(self, workspace_name, name):
        """(default style, [other styles]) of a layer. Raises on HTTP errors.

        TODO(#50): rest_service.get_layer() keeps a single other style as the
        bare {"name", "href"} dict GeoServer sends, and Layer.asdict() then
        reads its keys as two styles, "name" and "href" (row 62): Set style
        refused to save, and deleting those lines wiped the real style. So
        the layer document is read here and unwrapped like every list.
        """
        payload = self._raw_rest(
            "get", self._layers_url(f"{workspace_name}:{name}")
        ).json()
        layer = payload.get("layer") or {}
        default = (layer.get("defaultStyle") or {}).get("name")
        others = [
            self._name_of(style)
            for style in unwrap(layer, "styles", "style")
            if isinstance(style, dict)
        ]
        return default, others

    def _style_choices(self, workspace_name):
        """Styles a layer in this workspace may use: global ones and its workspace's.

        A workspace style is referenced by its qualified name, "ws:style".
        """
        choices = [self._name_of(st) for st in self._fetch_list(self.gs.get_styles)]
        if workspace_name:  # the global scope has no workspace styles of its own
            choices += [
                f"{workspace_name}:{self._name_of(st)}"
                for st in self._fetch_list(self.gs.get_styles, workspace_name)
            ]
        return sorted(choices)

    def _set_layer_style(self, row_data):
        """Pick the default style of one layer, and the other styles it offers.

        The other styles are what a client may ask for with STYLES=; GeoServer
        lists them in the capabilities. Both go out only when they changed:
        the default through set_default_layer_style(), the others through
        rest_service.update_layer(), whose layer PUT replaces the list
        (measured on 2.28.5; an empty list clears it).
        """
        name, ws_name = row_data[0], row_data[1]
        fetched = self._fetch(
            lambda: (
                self._style_choices(ws_name),
                self._layer_styles(ws_name, name),
            ),
            translate("LayerTabMixin", "Failed to load styles for '{}'").format(name),
        )
        if fetched is None:
            return
        choices, (current, others) = fetched
        if current and current not in choices:
            choices.insert(0, current)

        dlg = ResourceFormDialog(
            title=translate("LayerTabMixin", "Styles of '{}'").format(name),
            description=translate(
                "LayerTabMixin",
                "Global styles and the styles of workspace '{}'.",
            ).format(ws_name),
            fields=[
                {
                    "key": "style",
                    "label": translate("LayerTabMixin", "Default style"),
                    "type": "combo",
                    "options": choices,
                    "default": current,
                    "required": True,
                },
                {
                    "key": "others",
                    "label": translate("LayerTabMixin", "Other styles"),
                    "type": "table",
                    "unique": True,
                    "default": list(others),
                    "choices": choices,
                    "columns": [{"label": translate("LayerTabMixin", "Style")}],
                    "help": translate(
                        "LayerTabMixin",
                        "The styles a client may also ask for. Empty for none.",
                    ),
                },
            ],
            parent=self,
            ok_label=translate("LayerTabMixin", "Set styles"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        values = dlg.get_values()
        style = values["style"]
        wanted = [name.strip() for name in values["others"] if name.strip()]
        wanted = list(dict.fromkeys(s for s in wanted if s != style))  # no repeats
        unknown = [s for s in wanted if s not in choices]
        if unknown:
            self.show_error_message(
                translate("LayerTabMixin", "No style named {} on the server.").format(
                    ", ".join(f"'{s}'" for s in unknown)
                )
            )
            return
        if style == current and sorted(wanted) == sorted(others):
            return

        def save():
            if style != current:
                self._check(self.gs.set_default_layer_style(name, ws_name, style))
            if sorted(wanted) != sorted(others):
                from geoservercloud.models.layer import Layer

                self._check(
                    self.gs.rest_service.update_layer(
                        Layer(name=name, styles=[{"name": s} for s in wanted]), ws_name
                    )
                )

        if self._run_action(
            lambda: self._wait_for_save(save),
            translate("LayerTabMixin", "Failed to set the styles of '{}'").format(name),
        ):
            self.show_success_message(
                translate("LayerTabMixin", "Styles of '{}' saved.").format(name)
            )
            self._load_layers()

    # -- Style from QGIS -------------------------------------------------------

    @staticmethod
    def _matching_project_layer(layer_name, layers):
        """The project layer that looks like this GeoServer layer, or None.

        Matched on the name, ignoring case and any "workspace:" prefix, because
        that is how a layer added by this plugin (or by QGIS's own browser)
        comes into a project.
        """
        wanted = layer_name.split(":")[-1].casefold()
        for layer in layers:
            if layer.name().split(":")[-1].casefold() == wanted:
                return layer
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
                "workspace '{}'. A style of that name there is replaced, that "
                "is how you push a change you just made in QGIS.",
            ).format(ws_name),
            fields=[
                {
                    "key": "qgis_layer",
                    "label": translate("LayerTabMixin", "QGIS layer"),
                    "type": "layer",
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
        layer = values["qgis_layer"]
        sld = self._fetch(
            lambda: layer_to_sld(layer),
            translate("LayerTabMixin", "Could not export the symbology of '{}'").format(
                layer.name()
            ),
            in_worker=False,
        )
        if sld is None:
            return

        style_name = geoserver_name(values["style"])
        outcome = {}
        if not self._run_action(
            lambda: outcome.setdefault(
                "pushed",
                self._push_qgis_style(
                    style_name, ws_name, sld, name, values["set_default"]
                ),
            ),
            translate("LayerTabMixin", "Failed to upload the style of '{}'").format(
                layer.name()
            ),
        ):
            return
        if not outcome.get("pushed"):
            self.show_warning_message(
                translate("LayerTabMixin", "Style '{}' left as it is.").format(
                    style_name
                )
            )
        else:
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

        Returns False when the style exists and the user chose to keep it:
        a style is shared, and every layer using it
        would render differently, so replacing is confirmed, never silent
        (the Styles tab refuses an existing name outright; here replacing is
        the stated workflow: push the change you just made in QGIS).

        Workspace styles are referenced by their qualified name, so the layer's
        defaultStyle gets "workspace:style"; a bare name there would resolve
        to a global style of the same name instead.
        """
        # The requests run off the GUI thread; only the question stays on it.
        exists = self._wait_for(
            lambda: self._resource_exists(
                self.gs.get_style_definition, style_name, workspace_name
            )
        )
        if exists and not self._confirm_replace_style(style_name, workspace_name):
            return False

        def write():
            if exists:
                self._put_sld_body(style_name, workspace_name, sld)
            else:
                # One request: a definition created first stayed behind,
                # empty, when GeoServer refused the body (_create_style).
                self._create_style(style_name, workspace_name, "sld", sld)
            if set_default:
                self._check(
                    self.gs.set_default_layer_style(
                        layer_name, workspace_name, f"{workspace_name}:{style_name}"
                    )
                )

        self._wait_for_save(write)
        return True

    def _confirm_replace_style(self, style_name, workspace_name):
        """Ask before a push overwrites a style other layers may share."""
        QApplication.setOverrideCursor(
            Qt.CursorShape.ArrowCursor
        )  # a caller's wait cursor
        try:
            reply = QMessageBox.question(
                self,
                translate("LayerTabMixin", "Replace the style?"),
                translate(
                    "LayerTabMixin",
                    "Style '{style}' already exists in '{workspace}'. Replace it? "
                    "Every layer that uses it will render differently.",
                ).format(style=style_name, workspace=workspace_name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
        finally:
            QApplication.restoreOverrideCursor()
        return reply == QMessageBox.StandardButton.Yes

    # -- Add to QGIS ----------------------------------------------------------

    @staticmethod
    def _layer_uri(protocol, base_url, qualified_name, authcfg=""):
        """Provider URI for one GeoServer layer. Returns (uri, provider_key).

        Credentials never go in the URI: `authcfg` is the id of the QGIS
        authentication config the plugin already stores, and the providers
        resolve it themselves, so a saved project holds no password.
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
            # No crs= here: the tile matrix set fixes it (EPSG:900913), and a
            # crs=EPSG:4326 alongside made QGIS accept the layer and reproject
            # every tile on the fly (measured on 2.28.5 / QGIS 3.44).
            return (
                f"format=image/png&layers={qualified_name}&styles="
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

        A URL for the browser, not a request from the plugin: the browser's
        session is not the plugin's, so a secured server asks it to log in.
        Without a usable bbox the map opens on the world. 768 px on the long
        side and the other from the bbox's aspect, as GeoServer's own Layer
        Preview page computes them.
        """
        base = base_url.rstrip("/")
        service = (
            f"{base}/{quote(workspace, safe='')}/wms" if workspace else f"{base}/wms"
        )
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

        The map layer is built like *Add to QGIS* builds one (credentials as
        the auth config id), but it lives in the preview window only: nothing
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
                "WMS and WMTS load rendered images. This layer has no features to "
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
                    # The features themselves for a vector; images otherwise.
                    "default": "WFS" if kind == VECTOR else "WMS",
                    "required": True,
                }
            ],
            parent=self,
            ok_label=translate("LayerTabMixin", "Add"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        protocol = dlg.get_values()["protocol"]

        def build():
            settings = self.plg_settings.get_plg_settings()
            uri, provider = self._layer_uri(
                protocol,
                settings.geoserver_url,
                f"{ws_name}:{name}",
                settings.geoserver_auth_cfg_id,
            )
            layer_class = QgsVectorLayer if provider == "WFS" else QgsRasterLayer
            # The constructor reads the capabilities: a request, so a worker's.
            layer = layer_class(uri, name, provider)
            if not layer.isValid():
                # Build first and check, instead of iface.addRasterLayer(), so an
                # unreachable layer becomes our banner rather than QGIS's modal.
                raise RuntimeError(
                    layer.error().message()
                    or translate("LayerTabMixin", "layer is not valid")
                )
            return layer

        layer = self._fetch(
            build, translate("LayerTabMixin", "Could not add '{}' to QGIS").format(name)
        )
        if layer is not None:
            QgsProject.instance().addMapLayer(layer)
            self.show_success_message(
                translate("LayerTabMixin", "'{}' added to the project as {}.").format(
                    name, protocol
                )
            )

    def _delete_layer(self, row_data):
        """Delete a single layer, with its resource, after confirmation."""
        self._delete_selected_layers([row_data])

    def _delete_layer_resource(self, workspace_name, kind, store, name):
        """Remove the resource behind a layer: the published layer goes with it."""
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
            lambda n: translate("LayerTabMixin", "%n layer(s)", None, n),
            # Every resource delete sends recurse=true, which removes the
            # published layer, but GeoServer refuses outright while a layer
            # group still references it (verified against 2.28.5).
            cascade=translate(
                "LayerTabMixin",
                "The published layer goes too; the table, file or remote layer "
                "behind it is not touched. GeoServer refuses while a layer group "
                "still uses the layer: remove it from the group first.",
            ),
        )
