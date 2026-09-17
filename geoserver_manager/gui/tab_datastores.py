#! python3  # noqa: E265

"""
Datastore tab — load, create, edit, delete datastores.

Used as a mixin for GeoServerMainDialog.
"""

from concurrent.futures import ThreadPoolExecutor

from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

# Datastore types supported by the library with dedicated or generic methods
_SUPPORTED_TYPES = [
    "PostGIS",
    "PostGIS (JNDI)",
    "PMTiles",
]

# Listing datastores needs one GET per workspace plus one per datastore.
# ponytail: 8 parallel GETs keep that bearable; it still runs on the GUI
# thread, so move to QgsTask if a big server still feels frozen.
_MAX_PARALLEL_REQUESTS = 8


class DatastoreTabMixin:
    """Mixin that adds datastore CRUD methods to the main dialog.

    ponytail: same translation caveat as WorkspaceTabMixin — self.tr() here is
    extracted under this class but resolved against the host dialog's context.
    """

    def _load_datastores(self):
        """Fetch all datastores across all workspaces and display them."""

        def load():
            self._setup_add_button(
                self.tr("Add a New Datastore"),
                self.tr("Create a new datastore"),
                self._add_datastore,
            )
            self._setup_delete_selected_button(self._delete_selected_datastores)
            self._name_click_callback = self._show_datastore_info
            self._extra_click_callbacks = {
                self.tr("Workspace"): self._open_workspace_from_row
            }
            self._row_actions = [
                (
                    "mActionDeleteSelected.svg",
                    self.tr("Delete"),
                    self._delete_datastore,
                ),
            ]
            self._setup_table(
                [
                    self.tr("Datastore Name"),
                    self.tr("Workspace"),
                    self.tr("Type"),
                    self.tr("Enabled"),
                    self.tr("Actions"),
                ]
            )

            ws_names = self._get_workspace_names(refresh=True)
            with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_REQUESTS) as pool:
                names_per_ws = pool.map(self._datastore_names, ws_names)
                pairs = [
                    (ws_name, ds_name)
                    for ws_name, ds_names in zip(ws_names, names_per_ws)
                    for ds_name in ds_names
                ]
                summaries = pool.map(lambda pair: self._datastore_summary(*pair), pairs)
                rows = [
                    [ds_name, ws_name, ds_type, enabled]
                    for (ws_name, ds_name), (ds_type, enabled) in zip(pairs, summaries)
                ]

            self._populate_rows(rows)

        self._run_action(load, self.tr("Failed to load datastores"))

    def _datastore_names(self, workspace_name):
        """Return the datastore names of one workspace. Raises on HTTP errors."""
        return [
            self._name_of(ds)
            for ds in self._fetch_list(self.gs.get_datastores, workspace_name)
        ]

    def _datastore_summary(self, workspace_name, datastore_name):
        """Best-effort (type, enabled) for the list view — "—" when unavailable.

        One datastore failing to load must not blank the whole table.
        """
        unknown = ("—", "—")
        try:
            detail, _ = self.gs.get_datastore(workspace_name, datastore_name)
        except Exception:
            return unknown
        if not isinstance(detail, dict):
            return unknown
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
                "label": self.tr("Workspace"),
                "type": "combo",
                "options": workspace_names,
                "required": True,
                "read_only": edit_mode,
                "help": self.tr("The workspace this datastore belongs to"),
            },
            {
                "key": "name",
                "label": self.tr("Name"),
                "type": "text",
                "required": True,
                # Renaming would upsert: a free name creates a second store and
                # a taken one overwrites it. Locked until the library grows a
                # real rename (workspaces do it with a TODO-tagged PUT).
                "read_only": edit_mode,
                "help": (
                    self.tr("A datastore cannot be renamed") if edit_mode else None
                ),
            },
            {
                "key": "type",
                "label": self.tr("Type"),
                "type": "combo",
                "options": _SUPPORTED_TYPES,
                "required": True,
                "on_change": on_type_changed,
            },
            {
                "key": "description",
                "label": self.tr("Description"),
                "type": "text",
                "placeholder": self.tr("Optional description"),
            },
            # --- PostGIS fields ---
            {
                "key": "pg_host",
                "label": self.tr("Host"),
                "type": "text",
                "required": True,
                "placeholder": "localhost",
                "group": self.tr("Connection"),
            },
            {
                "key": "pg_port",
                "label": self.tr("Port"),
                "type": "spinbox",
                "default": 5432,
                "min": 1,
                "max": 65535,
                "group": self.tr("Connection"),
            },
            {
                "key": "pg_db",
                "label": self.tr("Database"),
                "type": "text",
                "required": True,
                "group": self.tr("Connection"),
            },
            {
                "key": "pg_user",
                "label": self.tr("User"),
                "type": "text",
                "required": True,
                "group": self.tr("Connection"),
            },
            {
                "key": "pg_password",
                "label": self.tr("Password"),
                "type": "text",
                "required": True,
                "echo_password": True,
                "group": self.tr("Connection"),
                "help": (
                    self.tr("Re-enter the password to save changes")
                    if edit_mode
                    else None
                ),
            },
            {
                "key": "pg_schema",
                "label": self.tr("Schema"),
                "type": "text",
                "default": "public",
                "group": self.tr("Connection"),
            },
            # --- JNDI fields ---
            {
                "key": "jndi_reference",
                "label": self.tr("JNDI Reference"),
                "type": "text",
                "required": True,
                "placeholder": "java:comp/env/jdbc/mydb",
                "visible": False,
                "group": self.tr("Connection"),
                "help": self.tr("JNDI name of the database connection pool"),
            },
            # --- PMTiles fields ---
            {
                "key": "pmtiles_url",
                "label": self.tr("PMTiles URL"),
                "type": "text",
                "required": True,
                "placeholder": "file:///mnt/data/tiles.pmtiles",
                "visible": False,
                "group": self.tr("Connection"),
                "help": self.tr(
                    "Path or URL to the PMTiles file (file://, s3://, gs://, http(s)://)"
                ),
            },
        ]

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

    def _get_workspace_names(self, refresh=False):
        """Return the workspace names, cached between dialog openings.

        ponytail: the cache is refreshed whenever the datastore list reloads,
        so Refresh picks up workspaces created elsewhere. That is enough to
        stop every Add/Edit dialog from re-fetching the list.
        """
        if refresh or not self._workspace_names:
            workspaces = self._fetch_list(self.gs.get_workspaces)
            self._workspace_names = [self._name_of(ws) for ws in workspaces]
        return self._workspace_names

    def _add_datastore(self):
        """Open a form dialog to create a new datastore."""
        workspace_names = self._get_workspace_names()
        if not workspace_names:
            self.show_warning_message(
                self.tr("No workspaces available. Create a workspace first.")
            )
            return

        dlg = ResourceFormDialog(
            title=self.tr("New Datastore"),
            description=self.tr("Configure a new datastore"),
            fields=self._datastore_fields(workspace_names),
            parent=self,
        )
        self._wire_type_combo(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._create_datastore_from_values(values),
            self.tr("Failed to create datastore '{}'").format(values["name"]),
        ):
            self.show_success_message(
                self.tr("Datastore '{}' created.").format(values["name"])
            )
            self._load_datastores()

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
                self.tr("Datastore '{}' already exists in workspace '{}'.").format(
                    name, ws
                )
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
        else:
            raise ValueError(f"Unsupported datastore type: {ds_type}")

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

        A type the form cannot edit is shown against the first supported type
        purely so the combo has something to display; the caller hides Save.
        """
        return {
            "workspace": ws_name,
            "name": ds_name,
            "type": ds_type if ds_type in _SUPPORTED_TYPES else _SUPPORTED_TYPES[0],
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
        }

    def _show_datastore_info(self, row_data):
        """Open a form dialog to view/edit an existing datastore."""
        ds_name, ws_name, ds_type = row_data[0], row_data[1], row_data[2]
        detail = self._fetch(
            lambda: self._check(self.gs.get_datastore(ws_name, ds_name)),
            self.tr("Failed to load datastore details"),
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
            title=self.tr("Edit Datastore '{}'").format(ds_name),
            description=(
                self.tr("Modify datastore settings")
                if editable
                else self.tr(
                    "Datastore type '{}' is read-only (not supported for editing)"
                ).format(ds_type)
            ),
            fields=self._datastore_fields(self._get_workspace_names(), edit_mode=True),
            values=values,
            parent=self,
        )
        if editable:
            self._wire_type_combo(dlg, initial_type=values["type"], locked=True)
        else:
            dlg.hide_save_button()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._update_datastore_from_values(values, detail, conn_params),
            self.tr("Failed to update datastore '{}'").format(values["name"]),
        ):
            self.show_success_message(
                self.tr("Datastore '{}' updated.").format(values["name"])
            )
            self._load_datastores()

    def _delete_datastore(self, row_data):
        """Delete a single datastore after confirmation."""
        self._delete_selected_datastores([row_data])

    def _delete_selected_datastores(self, selected_rows):
        """Delete one or more datastores after confirmation."""
        self._delete_many(
            self.tr("datastore"),
            [
                (
                    f"{row[1]}/{row[0]}",
                    lambda ws=row[1], ds=row[0]: self._do_delete_datastore(ws, ds),
                )
                for row in selected_rows
            ],
            self._load_datastores,
            # _do_delete_datastore sends recurse=true
            cascade=self.tr("Every layer published from it is deleted too.\n\n"),
        )

    def _do_delete_datastore(self, workspace_name, datastore_name):
        """Execute the REST DELETE for a datastore (recurse=true removes feature types too)."""
        # TODO: Replace with gs.delete_datastore() once the library adds this method.
        # Workaround: direct DELETE to /workspaces/{ws}/datastores/{ds}.json?recurse=true
        path = self.gs.rest_service.rest_endpoints.datastore(
            workspace_name, datastore_name
        )
        self._raw_rest("delete", path, params={"recurse": "true"})

    def _open_workspace_from_row(self, row_data):
        """Open the workspace info dialog for the workspace in a datastore row."""
        self._show_workspace_info([row_data[1]])
