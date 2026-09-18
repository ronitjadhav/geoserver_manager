#! python3  # noqa: E265

"""
Coverage Stores tab — list and create raster stores, view and publish their
coverages, delete a store.

Used as a mixin for GeoServerMainDialog. Two helpers come from its siblings on
that class: `_open_workspace_from_row` (DatastoreTabMixin) and `_unwrap`, which
flattens GeoServer's collection payloads (LayerGroupTabMixin).

A coverage store is to rasters what a datastore is to tables, with one twist:
creating the store does not publish anything (except for an ImageMosaic built
from a directory, which auto-discovers its coverages), so a new store starts
with zero coverages and the *Publish* row action turns one into a layer.
"""

from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

# Store types offered by the Add form. GeoServer knows more (ArcGrid, WorldImage,
# NetCDF, …); these are the ones the library has a call for.
GEOTIFF = "GeoTIFF"
COG = "GeoTIFF (COG)"
MOSAIC_DIRECTORY = "ImageMosaic (server directory)"
MOSAIC_ZIP = "ImageMosaic (properties ZIP)"
STORE_TYPES = (GEOTIFF, COG, MOSAIC_DIRECTORY, MOSAIC_ZIP)

# A cloud-optimised GeoTIFF is a GeoTIFF store plus this metadata entry; the
# library turns {"cogSettings": …} into GeoServer's {"@key": "CogSettings.Key"}
# wrapper itself. Needs GeoServer's COG extension installed server-side.
_COG_METADATA = {"cogSettings": {"rangeReaderSettings": "HTTP"}}

# Fields of the Add form that belong to one store type only.
_TYPE_FIELDS = {
    GEOTIFF: ("url",),
    COG: ("url",),
    MOSAIC_DIRECTORY: ("directory",),
    MOSAIC_ZIP: ("zip",),
}


