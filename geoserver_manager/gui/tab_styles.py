#! python3  # noqa: E265

"""
Styles tab — list, view/edit, upload and delete styles.

Used as a mixin for GeoServerMainDialog.
"""

from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QDialog, QFileDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.toolbelt.sld import (
    SLD_1_0,
    apply_sld_to_layer,
    layer_to_sld,
    project_layer_by_label,
    sld_content_type,
    sld_version,
    styleable_project_layers,
)

# Styles live either globally or inside a workspace. Rows are display strings,
# so the global scope needs a label; _scope() maps it back to None for the API.
GLOBAL = "(global)"

# Formats whose body the library can PUT back (rest_service.create_style).
# Anything else (css, …) is shown read-only.
_EDITABLE_FORMATS = ("sld", "mbstyle")

_SOURCE_PASTE = "Paste SLD"
_SOURCE_FILE = "From file"
_SOURCE_QGIS = "From a QGIS layer"


# Every user-visible string in this file goes through translate() with this
# file's own class as the context. self.tr() cannot: pylupdate extracts it
# under StyleTabMixin, but at runtime self.tr is QObject.tr with the context of the
# *instance's* class, GeoServerMainDialog — QDialog precedes the mixins in the
# MRO — so every lookup would miss. A wrapper function would not be extracted
# at all (pylupdate only understands a literal context), hence the repetition.
translate = QCoreApplication.translate


