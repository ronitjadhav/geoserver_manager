#! python3  # noqa: E265

"""
Workspace tab: load, create, edit, delete workspaces.

Used as a mixin for GeoServerMainDialog.
"""

from qgis.core import Qgis
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

# GeoServer spells the WMS abstract "abstrct" in its JSON, a typo old enough to
# be API. Keywords and the SRS list arrive wrapped as {"string": [...]}.
_ABSTRACT = "abstrct"


# Every user-visible string in this file goes through translate() with this
# file's own class as the context. self.tr() cannot: pylupdate extracts it
# under WorkspaceTabMixin, but at runtime self.tr is QObject.tr with the context of the
# *instance's* class, GeoServerMainDialog. QDialog precedes the mixins in the
# MRO, so every lookup would miss. A wrapper function would not be extracted
# at all (pylupdate only understands a literal context), hence the repetition.
translate = QCoreApplication.translate


class WorkspaceTabMixin:
    """Mixin that adds workspace CRUD methods to the main dialog."""

    def _load_workspaces(self):
        """Arm the Workspaces tab, then fetch its rows in the background."""
        self._setup_add_button(
            translate("WorkspaceTabMixin", "Add a Workspace"),
            translate(
                "WorkspaceTabMixin",
                "Create a workspace to hold stores, layers and styles",
            ),
            self._add_workspace,
        )
        self._setup_delete_selected_button(self._delete_selected_workspaces)
        self._name_click_callback = self._show_workspace_info
        self._extra_click_callbacks = {}
        self._row_actions = [
            (
                "delete",
                translate("WorkspaceTabMixin", "Delete"),
                self._delete_workspace,
            ),
        ]
        self._setup_table(
            [
                translate("WorkspaceTabMixin", "Name"),
                translate("WorkspaceTabMixin", "Default"),
                self.actions_column_label(),
            ]
        )
        self._start_load(
            translate("WorkspaceTabMixin", "Failed to load workspaces"),
            self._fetch_workspace_rows,
        )

    def _fetch_workspace_rows(self, task=None):
        """(rows, failures) for the Workspaces table. Runs in a worker thread."""
        workspaces = self._fetch_list(self.gs.get_workspaces)
        # Shown in the list so the server's truth is visible at a glance:
        # GeoServer always has exactly one default and it cannot be unset.
        default = self._default_workspace_name()
        rows = [
            [name, translate("WorkspaceTabMixin", "default") if name == default else ""]
            for name in (self._name_of(ws) for ws in workspaces)
        ]
        return rows, []

    def _workspace_fields(self, is_default=False, with_wms=False):
        """Return workspace form field definitions.

        :param is_default: the workspace being edited already is GeoServer's
            default; the checkbox is then shown ticked and locked, because the
            REST API has no "unset default", only "set another one".
        :param with_wms: append the WMS service group. Only for an existing
            workspace: its settings can only be PUT once it exists.
        """
        fields = [
            {
                "key": "name",
                "label": translate("WorkspaceTabMixin", "Name"),
                "type": "text",
                "required": True,
            },
            {
                "key": "isolated",
                "label": translate("WorkspaceTabMixin", "Isolated Workspace"),
                "type": "checkbox",
                "default": False,
                "help": translate(
                    "WorkspaceTabMixin",
                    "Its layers are served only under the workspace's own URLs "
                    "(…/{name}/wms), so another workspace may share its namespace URI",
                ),
            },
            {
                "key": "set_default",
                "label": translate("WorkspaceTabMixin", "Default Workspace"),
                "type": "checkbox",
                "default": False,
                "read_only": is_default,
                "help": (
                    translate(
                        "WorkspaceTabMixin",
                        "This is GeoServer's default workspace. There is always "
                        "exactly one and it cannot be unset. To change it, tick "
                        "Default on another workspace.",
                    )
                    if is_default
                    else translate(
                        "WorkspaceTabMixin",
                        "Make this GeoServer's default workspace (replaces the current one)",
                    )
                ),
            },
        ]
        return fields + self._wms_fields() if with_wms else fields

    # -- WMS service settings --------------------------------------------------

    def _wms_fields(self):
        """The WMS group: one workspace's own WMS service settings."""
        group = translate("WorkspaceTabMixin", "WMS")
        return [
            {
                "key": "wms_own",
                "label": translate("WorkspaceTabMixin", "Own WMS settings"),
                "type": "checkbox",
                "group": group,
                "help": translate(
                    "WorkspaceTabMixin",
                    "Untick to fall back to GeoServer's global WMS settings. The "
                    "workspace's own are then removed.",
                ),
            },
            {
                "key": "wms_enabled",
                "label": translate("WorkspaceTabMixin", "Service enabled"),
                "type": "checkbox",
                "group": group,
                "help": translate(
                    "WorkspaceTabMixin", "Serve WMS for this workspace at all"
                ),
            },
            {
                "key": "wms_title",
                "label": translate("WorkspaceTabMixin", "Title"),
                "type": "text",
                "group": group,
            },
            {
                "key": "wms_abstract",
                "label": translate("WorkspaceTabMixin", "Abstract"),
                "type": "textarea",
                "group": group,
            },
            {
                "key": "wms_keywords",
                "label": translate("WorkspaceTabMixin", "Keywords"),
                "type": "text",
                "group": group,
                "help": translate("WorkspaceTabMixin", "Comma separated"),
            },
            {
                "key": "wms_srs",
                "label": translate("WorkspaceTabMixin", "SRS list"),
                "type": "text",
                "group": group,
                "help": translate(
                    "WorkspaceTabMixin",
                    "EPSG codes without the prefix, comma separated (4326, 3857). "
                    "Empty advertises every SRS GeoServer knows.",
                ),
            },
            {
                "key": "wms_max_rendering_time",
                "label": translate("WorkspaceTabMixin", "Max rendering time (s)"),
                "type": "spinbox",
                "min": 0,
                "max": 86400,
                "group": group,
                "help": translate("WorkspaceTabMixin", "0 means no limit"),
            },
            {
                "key": "wms_max_rendering_errors",
                "label": translate("WorkspaceTabMixin", "Max rendering errors"),
                "type": "spinbox",
                "min": 0,
                "max": 1000000,
                "group": group,
                "help": translate("WorkspaceTabMixin", "0 means no limit"),
            },
            {
                "key": "wms_default_locale",
                "label": translate("WorkspaceTabMixin", "Default locale"),
                "type": "text",
                "group": group,
                "help": translate(
                    "WorkspaceTabMixin",
                    "Language of the internationalised title and abstract, e.g. en",
                ),
            },
        ]

    def _wms_settings_path(self, workspace_name):
        return self.gs.rest_service.rest_endpoints.workspace_wms_settings(
            workspace_name
        )

    def _wms_settings(self, workspace_name):
        """One workspace's WMS settings, or None when it has none of its own.

        TODO(#50): upstream: WmsSettings models neither the title, the
        abstract, the keywords nor the SRS list, so
        get_workspace_wms_settings() cannot show what this form is for. The
        facade call is still what answers "does this workspace have its own
        settings" (404 when it does not); the payload comes from a raw GET.
        """
        if not self._resource_exists(
            self.gs.get_workspace_wms_settings, workspace_name
        ):
            return None
        payload = self._raw_rest("get", self._wms_settings_path(workspace_name)).json()
        return payload.get("wms") or {}

    @staticmethod
    def _joined(value):
        """A GeoServer string list ({"string": [...]}, or a bare value) as text."""
        items = value.get("string") if isinstance(value, dict) else value
        if isinstance(items, (str, int)):
            items = [items]
        return ", ".join(str(item) for item in (items or []))

    @classmethod
    def _wms_form_values(cls, settings):
        """Prefill for the WMS group; settings is None for "no own settings"."""
        present = settings is not None
        settings = settings or {}
        return {
            "wms_own": present,
            "wms_enabled": bool(settings.get("enabled", True)),
            "wms_title": settings.get("title") or "",
            "wms_abstract": settings.get(_ABSTRACT) or "",
            "wms_keywords": cls._joined(settings.get("keywords")),
            "wms_srs": cls._joined(settings.get("srs")),
            "wms_max_rendering_time": int(settings.get("maxRenderingTime") or 0),
            "wms_max_rendering_errors": int(settings.get("maxRenderingErrors") or 0),
            "wms_default_locale": settings.get("defaultLocale") or "",
        }

    def _on_wms_own_changed(self, dlg, own):
        """The WMS fields only matter when the workspace keeps its own settings."""
        for field in self._wms_fields()[1:]:
            dlg.set_field_visible(field["key"], own)

    @staticmethod
    def _split(text):
        return [item.strip() for item in text.split(",") if item.strip()]

    def _apply_wms_settings(self, workspace_name, values, existed):
        """Create, update or remove one workspace's own WMS settings.

        TODO(#50): see _wms_settings; put_workspace_wms_settings() cannot
        carry the title, abstract, keywords or SRS list, so this PUTs the
        settings path itself.
        """
        path = self._wms_settings_path(workspace_name)
        if not values["wms_own"]:
            if existed:
                self._raw_rest("delete", path)
            return

        # A partial PUT merges: GeoServer keeps every field this form does not
        # model (watermark, buffers, metadata links, …), verified on 2.28.5,
        # and the same PUT creates the settings when the workspace has none
        # (a POST there answers 405).
        settings = {
            "workspace": {"name": workspace_name},
            "name": "WMS",
            "enabled": values["wms_enabled"],
            "title": values["wms_title"],
            _ABSTRACT: values["wms_abstract"],
            "keywords": {"string": self._split(values["wms_keywords"])},
            "srs": {"string": self._split(values["wms_srs"])},
            "maxRenderingTime": values["wms_max_rendering_time"],
            "maxRenderingErrors": values["wms_max_rendering_errors"],
            # Empty, never null: GeoServer's LocaleConverter throws an NPE on
            # a null defaultLocale (500, "Cannot invoke String.indexOf … in is
            # null"), while "" is accepted and reads back as no locale.
            "defaultLocale": values["wms_default_locale"].strip(),
        }
        self._raw_rest("put", path, json={"wms": settings})

    def _default_workspace_name(self):
        """Name of GeoServer's default workspace, or None if it cannot be read.

        TODO(#50): upstream as get_default_workspace(); no getter exists.
        """
        try:
            base = self.gs.rest_service.rest_endpoints.base_url
            payload = self._raw_rest("get", f"{base}/workspaces/default.json").json()
            return payload.get("workspace", {}).get("name")
        except Exception:  # best-effort prefill: unreadable means "unknown"
            return None

    def _set_default_workspace(self, name):
        """Set the GeoServer default workspace.

        TODO(#50): upstream as set_default_workspace(). The library's
        create_workspace(set_default_workspace=True) only sets a client-side
        attribute and never calls the server. Workaround: PUT
        /rest/workspaces/default.json
        """
        path = f"{self.gs.rest_service.rest_endpoints.base_url}/workspaces/default.json"
        self._raw_rest("put", path, json={"workspace": {"name": name}})

    def _put_workspace(self, old_name, new_name, isolated):
        """Update a workspace in place, a rename when the names differ.

        TODO(#50): upstream as update_workspace(name, new_name=..., isolated=...).
        The library has no update and no rename, and create_workspace() on an
        existing name costs a POST that answers 409 before it PUTs. Workaround:
        one PUT to /rest/workspaces/{old_name}.
        """
        from geoservercloud.models.workspace import Workspace

        path = self.gs.rest_service.rest_endpoints.workspace(old_name)
        self._raw_rest("put", path, json=Workspace(new_name, isolated).put_payload())

    def _save_workspace(self, values, old_name=None):
        """Create (old_name None) or update a workspace from form values."""
        name = values["name"]
        if old_name is None or name != old_name:
            # A new name goes into a REST path: refuse what a URL would eat.
            self._require_safe_name(name)
        if old_name is None:
            # create_workspace upserts, so an existing name would silently
            # reconfigure the live workspace and report it as created
            if self._resource_exists(self.gs.get_workspace, name):
                raise ValueError(
                    translate(
                        "WorkspaceTabMixin", "Workspace '{}' already exists."
                    ).format(name)
                )
            self._check(self.gs.create_workspace(name, isolated=values["isolated"]))
        else:
            # One PUT, rename or not (create_workspace would POST, get a 409,
            # then PUT).
            self._put_workspace(old_name, name, values["isolated"])
        if values["set_default"]:
            # Separate from the save: a 403 here must not report the (already
            # successful) create or rename as failed, nor skip the reload.
            try:
                self._set_default_workspace(name)
            except Exception as e:
                self.show_warning_message(
                    translate(
                        "WorkspaceTabMixin",
                        "Workspace '{}' saved, but it could not be made the default: {}",
                    ).format(name, e)
                )
                self.log(f"Set default workspace error: {e}", Qgis.MessageLevel.Warning)

    def _add_workspace(self):
        """Open a form dialog to create a new workspace."""
        dlg = ResourceFormDialog(
            title=translate("WorkspaceTabMixin", "Add a Workspace"),
            description=translate(
                "WorkspaceTabMixin",
                "A workspace groups stores, layers and styles under one name, "
                "which also prefixes its layers (workspace:layer).",
            ),
            fields=self._workspace_fields(),
            parent=self,
            ok_label=translate("WorkspaceTabMixin", "Create"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._save_workspace(values),
            translate("WorkspaceTabMixin", "Failed to create workspace '{}'").format(
                values["name"]
            ),
        ):
            self.show_success_message(
                translate("WorkspaceTabMixin", "Workspace '{}' created.").format(
                    values["name"]
                )
            )
            self._load_workspaces()

    def _show_workspace_info(self, row_data):
        """Open a form dialog to view/edit an existing workspace and its WMS."""
        old_name = row_data[0]
        fetched = self._fetch(
            lambda: (
                self._check(self.gs.get_workspace(old_name)),
                self._wms_settings(old_name),
            ),
            translate("WorkspaceTabMixin", "Failed to load workspace details"),
        )
        if fetched is None:
            return
        detail, wms_settings = fetched

        is_default = self._default_workspace_name() == old_name
        values = {
            "name": old_name,
            "isolated": (
                bool(detail.get("isolated", False))
                if isinstance(detail, dict)
                else False
            ),
            "set_default": is_default,
        }
        values.update(self._wms_form_values(wms_settings))
        dlg = ResourceFormDialog(
            title=translate("WorkspaceTabMixin", "Edit Workspace '{}'").format(
                old_name
            ),
            description=translate(
                "WorkspaceTabMixin",
                "Rename it, toggle isolation, make it the default, or give it its "
                "own WMS settings. Save applies all of it at once.",
            ),
            fields=self._workspace_fields(is_default=is_default, with_wms=True),
            values=values,
            parent=self,
        )
        own = dlg.get_widget("wms_own")
        own.toggled.connect(lambda checked: self._on_wms_own_changed(dlg, checked))
        self._on_wms_own_changed(dlg, own.isChecked())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        had_wms = wms_settings is not None
        if self._run_action(
            lambda: self._save_workspace_and_wms(values, old_name, had_wms),
            translate("WorkspaceTabMixin", "Failed to update workspace '{}'").format(
                values["name"]
            ),
        ):
            self.show_success_message(
                translate("WorkspaceTabMixin", "Workspace '{}' updated.").format(
                    values["name"]
                )
            )
            # Reachable from the datastore tab, so reload whatever is on screen
            self._reload_current_tab()

    def _save_workspace_and_wms(self, values, old_name, had_wms):
        """Save the workspace, then its WMS settings, in that order.

        A rename has to land first: the settings live under the workspace's
        (new) name.
        """
        self._save_workspace(values, old_name=old_name)
        self._apply_wms_settings(values["name"], values, had_wms)

    def _delete_workspace(self, row_data):
        """Delete a single workspace after confirmation."""
        self._delete_selected_workspaces([row_data])

    def _delete_selected_workspaces(self, selected_rows):
        """Delete one or more workspaces after confirmation."""
        self._delete_many(
            translate("WorkspaceTabMixin", "workspace"),
            [
                (row[0], lambda n=row[0]: self._check(self.gs.delete_workspace(n)))
                for row in selected_rows
            ],
            self._load_workspaces,
            # delete_workspace() sends recurse=true
            cascade=translate(
                "WorkspaceTabMixin",
                "Everything it contains is deleted too: datastores, coverage "
                "stores, cascaded stores, layers, layer groups and styles.",
            ),
        )
