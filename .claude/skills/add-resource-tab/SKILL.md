---
name: add-resource-tab
description: Add a new GeoServer resource type (layers, styles, layer groups, coverage stores, …) as a tab in the main dialog, following the plugin's mixin + TABS registry pattern and its safety invariants. Use whenever a roadmap item adds a resource type to browse, create, edit or delete.
---

# Add a resource-type tab

A tab is one mixin file plus one line in the registry. Everything else (table,
search, pagination, buttons, wait cursor, error reporting, delete confirmation)
is inherited from `GeoServerMainDialog`. Do not re-implement any of it.

Read `AGENTS.md` first; the invariants there are the acceptance criteria, and
`docs/development/geoserver-notes.md` has the library facts.

## 1. Check what the library offers

Unzip `geoserver_manager/extras/geoservercloud-*.whl` into a scratch dir and read
`geoservercloud/geoservercloud.py` for the resource's `get_*s`, `get_*`,
`create_*`, `delete_*` methods. Note:

- Which calls return `(content, status)`: wrap them in `self._check(...)`.
- Whether `create_*` upserts (it usually does): then *Add* needs `_resource_exists`.
- What is **missing**. A missing call becomes a `self._raw_rest(...)` workaround
  with a `TODO(#50)` comment, using `rest_endpoints.*` for the path, **and a new
  row in issue #50** (call site, REST verb + path, proposed library API) so it can
  be implemented upstream in python-geoservercloud. Check the "anticipated" list
  in #50 first; your resource may already be there.

## 2. Write the mixin: `geoserver_manager/gui/tab_<resource>.py`

Copy the shape of `tab_workspaces.py` (simplest) or `tab_datastores.py` (typed
form, nested listing, parallel fetch). Skeleton:

```python
from qgis.PyQt.QtCore import QCoreApplication

# Strings are looked up in this file's own context: self.tr() would resolve
# against GeoServerMainDialog instead (see AGENTS.md).
translate = QCoreApplication.translate


class StyleTabMixin:
    """Mixin that adds style CRUD methods to the main dialog."""

    def _load_styles(self):
        """Arm the tab, then fetch its rows in the background."""
        self._setup_add_button(
            translate("StyleTabMixin", "Add a Style"),
            translate("StyleTabMixin", "Create a style from an SLD"),
            self._add_style,
        )
        self._setup_delete_selected_button(self._delete_selected_styles)
        self._name_click_callback = self._show_style_info
        self._extra_click_callbacks = {
            translate("StyleTabMixin", "Workspace"): self._open_workspace_from_row
        }
        self._row_actions = [
            ("delete", translate("StyleTabMixin", "Delete"), self._delete_style)
        ]
        self._setup_table([
            translate("StyleTabMixin", "Style Name"),
            translate("StyleTabMixin", "Workspace"),
            self.actions_column_label(),          # never translate "Actions" here
        ])
        self._start_load(translate("StyleTabMixin", "Failed to load styles"), self._fetch_style_rows)

    def _fetch_style_rows(self, task=None):
        """(rows, failures) for the table. Runs in a worker thread."""
        rows = [[self._name_of(s), ws] for ws, s in self._fetch_styles(task)]
        return rows, []
```

Rules for the mixin:

- **Translate in your own context.** `translate("<YourMixin>", "…")` with the alias at the
  top of the file. Never `self.tr()`, which resolves against `GeoServerMainDialog` and so can
  never find your strings. The row-actions column is the one exception: take its label from
  `self.actions_column_label()`, because `_setup_table` compares it. `tests/qgis/test_i18n.py`
  checks both, and knows the list of `tab_*.py` files; add yours to `CONTEXTS` there.
- **Column 0 is the resource name.** Row lists are display strings; keep the
  order stable because callbacks index into them (`row[0]`, `row[1]`, …).
- **The loader only arms the GUI.** Buttons, callbacks and `_setup_table` on the GUI
  thread, then `_start_load(failure_message, fetch)` and return. The fetch is
  `_fetch_<x>_rows(task=None) -> (rows, failures)`: it runs in a `QgsTask`, so it must
  not touch a widget, must not read `self._all_rows`, and reaches the task only by
  handing it to `_fan_out`. Everything it collects is rendered for it.
- **All server calls through the dialog helpers** (`_run_action`, `_fetch`,
  `_check`, `_fetch_list`, `_resource_exists`, `_raw_rest`). Never write a
  `try/except … setCursor` block yourself.
- **Name the primary button.** Pass `ok_label=translate("<YourMixin>", "Create")` (or
  "Publish" / "Upload" / "Apply") to every `ResourceFormDialog` that is not an edit; an edit
  keeps the default "Save". Title the dialog with the Add button's own words, and start that
  label with a verb, never "New"; `test_ux.py` sweeps every tab for both.