class StyleTabMixin:
    """Mixin that adds style methods to the main dialog."""

    @staticmethod
    def _scope(workspace_label):
        """Workspace name for the API, or None for the global scope."""
        return None if workspace_label in ("", GLOBAL) else workspace_label

    def _load_styles(self):
        """Arm the Styles tab, then fetch its rows in the background."""
        self._setup_add_button(
            translate("StyleTabMixin", "Upload a Style"),
            translate("StyleTabMixin", "Upload a style from an SLD file or pasted SLD"),
            self._add_style,
        )
        self._setup_delete_selected_button(self._delete_selected_styles)
        self._name_click_callback = self._show_style_info
        self._extra_click_callbacks = {
            translate("StyleTabMixin", "Workspace"): self._open_workspace_from_style_row
        }
        self._row_actions = [
            (
                "mActionSharingImport.svg",
                translate("StyleTabMixin", "Apply to a QGIS layer"),
                self._apply_style_to_qgis,
            ),
            (
                "mActionFileSaveAs.svg",
                translate("StyleTabMixin", "Save as SLD"),
                self._save_style_to_disk,
            ),
            (
                "mActionDeleteSelected.svg",
                translate("StyleTabMixin", "Delete"),
                self._delete_style,
            ),
        ]
        self._setup_table(
            [
                translate("StyleTabMixin", "Style Name"),
                translate("StyleTabMixin", "Workspace"),
                self.actions_column_label(),
            ]
        )
        self._start_load(
            translate("StyleTabMixin", "Failed to load styles"), self._fetch_style_rows
        )

    def _fetch_style_rows(self, task=None):
        """(rows, failures) for the Styles table. Runs in a worker thread."""
        rows = [
            [self._name_of(style), GLOBAL]
            for style in self._fetch_list(self.gs.get_styles)
        ]
        ws_names = self._get_workspace_names()
        failures = []
        for ws_name, (styles, error) in zip(
            ws_names,
            self._fan_out(
                lambda ws: self._fetch_list(self.gs.get_styles, ws), ws_names, task
            ),
        ):
            if error:
                failures.append((ws_name, error))
                continue
            rows.extend([self._name_of(style), ws_name] for style in styles)
        return rows, failures

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
        if style_format == "sld":
            self._put_sld_body(name, workspace_name, body)
            return
        self._check(
            self.gs.rest_service.create_style(
                name, body.encode("utf-8"), workspace_name, format=style_format
            )
        )

    def _put_sld_body(self, name, workspace_name, sld):
        """PUT an SLD body with the content type its own version needs.

        TODO(#50): upstream as a content type chosen from the document (or a
        `content_type=` argument). rest_service.create_style() derives it from
        the *format* alone and only knows application/vnd.ogc.sld+xml, so an
        SLD 1.1 document — which is what QgsMapLayer.saveSldStyle() writes,
        always — is stored with languageVersion 1.0.0: accepted, rendered, and
        mislabelled. Sending application/vnd.ogc.se+xml records it as 1.1.0.
        """
        content_type = sld_content_type(sld)
        if content_type == SLD_1_0:
            self._check(
                self.gs.rest_service.create_style(
                    name, sld.encode("utf-8"), workspace_name, format="sld"
                )
            )
            return
        path = self.gs.rest_service.rest_endpoints.style(
            name, workspace_name, format="sld"
        )
        self._raw_rest(
            "put",
            path,
            data=sld.encode("utf-8"),
            headers={"Content-Type": content_type},
        )

    # -- View / edit -----------------------------------------------------------

    @staticmethod
    def _language_version(definition):
        """The SLD version GeoServer recorded for a style, or "" if unknown."""
        value = (definition or {}).get("languageVersion")
        if isinstance(value, dict):
            value = value.get("version")
        return str(value) if value else ""

    def _style_fields(self, editable, language_version=""):
        """Field definitions for the style dialog."""
        return [
            {
                "key": "name",
                "label": translate("StyleTabMixin", "Style Name"),
                "type": "text",
                "read_only": True,
            },
            {
                "key": "workspace",
                "label": translate("StyleTabMixin", "Workspace"),
                "type": "text",
                "read_only": True,
            },
            {
                "key": "format",
                "label": translate("StyleTabMixin", "Format"),
                "type": "text",
                "read_only": True,
            },
            {
                "key": "version",
                "label": translate("StyleTabMixin", "SLD version"),
                "type": "text",
                "read_only": True,
                "help": (
                    # GeoServer keeps the 1.1 document but serves .sld as its
                    # 1.0 rendition, so the body below is not the stored bytes.
                    translate(
                        "StyleTabMixin",
                        "Stored as SLD 1.1 (Symbology Encoding) — what QGIS "
                        "exports. GeoServer serves it here as its SLD 1.0 "
                        "rendition, and saving stores that rendition instead.",
                    )
                    if language_version.startswith("1.1")
                    else None
                ),
            },
            {
                "key": "filename",
                "label": translate("StyleTabMixin", "File"),
                "type": "text",
                "read_only": True,
            },
            {
                "key": "body",
                "label": translate("StyleTabMixin", "Definition"),
                "type": "textarea",
                "read_only": not editable,
                "required": editable,
                "group": translate("StyleTabMixin", "Style"),
                "help": (
                    translate(
                        "StyleTabMixin",
                        "Edit and Save to replace the style on the server.",
                    )
                    if editable
                    else translate(
                        "StyleTabMixin",
                        "Read-only: only SLD and MBStyle bodies can be saved here.",
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

        fetched = self._fetch(
            fetch, translate("StyleTabMixin", "Failed to load style '{}'").format(name)
        )
        if fetched is None:
            return
        definition, style_format, body = fetched
        editable = style_format in _EDITABLE_FORMATS
        language_version = self._language_version(definition)

        dlg = ResourceFormDialog(
            title=translate("StyleTabMixin", "Style '{}'").format(name),
            description=(
                translate("StyleTabMixin", "Modify the style") if editable else None
            ),
            fields=self._style_fields(editable, language_version),
            values={
                "name": name,
                "workspace": row_data[1],
                "format": style_format,
                "version": language_version or "—",
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
            translate("StyleTabMixin", "Failed to save style '{}'").format(name),
        ):
            self.show_success_message(
                translate("StyleTabMixin", "Style '{}' saved.").format(name)
            )

    # -- Upload ----------------------------------------------------------------

    def _upload_fields(self, workspace_names):
        return [
            {
                "key": "name",
                "label": translate("StyleTabMixin", "Style Name"),
                "type": "text",
                "required": True,
            },
            {
                "key": "workspace",
                "label": translate("StyleTabMixin", "Workspace"),
                "type": "combo",
                "options": [GLOBAL] + list(workspace_names),
                "help": translate(
                    "StyleTabMixin",
                    "Global styles can be used by layers of every workspace",
                ),
            },
            {
                "key": "source",
                "label": translate("StyleTabMixin", "Source"),
                "type": "combo",
                "options": [_SOURCE_PASTE, _SOURCE_FILE, _SOURCE_QGIS],
            },
            {
                "key": "sld",
                "label": translate("StyleTabMixin", "SLD"),
                "type": "textarea",
                "required": True,
                "group": translate("StyleTabMixin", "Style"),
                "placeholder": translate(
                    "StyleTabMixin", "Paste the SLD document here"
                ),
            },
            {
                "key": "file",
                "label": translate("StyleTabMixin", "File"),
                "type": "file",
                "required": True,
                "visible": False,
                "group": translate("StyleTabMixin", "Style"),
                "filter": "Styles (*.sld *.zip *.mbstyle);;All files (*)",
                "help": translate(
                    "StyleTabMixin",
                    ".sld, a .zip with an SLD and its resources, or .mbstyle",
                ),
            },
            {
                "key": "qgis_layer",
                "label": translate("StyleTabMixin", "QGIS layer"),
                "type": "combo",
                "options": [label for label, _layer in styleable_project_layers()],
                "required": True,
                "visible": False,
                "group": translate("StyleTabMixin", "Style"),
                "help": translate(
                    "StyleTabMixin",
                    "The layer's symbology is exported as SLD and uploaded. QGIS "
                    "writes SLD 1.1, which GeoServer stores as such.",
                ),
            },
        ]

    def _on_style_source_changed(self, dlg, source):
        dlg.set_field_visible("sld", source == _SOURCE_PASTE)
        dlg.set_field_visible("file", source == _SOURCE_FILE)
        dlg.set_field_visible("qgis_layer", source == _SOURCE_QGIS)

    def _add_style(self):
        """Upload a style from pasted SLD or from a file."""
        dlg = ResourceFormDialog(
            title=translate("StyleTabMixin", "Upload a Style"),
            description=translate(
                "StyleTabMixin",
                "Create a style from an SLD you paste, a file you pick, or the "
                "symbology of a layer in this QGIS project.",
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
            translate("StyleTabMixin", "Failed to upload style '{}'").format(
                values["name"]
            ),
        ):
            self.show_success_message(
                translate("StyleTabMixin", "Style '{}' uploaded.").format(
                    values["name"]
                )
            )
            self._load_styles()

    def _create_style_from_values(self, values):
        """Create a style through the library, refusing to overwrite an existing one."""
        name, workspace_name = values["name"], self._scope(values["workspace"])
        # create_style_* upsert (and rewrite the definition's filename)
        if self._resource_exists(self.gs.get_style_definition, name, workspace_name):
            raise ValueError(
                translate("StyleTabMixin", "Style '{}' already exists in {}.").format(
                    name, values["workspace"] or GLOBAL
                )
            )
        source = values.get("source")
        if source == _SOURCE_FILE:
            path = Path(values["file"])
            if path.suffix.lower() != ".sld":
                # A .zip carries an SLD plus its resources and an .mbstyle is
                # not SLD at all: both are the library's job, untouched.
                self._check(
                    self.gs.create_style_from_file(name, str(path), workspace_name)
                )
                return
            self._create_sld_style(
                name, workspace_name, path.read_text(encoding="utf-8")
            )
        elif source == _SOURCE_QGIS:
            self._create_sld_style(
                name, workspace_name, layer_to_sld(self._picked_layer(values))
            )
        else:
            self._create_sld_style(name, workspace_name, values["sld"])

    def _create_sld_style(self, name, workspace_name, sld):
        """Create the style definition, then upload the body as its version."""
        # create_style_from_string would do both, but always with the SLD 1.0
        # content type — see _put_sld_body.
        self._check(
            self.gs.create_style_definition(name, f"{name}.sld", workspace_name)
        )
        self._put_sld_body(name, workspace_name, sld)

    @staticmethod
    def _picked_layer(values):
        """The project layer the form's QGIS-layer combo points at."""
        return project_layer_by_label(values["qgis_layer"])

    # -- QGIS <-> GeoServer ----------------------------------------------------

    def _sld_for_qgis(self, row_data):
        """One style's SLD body, or None once the reason has been reported.

        QGIS reads SLD only, so a CSS or MBStyle style is refused here rather
        than handed over for QGIS to fail on.
        """
        name, workspace_name = row_data[0], self._scope(row_data[1])
        fetched = self._fetch(
            lambda: self._check(self.gs.get_style_definition(name, workspace_name)),
            translate("StyleTabMixin", "Failed to load style '{}'").format(name),
        )
        if fetched is None:
            return None
        style_format = str((fetched or {}).get("format") or "sld").lower()
        if style_format != "sld":
            self.show_warning_message(
                translate(
                    "StyleTabMixin", "'{}' is a {} style — QGIS can only read SLD."
                ).format(name, style_format.upper())
            )
            return None
        return self._fetch(
            lambda: self._style_body(name, workspace_name, "sld"),
            translate("StyleTabMixin", "Failed to load the SLD of '{}'").format(name),
        )

    def _apply_style_to_qgis(self, row_data):
        """Load a server style into one of the project's layers."""
        name = row_data[0]
        layers = styleable_project_layers()
        if not layers:
            self.show_warning_message(
                translate(
                    "StyleTabMixin",
                    "This QGIS project has no vector or raster layer to style.",
                )
            )
            return
        sld = self._sld_for_qgis(row_data)
        if sld is None:
            return

        dlg = ResourceFormDialog(
            title=translate("StyleTabMixin", "Apply '{}' to a QGIS layer").format(name),
            description=translate(
                "StyleTabMixin",
                "The style is applied to the layer in this project only — the "
                "server is not touched.",
            ),
            fields=[
                {
                    "key": "qgis_layer",
                    "label": translate("StyleTabMixin", "QGIS layer"),
                    "type": "combo",
                    "options": [label for label, _layer in layers],
                    "required": True,
                }
            ],
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        layer = self._picked_layer(dlg.get_values())
        outcome = []
        if not self._run_action(
            lambda: outcome.extend(apply_sld_to_layer(layer, sld)),
            translate("StyleTabMixin", "Failed to apply '{}' to '{}'").format(
                name, layer.name()
            ),
        ):
            return
        ok, message = outcome[0], outcome[1]
        if ok:
            self.show_success_message(
                translate("StyleTabMixin", "'{}' now uses the style '{}'.").format(
                    layer.name(), name
                )
            )
        else:
            # QGIS reads less SLD than it writes; say what it could not take.
            self.show_warning_message(
                translate(
                    "StyleTabMixin", "QGIS could not read all of '{}': {}"
                ).format(name, message or translate("StyleTabMixin", "no detail given"))
            )

    def _save_style_to_disk(self, row_data):
        """Write a style's body to a file the user picks."""
        name, workspace_name = row_data[0], self._scope(row_data[1])
        definition = self._fetch(
            lambda: self._check(self.gs.get_style_definition(name, workspace_name)),
            translate("StyleTabMixin", "Failed to load style '{}'").format(name),
        )
        if definition is None:
            return
        style_format = str((definition or {}).get("format") or "sld").lower()
        body = self._fetch(
            lambda: self._style_body(name, workspace_name, style_format),
            translate("StyleTabMixin", "Failed to load the body of '{}'").format(name),
        )
        if body is None:
            return

        suggested = (definition or {}).get("filename") or f"{name}.{style_format}"
        path, _selected = QFileDialog.getSaveFileName(
            self,
            translate("StyleTabMixin", "Save style '{}'").format(name),
            suggested,
            f"{style_format.upper()} (*.{style_format});;All files (*)",
        )
        if not path:
            return
        if self._run_action(
            lambda: Path(path).write_text(body, encoding="utf-8"),
            translate("StyleTabMixin", "Failed to save '{}'").format(name),
        ):
            self.show_success_message(
                translate("StyleTabMixin", "Style '{}' saved as {} ({}).").format(
                    name, Path(path).name, sld_version(body)
                )
                if style_format == "sld"
                else translate("StyleTabMixin", "Style '{}' saved as {}.").format(
                    name, Path(path).name
                )
            )

    # -- Delete ----------------------------------------------------------------

    def _delete_style(self, row_data):
        """Delete a single style after confirmation."""
        self._delete_selected_styles([row_data])

    def _delete_selected_styles(self, selected_rows):
        """Delete one or more styles after confirmation."""
        self._delete_many(
            translate("StyleTabMixin", "style"),
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
            cascade=translate(
                "StyleTabMixin",
                "The style file is removed from the server too, and layers that used "
                "it fall back to GeoServer's default style.\n\n",
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