class CoverageStoreTabMixin:
    """Mixin that adds coverage-store methods to the main dialog.

    ponytail: same translation caveat as the other tab mixins — self.tr() here
    is extracted under this class but resolved against the host dialog.
    """

    # -- Listing ---------------------------------------------------------------

    def _load_coverage_stores(self):
        """Arm the Coverage Stores tab, then fetch its rows in the background."""
        self._setup_add_button(
            self.tr("Add a Coverage Store"),
            self.tr("Create a raster store from a GeoTIFF, a COG or an ImageMosaic"),
            self._add_coverage_store,
        )
        self._setup_delete_selected_button(self._delete_selected_coverage_stores)
        self._name_click_callback = self._show_coverage_store_info
        self._extra_click_callbacks = {
            self.tr("Workspace"): self._open_workspace_from_row
        }
        self._row_actions = [
            (
                "mIconRaster.svg",
                self.tr("Coverages"),
                self._show_coverages,
            ),
            (
                "mActionAddRasterLayer.svg",
                self.tr("Publish a coverage"),
                self._publish_coverage,
            ),
            (
                "mActionDeleteSelected.svg",
                self.tr("Delete"),
                self._delete_coverage_store,
            ),
        ]
        self._setup_table(
            [
                self.tr("Coverage Store"),
                self.tr("Workspace"),
                self.tr("Type"),
                self.tr("Coverages"),
                self.tr("Actions"),
            ]
        )
        self._start_load(
            self.tr("Failed to load coverage stores"), self._fetch_coverage_store_rows
        )

    def _fetch_coverage_store_rows(self, task=None):
        """(rows, failures) for the Coverage Stores table. Runs in a worker."""
        failures = []
        stores = []
        ws_names = self._get_workspace_names()
        for ws_name, (names, error) in zip(
            ws_names, self._fan_out(self._coverage_store_names, ws_names, task)
        ):
            if error:
                failures.append((ws_name, error))
                continue
            stores.extend((ws_name, name) for name in names)

        rows = []
        for (ws_name, name), (summary, error) in zip(
            stores,
            self._fan_out(
                lambda store: self._coverage_store_summary(*store), stores, task
            ),
        ):
            if error:
                failures.append((f"{ws_name}/{name}", error))
                continue
            store_type, coverage_count = summary
            rows.append([name, ws_name, store_type, str(coverage_count)])
        return rows, failures

    def _coverage_store_names(self, workspace_name):
        """Coverage-store names of one workspace. Raises on HTTP errors.

        TODO(#50): upstream as get_coverage_stores(ws) — the library has
        get_coverage_store() for one store but no call that lists them, so the
        whole tab would have nothing to show. Workaround: GET the collection.
        """
        path = self.gs.rest_service.rest_endpoints.coveragestores(workspace_name)
        payload = self._raw_rest("get", path).json()
        return sorted(
            self._name_of(store)
            for store in self._unwrap(payload, "coverageStores", "coverageStore")
        )

    def _coverage_store_summary(self, workspace_name, name):
        """(type, number of published coverages). Raises on HTTP errors."""
        detail = self._coverage_store_detail(workspace_name, name)
        published = self._published_coverage_names(workspace_name, name)
        return detail.get("type", "—"), len(published)

    # -- One store -------------------------------------------------------------

    def _coverage_store_detail(self, workspace_name, name):
        """One coverage store, as GeoServer stores it.

        TODO(#50): upstream — get_coverage_store() exists, but its model drops
        the store's description, and CoverageStore.put_payload() raises
        NotImplementedError, so there is no way to edit a store either.
        Workaround: GET the store path.
        """
        path = self.gs.rest_service.rest_endpoints.coveragestore(workspace_name, name)
        payload = self._raw_rest("get", path).json()
        return payload.get("coverageStore") or {}

    def _published_coverage_names(self, workspace_name, store_name):
        """The store's coverages that are published as layers.

        TODO(#50): upstream as get_coverages(ws, store, list="configured") —
        the library hardcodes `list=all`, which returns every coverage the
        store can expose, published or not. Both are needed: "all" to offer
        publish candidates, "configured" to say what is live.
        """
        path = self.gs.rest_service.rest_endpoints.coverages(workspace_name, store_name)
        payload = self._raw_rest("get", path, params={"list": "configured"}).json()
        return sorted(
            self._name_of(coverage)
            for coverage in self._unwrap(payload, "coverages", "coverage")
        )

    def _coverage_store_info_fields(self):
        """Field definitions for the read-only store dialog."""
        fields = [
            {"key": key, "label": label, "type": "text", "read_only": True}
            for key, label in (
                ("name", self.tr("Coverage Store")),
                ("workspace", self.tr("Workspace")),
                ("type", self.tr("Type")),
                ("url", self.tr("URL")),
                ("enabled", self.tr("Enabled")),
            )
        ]
        fields.append(
            {
                "key": "description",
                "label": self.tr("Description"),
                "type": "textarea",
                "read_only": True,
            }
        )
        fields.append(
            {
                "key": "coverages",
                "label": self.tr("Published coverages"),
                "type": "textarea",
                "read_only": True,
                "group": self.tr("Coverages"),
                "help": self.tr(
                    "Open the Coverages action for one coverage's details."
                ),
            }
        )
        return fields

    @staticmethod
    def _coverage_store_form_values(detail, published):
        """Prefill for the store dialog. Pure, so it is unit-testable."""
        return {
            "name": detail.get("name", ""),
            "workspace": (detail.get("workspace") or {}).get("name", ""),
            "type": detail.get("type", ""),
            "url": detail.get("url", ""),
            "enabled": str(detail.get("enabled", "")),
            "description": detail.get("description", ""),
            "coverages": "\n".join(published) or "—",
        }

    def _show_coverage_store_info(self, row_data):
        """Open a coverage store, read-only."""
        name, ws_name = row_data[0], row_data[1]
        fetched = self._fetch(
            lambda: (
                self._coverage_store_detail(ws_name, name),
                self._published_coverage_names(ws_name, name),
            ),
            self.tr("Failed to load coverage store '{}'").format(name),
        )
        if fetched is None:
            return
        detail, published = fetched

        dlg = ResourceFormDialog(
            title=self.tr("Coverage Store '{}'").format(name),
            description=self.tr(
                "Read-only: GeoServer's REST API has no update for a coverage "
                "store, so a change means creating it again."
            ),
            fields=self._coverage_store_info_fields(),
            values=self._coverage_store_form_values(detail, published),
            parent=self,
        )
        dlg.hide_save_button()
        dlg.exec()

    # -- Coverages -------------------------------------------------------------

    def _coverage_detail(self, workspace_name, store_name, name):
        """One coverage, as GeoServer stores it.

        TODO(#50): upstream — get_coverage() exists, but Coverage.asdict()
        drops nativeBoundingBox, latLonBoundingBox and keywords, which is most
        of what a detail view is for. Workaround: GET the coverage path.
        """
        path = self.gs.rest_service.rest_endpoints.coverage(
            workspace_name, store_name, name
        )
        payload = self._raw_rest("get", path).json()
        return payload.get("coverage") or {}

    @staticmethod
    def _crs_text(value):
        """A CRS, which GeoServer gives either as a string or as {"$": …}."""
        if isinstance(value, dict):
            return str(value.get("$", ""))
        return "" if value is None else str(value)

    @classmethod
    def _coverage_form_values(cls, detail):
        """Prefill for the coverage viewer. Pure, so it is unit-testable."""
        bbox = detail.get("nativeBoundingBox") or {}
        bounds = (
            "{minx}, {miny} → {maxx}, {maxy}  ({crs})".format(
                crs=cls._crs_text(bbox.get("crs")),
                **{key: bbox[key] for key in ("minx", "miny", "maxx", "maxy")},
            )
            if {"minx", "miny", "maxx", "maxy"} <= set(bbox)
            else ""
        )

        # GeoServer writes the grid range's "high" as the exclusive upper bound,
        # so the size is high - low: sfdem reports "0 0" / "634 477" and gdalinfo
        # says 634 x 477, and Arc_Sample's "720 360" is a half-degree world grid.
        grid_range = (detail.get("grid") or {}).get("range") or {}
        size = ""
        try:
            low = [int(value) for value in str(grid_range["low"]).split()]
            high = [int(value) for value in str(grid_range["high"]).split()]
            size = " × ".join(str(h - lo) for lo, h in zip(low, high))
        except (KeyError, ValueError):
            pass

        dimensions = (detail.get("dimensions") or {}).get("coverageDimension") or []
        if isinstance(dimensions, dict):  # a single band is not a list
            dimensions = [dimensions]
        bands = "\n".join(
            "{}{}".format(
                band.get("name", "?"),
                (
                    "  ({min} … {max})".format(**band["range"])
                    if isinstance(band.get("range"), dict)
                    and {"min", "max"} <= set(band["range"])
                    else ""
                ),
            )
            for band in dimensions
            if isinstance(band, dict)
        )
        keywords = (detail.get("keywords") or {}).get("string") or []
        if isinstance(keywords, str):
            keywords = [keywords]

        return {
            "native_name": detail.get("nativeName", ""),
            "title": detail.get("title", ""),
            "srs": detail.get("srs", ""),
            "native_format": detail.get("nativeFormat", ""),
            "enabled": str(detail.get("enabled", "")),
            "size": size,
            "bounds": bounds,
            "keywords": ", ".join(str(keyword) for keyword in keywords),
            "abstract": detail.get("description") or detail.get("abstract") or "",
            "bands": bands or "—",
        }

    def _coverage_fields(self, names):
        """Field definitions for the coverage viewer: a picker plus its details."""
        fields = [
            {
                "key": "coverage",
                "label": self.tr("Coverage"),
                "type": "combo",
                "options": list(names),
            }
        ]
        fields += [
            {"key": key, "label": label, "type": "text", "read_only": True}
            for key, label in (
                ("native_name", self.tr("Native name")),
                ("title", self.tr("Title")),
                ("srs", self.tr("SRS")),
                ("native_format", self.tr("Native format")),
                ("enabled", self.tr("Enabled")),
                ("size", self.tr("Size in pixels")),
                ("bounds", self.tr("Bounds")),
                ("keywords", self.tr("Keywords")),
            )
        ]
        fields += [
            {
                "key": "abstract",
                "label": self.tr("Abstract"),
                "type": "textarea",
                "read_only": True,
            },
            {
                "key": "bands",
                "label": self.tr("Bands"),
                "type": "textarea",
                "read_only": True,
                "group": self.tr("Bands"),
            },
        ]
        return fields

    def _refill_coverage_detail(self, dlg, workspace_name, store_name, name):
        """Show one coverage's details in the viewer."""
        if not name:
            return
        detail = self._fetch(
            lambda: self._coverage_detail(workspace_name, store_name, name),
            self.tr("Failed to load coverage '{}'").format(name),
        )
        values = self._coverage_form_values(detail or {})
        for key, value in values.items():
            widget = dlg.get_widget(key)
            if hasattr(widget, "setPlainText"):
                widget.setPlainText(value)
            else:
                widget.setText(value)

    def _show_coverages(self, row_data):
        """List the store's published coverages and view one at a time."""
        store_name, ws_name = row_data[0], row_data[1]
        published = self._fetch(
            lambda: self._published_coverage_names(ws_name, store_name),
            self.tr("Failed to load the coverages of '{}'").format(store_name),
        )
        if published is None:
            return
        if not published:
            self.show_warning_message(
                self.tr(
                    "'{}' has no published coverage yet — use Publish a coverage."
                ).format(store_name)
            )
            return

        dlg = ResourceFormDialog(
            title=self.tr("Coverages of '{}'").format(store_name),
            description=self.tr("Read-only view of what this store publishes."),
            fields=self._coverage_fields(published),
            parent=self,
        )
        dlg.get_widget("coverage").currentTextChanged.connect(
            lambda name: self._refill_coverage_detail(dlg, ws_name, store_name, name)
        )
        self._refill_coverage_detail(dlg, ws_name, store_name, published[0])
        dlg.hide_save_button()
        dlg.exec()

    # -- Publish ---------------------------------------------------------------

    def _publishable_coverages(self, workspace_name, store_name):
        """Coverages the store exposes that are not published yet.

        The library's get_coverages() answers `list=all` — everything the store
        can expose — so the candidates are that list minus what is already
        configured (see _published_coverage_names).
        """
        every = [
            self._name_of(coverage)
            for coverage in self._fetch_list(
                self.gs.get_coverages, workspace_name, store_name
            )
        ]
        published = set(self._published_coverage_names(workspace_name, store_name))
        return [name for name in every if name not in published]

    def _publish_coverage(self, row_data):
        """Publish one of the store's coverages as a layer."""
        store_name, ws_name = row_data[0], row_data[1]
        candidates = self._fetch(
            lambda: self._publishable_coverages(ws_name, store_name),
            self.tr("Failed to list the coverages of '{}'").format(store_name),
        )
        if candidates is None:
            return
        if not candidates:
            self.show_warning_message(
                self.tr("Every coverage of '{}' is already published.").format(
                    store_name
                )
            )
            return

        dlg = ResourceFormDialog(
            title=self.tr("Publish a coverage of '{}'").format(store_name),
            description=self.tr(
                "Publishing a coverage makes it a layer. Leave the layer name "
                "empty to reuse the coverage's own name."
            ),
            fields=[
                {
                    "key": "native_name",
                    "label": self.tr("Coverage"),
                    "type": "combo",
                    "options": candidates,
                    "required": True,
                },
                {"key": "name", "label": self.tr("Layer name"), "type": "text"},
                {"key": "title", "label": self.tr("Title"), "type": "text"},
            ],
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        published_name = values["name"] or values["native_name"]
        if self._run_action(
            lambda: self._check(
                self.gs.create_coverage(
                    ws_name,
                    store_name,
                    published_name,
                    title=values["title"] or None,
                    native_name=values["native_name"],
                )
            ),
            self.tr("Failed to publish '{}'").format(values["native_name"]),
        ):
            self.show_success_message(
                self.tr("'{}' published as a layer.").format(published_name)
            )
            self._load_coverage_stores()

    # -- Create ----------------------------------------------------------------

    def _coverage_store_fields(self, workspace_names):
        """Field definitions for the Add form."""
        return [
            {
                "key": "name",
                "label": self.tr("Coverage Store"),
                "type": "text",
                "required": True,
            },
            {
                "key": "workspace",
                "label": self.tr("Workspace"),
                "type": "combo",
                "options": list(workspace_names),
                "required": True,
            },
            {
                "key": "type",
                "label": self.tr("Type"),
                "type": "combo",
                "options": list(STORE_TYPES),
                "default": GEOTIFF,
            },
            {
                "key": "url",
                "label": self.tr("URL"),
                "type": "text",
                "required": True,
                "group": self.tr("Source"),
                "placeholder": "file:data/sf/sfdem.tif",
                "help": self.tr(
                    "A path on the GeoServer machine (file:…) or, for a COG, an "
                    "http(s):// or s3:// URL. Paths are resolved by the server, "
                    "not by QGIS."
                ),
            },
            {
                "key": "directory",
                "label": self.tr("Directory"),
                "type": "text",
                "required": True,
                "visible": False,
                "group": self.tr("Source"),
                "placeholder": "/opt/geoserver_data/coverages/my_mosaic",
                "help": self.tr(
                    "A directory on the GeoServer machine holding the granules. "
                    "Its coverages are discovered and published automatically."
                ),
            },
            {
                "key": "zip",
                "label": self.tr("Properties ZIP"),
                "type": "file",
                "required": True,
                "visible": False,
                "group": self.tr("Source"),
                "filter": "ZIP (*.zip);;All files (*)",
                "help": self.tr(
                    "A ZIP holding indexer.properties, datastore.properties and at "
                    "least one granule — GeoServer refuses a properties-only "
                    "archive. Nothing is published yet. Give the indexer a Name "
                    "nobody used before: deleting a mosaic store leaves its "
                    "granule index table behind, and a re-used name picks it up."
                ),
            },
        ]

    def _on_store_type_changed(self, dlg, store_type):
        """Show only the fields the chosen store type needs."""
        wanted = _TYPE_FIELDS.get(store_type, ())
        for key in ("url", "directory", "zip"):
            dlg.set_field_visible(key, key in wanted)

    def _add_coverage_store(self):
        """Create a coverage store."""
        workspace_names = self._fetch(
            self._get_workspace_names, self.tr("Failed to load the workspaces")
        )
        if workspace_names is None:
            return

        dlg = ResourceFormDialog(
            title=self.tr("Add a Coverage Store"),
            description=self.tr(
                "A coverage store is a source of rasters. Creating it does not "
                "publish anything — except an ImageMosaic from a directory, "
                "which discovers its coverages itself."
            ),
            fields=self._coverage_store_fields(workspace_names),
            parent=self,
        )
        dlg.get_widget("type").currentTextChanged.connect(
            lambda store_type: self._on_store_type_changed(dlg, store_type)
        )
        self._on_store_type_changed(dlg, GEOTIFF)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._create_coverage_store_from_values(values),
            self.tr("Failed to create coverage store '{}'").format(values["name"]),
        ):
            self.show_success_message(
                self.tr("Coverage store '{}' created.").format(values["name"])
            )
            self._warn_if_cog_settings_dropped(values)
            self._load_coverage_stores()

    def _warn_if_cog_settings_dropped(self, values):
        """Say so when GeoServer keeps the store but throws the COG settings away.

        Store metadata it does not understand is dropped silently (verified on
        2.28.5 with both the object and the array payload shape), so without
        GeoServer's COG extension the store ends up a plain GeoTIFF that reads
        whole files instead of ranges. That still works, so it is a warning
        rather than a failure — but it must not pass unmentioned.
        """
        if values["type"] != COG:
            return
        try:
            detail = self._coverage_store_detail(values["workspace"], values["name"])
        except Exception:  # best effort: the store itself is already created
            return
        if not (detail.get("metadata") or {}):
            self.show_warning_message(
                self.tr(
                    "'{}' was created, but GeoServer dropped the COG settings — it "
                    "will read whole files instead of ranges. Is the COG extension "
                    "installed on the server?"
                ).format(values["name"])
            )

    def _create_coverage_store_from_values(self, values):
        """Create a store through the library, refusing an existing name."""
        name, ws_name, store_type = values["name"], values["workspace"], values["type"]
        # create_coverage_store POSTs to the collection, and GeoServer answers
        # 409 for a name in use — but the message is clearer from here, and the
        # mosaic calls are PUTs, which would overwrite the store instead.
        if self._resource_exists(self.gs.get_coverage_store, ws_name, name):
            raise ValueError(
                self.tr("Coverage store '{}' already exists in '{}'.").format(
                    name, ws_name
                )
            )

        if store_type == MOSAIC_DIRECTORY:
            self._check(
                self.gs.create_imagemosaic_store_from_directory(
                    ws_name, name, values["directory"]
                )
            )
        elif store_type == MOSAIC_ZIP:
            with open(values["zip"], "rb") as handle:
                self._check(
                    self.gs.create_imagemosaic_store_from_properties_zip(
                        ws_name, name, handle.read()
                    )
                )
        else:
            self._check(
                self.gs.create_coverage_store(
                    ws_name,
                    name,
                    values["url"],
                    type=GEOTIFF,
                    metadata=_COG_METADATA if store_type == COG else None,
                )
            )

    # -- Delete ----------------------------------------------------------------

    def _delete_coverage_store(self, row_data):
        """Delete a single coverage store after confirmation."""
        self._delete_selected_coverage_stores([row_data])

    def _delete_selected_coverage_stores(self, selected_rows):
        """Delete one or more coverage stores after confirmation."""
        self._delete_many(
            self.tr("coverage store"),
            [
                (
                    f"{row[1]}/{row[0]}",
                    lambda name=row[0], ws=row[1]: self._check(
                        self.gs.delete_coverage_store(ws, name)
                    ),
                )
                for row in selected_rows
            ],
            self._load_coverage_stores,
            cascade=self.tr(
                "The delete recurses: the store, its coverages and the layers "
                "published from them all go. The raster files themselves stay "
                "on the server.\n\n"
            ),
        )
