#! python3  # noqa: E265

"""
Workspace tab — load, create, edit, delete workspaces.

Used as a mixin for GeoServerMainDialog.
"""

from qgis.core import Qgis
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog


class WorkspaceTabMixin:
    """Mixin that adds workspace CRUD methods to the main dialog."""

    def _load_workspaces(self):
        """Fetch all workspaces and display them in the results table."""
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self._setup_add_button(
                self.tr("Add a New Workspace"),
                self.tr("Create a new workspace"),
                self._add_workspace,
            )
            self._setup_delete_selected_button(self._delete_selected_workspaces)
            self._name_click_callback = self._show_workspace_info
            self._extra_click_callbacks = {}
            self._row_actions = [
                (
                    "mActionDeleteSelected.svg",
                    self.tr("Delete"),
                    self._delete_workspace,
                ),
            ]
            self._setup_table(
                [
                    self.tr("Workspace Name"),
                    self.tr("Actions"),
                ]
            )
            workspaces = self._fetch_list(self.gs.get_workspaces)
            rows = [
                [ws.get("name", str(ws)) if isinstance(ws, dict) else str(ws)]
                for ws in workspaces
            ]
            self._populate_rows(rows)
        except Exception as e:
            self.show_error_message(self.tr("Failed to load workspaces: {}").format(e))
            self.log(f"Workspace load error: {e}", log_level=Qgis.MessageLevel.Critical)
        finally:
            self.unsetCursor()

    def _workspace_fields(self):
        """Return workspace form field definitions."""
        return [
            {"key": "name", "label": self.tr("Name"), "type": "text", "required": True},
            {
                "key": "isolated",
                "label": self.tr("Isolated Workspace"),
                "type": "checkbox",
                "default": False,
                "help": self.tr(
                    "Allow objects with the same name to coexist in this workspace"
                ),
            },
            {
                "key": "set_default",
                "label": self.tr("Default Workspace"),
                "type": "checkbox",
                "default": False,
                "help": self.tr("Set this as the default workspace for GeoServer"),
            },
        ]

    def _set_default_workspace(self, name):
        """Set the GeoServer default workspace.

        TODO: move to geoservercloud — its create_workspace(set_default_workspace=True)
        only sets a client-side attribute, it never calls the server.
        Workaround: PUT /rest/workspaces/default.json
        """
        path = f"{self.gs.rest_service.rest_endpoints.base_url}/workspaces/default.json"
        response = self.gs.rest_service.rest_client.put(
            path, json={"workspace": {"name": name}}
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"HTTP {response.status_code}: {response.content.decode()}"
            )

    def _add_workspace(self):
        """Open a form dialog to create a new workspace."""
        dlg = ResourceFormDialog(
            title=self.tr("New Workspace"),
            description=self.tr("Configure a new workspace"),
            fields=self._workspace_fields(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self._check(
                self.gs.create_workspace(values["name"], isolated=values["isolated"])
            )
            if values["set_default"]:
                self._set_default_workspace(values["name"])
            self.show_success_message(
                self.tr("Workspace '{}' created.").format(values["name"])
            )
            self._load_workspaces()
        except Exception as e:
            self.show_error_message(
                self.tr("Failed to create workspace '{}': {}").format(values["name"], e)
            )
            self.log(
                f"Create workspace error: {e}",
                log_level=Qgis.MessageLevel.Critical,
            )
        finally:
            self.unsetCursor()

    def _show_workspace_info(self, row_data):
        """Open a form dialog to view/edit an existing workspace."""
        old_name = row_data[0]

        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            detail = self._check(self.gs.get_workspace(old_name))
        except Exception as e:
            self.show_error_message(
                self.tr("Failed to load workspace details: {}").format(e)
            )
            return
        finally:
            self.unsetCursor()

        current_values = {
            "name": old_name,
            "isolated": (
                bool(detail.get("isolated", False))
                if isinstance(detail, dict)
                else False
            ),
            "set_default": False,
        }
        dlg = ResourceFormDialog(
            title=self.tr("Edit Workspace '{}'").format(old_name),
            description=self.tr("Modify workspace settings"),
            fields=self._workspace_fields(),
            values=current_values,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        new_name = values["name"]
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            if new_name != old_name:
                # TODO: Replace this workaround with a proper
                # `gs.update_workspace()` method once geoservercloud adds
                # rename support. See: https://github.com/camptocamp/python-geoservercloud
                # Workaround: direct PUT to /workspaces/{old_name} with new name.
                from geoservercloud.models.workspace import Workspace

                ws = Workspace(new_name, values["isolated"])
                path = self.gs.rest_service.rest_endpoints.workspace(old_name)
                response = self.gs.rest_service.rest_client.put(
                    path, json=ws.put_payload()
                )
                if response.status_code >= 400:
                    raise RuntimeError(response.content.decode())
            else:
                self._check(
                    self.gs.create_workspace(new_name, isolated=values["isolated"])
                )
            if values["set_default"]:
                self._set_default_workspace(new_name)
            self.show_success_message(
                self.tr("Workspace '{}' updated.").format(new_name)
            )
            self._load_workspaces()
        except Exception as e:
            self.show_error_message(
                self.tr("Failed to update workspace '{}': {}").format(values["name"], e)
            )
            self.log(
                f"Update workspace error: {e}",
                log_level=Qgis.MessageLevel.Critical,
            )
        finally:
            self.unsetCursor()

    def _delete_workspace(self, row_data):
        """Delete a single workspace after confirmation."""
        self._delete_selected_workspaces([row_data])

    def _delete_selected_workspaces(self, selected_rows):
        """Delete one or more workspaces after confirmation."""
        self._delete_many(
            self.tr("workspace"),
            [
                (row[0], lambda n=row[0]: self._check(self.gs.delete_workspace(n)))
                for row in selected_rows
            ],
            self._load_workspaces,
        )
