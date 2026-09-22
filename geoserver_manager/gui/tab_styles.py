#! python3  # noqa: E265

"""
Styles tab: list, view/edit, upload and delete styles.

Used as a mixin for GeoServerMainDialog.
"""

import re
from pathlib import Path
from urllib.parse import quote

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import QDialog, QFileDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.scope import GLOBAL, scope
from geoserver_manager.toolbelt.sld import (
    SLD_1_0,
    apply_sld_to_layer,
    layer_to_sld,
    project_layer_by_label,
    sld_content_type,
    sld_version,
    styleable_project_layers,
)

# Styles live either globally or inside a workspace; the label for the global
# scope and the mapping back to None are shared with layer groups (gui.scope).

# Formats whose body the library can PUT back (rest_service.create_style).
# Anything else (css, …) is shown read-only.
_EDITABLE_FORMATS = ("sld", "mbstyle")

_SOURCE_PASTE = "Paste SLD"
_SOURCE_FILE = "From file"
_SOURCE_QGIS = "From a QGIS layer"


# Every user-visible string in this file goes through translate() with this
# file's own class as the context. self.tr() cannot: pylupdate extracts it
# under StyleTabMixin, but at runtime self.tr is QObject.tr with the context of the
# *instance's* class, GeoServerMainDialog. QDialog precedes the mixins in the
# MRO, so every lookup would miss. A wrapper function would not be extracted
# at all (pylupdate only understands a literal context), hence the repetition.
translate = QCoreApplication.translate


