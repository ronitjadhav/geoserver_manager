#! python3  # noqa: E265

"""
Tile Cache tab — the layers GeoWebCache caches, with their gridsets and
formats, and the two things one does to a cache: truncate it, stop caching.

Used as a mixin for GeoServerMainDialog.

GeoWebCache's REST API is XML-first, and on GeoServer 2.28.5 its JSON *writes*
are broken: a PUT of the very document a GET returned fails with "Duplicate
field mimeFormats" (every array) or "defaultValue" (the STYLES parameter filter
loses its class). Every write here is therefore XML — GET `.xml`, edit the
document, PUT `.xml` — which round-trips byte for byte. Reads stay JSON.
"""

import xml.etree.ElementTree as ElementTree
from xml.sax.saxutils import escape

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QDialog

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.scope import GLOBAL

_XML = {"Content-Type": "application/xml"}

# What GeoServer itself configures when it caches a new layer automatically.
DEFAULT_GRIDSETS = ("EPSG:4326", "EPSG:900913")
DEFAULT_FORMATS = ("image/png", "image/jpeg")

# The document GeoServer writes for a new layer, minus the id it fills in
# itself. The STYLES filter is what lets one cache hold a tile set per style.
_NEW_LAYER_XML = (
    "<GeoServerLayer><enabled>true</enabled><name>{name}</name>"
    "<mimeFormats/><gridSubsets/><metaWidthHeight/>"
    "<expireCache>0</expireCache><expireClients>0</expireClients><gutter>0</gutter>"
    "<parameterFilters><styleParameterFilter><key>STYLES</key>"
    "<defaultValue></defaultValue></styleParameterFilter></parameterFilters>"
    "</GeoServerLayer>"
)


# Every user-visible string in this file goes through translate() with this
# file's own class as the context. self.tr() cannot: pylupdate extracts it
# under GwcTabMixin, but at runtime self.tr is QObject.tr with the context of
# the *instance's* class, GeoServerMainDialog — QDialog precedes the mixins in
# the MRO — so every lookup would miss. A wrapper function would not be
# extracted at all (pylupdate only understands a literal context), hence the
# repetition.
translate = QCoreApplication.translate


def _int_or_zero(text):
    """An integer out of a GWC document, 0 when it is not one."""
    try:
        return int(text or 0)
    except ValueError:
        return 0


