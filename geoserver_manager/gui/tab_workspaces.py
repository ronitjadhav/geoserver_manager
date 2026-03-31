#! python3  # noqa: E265

"""
Workspace tab — load, create, edit, delete workspaces.

Used as a mixin for GeoServerMainDialog.
"""

from qgis.core import Qgis
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QMessageBox

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
                    self.tr("Isolated"),
                    self.tr("Actions"),
                ]
            )
            workspaces = self._fetch_list(self.gs.get_workspaces)

            rows = []
            for ws in workspaces:
                name = ws.get("name", str(ws)) if isinstance(ws, dict) else str(ws)
                detail, _ = self.gs.get_workspace(name)
                isolated = (
                    str(detail.get("isolated", False))
                    if isinstance(detail, dict)
                    else "—"
                )
                rows.append([name, isolated])

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
            self.gs.create_workspace(
                values["name"],
                isolated=values["isolated"],
                set_default_workspace=values["set_default"],
            )
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
        current_values = {
            "name": old_name,
            "isolated": row_data[1] == "True",
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
                    raise Exception(response.content.decode())
            else:
                self.gs.create_workspace(
                    new_name,
                    isolated=values["isolated"],
                    set_default_workspace=values["set_default"],
                )
            if values["set_default"]:
                self.gs.default_workspace = new_name
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

    def _delete_selected_workspaces(self, selected_rows):
        """Delete multiple workspaces after confirmation."""
        if not selected_rows:
            return

        names = [row[0] for row in selected_rows]
        reply = QMessageBox.warning(
            self,
            self.tr("Confirm Delete"),
            self.tr(
                "Are you sure you want to delete {} workspace(s)?\n\n{}\n\n"
                "This action cannot be undone."
            ).format(len(names), "\n".join(f"  \u2022 {n}" for n in names)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.setCursor(Qt.CursorShape.WaitCursor)
        errors = []
        try:
            for name in names:
                try:
                    self.gs.delete_workspace(name)
                except Exception as e:
                    errors.append(f"{name}: {e}")
            if errors:
                self.show_error_message(
                    self.tr("Failed to delete some workspaces:\n{}").format(
                        "\n".join(errors)
                    )
                )
            else:
                self.show_success_message(
                    self.tr("{} workspace(s) deleted.").format(len(names))
                )
            self._load_workspaces()
        finally:
            self.unsetCursor()

    def _delete_workspace(self, row_data):
        """Delete the workspace after confirmation."""
        name = row_data[0]
        if not self._confirm_delete(self.tr("workspace"), name):
            return

        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            self.gs.delete_workspace(name)
            self.show_success_message(self.tr("Workspace '{}' deleted.").format(name))
            self._load_workspaces()
        except Exception as e:
            self.show_error_message(
                self.tr("Failed to delete workspace '{}': {}").format(name, e)
            )
            self.log(
                f"Delete workspace error: {e}",
                log_level=Qgis.MessageLevel.Critical,
            )
        finally:
            self.unsetCursor()