class StyleTabMixin:
    """Mixin that adds style methods to the main dialog."""

    def _load_styles(self):
        """Arm the Styles tab, then fetch its rows in the background."""
        self._setup_add_button(
            translate("StyleTabMixin", "Upload a Style"),
            translate(
                "StyleTabMixin",
                "Upload a style from an SLD file, pasted SLD, or a QGIS layer's symbology",
            ),
            self._add_style,
        )
        self._setup_delete_selected_button(self._delete_selected_styles)
        self._name_click_callback = self._show_style_info
        self._extra_click_callbacks = {
            translate("StyleTabMixin", "Workspace"): self._open_workspace_from_row
        }
        self._row_actions = [
            (
                "apply-style",
                translate("StyleTabMixin", "Apply to a QGIS layer"),
                self._apply_style_to_qgis,
                translate(
                    "StyleTabMixin",
                    "Put this server style on a layer of the open project, the same "
                    "as the layer tree's Apply style from GeoServer, from this end",
                ),
            ),
            (
                "save-style",
                translate("StyleTabMixin", "Save to disk"),
                self._save_style_to_disk,
                translate(
                    "StyleTabMixin",
                    "Write the style's body (SLD, CSS or MBStyle) to a file",
                ),
            ),
            (
                "delete",
                translate("StyleTabMixin", "Delete"),
                self._delete_style,
            ),
        ]
        self._setup_table(
            [
                translate("StyleTabMixin", "Name"),
                translate("StyleTabMixin", "Workspace"),
                translate("StyleTabMixin", "Format"),
                translate("StyleTabMixin", "Version"),
                self.actions_column_label(),
            ]
        )
        self._start_load(
            translate("StyleTabMixin", "Failed to load styles"), self._fetch_style_rows
        )

    def _fetch_style_rows(self, task=None):
        """(rows, failures) for the Styles table. Runs in a worker thread.

        The format and the SLD version come from each style's definition. One
        GET per style, fanned out, because whether a style is SLD decides what
        *Apply to a QGIS layer* can do with it.
        """
        pairs = [
            (self._name_of(style), GLOBAL)
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
            pairs.extend((self._name_of(style), ws_name) for style in styles)
        details = self._fan_out(
            lambda pair: self._style_summary(pair[0], scope(pair[1])), pairs, task
        )
        rows = [
            [name, ws_label, *(summary or ("-", "-"))]
            for (name, ws_label), (summary, _error) in zip(pairs, details)
        ]
        failures += [
            (f"{ws_label}/{name}", error)
            for (name, ws_label), (_summary, error) in zip(pairs, details)
            if error
        ]
        return rows, failures

    def _style_summary(self, name, workspace_name):
        """(format, SLD version) cells of one style. Raises on HTTP errors."""
        definition = self._check(self.gs.get_style_definition(name, workspace_name))
        if not isinstance(definition, dict):
            return ("-", "-")
        return (
            str(definition.get("format") or "sld").lower(),
            self._language_version(definition) or "-",
        )

    # -- Body ------------------------------------------------------------------

    def _style_body(self, name, workspace_name, style_format):
        """The style document itself (SLD, CSS, …), as text.

        TODO(#50): upstream as get_style_body(name, ws, format) on the facade.
        rest_service.get_style() exists but its endpoint only knows json / sld /
        mbstyle, so a CSS style comes back as its JSON definition instead of its
        body. Workaround: GET the style path with the definition's own format.
        """
        path = self._style_path(name, workspace_name, "json")
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
        SLD 1.1 document (which is what QgsMapLayer.saveSldStyle() writes,
        always) is stored with languageVersion 1.0.0: accepted, rendered, and
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
        self._raw_rest(
            "put",
            self._style_path(name, workspace_name, "sld"),
            data=sld.encode("utf-8"),
            headers={"Content-Type": content_type},
        )

    def _style_path(self, name, workspace_name, style_format):
        """The style's REST path with its segments URL-quoted.

        TODO(#50): `RestEndpoints.style()` interpolates the names raw, and
        `requests` sends `styles/a#b.json` as `styles/a`, a different style.
        Pre-quoting the segments the builder receives is the smallest fix; it
        has to go when the library quotes them itself, or `%` doubles.
        """
        return self.gs.rest_service.rest_endpoints.style(
            quote(name, safe=""),
            quote(workspace_name, safe="") if workspace_name else None,
            format=style_format,
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
                        "Stored as SLD 1.1 (Symbology Encoding), what QGIS "
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
                "key": "legend",
                "label": translate("StyleTabMixin", "Legend"),
                "type": "image",
                "placeholder": translate(
                    "StyleTabMixin", "Asking GeoServer for the legend…"
                ),
                "help": translate(
                    "StyleTabMixin", "As GeoServer renders it (GetLegendGraphic)."
                ),
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
        name, workspace_name = row_data[0], scope(row_data[1])

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
                translate(
                    "StyleTabMixin",
                    "Edit the definition below and Save to replace it on the server; "
                    "every layer using the style changes with it.",
                )
                if editable
                else None
            ),
            fields=self._style_fields(editable, language_version),
            values={
                "name": name,
                "workspace": row_data[1],
                "format": style_format,
                "version": language_version or "-",
                "filename": definition.get("filename", ""),
                "body": body,
            },
            parent=self,
        )
        dlg.get_widget("body").setMaximumHeight(400)
        self._load_legend(dlg, name, workspace_name)
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

    # -- Legend ----------------------------------------------------------------

    def _legend_layer(self, workspace_name):
        """A published layer to draw the legend with, or None when there is none.

        GetLegendGraphic needs a LAYER even for a stored style; the layer only
        supplies the rendering context, so any published layer does. One from
        the style's own workspace is preferred. TODO(#50): the facade has no
        get_layers() and RestEndpoints has no path for GeoServer's layer list
        (its layers() / layer() are GeoWebCache's), so this GETs
        /rest/layers.json: the global list, qualified names included.
        """
        base = self.gs.rest_service.rest_endpoints.base_url
        if workspace_name:
            # The workspace's own collection: names come back bare there.
            path = f"{base}/workspaces/{quote(workspace_name, safe='')}/layers.json"
            payload = self._raw_rest("get", path).json()
            for entry in self._unwrap(payload, "layers", "layer"):
                name = self._name_of(entry)
                return name if ":" in name else f"{workspace_name}:{name}"
        payload = self._raw_rest("get", f"{base}/layers.json").json()
        names = [
            self._name_of(entry) for entry in self._unwrap(payload, "layers", "layer")
        ]
        return names[0] if names else None

    def _legend_png(self, layer, name, workspace_name):
        """The legend GeoServer renders for the style, as PNG bytes.

        TODO(#50): get_legend_graphic() is a plain GET through the REST client
        (stateless, so fine in a worker), but it hands back the raw Response, an
        OGC exception is HTTP 200 with an XML body, and it runs with the
        client's 120 s timeout.
        """
        style = f"{workspace_name}:{name}" if workspace_name else name
        response = self.gs.get_legend_graphic(layer, style=style)
        if not response.headers.get("Content-Type", "").startswith("image/"):
            raise RuntimeError(self._ogc_exception_text(response.text))
        return response.content

    @staticmethod
    def _ogc_exception_text(text):
        """The sentence inside an OGC exception report, else its first line."""
        match = re.search(
            r"<(?:\w+:)?(?:ServiceException|ExceptionText)\b[^>]*>\s*([^<]+?)\s*<",
            text or "",
        )
        if match:
            return match.group(1)
        lines = (text or "").strip().splitlines()
        return lines[0][:200] if lines else "GeoServer returned no image"

    def _load_legend(self, dlg, name, workspace_name):
        """Fetch the legend into the dialog's image field, off the GUI thread.

        The dialog is modal and may be closed, even gone, before the picture
        lands, so the landing looks before it paints. Failures land in the
        field too: a banner would sit behind the modal.
        """
        closed = []
        dlg.finished.connect(lambda _result: closed.append(True))

        def work(task):
            try:
                layer = self._legend_layer(workspace_name)
                if layer is None:
                    return None, translate(
                        "StyleTabMixin",
                        "No published layer to draw the legend with. "
                        "GetLegendGraphic needs one.",
                    )
                return self._legend_png(layer, name, workspace_name), None
            except Exception as e:
                return None, translate("StyleTabMixin", "No legend: {}").format(
                    self._error_text(e)
                )

        def landed(result):
            if closed or sip.isdeleted(dlg):
                return
            png, problem = result
            pixmap = QPixmap()
            if png and pixmap.loadFromData(png):
                dlg.set_image("legend", pixmap)
            else:
                dlg.set_image(
                    "legend",
                    None,
                    problem
                    or translate("StyleTabMixin", "GeoServer did not return an image."),
                )

        self._run_quietly(
            translate("StyleTabMixin", "Failed to load the legend"), work, landed
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
        """Upload a style from pasted SLD, a file, or a QGIS layer."""
        workspace_names = self._fetch(
            self._get_workspace_names,
            translate("StyleTabMixin", "Failed to load the workspaces"),
        )
        if workspace_names is None:
            return
        dlg = ResourceFormDialog(
            title=translate("StyleTabMixin", "Upload a Style"),
            description=translate(
                "StyleTabMixin",
                "Create a style from an SLD you paste, a file you pick, or the "
                "symbology of a layer in this QGIS project.",
            ),
            fields=self._upload_fields(workspace_names),
            parent=self,
            ok_label=translate("StyleTabMixin", "Upload"),
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
        name, workspace_name = values["name"].strip(), scope(values["workspace"])
        self._require_safe_name(name)
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
        # content type; see _put_sld_body.
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
        name, workspace_name = row_data[0], scope(row_data[1])
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
                    "StyleTabMixin", "'{}' is a {} style. QGIS can only read SLD."
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
                "The style is applied to the layer in this project only. The "
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
            ok_label=translate("StyleTabMixin", "Apply"),
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
        name, workspace_name = row_data[0], scope(row_data[1])
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
                    lambda name=row[0], ws=scope(row[1]): self._do_delete_style(
                        name, ws
                    ),
                )
                for row in selected_rows
            ],
            self._load_styles,
            cascade=translate(
                "StyleTabMixin",
                "The style file is removed from the server too, and layers that used "
                "it fall back to GeoServer's default style.",
            ),
        )

    def _do_delete_style(self, name, workspace_name):
        """DELETE a style, its file (purge) and its references (recurse).

        TODO(#50): upstream as delete_style(name, ws, purge=True, recurse=True):
        the library has no delete for styles. Workaround: DELETE the style path
        with purge=true&recurse=true.
        """
        self._raw_rest(
            "delete",
            self._style_path(name, workspace_name, "json"),
            params={"purge": "true", "recurse": "true"},
        )