class GwcTabMixin:
    """Mixin that adds the tile-cache (GeoWebCache) methods to the main dialog."""

    # -- Load -----------------------------------------------------------------

    def _load_gwc_layers(self):
        """Arm the Tile Cache tab, then fetch its rows in the background."""
        self._setup_add_button(
            translate("GwcTabMixin", "Add a Layer to the Cache"),
            translate(
                "GwcTabMixin",
                "Configure GeoWebCache for a published layer it does not cache yet",
            ),
            self._add_gwc_layer,
        )
        self._setup_delete_selected_button(
            self._remove_selected_gwc_layers,
            translate("GwcTabMixin", "Remove Selected from Cache"),
        )
        self._name_click_callback = self._show_gwc_layer_info
        self._extra_click_callbacks = {
            translate("GwcTabMixin", "Workspace"): self._open_workspace_from_row
        }
        self._row_actions = [
            (
                "mIconClearItem.svg",
                translate("GwcTabMixin", "Truncate"),
                self._truncate_gwc_layer,
                translate(
                    "GwcTabMixin",
                    "Delete every cached tile of the layer; its cache configuration "
                    "stays",
                ),
            ),
            (
                "mActionDeleteSelected.svg",
                translate("GwcTabMixin", "Remove from cache"),
                self._remove_gwc_layer,
                translate(
                    "GwcTabMixin",
                    "Stop caching the layer: its tiles and cache configuration go, "
                    "the layer itself stays",
                ),
            ),
        ]
        self._setup_table(
            [
                translate("GwcTabMixin", "Layer"),
                translate("GwcTabMixin", "Workspace"),
                translate("GwcTabMixin", "Enabled"),
                translate("GwcTabMixin", "Gridsets"),
                translate("GwcTabMixin", "Formats"),
                self.actions_column_label(),
            ]
        )
        self._start_load(
            translate("GwcTabMixin", "Failed to load the tile cache"),
            self._fetch_gwc_rows,
        )

    def _fetch_gwc_rows(self, task=None):
        """(rows, failures) for the table. Runs in a worker thread."""
        names = self._gwc_layer_names()
        details = self._fan_out(self._gwc_layer_detail, names, task)
        rows = [
            [name, self._gwc_workspace(name), *self._gwc_layer_summary(detail)]
            for name, (detail, _error) in zip(names, details)
        ]
        failures = [
            (name, error) for name, (_detail, error) in zip(names, details) if error
        ]
        return rows, failures

    # -- Reads ----------------------------------------------------------------

    def _gwc_base(self):
        """GeoWebCache's REST root, `/gwc/rest` on a stock GeoServer."""
        return self.gs.rest_service.gwc_endpoints.base_url

    def _gwc_layer_path(self, name, ext="json"):
        """REST path of one cached layer, by its qualified (or bare) name."""
        return f"{self._gwc_base()}/layers/{name}.{ext}"

    def _gwc_layer_names(self):
        """Every layer GeoWebCache caches: `ws:name`, a global layer group bare.

        TODO(#50): the library has the endpoint (`GwcEndpoints.layers()`, which
        ignores its workspace argument) but no method that calls it.
        Workaround: GET the collection, a plain JSON array of names.
        """
        endpoints = self.gs.rest_service.gwc_endpoints
        payload = self._raw_rest("get", endpoints.layers(None)).json()
        return sorted(str(name) for name in self._as_list(payload))

    def _gwc_layer_detail(self, name):
        """The GeoServerLayer document: enabled, gridSubsets, mimeFormats, …"""
        workspace, _, layer = name.rpartition(":")
        if workspace:
            payload = self._check(self.gs.get_gwc_layer(workspace, layer))
        else:
            # TODO(#50): get_gwc_layer() takes a workspace and a layer, so a
            # global layer group — cached under its bare name — is out of reach.
            payload = self._raw_rest("get", self._gwc_layer_path(name)).json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected response: {str(payload)[:200]}")
        return payload.get("GeoServerLayer") or {}

    def _gwc_layer_xml(self, name):
        """The same document as XML — the only form a PUT accepts.

        TODO(#50): get_gwc_layer() reads JSON only, and nothing updates a
        cached layer. Workaround: GET the `.xml` rendition and edit it.
        """
        return self._raw_rest("get", self._gwc_layer_path(name, "xml")).text

    def _gwc_layer_exists(self, name):
        """True when GeoWebCache already caches the layer."""
        workspace, _, layer = name.rpartition(":")
        if workspace:
            return self._resource_exists(self.gs.get_gwc_layer, workspace, layer)
        service = self.gs.rest_service  # TODO(#50): as in _gwc_layer_detail
        return service.resource_exists(self._gwc_layer_path(name))

    def _gridset_names(self):
        """The gridsets the server knows, for the picker.

        TODO(#50): create_gridset(epsg) PUTs one of three shipped definitions
        and nothing lists them. Workaround: GET the collection.
        """
        endpoints = self.gs.rest_service.gwc_endpoints
        payload = self._raw_rest("get", endpoints.gridsets()).json()
        return sorted(str(name) for name in self._as_list(payload))

    def _uncached_layer_names(self):
        """Published layers and global layer groups GeoWebCache does not cache."""
        base = self.gs.rest_service.rest_endpoints.base_url
        # TODO(#50): no get_layers() in the library (row 39), and the global
        # layer-group collection is out of its reach too (row 16).
        layers = self._raw_rest("get", f"{base}/layers.json").json()
        groups = self._raw_rest("get", f"{base}/layergroups.json").json()
        published = {
            self._name_of(item) for item in self._unwrap(layers, "layers", "layer")
        }
        published |= {
            self._name_of(item)
            for item in self._unwrap(groups, "layerGroups", "layerGroup")
        }
        return sorted(published - set(self._gwc_layer_names()))

    @staticmethod
    def _gwc_workspace(name):
        """The workspace a cached layer belongs to; a global group has none."""
        workspace, _, _layer = name.rpartition(":")
        return workspace or GLOBAL

    @staticmethod
    def _as_list(value):
        """GeoWebCache's JSON writes an empty collection as "" and may write a
        one-entry collection bare."""
        if value in (None, ""):
            return []
        return [value] if isinstance(value, (dict, str)) else list(value)

    @staticmethod
    def _gwc_layer_summary(detail):
        """(enabled, gridsets, formats) cells; a layer whose GET failed shows dashes."""
        if not isinstance(detail, dict) or not detail:
            return ("—", "—", "—")
        gridsets = ", ".join(
            (
                str(subset.get("gridSetName", "?"))
                if isinstance(subset, dict)
                else str(subset)
            )
            for subset in GwcTabMixin._as_list(detail.get("gridSubsets"))
        )
        formats = ", ".join(
            str(fmt) for fmt in GwcTabMixin._as_list(detail.get("mimeFormats"))
        )
        return (str(detail.get("enabled", True)), gridsets or "—", formats or "—")

    # -- The document ---------------------------------------------------------

    @staticmethod
    def _lines(text):
        """Non-empty, stripped, de-duplicated lines of a textarea, in order."""
        lines = []
        for line in (text or "").splitlines():
            line = line.strip()
            if line and line not in lines:
                lines.append(line)
        return lines

    @staticmethod
    def _parse_xml(xml_text):
        if isinstance(xml_text, str):
            # fromstring() refuses a str that carries an encoding declaration
            xml_text = xml_text.encode("utf-8")
        return ElementTree.fromstring(xml_text)

    @staticmethod
    def _gwc_form_values(xml_text):
        """Prefill for the dialog, from the XML document. Pure."""
        root = GwcTabMixin._parse_xml(xml_text)

        def number(tag):
            try:
                return int(root.findtext(tag) or 0)
            except ValueError:
                return 0

        meta = [
            _int_or_zero(element.text)
            for element in root.findall("metaWidthHeight/int")
        ]
        return {
            "name": root.findtext("name") or "",
            "enabled": (root.findtext("enabled") or "true").strip().lower() == "true",
            "gridsets": "\n".join(
                element.findtext("gridSetName") or ""
                for element in root.findall("gridSubsets/gridSubset")
            ),
            "formats": "\n".join(
                element.text or "" for element in root.findall("mimeFormats/string")
            ),
            "meta_width": meta[0] if len(meta) > 0 else 4,
            "meta_height": meta[1] if len(meta) > 1 else 4,
            "expire_cache": number("expireCache"),
            "expire_clients": number("expireClients"),
            "gutter": number("gutter"),
        }

    @staticmethod
    def _gwc_xml_with_values(xml_text, values):
        """The document with the form's fields written into it. Pure.

        Everything the form does not model — the id, the parameter filters, a
        gridset's zoom bounds and extent — stays as GeoServer wrote it: a kept
        gridset keeps its element, only new ones are created bare.
        """
        gridsets = GwcTabMixin._lines(values.get("gridsets"))
        formats = GwcTabMixin._lines(values.get("formats"))
        if not gridsets:
            raise ValueError(
                translate("GwcTabMixin", "At least one gridset is required.")
            )
        if not formats:
            raise ValueError(
                translate("GwcTabMixin", "At least one format is required.")
            )
        root = GwcTabMixin._parse_xml(xml_text)

        def child(tag):
            element = root.find(tag)
            if element is None:
                element = ElementTree.SubElement(root, tag)
            return element

        def leaf(tag, text):
            element = ElementTree.Element(tag)
            element.text = text
            return element

        def replace_children(tag, elements):
            parent = child(tag)
            for old in list(parent):
                parent.remove(old)
            for element in elements:
                parent.append(element)

        child("enabled").text = "true" if values.get("enabled", True) else "false"
        replace_children("mimeFormats", [leaf("string", fmt) for fmt in formats])
        kept = {
            element.findtext("gridSetName"): element
            for element in root.findall("gridSubsets/gridSubset")
        }
        subsets = []
        for name in gridsets:
            element = kept.get(name)
            if element is None:
                element = ElementTree.Element("gridSubset")
                element.append(leaf("gridSetName", name))
            subsets.append(element)
        replace_children("gridSubsets", subsets)
        replace_children(
            "metaWidthHeight",
            [
                leaf("int", str(int(values.get("meta_width", 4)))),
                leaf("int", str(int(values.get("meta_height", 4)))),
            ],
        )
        child("expireCache").text = str(int(values.get("expire_cache", 0)))
        child("expireClients").text = str(int(values.get("expire_clients", 0)))
        child("gutter").text = str(int(values.get("gutter", 0)))
        return ElementTree.tostring(root, encoding="unicode")

    # -- Writes ---------------------------------------------------------------

    def _save_gwc_layer(self, name, xml_text, values):
        """PUT the edited document back. Raises on a bad form or an HTTP error."""
        document = self._gwc_xml_with_values(xml_text, values)
        # TODO(#50): no update of a cached layer in the library, and a JSON PUT
        # fails server-side ("Duplicate field mimeFormats") — XML it is.
        self._raw_rest(
            "put",
            self._gwc_layer_path(name, "xml"),
            data=document.encode("utf-8"),
            headers=_XML,
        )

    def _create_gwc_layer_from_values(self, values):
        """Start caching the layer the form names. Raises when it is cached already."""
        name = (values.get("layer") or "").strip()
        if not name:
            raise ValueError(translate("GwcTabMixin", "Pick a layer."))
        if self._gwc_layer_exists(name):
            raise ValueError(
                translate("GwcTabMixin", "'{}' is cached already.").format(name)
            )
        # TODO(#50): publish_gwc_layer() PUTs a JSON template GeoWebCache reads
        # as a degraded configuration — no formats, 0×0 meta-tiles, a single
        # gridset, no STYLES filter — after a needless configuration reload.
        # Workaround: PUT the XML document GeoServer itself would write.
        document = self._gwc_xml_with_values(
            _NEW_LAYER_XML.format(name=escape(name)), values
        )
        self._raw_rest(
            "put",
            self._gwc_layer_path(name, "xml"),
            data=document.encode("utf-8"),
            headers=_XML,
        )

    def _do_truncate_gwc_layer(self, name):
        """Drop every cached tile of the layer; its configuration stays.

        TODO(#50): the library has no seed or truncate call. Workaround: GWC's
        mass-truncate endpoint, the one request that covers every gridset,
        format and parameter set at once — the seed endpoint takes one
        combination per request. It wants `text/xml`: `application/xml`, which
        the layer PUTs take, is a 400 "Format extension unknown" here.
        """
        self._raw_rest(
            "post",
            f"{self._gwc_base()}/masstruncate",
            data=f"<truncateLayer><layerName>{escape(name)}</layerName></truncateLayer>",
            headers={"Content-Type": "text/xml"},
        )

    def _do_remove_gwc_layer(self, name):
        """Delete the cache configuration and the tiles; the layer itself stays."""
        workspace, _, layer = name.rpartition(":")
        if workspace:
            self._check(self.gs.delete_gwc_layer(workspace, layer))
            return
        # TODO(#50): delete_gwc_layer() takes a workspace and a layer; a global
        # layer group is cached under its bare name.
        self._raw_rest("delete", self._gwc_layer_path(name))

    # -- Forms ----------------------------------------------------------------

    def _gwc_fields(self, gridset_names, layer_names=None):
        """Field definitions: the picker for a new cache, read-only name for an edit."""
        advanced = translate("GwcTabMixin", "Advanced")
        if layer_names is None:
            first = {
                "key": "name",
                "label": translate("GwcTabMixin", "Layer"),
                "type": "text",
                "read_only": True,
            }
        else:
            first = {
                "key": "layer",
                "label": translate("GwcTabMixin", "Layer"),
                "type": "combo",
                "options": list(layer_names),
                "required": True,
                "help": translate(
                    "GwcTabMixin",
                    "A published layer or layer group GeoWebCache does not cache yet.",
                ),
            }
        return [
            first,
            {
                "key": "enabled",
                "label": translate("GwcTabMixin", "Enabled"),
                "type": "checkbox",
                "help": translate(
                    "GwcTabMixin",
                    "Disabled, GeoWebCache neither serves nor stores tiles for it.",
                ),
            },
            {
                "key": "gridsets",
                "label": translate("GwcTabMixin", "Gridsets"),
                "type": "textarea",
                "required": True,
                "help": translate(
                    "GwcTabMixin",
                    "One per line: the tile grids the layer is cached in.",
                ),
            },
            {
                "key": "add_gridset",
                "label": translate("GwcTabMixin", "Add a gridset"),
                "type": "combo",
                "options": [""] + list(gridset_names),
                "help": translate("GwcTabMixin", "Appends to the list above."),
            },
            {
                "key": "formats",
                "label": translate("GwcTabMixin", "Formats"),
                "type": "textarea",
                "required": True,
                "help": translate(
                    "GwcTabMixin",
                    "One MIME type per line, e.g. image/png, image/jpeg, image/png8.",
                ),
            },
            {
                "key": "meta_width",
                "label": translate("GwcTabMixin", "Meta-tile width"),
                "type": "spinbox",
                "min": 1,
                "max": 20,
                "group": advanced,
                "help": translate(
                    "GwcTabMixin",
                    "Tiles rendered together in one request, so labels are not cut "
                    "at tile edges.",
                ),
            },
            {
                "key": "meta_height",
                "label": translate("GwcTabMixin", "Meta-tile height"),
                "type": "spinbox",
                "min": 1,
                "max": 20,
                "group": advanced,
            },
            {
                "key": "gutter",
                "label": translate("GwcTabMixin", "Gutter (px)"),
                "type": "spinbox",
                "min": 0,
                "max": 100,
                "group": advanced,
                "help": translate(
                    "GwcTabMixin",
                    "Extra pixels rendered around each meta-tile, for symbols that "
                    "overflow.",
                ),
            },
            {
                "key": "expire_cache",
                "label": translate("GwcTabMixin", "Expire cached tiles after (s)"),
                "type": "spinbox",
                "min": 0,
                "max": 2147483647,
                "group": advanced,
                "help": translate(
                    "GwcTabMixin", "0 keeps a tile until it is truncated."
                ),
            },
            {
                "key": "expire_clients",
                "label": translate("GwcTabMixin", "Client cache max-age (s)"),
                "type": "spinbox",
                "min": 0,
                "max": 2147483647,
                "group": advanced,
                "help": translate(
                    "GwcTabMixin",
                    "Sent to browsers and QGIS as Cache-Control; 0 sends none.",
                ),
            },
        ]

    def _wire_gridset_picker(self, dlg):
        """The Add-a-gridset combo appends its pick to the gridsets textarea."""
        combo = dlg.get_widget("add_gridset")
        textarea = dlg.get_widget("gridsets")

        def append(name):
            if not name:
                return
            lines = self._lines(textarea.toPlainText())
            if name not in lines:
                lines.append(name)
                textarea.setPlainText("\n".join(lines))
            combo.setCurrentIndex(0)

        combo.currentTextChanged.connect(append)

    def _show_gwc_layer_info(self, row_data):
        """Open a cached layer's configuration for editing."""
        name = row_data[0]
        fetched = self._fetch(
            lambda: (self._gwc_layer_xml(name), self._gridset_names()),
            translate("GwcTabMixin", "Failed to load the tile cache of '{}'").format(
                name
            ),
        )
        if fetched is None:
            return
        xml_text, gridset_names = fetched

        dlg = ResourceFormDialog(
            title=translate("GwcTabMixin", "Tile cache of '{}'").format(name),
            description=translate(
                "GwcTabMixin",
                "How GeoWebCache caches this layer. Changes apply to the tiles "
                "rendered from now on; Truncate clears what is cached already.",
            ),
            fields=self._gwc_fields(gridset_names),
            values=self._gwc_form_values(xml_text),
            parent=self,
        )
        self._wire_gridset_picker(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._save_gwc_layer(name, xml_text, values),
            translate("GwcTabMixin", "Failed to save the tile cache of '{}'").format(
                name
            ),
        ):
            self.show_success_message(
                translate("GwcTabMixin", "Tile cache of '{}' saved.").format(name)
            )
            self._load_gwc_layers()

    def _add_gwc_layer(self):
        """Open a form dialog to start caching a published layer."""
        fetched = self._fetch(
            lambda: (self._uncached_layer_names(), self._gridset_names()),
            translate("GwcTabMixin", "Failed to list the layers that can be cached"),
        )
        if fetched is None:
            return
        candidates, gridset_names = fetched
        if not candidates:
            self.show_warning_message(
                translate(
                    "GwcTabMixin",
                    "Every published layer is cached already — GeoServer caches new "
                    "layers by itself.",
                )
            )
            return

        dlg = ResourceFormDialog(
            title=translate("GwcTabMixin", "Add a Layer to the Cache"),
            description=translate(
                "GwcTabMixin",
                "GeoServer caches every new layer by itself, so this is for a layer "
                "whose cache was removed. Tiles are stored the first time they are "
                "requested.",
            ),
            fields=self._gwc_fields(gridset_names, layer_names=candidates),
            values={
                "enabled": True,
                "gridsets": "\n".join(DEFAULT_GRIDSETS),
                "formats": "\n".join(DEFAULT_FORMATS),
                "meta_width": 4,
                "meta_height": 4,
                "gutter": 0,
                "expire_cache": 0,
                "expire_clients": 0,
            },
            parent=self,
            ok_label=translate("GwcTabMixin", "Create"),
        )
        self._wire_gridset_picker(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        values = dlg.get_values()
        if self._run_action(
            lambda: self._create_gwc_layer_from_values(values),
            translate("GwcTabMixin", "Failed to cache '{}'").format(
                values.get("layer", "")
            ),
        ):
            self.show_success_message(
                translate("GwcTabMixin", "'{}' is now cached.").format(values["layer"])
            )
            self._load_gwc_layers()

    # -- Truncate / remove ----------------------------------------------------

    def _truncate_gwc_layer(self, row_data):
        """Drop the layer's cached tiles after confirmation."""
        name = row_data[0]
        if not self._confirm_delete(
            translate("GwcTabMixin", "the tiles of layer"),
            [name],
            verb=translate("GwcTabMixin", "truncate"),
            cascade=translate(
                "GwcTabMixin",
                "Every tile GeoWebCache stored for this layer is deleted, in every "
                "gridset and format. The layer and its cache configuration stay; "
                "tiles are rendered again on request.\n\n",
            ),
        ):
            return
        if self._run_action(
            lambda: self._do_truncate_gwc_layer(name),
            translate(
                "GwcTabMixin", "Failed to truncate the tile cache of '{}'"
            ).format(name),
        ):
            self.show_success_message(
                translate("GwcTabMixin", "Tile cache of '{}' truncated.").format(name)
            )

    def _remove_gwc_layer(self, row_data):
        """Stop caching a single layer after confirmation."""
        self._remove_selected_gwc_layers([row_data])

    def _remove_selected_gwc_layers(self, selected_rows):
        """Stop caching one or more layers after confirmation."""
        self._delete_many(
            translate("GwcTabMixin", "layer"),
            [
                (row[0], lambda name=row[0]: self._do_remove_gwc_layer(name))
                for row in selected_rows
            ],
            self._load_gwc_layers,
            verb=translate("GwcTabMixin", "stop caching"),
            done=translate("GwcTabMixin", "removed from the cache"),
            cascade=translate(
                "GwcTabMixin",
                "The cached tiles and the cache configuration are removed; the layer "
                "itself stays published and can be added to the cache again.\n\n",
            ),
        )
