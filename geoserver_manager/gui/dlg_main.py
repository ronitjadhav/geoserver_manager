#! python3  # noqa: E265

"""
Main plugin dialog — GeoServer resource browser.
"""

# standard
from pathlib import Path

# PyQGIS
from qgis.core import Qgis, QgsApplication
from qgis.gui import QgsMessageBar
from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QSizePolicy,
    QTreeWidgetItem,
    QWidget,
)

# project
from geoserver_manager.__about__ import __title__
from geoserver_manager.toolbelt.log_handler import PlgLogger
from geoserver_manager.toolbelt.preferences import PlgOptionsManager


# ── Tree item data roles ──────────────────────────────────────────────
ROLE_TYPE      = Qt.UserRole       # what kind of resource (workspace/layer/…)
ROLE_NAME      = Qt.UserRole + 1   # resource name
ROLE_WORKSPACE = Qt.UserRole + 2   # parent workspace name (for ds / layer)
ROLE_DATASTORE = Qt.UserRole + 3   # parent datastore name (for layer)

# Resource type labels
TYPE_CATEGORY = "category"
TYPE_WORKSPACE = "workspace"
TYPE_DATASTORE = "datastore"
TYPE_LAYER     = "style"          # deliberately same slot, label differs in UI
TYPE_LAYER     = "layer"
TYPE_STYLE     = "style"

# Category icons (QGIS built-in SVG names)
CATEGORY_ICONS = {
    TYPE_WORKSPACE: "mIconFolder.svg",
    TYPE_DATASTORE: "mIconDbSchema.svg",
    TYPE_LAYER:     "mIconVector.svg",
    TYPE_STYLE:     "mIconRendererCategory.svg",
}


def _get_name(item) -> str:
    """Return the 'name' field from a dict, or str(item) as fallback."""
    return item.get("name", str(item)) if isinstance(item, dict) else str(item)


