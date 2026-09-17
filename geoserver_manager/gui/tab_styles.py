#! python3  # noqa: E265

"""
Styles tab — list, view/edit, upload and delete styles.

Used as a mixin for GeoServerMainDialog.
"""

from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

# Styles live either globally or inside a workspace. Rows are display strings,
# so the global scope needs a label; _scope() maps it back to None for the API.
GLOBAL = "(global)"

# Formats whose body the library can PUT back (rest_service.create_style).
# Anything else (css, …) is shown read-only.
_EDITABLE_FORMATS = ("sld", "mbstyle")

_SOURCE_PASTE = "Paste SLD"
_SOURCE_FILE = "From file"


class StyleTabMixin:
    """Mixin that adds style methods to the main dialog.

    ponytail: same translation caveat as WorkspaceTabMixin — self.tr() here is
    extracted under this class but resolved against the host dialog's context.
    """

    @staticmethod
    def _scope(workspace_label):
        """Workspace name for the API, or None for the global scope."""
        return None if workspace_label in ("", GLOBAL) else workspace_label

    def _load_styles(self):
        """List global styles and every workspace's styles."""

        def load():
            self._setup_add_button(
                self.tr("Upload a Style"),
                self.tr("Upload a style from an SLD file or pasted SLD"),
                self._add_style,
            )
            self._setup_delete_selected_button(self._delete_selected_styles)
            self._name_click_callback = self._show_style_info
            self._extra_click_callbacks = {
                self.tr("Workspace"): self._open_workspace_from_style_row
            }
            self._row_actions = [
                ("mActionDeleteSelected.svg", self.tr("Delete"), self._delete_style),
            ]
            self._setup_table(
                [self.tr("Style Name"), self.tr("Workspace"), self.tr("Actions")]
            )

            rows = [
                [self._name_of(style), GLOBAL]
                for style in self._fetch_list(self.gs.get_styles)
            ]
            ws_names = self._get_workspace_names()
            failures = []
            for ws_name, (styles, error) in zip(
                ws_names,
                self._fan_out(
                    lambda ws: self._fetch_list(self.gs.get_styles, ws), ws_names
                ),
            ):
                if error:
                    failures.append((ws_name, error))
                    continue
                rows.extend([self._name_of(style), ws_name] for style in styles)
            self._populate_rows(rows)
            self._report_partial_failures(failures)

        self._run_action(load, self.tr("Failed to load styles"))

    def _open_workspace_from_style_row(self, row_data):
        """The Workspace column links to the workspace — unless it is the global scope."""
        if self._scope(row_data[1]) is not None:
            self._show_workspace_info([row_data[1]])

    # -- Body ------------------------------------------------------------------

    def _style_body(self, name, workspace_name, style_format):
        """The style document itself (SLD, CSS, …), as text.

        TODO(#50): upstream as get_style_body(name, ws, format) on the facade.
        rest_service.get_style() exists but its endpoint only knows json / sld /
        mbstyle, so a CSS style comes back as its JSON definition instead of its
        body. Workaround: GET the style path with the definition's own format.
        """
        path = self.gs.rest_service.rest_endpoints.style(
            name, workspace_name, format="json"
        )
        path = path[: -len(".json")] + f".{style_format}"
        content = self._raw_rest("get", path).content
        return content.decode("utf-8", errors="replace")

    def _save_style_body(self, name, workspace_name, style_format, body):
        """PUT a new body for an existing style, leaving its definition alone."""
        # Not create_style_from_string: that also rewrites the definition and
        # renames the file to <name>.sld, which changes a style that was
        # e.g. popshade.sld under the hood.
        self._check(
            self.gs.rest_service.create_style(
                name, body.encode("utf-8"), workspace_name, format=style_format
            )
        )

    # -- View / edit -----------------------------------------------------------

    def _style_fields(self, editable):
        """Field definitions for the style dialog."""
        return [
            {
                "key": "name",
                "label": self.tr("Style Name"),
                "type": "text",
                "read_only": True,
            },
            {
                "key": "workspace",
                "label": self.tr("Workspace"),
                "type": "text",
                "read_only": True,
            },
            {
                "key": "format",
                "label": self.tr("Format"),
                "type": "text",
                "read_only": True,
            },
            {
                "key": "filename",
                "label": self.tr("File"),
                "type": "text",
                "read_only": True,
            },
            {
                "key": "body",
                "label": self.tr("Definition"),
                "type": "textarea",
                "read_only": not editable,
                "required": editable,
                "group": self.tr("Style"),
                "help": (
                    self.tr("Edit and Save to replace the style on the server.")
                    if editable
                    else self.tr(
                        "Read-only: only SLD and MBStyle bodies can be saved here."
                    )
                ),
            },
        ]

    def _show_style_info(self, row_data):
        """Open a style: definition read-only, body editable for SLD/MBStyle."""
        name, workspace_name = row_data[0], self._scope(row_data[1])

        def fetch():
            definition = self._check(self.gs.get_style_definition(name, workspace_name))
            definition = definition if isinstance(definition, dict) else {}
            style_format = str(definition.get("format") or "sld").lower()
            return (
                definition,
                style_format,
                self._style_body(name, workspace_name, style_format),
            )

        fetched = self._fetch(fetch, self.tr("Failed to load style '{}'").format(name))
        if fetched is None:
            return
        definition, style_format, body = fetched
        editable = style_format in _EDITABLE_FORMATS

        dlg = ResourceFormDialog(
            title=self.tr("Style '{}'").format(name),
            description=self.tr("Modify the style") if editable else None,
            fields=self._style_fields(editable),
            values={
                "name": name,
                "workspace": row_data[1],
                "format": style_format,
                "filename": definition.get("filename", ""),
                "body": body,
            },
            parent=self,
        )
        dlg.get_widget("body").setMaximumHeight(400)
        if not editable:
            dlg.hide_save_button()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_body = dlg.get_values()["body"]
        if new_body == body.strip():
            return
        if self._run_action(
            lambda: self._save_style_body(name, workspace_name, style_format, new_body),
            self.tr("Failed to save style '{}'").format(name),
        ):
            self.show_success_message(self.tr("Style '{}' saved.").format(name))

    # -- Upload ----------------------------------------------------------------

    def _upload_fields(self, workspace_names):
        return [
            {
                "key": "name",
                "label": self.tr("Style Name"),
                "type": "text",
                "required": True,
            },
            {
                "key": "workspace",
                "label": self.tr("Workspace"),
                "type": "combo",
                "options": [GLOBAL] + list(workspace_names),
                "help": self.tr(
                    "Global styles can be used by layers of every workspace"
                ),
            },
            {
                "key": "source",
                "label": self.tr("Source"),
                "type": "combo",
                "options": [_SOURCE_PASTE, _SOURCE_FILE],
            },
            {
                "key": "sld",
                "label": self.tr("SLD"),
                "type": "textarea",
                "required": True,
                "group": self.tr("Style"),
                "placeholder": self.tr("Paste the SLD document here"),
            },
            {
                "key": "file",
                "label": self.tr("File"),
                "type": "file",
                "required": True,
                "visible": False,
                "group": self.tr("Style"),
                "filter": "Styles (*.sld *.zip *.mbstyle);;All files (*)",
                "help": self.tr(
                    ".sld, a .zip with an SLD and its resources, or .mbstyle"
                ),
            },
        ]

    def _on_style_source_changed(self, dlg, source):
        dlg.set_field_visible("sld", source == _SOURCE_PASTE)
        dlg.set_field_visible("file", source == _SOURCE_FILE)

    def _add_style(self):
        """Upload a style from pasted SLD or from a file."""
        dlg = ResourceFormDialog(
            title=self.tr("Upload a Style"),
            description=self.tr(
                "Create a style from an SLD you paste or a file you pick."
            ),
            fields=self._upload_fields(self._get_workspace_names()),
            parent=self,
        )
        dlg.get_widget("source").currentTextChanged.connect(
            lambda source: self._on_style_source_changed(dlg, source)
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._create_style_from_values(values),
            self.tr("Failed to upload style '{}'").format(values["name"]),
        ):
            self.show_success_message(
                self.tr("Style '{}' uploaded.").format(values["name"])
            )
            self._load_styles()

    def _create_style_from_values(self, values):
        """Create a style through the library, refusing to overwrite an existing one."""
        name, workspace_name = values["name"], self._scope(values["workspace"])
        # create_style_* upsert (and rewrite the definition's filename)
        if self._resource_exists(self.gs.get_style_definition, name, workspace_name):
            raise ValueError(
                self.tr("Style '{}' already exists in {}.").format(
                    name, values["workspace"] or GLOBAL
                )
            )
        if values.get("source") == _SOURCE_FILE:
            self._check(
                self.gs.create_style_from_file(name, values["file"], workspace_name)
            )
        else:
            self._check(
                self.gs.create_style_from_string(name, values["sld"], workspace_name)
            )

    # -- Delete ----------------------------------------------------------------

    def _delete_style(self, row_data):
        """Delete a single style after confirmation."""
        self._delete_selected_styles([row_data])

    def _delete_selected_styles(self, selected_rows):
        """Delete one or more styles after confirmation."""
        self._delete_many(
            self.tr("style"),
            [
                (
                    f"{row[1]}/{row[0]}",
                    lambda name=row[0], ws=self._scope(row[1]): self._do_delete_style(
                        name, ws
                    ),
                )
                for row in selected_rows
            ],
            self._load_styles,
            cascade=self.tr(
                "The style file is removed from the server too, and layers that used "
                "it fall back to GeoServer's default style.\n\n"
            ),
        )

    def _do_delete_style(self, name, workspace_name):
        """DELETE a style, its file (purge) and its references (recurse).

        TODO(#50): upstream as delete_style(name, ws, purge=True, recurse=True) —
        the library has no delete for styles. Workaround: DELETE the style path
        with purge=true&recurse=true.
        """
        path = self.gs.rest_service.rest_endpoints.style(
            name, workspace_name, format="json"
        )
        self._raw_rest("delete", path, params={"purge": "true", "recurse": "true"})
