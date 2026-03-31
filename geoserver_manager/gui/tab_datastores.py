#! python3  # noqa: E265

"""
Datastore tab — load, create, edit, delete datastores.

Used as a mixin for GeoServerMainDialog.
"""

from qgis.core import Qgis
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QMessageBox

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

# Datastore types supported by the library with dedicated or generic methods
_SUPPORTED_TYPES = [
    "PostGIS",
    "PostGIS (JNDI)",
    "PMTiles",
]

# Fields that are specific to each type.
# Keys match field "key" values used in the form.
_POSTGIS_KEYS = ["pg_host", "pg_port", "pg_db", "pg_user", "pg_password", "pg_schema"]
_JNDI_KEYS = ["jndi_reference", "pg_schema"]
_PMTILES_KEYS = ["pmtiles_url"]


class DatastoreTabMixin:
    """Mixin that adds datastore CRUD methods to the main dialog."""

    def _load_datastores(self):
        """Fetch all datastores across all workspaces and display them."""
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self._setup_add_button(
                self.tr("Add a New Datastore"),
                self.tr("Create a new datastore"),
                self._add_datastore,
            )
            self._setup_delete_selected_button(self._delete_selected_datastores)
            self._name_click_callback = self._show_datastore_info
            self._extra_click_callbacks = {1: self._open_workspace_from_row}
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

            workspaces = self._fetch_list(self.gs.get_workspaces)
            rows = []
            for ws in workspaces:
                ws_name = ws.get("name", str(ws)) if isinstance(ws, dict) else str(ws)
                datastores = self._fetch_list(self.gs.get_datastores, ws_name)
                for ds in datastores:
                    ds_name = (
                        ds.get("name", str(ds)) if isinstance(ds, dict) else str(ds)
                    )
                    try:
                        detail, _ = self.gs.get_datastore(ws_name, ds_name)
                        if isinstance(detail, dict):
                            ds_type = detail.get("type", "—")
                            enabled = str(detail.get("enabled", True))
                        else:
                            ds_type = "—"
                            enabled = "—"
                    except Exception:
                        ds_type = "—"
                        enabled = "—"
                    rows.append([ds_name, ws_name, ds_type, enabled])

            self._populate_rows(rows)
        except Exception as e:
            self.show_error_message(self.tr("Failed to load datastores: {}").format(e))
            self.log(f"Datastore load error: {e}", log_level=Qgis.MessageLevel.Critical)
        finally:
            self.unsetCursor()

    def _datastore_fields(
        self, workspace_names, on_type_changed=None, read_only_workspace=False
    ):
        """Return datastore form field definitions with type-specific params.

        :param workspace_names: list of workspace names for the combo box.
        :param on_type_changed: callback(new_type) when the type combo changes.
        :param read_only_workspace: disable workspace field in edit mode.
        """
        return [
            {
                "key": "workspace",
                "label": self.tr("Workspace"),
                "type": "combo",
                "options": workspace_names,
                "required": True,
                "read_only": read_only_workspace,
                "help": self.tr("The workspace this datastore belongs to"),
            },
            {
                "key": "name",
                "label": self.tr("Name"),
                "type": "text",
                "required": True,
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
        for key in _POSTGIS_KEYS:
            dlg.set_field_visible(key, new_type == "PostGIS")
        for key in _JNDI_KEYS:
            dlg.set_field_visible(
                key,
                new_type == "PostGIS (JNDI)"
                or (key == "pg_schema" and new_type == "PostGIS"),
            )
        for key in _PMTILES_KEYS:
            dlg.set_field_visible(key, new_type == "PMTiles")

    def _get_workspace_names(self):
        """Return a list of workspace names from the current connection."""
        workspaces = self._fetch_list(self.gs.get_workspaces)
        return [
            ws.get("name", str(ws)) if isinstance(ws, dict) else str(ws)
            for ws in workspaces
        ]

    def _add_datastore(self):
        """Open a form dialog to create a new datastore."""
        workspace_names = self._get_workspace_names()
        if not workspace_names:
            self.show_warning_message(
                self.tr("No workspaces available. Create a workspace first.")
            )
            return

        # Build dialog with a deferred on_change so we get a reference to dlg
        dlg = ResourceFormDialog(
            title=self.tr("New Datastore"),
            description=self.tr("Configure a new datastore"),
            fields=self._datastore_fields(workspace_names),
            parent=self,
        )
        # Wire type combo after dialog is constructed
        type_combo = dlg.get_widget("type")
        if type_combo:
            type_combo.currentTextChanged.connect(
                lambda t: self._on_type_changed(dlg, t)
            )
            # Apply initial visibility for the default type
            self._on_type_changed(dlg, type_combo.currentText())

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self._create_datastore_from_values(values)
            self.show_success_message(
                self.tr("Datastore '{}' created.").format(values["name"])
            )
            self._load_datastores()
        except Exception as e:
            self.show_error_message(
                self.tr("Failed to create datastore '{}': {}").format(values["name"], e)
            )
            self.log(
                f"Create datastore error: {e}", log_level=Qgis.MessageLevel.Critical
            )
        finally:
            self.unsetCursor()

    def _create_datastore_from_values(self, values):
        """Call the appropriate library method based on the datastore type."""
        ws = values["workspace"]
        name = values["name"]
        ds_type = values["type"]
        description = values.get("description") or None

        if ds_type == "PostGIS":
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
        elif ds_type == "PostGIS (JNDI)":
            self.gs.create_jndi_datastore(
                workspace_name=ws,
                datastore_name=name,
                jndi_reference=values.get("jndi_reference", ""),
                pg_schema=values.get("pg_schema", "public") or "public",
                description=description,
            )
        elif ds_type == "PMTiles":
            self.gs.create_pmtiles_datastore(
                workspace_name=ws,
                datastore_name=name,
                pmtiles_url=values.get("pmtiles_url", ""),
                description=description,
            )
        else:
            raise ValueError(f"Unsupported datastore type: {ds_type}")

    def _show_datastore_info(self, row_data):
        """Open a form dialog to view/edit an existing datastore."""
        ds_name = row_data[0]
        ws_name = row_data[1]
        ds_type = row_data[2]

        # Fetch full detail for connection_params
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            detail, _ = self.gs.get_datastore(ws_name, ds_name)
        except Exception as e:
            self.show_error_message(
                self.tr("Failed to load datastore details: {}").format(e)
            )
            return
        finally:
            self.unsetCursor()

        conn_params = {}
        if isinstance(detail, dict):
            conn_entry = detail.get("connectionParameters", {}).get("entry", {})
            conn_params = conn_entry if isinstance(conn_entry, dict) else {}

        # Map library type to our supported combo values; unsupported types are read-only
        type_for_form = ds_type
        if ds_type not in _SUPPORTED_TYPES:
            type_for_form = _SUPPORTED_TYPES[0]  # fallback display
            is_unsupported = True
        else:
            is_unsupported = False

        current_values = {
            "workspace": ws_name,
            "name": ds_name,
            "type": type_for_form,
            "description": (
                detail.get("description", "") if isinstance(detail, dict) else ""
            ),
            # PostGIS fields
            "pg_host": conn_params.get("host", ""),
            "pg_port": int(conn_params.get("port", 5432) or 5432),
            "pg_db": conn_params.get("database", ""),
            "pg_user": conn_params.get("user", ""),
            "pg_password": conn_params.get("passwd", ""),
            "pg_schema": conn_params.get("schema", "public"),
            # JNDI fields
            "jndi_reference": conn_params.get("jndiReferenceName", ""),
            # PMTiles fields
            "pmtiles_url": conn_params.get("pmtiles", ""),
        }

        workspace_names = self._get_workspace_names()
        dlg = ResourceFormDialog(
            title=self.tr("Edit Datastore '{}'").format(ds_name),
            description=(
                self.tr("Modify datastore settings")
                if not is_unsupported
                else self.tr(
                    "Datastore type '{}' is read-only (not supported for editing)"
                ).format(ds_type)
            ),
            fields=self._datastore_fields(workspace_names, read_only_workspace=True),
            values=current_values,
            parent=self,
        )

        if is_unsupported:
            # Disable all fields — user cannot edit unsupported types
            dlg.set_all_fields_enabled(False)
        else:
            # Wire type combo and apply visibility
            type_combo = dlg.get_widget("type")
            if type_combo:
                type_combo.currentTextChanged.connect(
                    lambda t: self._on_type_changed(dlg, t)
                )
                self._on_type_changed(dlg, type_for_form)
            # Disable type change in edit mode
            type_combo.setEnabled(False)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if is_unsupported:
            return

        values = dlg.get_values()
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self._create_datastore_from_values(values)
            self.show_success_message(
                self.tr("Datastore '{}' updated.").format(values["name"])
            )
            self._load_datastores()
        except Exception as e:
            self.show_error_message(
                self.tr("Failed to update datastore '{}': {}").format(values["name"], e)
            )
            self.log(
                f"Update datastore error: {e}", log_level=Qgis.MessageLevel.Critical
            )
        finally:
            self.unsetCursor()

    def _delete_datastore(self, row_data):
        """Delete a single datastore after confirmation."""
        ds_name, ws_name = row_data[0], row_data[1]
        if not self._confirm_delete(self.tr("datastore"), f"{ws_name}/{ds_name}"):
            return

        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self._do_delete_datastore(ws_name, ds_name)
            self.show_success_message(
                self.tr("Datastore '{}' deleted.").format(ds_name)
            )
            self._load_datastores()
        except Exception as e:
            self.show_error_message(
                self.tr("Failed to delete datastore '{}': {}").format(ds_name, e)
            )
            self.log(
                f"Delete datastore error: {e}", log_level=Qgis.MessageLevel.Critical
            )
        finally:
            self.unsetCursor()

    def _delete_selected_datastores(self, selected_rows):
        """Delete multiple datastores after confirmation."""
        if not selected_rows:
            return

        labels = [f"{row[1]}/{row[0]}" for row in selected_rows]
        reply = QMessageBox.warning(
            self,
            self.tr("Confirm Delete"),
            self.tr(
                "Are you sure you want to delete {} datastore(s)?\n\n{}\n\n"
                "This action cannot be undone."
            ).format(len(labels), "\n".join(f"  \u2022 {lbl}" for lbl in labels)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.setCursor(Qt.CursorShape.WaitCursor)
        errors = []
        try:
            for row in selected_rows:
                ds_name, ws_name = row[0], row[1]
                try:
                    self._do_delete_datastore(ws_name, ds_name)
                except Exception as e:
                    errors.append(f"{ws_name}/{ds_name}: {e}")
            if errors:
                self.show_error_message(
                    self.tr("Failed to delete some datastores:\n{}").format(
                        "\n".join(errors)
                    )
                )
            else:
                self.show_success_message(
                    self.tr("{} datastore(s) deleted.").format(len(selected_rows))
                )
            self._load_datastores()
        finally:
            self.unsetCursor()

    def _do_delete_datastore(self, workspace_name, datastore_name):
        """Execute the REST DELETE for a datastore (recurse=true removes feature types too)."""
        # TODO: Replace with gs.delete_datastore() once the library adds this method.
        # Workaround: direct DELETE to /workspaces/{ws}/datastores/{ds}.json?recurse=true
        path = self.gs.rest_service.rest_endpoints.datastore(
            workspace_name, datastore_name
        )
        response = self.gs.rest_service.rest_client.delete(
            path, params={"recurse": "true"}
        )
        if response.status_code >= 400:
            raise Exception(response.content.decode())

    def _open_workspace_from_row(self, row_data):
        """Open the workspace info dialog for the workspace in a datastore row."""
        ws_name = row_data[1]
        try:
            detail, _ = self.gs.get_workspace(ws_name)
            isolated = (
                str(detail.get("isolated", False)) if isinstance(detail, dict) else "—"
            )
        except Exception:
            isolated = "—"
        self._show_workspace_info([ws_name, isolated])
