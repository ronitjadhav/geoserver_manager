#! python3  # noqa: E265

"""
Datastore tab — load, create, edit, delete datastores.

Used as a mixin for GeoServerMainDialog.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

# Datastore types this form has dedicated fields for. Every other type still
# opens in the generic "key = value" editor.
_SHAPEFILE = "Shapefile"
_SHAPEFILE_DIRECTORY = "Directory of spatial files (shapefiles)"
_GEOPACKAGE = "GeoPackage"
_SUPPORTED_TYPES = [
    "PostGIS",
    "PostGIS (JNDI)",
    "PMTiles",
    _SHAPEFILE,
    _SHAPEFILE_DIRECTORY,
    _GEOPACKAGE,
]

# GeoServer picks the GeoPackage factory by this connection parameter, so it
# travels with every GeoPackage store the form saves.
_GEOPACKAGE_DBTYPE = "geopkg"

# Stands in for password-like values in the generic editor; never sent back as-is
_MASKED = "••••"

# Every field that belongs to one of those types (shown/hidden by _on_type_changed)
_TYPE_SPECIFIC_FIELDS = (
    "pg_host",
    "pg_port",
    "pg_db",
    "pg_user",
    "pg_password",
    "pg_schema",
    "jndi_reference",
    "pmtiles_url",
    "file_url",
    "charset",
    "spatial_index",
    "gpkg_database",
    "gpkg_read_only",
    "gpkg_expose_pk",
)


# Every user-visible string in this file goes through translate() with this
# file's own class as the context. self.tr() cannot: pylupdate extracts it
# under DatastoreTabMixin, but at runtime self.tr is QObject.tr with the context of the
# *instance's* class, GeoServerMainDialog — QDialog precedes the mixins in the
# MRO — so every lookup would miss. A wrapper function would not be extracted
# at all (pylupdate only understands a literal context), hence the repetition.
translate = QCoreApplication.translate


class DatastoreTabMixin:
    """Mixin that adds datastore CRUD methods to the main dialog."""

    def _load_datastores(self):
        """Arm the Datastores tab, then fetch its rows in the background."""
        self._setup_add_button(
            translate("DatastoreTabMixin", "Add a New Datastore"),
            translate("DatastoreTabMixin", "Create a new datastore"),
            self._add_datastore,
        )
        self._setup_delete_selected_button(self._delete_selected_datastores)
        self._name_click_callback = self._show_datastore_info
        self._extra_click_callbacks = {
            translate("DatastoreTabMixin", "Workspace"): self._open_workspace_from_row
        }
        self._row_actions = [
            (
                "mActionDeleteSelected.svg",
                translate("DatastoreTabMixin", "Delete"),
                self._delete_datastore,
            ),
        ]
        self._setup_table(
            [
                translate("DatastoreTabMixin", "Datastore Name"),
                translate("DatastoreTabMixin", "Workspace"),
                translate("DatastoreTabMixin", "Type"),
                translate("DatastoreTabMixin", "Enabled"),
                self.actions_column_label(),
            ]
        )
        self._start_load(
            translate("DatastoreTabMixin", "Failed to load datastores"),
            self._fetch_datastore_rows,
        )

    def _fetch_datastore_rows(self, task=None):
        """(rows, failures) for the Datastores table. Runs in a worker thread."""
        ws_names = self._get_workspace_names()
        listed = self._fan_out(self._datastore_names, ws_names, task)
        pairs = [
            (ws_name, ds_name)
            for ws_name, (ds_names, error) in zip(ws_names, listed)
            if error is None
            for ds_name in ds_names
        ]
        details = self._fan_out(
            lambda pair: self._datastore_summary(*pair), pairs, task
        )
        rows = [
            [ds_name, ws_name, *(summary or ("—", "—"))]
            for (ws_name, ds_name), (summary, _error) in zip(pairs, details)
        ]
        failures = [(ws, err) for ws, (_names, err) in zip(ws_names, listed) if err]
        failures += [
            (f"{ws}/{ds}", err)
            for (ws, ds), (_summary, err) in zip(pairs, details)
            if err
        ]
        return rows, failures

    def _datastore_names(self, workspace_name):
        """Return the datastore names of one workspace. Raises on HTTP errors."""
        return [
            self._name_of(ds)
            for ds in self._fetch_list(self.gs.get_datastores, workspace_name)
        ]

    def _datastore_summary(self, workspace_name, datastore_name):
        """(type, enabled) for the list view. Raises on HTTP errors."""
        detail = self._check(self.gs.get_datastore(workspace_name, datastore_name))
        if not isinstance(detail, dict):
            return ("—", "—")
        return (detail.get("type", "—"), str(detail.get("enabled", True)))

    def _datastore_fields(self, workspace_names, on_type_changed=None, edit_mode=False):
        """Return datastore form field definitions with type-specific params.

        :param workspace_names: list of workspace names for the combo box.
        :param on_type_changed: callback(new_type) when the type combo changes.
        :param edit_mode: editing an existing datastore — the workspace is
            fixed and the password has to be re-entered.
        """
        return [
            {
                "key": "workspace",
                "label": translate("DatastoreTabMixin", "Workspace"),
                "type": "combo",
                "options": workspace_names,
                "required": True,
                "read_only": edit_mode,
                "help": translate(
                    "DatastoreTabMixin", "The workspace this datastore belongs to"
                ),
            },
            {
                "key": "name",
                "label": translate("DatastoreTabMixin", "Name"),
                "type": "text",
                "required": True,
                # Renaming would upsert: a free name creates a second store and
                # a taken one overwrites it. Locked until the library grows a
                # real rename (#50; workspaces do it with a raw PUT).
                "read_only": edit_mode,
                "help": (
                    translate("DatastoreTabMixin", "A datastore cannot be renamed")
                    if edit_mode
                    else None
                ),
            },
            {
                "key": "type",
                "label": translate("DatastoreTabMixin", "Type"),
                "type": "combo",
                "options": _SUPPORTED_TYPES,
                "required": True,
                "on_change": on_type_changed,
            },
            {
                "key": "description",
                "label": translate("DatastoreTabMixin", "Description"),
                "type": "text",
                "placeholder": translate("DatastoreTabMixin", "Optional description"),
            },
            # --- PostGIS fields ---
            {
                "key": "pg_host",
                "label": translate("DatastoreTabMixin", "Host"),
                "type": "text",
                "required": True,
                "placeholder": "localhost",
                "group": translate("DatastoreTabMixin", "Connection"),
            },
            {
                "key": "pg_port",
                "label": translate("DatastoreTabMixin", "Port"),
                "type": "spinbox",
                "default": 5432,
                "min": 1,
                "max": 65535,
                "group": translate("DatastoreTabMixin", "Connection"),
            },
            {
                "key": "pg_db",
                "label": translate("DatastoreTabMixin", "Database"),
                "type": "text",
                "required": True,
                "group": translate("DatastoreTabMixin", "Connection"),
            },
            {
                "key": "pg_user",
                "label": translate("DatastoreTabMixin", "User"),
                "type": "text",
                "required": True,
                "group": translate("DatastoreTabMixin", "Connection"),
            },
            {
                "key": "pg_password",
                "label": translate("DatastoreTabMixin", "Password"),
                "type": "text",
                "required": True,
                "echo_password": True,
                "group": translate("DatastoreTabMixin", "Connection"),
                "help": (
                    translate(
                        "DatastoreTabMixin", "Re-enter the password to save changes"
                    )
                    if edit_mode
                    else None
                ),
            },
            {
                "key": "pg_schema",
                "label": translate("DatastoreTabMixin", "Schema"),
                "type": "text",
                "default": "public",
                "group": translate("DatastoreTabMixin", "Connection"),
            },
            # --- JNDI fields ---
            {
                "key": "jndi_reference",
                "label": translate("DatastoreTabMixin", "JNDI Reference"),
                "type": "text",
                "required": True,
                "placeholder": "java:comp/env/jdbc/mydb",
                "visible": False,
                "group": translate("DatastoreTabMixin", "Connection"),
                "help": translate(
                    "DatastoreTabMixin", "JNDI name of the database connection pool"
                ),
            },
            # --- any other type: shown read-only, since the form cannot edit it ---
            {
                "key": "raw_params",
                "label": translate("DatastoreTabMixin", "Connection parameters"),
                "type": "textarea",
                "visible": False,
                "group": translate("DatastoreTabMixin", "Connection"),
                "help": translate(
                    "DatastoreTabMixin",
                    "One 'key = value' per line, exactly as GeoServer stores them. "
                    "Lines you remove are removed on the server; a masked password "
                    "(••••) is kept as it is unless you replace it.",
                ),
            },
            # --- PMTiles fields ---
            {
                "key": "pmtiles_url",
                "label": translate("DatastoreTabMixin", "PMTiles URL"),
                "type": "text",
                "required": True,
                "placeholder": "file:///mnt/data/tiles.pmtiles",
                "visible": False,
                "group": translate("DatastoreTabMixin", "Connection"),
                "help": translate(
                    "DatastoreTabMixin",
                    "Path or URL to the PMTiles file (file://, s3://, gs://, http(s)://)",
                ),
            },
            # --- Shapefile / directory of shapefiles ---
            {
                "key": "file_url",
                "label": translate("DatastoreTabMixin", "File or folder"),
                "type": "text",
                "required": True,
                "visible": False,
                "placeholder": "file:data/shapefiles/states.shp",
                "group": translate("DatastoreTabMixin", "Connection"),
                "help": translate(
                    "DatastoreTabMixin",
                    "A path on the GeoServer machine: relative to its data "
                    "directory (file:data/…) or absolute (file:///…). A single "
                    ".shp, or the folder holding them for a directory store.",
                ),
            },
            {
                "key": "charset",
                "label": translate("DatastoreTabMixin", "Attribute charset"),
                "type": "text",
                "visible": False,
                "placeholder": translate(
                    "DatastoreTabMixin", "Leave empty for GeoServer's default"
                ),
                "group": translate("DatastoreTabMixin", "Connection"),
                "help": translate(
                    "DatastoreTabMixin",
                    "How the .dbf attribute text is encoded — UTF-8, or "
                    "ISO-8859-1, which is what GeoServer assumes",
                ),
            },
            {
                "key": "spatial_index",
                "label": translate("DatastoreTabMixin", "Create a spatial index"),
                "type": "checkbox",
                "default": True,
                "visible": False,
                "group": translate("DatastoreTabMixin", "Connection"),
                "help": translate(
                    "DatastoreTabMixin", "Writes a .qix file next to the data, once"
                ),
            },
            # --- GeoPackage ---
            {
                "key": "gpkg_database",
                "label": translate("DatastoreTabMixin", "GeoPackage file"),
                "type": "text",
                "required": True,
                "visible": False,
                "placeholder": "file:data/ne/natural_earth.gpkg",
                "group": translate("DatastoreTabMixin", "Connection"),
                "help": translate(
                    "DatastoreTabMixin",
                    "A path on the GeoServer machine. To publish a .gpkg from "
                    "this computer instead, use Publish a Layer on the Layers "
                    "tab, which uploads it.",
                ),
            },
            {
                "key": "gpkg_read_only",
                "label": translate("DatastoreTabMixin", "Read-only"),
                "type": "checkbox",
                "default": False,
                "visible": False,
                "group": translate("DatastoreTabMixin", "Connection"),
                "help": translate(
                    "DatastoreTabMixin",
                    "Recommended when nothing writes to the file: GeoServer "
                    "then serves it without taking write locks",
                ),
            },
            {
                "key": "gpkg_expose_pk",
                "label": translate("DatastoreTabMixin", "Expose primary keys"),
                "type": "checkbox",
                "default": False,
                "visible": False,
                "group": translate("DatastoreTabMixin", "Connection"),
                "help": translate(
                    "DatastoreTabMixin",
                    "Publish the tables' primary key as an attribute",
                ),
            },
        ]

    @staticmethod
    def _file_store_params(ds_type, values):
        """Connection parameters for a file-based store, from the typed fields.

        Only the keys the form owns: the caller merges them onto whatever
        GeoServer already has (invariant 3), so an unmentioned parameter like
        `namespace` or `fetch size` survives an edit.

        TODO(#50): upstream as create_shapefile_datastore() /
        create_geopackage_datastore(), next to create_pg_datastore() — the
        library has typed creators for PostGIS, JNDI and PMTiles only, so
        these go through the generic create_datastore().
        """
        if ds_type == _GEOPACKAGE:
            return {
                "database": values.get("gpkg_database", ""),
                # How GeoServer picks the GeoPackage factory.
                "dbtype": _GEOPACKAGE_DBTYPE,
                "read_only": str(bool(values.get("gpkg_read_only"))).lower(),
                "Expose primary keys": str(bool(values.get("gpkg_expose_pk"))).lower(),
            }
        params = {"url": values.get("file_url", "")}
        charset = (values.get("charset") or "").strip()
        if charset:
            # Left empty, GeoServer applies its own default rather than a
            # blank charset the shapefile reader would choke on.
            params["charset"] = charset
        if ds_type == _SHAPEFILE:
            params["create spatial index"] = str(
                bool(values.get("spatial_index"))
            ).lower()
        return params

    def _on_type_changed(self, dlg, new_type):
        """Show/hide form fields based on the selected datastore type."""
        is_postgis = new_type == "PostGIS"
        is_jndi = new_type == "PostGIS (JNDI)"
        is_pmtiles = new_type == "PMTiles"

        # PostGIS-only fields
        for key in ["pg_host", "pg_port", "pg_db", "pg_user", "pg_password"]:
            dlg.set_field_visible(key, is_postgis)

        # pg_schema is shared by PostGIS and JNDI
        dlg.set_field_visible("pg_schema", is_postgis or is_jndi)

        # JNDI-only fields
        dlg.set_field_visible("jndi_reference", is_jndi)

        # PMTiles-only fields
        dlg.set_field_visible("pmtiles_url", is_pmtiles)

        # Shapefile and directory-of-shapefiles share the path and the charset;
        # only a single-file store offers the spatial index.
        is_shapefile = new_type == _SHAPEFILE
        is_directory = new_type == _SHAPEFILE_DIRECTORY
        dlg.set_field_visible("file_url", is_shapefile or is_directory)
        dlg.set_field_visible("charset", is_shapefile or is_directory)
        dlg.set_field_visible("spatial_index", is_shapefile)

        # GeoPackage-only fields
        is_geopackage = new_type == _GEOPACKAGE
        for key in ("gpkg_database", "gpkg_read_only", "gpkg_expose_pk"):
            dlg.set_field_visible(key, is_geopackage)

    def _add_datastore(self):
        """Open a form dialog to create a new datastore."""
        workspace_names = self._get_workspace_names()
        if not workspace_names:
            self.show_warning_message(
                translate(
                    "DatastoreTabMixin",
                    "No workspaces available. Create a workspace first.",
                )
            )
            return

        dlg = ResourceFormDialog(
            title=translate("DatastoreTabMixin", "New Datastore"),
            description=translate("DatastoreTabMixin", "Configure a new datastore"),
            fields=self._datastore_fields(workspace_names),
            parent=self,
        )
        self._wire_type_combo(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._create_datastore_from_values(values),
            translate("DatastoreTabMixin", "Failed to create datastore '{}'").format(
                values["name"]
            ),
        ):
            self.show_success_message(
                translate("DatastoreTabMixin", "Datastore '{}' created.").format(
                    values["name"]
                )
            )
            self._load_datastores()

    def _show_generic_editor(self, dlg, ds_type):
        """Edit a datastore type the form has no dedicated fields for.

        Shapefile, GeoPackage, Directory, WFS, …: the real type, locked; the
        type-specific field groups hidden; the stored connection parameters
        editable as 'key = value' lines. The save path is the same merge as
        for typed stores, so GeoServer still validates the result.
        """
        combo = dlg.get_widget("type")
        if combo is not None:
            combo.addItem(ds_type)
            combo.setCurrentText(ds_type)
            combo.setEnabled(False)
        for key in _TYPE_SPECIFIC_FIELDS:
            dlg.set_field_visible(key, False)
        dlg.set_field_visible("raw_params", True)

    @staticmethod
    def _parse_params(text):
        """Parse 'key = value' lines back into a dict. Raises ValueError on a bad line."""
        params = {}
        for number, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"Line {number} is not 'key = value': {raw!r}")
            key, value = line.split("=", 1)
            params[key.strip()] = value.strip()
        return params

    def _wire_type_combo(self, dlg, initial_type=None, locked=False):
        """Show only the connection fields that belong to the selected type.

        The combo is wired after the dialog exists because the handler needs
        the dialog itself. `locked` is for edit mode: the type is displayed
        but cannot be changed.
        """
        type_combo = dlg.get_widget("type")
        if type_combo is None:
            return
        type_combo.currentTextChanged.connect(lambda t: self._on_type_changed(dlg, t))
        self._on_type_changed(dlg, initial_type or type_combo.currentText())
        if locked:
            type_combo.setEnabled(False)

    def _create_datastore_from_values(self, values):
        """Call the appropriate library method based on the datastore type."""
        ws = values["workspace"]
        name = values["name"]
        ds_type = values["type"]
        description = values.get("description") or None

        # create_* upserts, so an existing name would overwrite a live store
        if self._resource_exists(self.gs.get_datastore, ws, name):
            raise ValueError(
                translate(
                    "DatastoreTabMixin",
                    "Datastore '{}' already exists in workspace '{}'.",
                ).format(name, ws)
            )

        if ds_type == "PostGIS":
            self._check(
                self.gs.create_pg_datastore(
                    workspace_name=ws,
                    datastore_name=name,
                    pg_host=values.get("pg_host", ""),
                    pg_port=int(values.get("pg_port", 5432)),
                    pg_db=values.get("pg_db", ""),
                    pg_user=values.get("pg_user", ""),
                    pg_password=values.get("pg_password", ""),
                    pg_schema=values.get("pg_schema", "public") or "public",
                    description=description,
                )
            )
        elif ds_type == "PostGIS (JNDI)":
            self._check(
                self.gs.create_jndi_datastore(
                    workspace_name=ws,
                    datastore_name=name,
                    jndi_reference=values.get("jndi_reference", ""),
                    pg_schema=values.get("pg_schema", "public") or "public",
                    description=description,
                )
            )
        elif ds_type == "PMTiles":
            self._check(
                self.gs.create_pmtiles_datastore(
                    workspace_name=ws,
                    datastore_name=name,
                    pmtiles_url=values.get("pmtiles_url", ""),
                    description=description,
                )
            )
        elif ds_type in (_SHAPEFILE, _SHAPEFILE_DIRECTORY, _GEOPACKAGE):
            self._check(
                self.gs.create_datastore(
                    workspace_name=ws,
                    datastore_name=name,
                    datastore_type=ds_type,
                    connection_parameters=self._file_store_params(ds_type, values),
                    description=description,
                )
            )
        else:
            raise ValueError(f"Unsupported datastore type: {ds_type}")

    def _update_datastore_from_values(self, values, detail, conn_params):
        """Save an edit without discarding server-side configuration.

        The typed create_* helpers post a fixed connection-parameter template
        and GeoServer applies it by REPLACING the stored map, so editing just a
        description used to drop pool settings, Loose bbox, the real namespace
        and the PMTiles range-reader config, and force enabled=true on a
        disabled store. Merge the fields the form owns onto what the server
        actually has, and keep its own type and enabled flag.

        TODO(#50): upstream as update_datastore(...) that merges server-side.
        """
        ds_type = detail.get("type") if isinstance(detail, dict) else None
        if not ds_type:
            raise RuntimeError(
                "GeoServer did not report this datastore's type, so it cannot "
                "be updated safely."
            )

        merged = dict(conn_params)
        if ds_type == "PostGIS":
            merged.update(
                {
                    "host": values.get("pg_host", ""),
                    "port": int(values.get("pg_port", 5432)),
                    "database": values.get("pg_db", ""),
                    "user": values.get("pg_user", ""),
                    "passwd": values.get("pg_password", ""),
                    "schema": values.get("pg_schema", "public") or "public",
                }
            )
        elif ds_type == "PostGIS (JNDI)":
            merged.update(
                {
                    "jndiReferenceName": values.get("jndi_reference", ""),
                    "schema": values.get("pg_schema", "public") or "public",
                }
            )
        elif ds_type == "PMTiles":
            merged["pmtiles"] = values.get("pmtiles_url", "")
        elif ds_type in (_SHAPEFILE, _SHAPEFILE_DIRECTORY, _GEOPACKAGE):
            merged.update(self._file_store_params(ds_type, values))
        else:
            # Generic editor: what the user left in the textarea is the whole
            # map (removed lines remove keys); a masked value keeps the original.
            edited = self._parse_params(values.get("raw_params", ""))
            merged = {
                key: (conn_params.get(key, "") if value == _MASKED else value)
                for key, value in edited.items()
            }

        enabled = detail.get("enabled", True)
        if isinstance(enabled, str):  # .json gives a bool, but do not assume
            enabled = enabled.strip().lower() == "true"

        self._check(
            self.gs.create_datastore(
                workspace_name=values["workspace"],
                datastore_name=values["name"],
                datastore_type=ds_type,
                connection_parameters=merged,
                description=values.get("description") or None,
                enabled=bool(enabled),
            )
        )

    @staticmethod
    def _connection_params(detail):
        """The datastore's connectionParameters as a plain dict."""
        if not isinstance(detail, dict):
            return {}
        entry = detail.get("connectionParameters", {}).get("entry", {})
        return entry if isinstance(entry, dict) else {}

    @staticmethod
    def _datastore_form_values(ws_name, ds_name, ds_type, detail, conn_params):
        """Prefill for the edit form, from what GeoServer returned.

        The type is passed through as-is; for a type without dedicated fields
        the caller (_show_generic_editor) adds it to the combo and locks it.
        """
        return {
            "workspace": ws_name,
            "name": ds_name,
            "type": ds_type,
            "description": (
                detail.get("description", "") if isinstance(detail, dict) else ""
            ),
            # PostGIS
            "pg_host": conn_params.get("host", ""),
            "pg_port": int(conn_params.get("port", 5432) or 5432),
            "pg_db": conn_params.get("database", ""),
            "pg_user": conn_params.get("user", ""),
            # Never prefilled: GeoServer returns it encrypted ("crypt1:…") or
            # not at all, and writing that back would replace the real password.
            "pg_password": "",
            "pg_schema": conn_params.get("schema", "public"),
            # JNDI
            "jndi_reference": conn_params.get("jndiReferenceName", ""),
            # PMTiles
            "pmtiles_url": conn_params.get("pmtiles", ""),
            # Shapefile and directory of shapefiles
            "file_url": conn_params.get("url", ""),
            "charset": conn_params.get("charset", ""),
            "spatial_index": str(
                conn_params.get("create spatial index", "true")
            ).lower()
            == "true",
            # GeoPackage
            "gpkg_database": conn_params.get("database", ""),
            "gpkg_read_only": str(conn_params.get("read_only", "false")).lower()
            == "true",
            "gpkg_expose_pk": str(
                conn_params.get("Expose primary keys", "false")
            ).lower()
            == "true",
            # Generic editor for types without dedicated fields; secrets masked
            "raw_params": "\n".join(
                f"{key} = {_MASKED if key.lower() in ('passwd', 'password') else value}"
                for key, value in sorted(conn_params.items())
            ),
        }

    def _show_datastore_info(self, row_data):
        """Open a form dialog to view/edit an existing datastore."""
        ds_name, ws_name, ds_type = row_data[0], row_data[1], row_data[2]
        detail = self._fetch(
            lambda: self._check(self.gs.get_datastore(ws_name, ds_name)),
            translate("DatastoreTabMixin", "Failed to load datastore details"),
        )
        if detail is None:
            return

        # The row's Type cell can be "—" after a transient GET failure at list
        # time; the detail we just fetched is authoritative.
        if isinstance(detail, dict) and detail.get("type"):
            ds_type = detail["type"]
        conn_params = self._connection_params(detail)
        values = self._datastore_form_values(
            ws_name, ds_name, ds_type, detail, conn_params
        )
        editable = ds_type in _SUPPORTED_TYPES

        dlg = ResourceFormDialog(
            title=translate("DatastoreTabMixin", "Edit Datastore '{}'").format(ds_name),
            description=(
                translate("DatastoreTabMixin", "Modify datastore settings")
                if editable
                else translate(
                    "DatastoreTabMixin",
                    "Datastore type '{}' has no dedicated form — edit its connection "
                    "parameters directly.",
                ).format(ds_type)
            ),
            fields=self._datastore_fields(self._get_workspace_names(), edit_mode=True),
            values=values,
            parent=self,
        )
        if editable:
            self._wire_type_combo(dlg, initial_type=values["type"], locked=True)
        else:
            self._show_generic_editor(dlg, ds_type)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._update_datastore_from_values(values, detail, conn_params),
            translate("DatastoreTabMixin", "Failed to update datastore '{}'").format(
                values["name"]
            ),
        ):
            self.show_success_message(
                translate("DatastoreTabMixin", "Datastore '{}' updated.").format(
                    values["name"]
                )
            )
            self._load_datastores()

    def _delete_datastore(self, row_data):
        """Delete a single datastore after confirmation."""
        self._delete_selected_datastores([row_data])

    def _delete_selected_datastores(self, selected_rows):
        """Delete one or more datastores after confirmation."""
        self._delete_many(
            translate("DatastoreTabMixin", "datastore"),
            [
                (
                    f"{row[1]}/{row[0]}",
                    lambda ws=row[1], ds=row[0]: self._do_delete_datastore(ws, ds),
                )
                for row in selected_rows
            ],
            self._load_datastores,
            # _do_delete_datastore sends recurse=true
            cascade=translate(
                "DatastoreTabMixin", "Every layer published from it is deleted too.\n\n"
            ),
        )

    def _do_delete_datastore(self, workspace_name, datastore_name):
        """Execute the REST DELETE for a datastore (recurse=true removes feature types too)."""
        # TODO(#50): upstream as delete_datastore(ws, ds, recurse=True) — the library
        # has none. Workaround: DELETE /workspaces/{ws}/datastores/{ds}.json?recurse=true
        path = self.gs.rest_service.rest_endpoints.datastore(
            workspace_name, datastore_name
        )
        self._raw_rest("delete", path, params={"recurse": "true"})

    def _open_workspace_from_row(self, row_data):
        """Open the workspace info dialog for the workspace in a datastore row."""
        self._show_workspace_info([row_data[1]])