- **The Workspace column** links through `self._open_workspace_from_row` (on the dialog); do
  not write your own. Global-scope rows use `GLOBAL` / `scope()` from `gui/scope.py`.
- **Add** calls `self._require_safe_name(name)` first (a `/`, `?`, `#` or `%` in a name changes the REST
  path), then pre-checks existence and raises `ValueError(translate("StyleTabMixin", "… already exists"))`
  inside the action; `_run_action` turns that into the banner. Quote any name you put in a raw path yourself
  (`urllib.parse.quote(name, safe="")`).
- **Cells and words.** A boolean column goes through `self._yes_no(value)`; the first column is headed "Name";
  collection payloads go through `self._unwrap` / `self._as_list` / `self._name_of` (toolbelt/payload.py); do
  not write a local copy. A tab whose header action is not a delete passes its own words:
  `_setup_delete_selected_button(cb, translate(..., "Remove Selected from Cache"))` and
  `_delete_many(..., verb="stop caching", done="removed from the cache")`. Add a one-line tooltip for the tab
  in `GeoServerMainDialog._tab_help()`.
- **Edit** fetches the current object with `_fetch`, prefills from *that* (a pure
  `_<resource>_form_values(...)` staticmethod, unit-testable), and saves by
  merging the form's fields onto the fetched payload. Never send a fixed template
  over an existing object. Lock the name field in edit mode unless the library
  offers a real rename.
- **Delete** goes through `_delete_many(kind, [(label, fn)], reload_fn, cascade=...)`.
  State the cascade if the call recurses.
- Reload with the specific loader after add/edit/delete, but with
  `_reload_current_tab()` for any action reachable from another tab.
- Forms: build the field list with `ResourceFormDialog` field dicts; put
  type-specific fields in a `group`, toggle them with `dlg.set_field_visible`,
  and if a type combo drives visibility, reuse the `_wire_type_combo` pattern.
- Fan out per-item GETs with `self._fan_out(fn, items, task)`: **only** stateless REST
  reads, never OWS calls (`self.wms`/`self.wmts` are shared state). Passing the task is
  what gives the load its progress bar and its Cancel. It returns `[(result, error)]` in
  order; return the failures as the second half of the tuple and `_render_rows` hands
  them to `_report_partial_failures`, so one broken parent costs one warning, not the
  whole table (see `_fetch_datastore_rows`).

## 3. Register it: two lines in `dlg_main.py`

```python
class GeoServerMainDialog(QDialog, WorkspaceTabMixin, DatastoreTabMixin, StyleTabMixin):
    ...
    TABS = (
        ("Workspaces", "workspaces", "_load_workspaces"),
        ("Datastores", "datastores", "_load_datastores"),
        ("Styles", "styles", "_load_styles"),
    )
```

Icons use registered IDs from `geoserver_manager/resources/icons/catalog.json`.
Reuse an existing meaning, or add a custom SVG on the 24 px grid with 1.2-unit
strokes. If artwork is pending, register `needs-custom`, a QGIS `fallback`
filename and design `notes`. Never use a raw QGIS filename in `TABS` or row
actions. Run `python scripts/build_icon_catalog.py` and review the gallery.
Read `docs/development/icon-style-guide.md` before drawing or generating an
icon. See `docs/development/icon-catalog.md` for the inventory and workflow.
Prefix the mixin's method names with the resource (`_load_styles`, `_add_style`)
so nothing collides in the shared namespace.

## 4. Tests: `tests/qgis/test_tab_<resource>.py`

Headless, no server:

```python
from qgis.testing import start_app, unittest
from tests.qgis.sync_dialog import SyncDialog  # runs the load inline
start_app()

class FakeGS:
    def get_styles(self, ws=None): return ([{"name": "a"}, {"name": "b"}], 200)

class TestStylesTab(unittest.TestCase):
    def test_fetches_rows(self):
        dlg = SyncDialog(); dlg.gs = FakeGS()
        rows, failures = dlg._fetch_style_rows()      # the seam: no task, no widgets
        self.assertEqual([r[0] for r in rows], ["a", "b"])
        dlg._load_styles()                            # the whole loader, inline
        self.assertEqual([r[0] for r in dlg._all_rows], ["a", "b"])
```

Never instantiate `GeoServerMainDialog` for a load test: its loads are asynchronous, so
the assertions would race the task. `SyncDialog` exists for exactly this.

Cover at least: rows load, the pure `_form_values` prefill, and that an edit
payload preserves fields the form does not model. Run the test against the code
with the fix removed once to prove it fails.

## 5. Finish

- `docs/github_issue_roadmap.md`: tick the items; `CHANGELOG.md`: add under *Unreleased*.
- Run the `verify-plugin` skill before committing.
- Commit message: `feat: add <resource> tab` with a body explaining any workaround.