class GeoServerMainDialog(QDialog):
    """Main dialog — GeoServer resource browser."""

    def __init__(self, parent=None, iface=None) -> None:
        super().__init__(parent)
        self.iface = iface
        self.log = PlgLogger().log
        self.gs = None  # GeoServerCloud client, set by _connect()

        uic.loadUi(Path(__file__).parent / "dlg_main.ui", self)

        self.plg_settings = PlgOptionsManager()

        # Inline message bar — sits above the splitter (no modal popups)
        self.message_bar = QgsMessageBar(self)
        self.message_bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.message_bar_layout.insertWidget(0, self.message_bar)

        # Left panel starts at ~280px, right panel gets the rest
        self.splitter.setSizes([280, 620])

        # Wire up buttons and tree signals
        self.btn_close.clicked.connect(self.close)
        self.btn_refresh.clicked.connect(self.refresh_ui)
        self.btn_edit_credentials.clicked.connect(self.edit_credentials)
        self.treeResources.itemClicked.connect(self._on_tree_item_clicked)

    # ── Message helpers ───────────────────────────────────────────────

    def show_success_message(self, text: str) -> None:
        self.message_bar.pushMessage("Success", text, Qgis.MessageLevel.Success, 5)

    def show_error_message(self, text: str) -> None:
        self.message_bar.pushMessage("Error", text, Qgis.MessageLevel.Critical, 5)

    def show_warning_message(self, text: str) -> None:
        self.message_bar.pushMessage("Warning", text, Qgis.MessageLevel.Warning, 5)

    def show_info_message(self, text: str) -> None:
        self.message_bar.pushMessage("Info", text, Qgis.MessageLevel.Info, 5)

    # ── Status label helper ───────────────────────────────────────────

    def _set_status(self, text: str, color: str = "black") -> None:
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"color: {color};")

    # ── Connection ────────────────────────────────────────────────────

    def _connect(self) -> bool:
        """Build a GeoServerCloud client from stored credentials.
        Returns True on success, False otherwise."""
        settings = self.plg_settings.get_plg_settings()

        if not settings.has_credentials():
            self._set_status("Not configured", "red")
            self.show_warning_message(
                "GeoServer not configured — open Settings to add your credentials."
            )
            self.gs = None
            return False

        username, password = settings.get_credentials()
        if not username or not password:
            self._set_status("Auth error", "red")
            self.show_error_message("Could not read credentials from the auth store.")
            self.gs = None
            return False

        try:
            from geoservercloud import GeoServerCloud
            self.gs = GeoServerCloud(
                url=settings.geoserver_url,
                user=username,
                password=password,
            )
            self._set_status(f"Connected — {settings.geoserver_url}", "green")
            return True
        except Exception as e:
            self._set_status("Connection error", "red")
            self.show_error_message(f"Failed to connect: {e}")
            self.log(f"Connection error: {e}", log_level=Qgis.MessageLevel.Critical)
            self.gs = None
            return False

    # ── Public refresh ────────────────────────────────────────────────

    def refresh_ui(self) -> None:
        """Connect and reload all resources. Called at startup and on Refresh."""
        if self._connect():
            self._load_tree()
            self.show_success_message("Resources loaded.")
        else:
            self.treeResources.clear()
            self._show_placeholder("Connect to a GeoServer to browse resources.")

    # ── Tree loading ──────────────────────────────────────────────────

    def _load_tree(self) -> None:
        """Fetch every resource type and populate the left tree."""
        self.treeResources.clear()
        self.setCursor(Qt.WaitCursor)
        try:
            self._load_workspaces()
            ws_names = self._ws_names()          # used by datastores & layers
            self._load_datastores(ws_names)
            ds_pairs = self._ds_pairs(ws_names)  # (ds_name, ws_name) pairs
            self._load_layers(ds_pairs)
            self._load_styles()
            self._show_placeholder("Select a resource from the tree to view details.")
        except Exception as e:
            self.show_error_message(f"Failed to load resources: {e}")
            self.log(f"Tree load error: {e}", log_level=Qgis.MessageLevel.Critical)
        finally:
            self.unsetCursor()

    # Tree loading helpers — one method per resource type ─────────────

    def _load_workspaces(self) -> None:
        ws_list = self._api_list(self.gs.get_workspaces)
        category = self._add_category("Workspaces", len(ws_list), TYPE_WORKSPACE)
        for ws in ws_list:
            self._add_leaf(category, _get_name(ws), TYPE_WORKSPACE, "mIconFolder.svg")

    def _load_datastores(self, ws_names: list) -> None:
        all_ds = self._ds_pairs(ws_names)
        category = self._add_category("Datastores", len(all_ds), TYPE_DATASTORE)
        for ds_name, ws_name in all_ds:
            item = self._add_leaf(category, ds_name, TYPE_DATASTORE, "mIconDbSchema.svg")
            item.setData(0, ROLE_WORKSPACE, ws_name)

    def _load_layers(self, ds_pairs: list) -> None:
        all_layers = []
        for ds_name, ws_name in ds_pairs:
            for ft in self._api_list(self.gs.get_feature_types, ws_name, ds_name):
                all_layers.append((_get_name(ft), ws_name, ds_name))

        category = self._add_category("Layers", len(all_layers), TYPE_LAYER)
        for ft_name, ws_name, ds_name in all_layers:
            item = self._add_leaf(category, ft_name, TYPE_LAYER, "mIconVector.svg")
            item.setData(0, ROLE_WORKSPACE, ws_name)
            item.setData(0, ROLE_DATASTORE, ds_name)

    def _load_styles(self) -> None:
        style_list = self._api_list(self.gs.get_styles)
        category = self._add_category("Styles", len(style_list), TYPE_STYLE)
        for st in style_list:
            self._add_leaf(category, _get_name(st), TYPE_STYLE, "mIconRendererCategory.svg")

    # Data-collection helpers ─────────────────────────────────────────

    def _ws_names(self) -> list:
        """Return a flat list of workspace name strings."""
        return [_get_name(ws) for ws in self._api_list(self.gs.get_workspaces)]

    def _ds_pairs(self, ws_names: list) -> list:
        """Return (datastore_name, workspace_name) pairs for every workspace."""
        pairs = []
        for ws_name in ws_names:
            for ds in self._api_list(self.gs.get_datastores, ws_name):
                pairs.append((_get_name(ds), ws_name))
        return pairs

    # Low-level tree helpers ──────────────────────────────────────────

    def _add_category(self, label: str, count: int, res_type: str) -> QTreeWidgetItem:
        """Add a bold top-level category row and return it."""
        item = QTreeWidgetItem(self.treeResources, [f"{label} ({count})"])
        item.setData(0, ROLE_TYPE, TYPE_CATEGORY)
        item.setData(0, ROLE_NAME, label)
        item.setFlags(item.flags() | Qt.ItemIsEnabled)

        font = item.font(0)
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        item.setFont(0, font)

        icon_name = CATEGORY_ICONS.get(res_type, "mIconFolder.svg")
        item.setIcon(0, QIcon(QgsApplication.iconPath(icon_name)))
        return item

    def _add_leaf(
        self, parent: QTreeWidgetItem, name: str, res_type: str, icon: str
    ) -> QTreeWidgetItem:
        """Add a child leaf row and return it."""
        item = QTreeWidgetItem(parent, [name])
        item.setData(0, ROLE_TYPE, res_type)
        item.setData(0, ROLE_NAME, name)
        item.setIcon(0, QIcon(QgsApplication.iconPath(icon)))
        return item

    def _api_list(self, method, *args) -> list:
        """Call a geoservercloud list API and return the list (or [] on error)."""
        try:
            result, _ = method(*args)
            return result if isinstance(result, list) else []
        except Exception as e:
            self.log(f"API error in {method.__name__}: {e}", log_level=Qgis.MessageLevel.Warning)
            return []

    # ── Tree click → detail panel ────────────────────────────────────

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """Expand/collapse categories; show details for leaf items."""
        res_type = item.data(0, ROLE_TYPE)

        if res_type == TYPE_CATEGORY:
            item.setExpanded(not item.isExpanded())
            return

        name = item.data(0, ROLE_NAME)
        ws   = item.data(0, ROLE_WORKSPACE)
        ds   = item.data(0, ROLE_DATASTORE)

        if res_type == TYPE_WORKSPACE:
            self._show_workspace_detail(name)
        elif res_type == TYPE_DATASTORE:
            self._show_datastore_detail(ws, name)
        elif res_type == TYPE_LAYER:
            self._show_layer_detail(ws, ds, name)
        elif res_type == TYPE_STYLE:
            self._show_style_detail(name)

    # ── Detail panel ─────────────────────────────────────────────────

    def _show_placeholder(self, text: str) -> None:
        self.lbl_detail_title.setText("GeoServer Manager")
        self.lbl_detail_content.setText(text)
        self._clear_detail_form()

    def _clear_detail_form(self) -> None:
        """Remove dynamically-added form widgets (keep label + spacer)."""
        while self.detailLayout.count() > 2:
            child = self.detailLayout.takeAt(1)
            if child.widget():
                child.widget().deleteLater()

    def _show_detail_form(self, title: str, fields: dict) -> None:
        """Render a key→value table in the right panel."""
        self.lbl_detail_title.setText(title)
        self.lbl_detail_content.setText("")
        self._clear_detail_form()

        form = QWidget()
        layout = QFormLayout(form)
        layout.setContentsMargins(0, 4, 0, 0)
        for key, value in fields.items():
            key_lbl = QLabel(f"<b>{key}:</b>")
            val_lbl = QLabel("—" if value is None else str(value))
            val_lbl.setWordWrap(True)
            val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addRow(key_lbl, val_lbl)

        # Insert before the stretching spacer at the end
        self.detailLayout.insertWidget(self.detailLayout.count() - 1, form)

    def _fetch_detail(self, api_call, title: str, build_fields) -> None:
        """Generic detail fetch: call API, build fields dict, show form.

        api_call    — zero-argument lambda that calls the API and returns (result, code)
        title       — panel title (e.g. "Workspace: ws1")
        build_fields — callable(result) → dict  (only called when result is a dict)
        """
        self.setCursor(Qt.WaitCursor)
        try:
            result, _code = api_call()
            if isinstance(result, dict):
                fields = build_fields(result)
            else:
                fields = {"Error": str(result)}
            self._show_detail_form(title, fields)
        except Exception as e:
            self._show_detail_form(title, {"Error": str(e)})
            self.show_error_message(f"Failed to load {title}: {e}")
        finally:
            self.unsetCursor()

    # Detail methods — each just defines what fields to show ──────────

    def _show_workspace_detail(self, ws_name: str) -> None:
        def build(r):
            ns = r.get("namespace", {})
            return {
                "Name":     r.get("name", ws_name),
                "Isolated": r.get("isolated", "N/A"),
                "URI":      ns.get("uri", "N/A") if isinstance(ns, dict) else "N/A",
            }
        self._fetch_detail(
            lambda: self.gs.get_workspace(ws_name),
            f"Workspace: {ws_name}",
            build,
        )

    def _show_datastore_detail(self, ws_name: str, ds_name: str) -> None:
        def build(r):
            fields = {
                "Name":        r.get("name", ds_name),
                "Workspace":   ws_name,
                "Type":        r.get("type", "N/A"),
                "Enabled":     r.get("enabled", "N/A"),
                "Description": r.get("description", "—"),
            }
            # Append connection parameters (mask passwords)
            for entry in r.get("connectionParameters", {}).get("entry", []):
                if isinstance(entry, dict):
                    key = entry.get("@key", "param")
                    val = entry.get("$", "")
                    if "password" in key.lower():
                        val = "••••••••"
                    fields[f"  {key}"] = val
            return fields

        self._fetch_detail(
            lambda: self.gs.get_datastore(ws_name, ds_name),
            f"Datastore: {ds_name}",
            build,
        )

    def _show_layer_detail(self, ws_name: str, ds_name: str, layer_name: str) -> None:
        def build(r):
            fields = {
                "Name":        r.get("name", layer_name),
                "Title":       r.get("title", "—"),
                "Workspace":   ws_name,
                "Datastore":   ds_name,
                "Native Name": r.get("nativeName", "—"),
                "SRS":         r.get("srs", "N/A"),
                "Enabled":     r.get("enabled", "N/A"),
            }
            bbox = r.get("nativeBoundingBox", {})
            if isinstance(bbox, dict):
                fields["Native BBox"] = (
                    f"{bbox.get('minx','?')}, {bbox.get('miny','?')} → "
                    f"{bbox.get('maxx','?')}, {bbox.get('maxy','?')}"
                )
                fields["BBox CRS"] = bbox.get("crs", "N/A")

            ll = r.get("latLonBoundingBox", {})
            if isinstance(ll, dict):
                fields["Lat/Lon BBox"] = (
                    f"{ll.get('minx','?')}, {ll.get('miny','?')} → "
                    f"{ll.get('maxx','?')}, {ll.get('maxy','?')}"
                )
            return fields

        self._fetch_detail(
            lambda: self.gs.get_feature_type(ws_name, ds_name, layer_name),
            f"Layer: {layer_name}",
            build,
        )

    def _show_style_detail(self, style_name: str) -> None:
        def build(r):
            lv = r.get("languageVersion", {})
            return {
                "Name":             r.get("name", style_name),
                "Format":           r.get("format", "N/A"),
                "Language Version": lv.get("version", "N/A") if isinstance(lv, dict) else "N/A",
                "Filename":         r.get("filename", "—"),
            }
        self._fetch_detail(
            lambda: self.gs.get_style_definition(style_name),
            f"Style: {style_name}",
            build,
        )

    # ── Actions ───────────────────────────────────────────────────────

    def edit_credentials(self) -> None:
        """Open the plugin settings page in the QGIS Options dialog."""
        if self.iface:
            self.hide()
            self.iface.showOptionsDialog(currentPage=f"mOptionsPage{__title__}")
            self.refresh_ui()
            self.show()
