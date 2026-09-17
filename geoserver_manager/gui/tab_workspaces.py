#! python3  # noqa: E265

"""
Workspace tab — load, create, edit, delete workspaces.

Used as a mixin for GeoServerMainDialog.
"""

from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog


class WorkspaceTabMixin:
    """Mixin that adds workspace CRUD methods to the main dialog.

    ponytail: the self.tr() calls below cannot resolve translations. They are
    extracted under this class name, but at runtime resolve to QObject.tr,
    whose context is the host dialog (QDialog precedes the mixins in the MRO,
    so overriding tr() here would be dead code). When the first translation
    lands, switch these sites to an explicit
    QCoreApplication.translate("WorkspaceTabMixin", ...).
    """

    def _load_workspaces(self):
        """Fetch all workspaces and display them in the results table."""

        def load():
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
            self._populate_rows([[self._name_of(ws)] for ws in workspaces])

        self._run_action(load, self.tr("Failed to load workspaces"))

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
        self._raw_rest("put", path, json={"workspace": {"name": name}})

    def _rename_workspace(self, old_name, new_name, isolated):
        """Rename a workspace in place.

        TODO: replace with gs.update_workspace() once geoservercloud has
        rename support. Workaround: PUT the new name to /workspaces/{old_name}.
        """
        from geoservercloud.models.workspace import Workspace

        path = self.gs.rest_service.rest_endpoints.workspace(old_name)
        self._raw_rest("put", path, json=Workspace(new_name, isolated).put_payload())

    def _save_workspace(self, values, old_name=None):
        """Create (old_name None) or update a workspace from form values."""
        name = values["name"]
        if old_name is None:
            # create_workspace upserts, so an existing name would silently
            # reconfigure the live workspace and report it as created
            if self._resource_exists(self.gs.get_workspace, name):
                raise ValueError(self.tr("Workspace '{}' already exists.").format(name))
            self._check(self.gs.create_workspace(name, isolated=values["isolated"]))
        elif name != old_name:
            self._rename_workspace(old_name, name, values["isolated"])
        else:
            self._check(self.gs.create_workspace(name, isolated=values["isolated"]))
        if values["set_default"]:
            self._set_default_workspace(name)

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
        if self._run_action(
            lambda: self._save_workspace(values),
            self.tr("Failed to create workspace '{}'").format(values["name"]),
        ):
            self.show_success_message(
                self.tr("Workspace '{}' created.").format(values["name"])
            )
            self._load_workspaces()

    def _show_workspace_info(self, row_data):
        """Open a form dialog to view/edit an existing workspace."""
        old_name = row_data[0]
        detail = self._fetch(
            lambda: self._check(self.gs.get_workspace(old_name)),
            self.tr("Failed to load workspace details"),
        )
        if detail is None:
            return

        dlg = ResourceFormDialog(
            title=self.tr("Edit Workspace '{}'").format(old_name),
            description=self.tr("Modify workspace settings"),
            fields=self._workspace_fields(),
            values={
                "name": old_name,
                "isolated": (
                    bool(detail.get("isolated", False))
                    if isinstance(detail, dict)
                    else False
                ),
                "set_default": False,
            },
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._save_workspace(values, old_name=old_name),
            self.tr("Failed to update workspace '{}'").format(values["name"]),
        ):
            self.show_success_message(
                self.tr("Workspace '{}' updated.").format(values["name"])
            )
            # Reachable from the datastore tab, so reload whatever is on screen
            self._reload_current_tab()

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
            # delete_workspace() sends recurse=true
            cascade=self.tr(
                "Everything it contains is deleted too: datastores, layers, "
                "styles and layer groups.\n\n"
            ),
        )
