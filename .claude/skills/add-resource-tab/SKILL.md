---
name: add-resource-tab
description: Add a new GeoServer resource type (layers, styles, layer groups, coverage stores, …) as a tab in the main dialog, following the plugin's mixin + TABS registry pattern and its safety invariants. Use whenever a roadmap item adds a resource type to browse, create, edit or delete.
---

# Add a resource-type tab

A tab is one mixin file plus one line in the registry. Everything else — table,
search, pagination, buttons, wait cursor, error reporting, delete confirmation —
is inherited from `GeoServerMainDialog`. Do not re-implement any of it.

Read `CLAUDE.md` first; the invariants there are the acceptance criteria.

## 1. Check what the library offers

Unzip `geoserver_manager/extras/geoservercloud-*.whl` into a scratch dir and read
`geoservercloud/geoservercloud.py` for the resource's `get_*s`, `get_*`,
`create_*`, `delete_*` methods. Note:

- Which calls return `(content, status)` — wrap them in `self._check(...)`.
- Whether `create_*` upserts (it usually does) — then *Add* needs `_resource_exists`.
- What is **missing**. A missing call becomes a `self._raw_rest(...)` workaround
  with a `TODO:` naming the upstream method, using `rest_endpoints.*` for the path.

## 2. Write the mixin: `geoserver_manager/gui/tab_<resource>.py`

Copy the shape of `tab_workspaces.py` (simplest) or `tab_datastores.py` (typed
form, nested listing, parallel fetch). Skeleton:

```python
class StyleTabMixin:
    """Mixin that adds style CRUD methods to the main dialog."""

    def _load_styles(self):
        def load():
            self._setup_add_button(self.tr("Add a New Style"), self.tr("Create a style"), self._add_style)
            self._setup_delete_selected_button(self._delete_selected_styles)
            self._name_click_callback = self._show_style_info
            self._extra_click_callbacks = {self.tr("Workspace"): self._open_workspace_from_row}
            self._row_actions = [("mActionDeleteSelected.svg", self.tr("Delete"), self._delete_style)]
            self._setup_table([self.tr("Style Name"), self.tr("Workspace"), self.tr("Actions")])
            rows = [[self._name_of(s), ws] for ws, s in self._fetch_styles()]
            self._populate_rows(rows)

        self._run_action(load, self.tr("Failed to load styles"))
```

Rules for the mixin:

- **Column 0 is the resource name.** Row lists are display strings; keep the
  order stable because callbacks index into them (`row[0]`, `row[1]`, …).
- **All server calls through the dialog helpers** (`_run_action`, `_fetch`,
  `_check`, `_fetch_list`, `_resource_exists`, `_raw_rest`). Never write a
  `try/except … setCursor` block yourself.
- **Add** pre-checks existence and raises `ValueError(self.tr("… already exists"))`
  inside the action; `_run_action` turns that into the banner.
- **Edit** fetches the current object with `_fetch`, prefills from *that* (a pure
  `_<resource>_form_values(...)` staticmethod — unit-testable), and saves by
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
- Fan out per-item GETs with `self._fan_out(fn, items)` — **only** stateless REST
  reads, never OWS calls (`self.wms`/`self.wmts` are shared state). It returns
  `[(result, error)]` in order; render what loaded and hand the failures to
  `self._report_partial_failures([(label, error), …])` so one broken parent
  costs one warning, not the whole table (see `_load_datastores`).

## 3. Register it — two lines in `dlg_main.py`

```python
class GeoServerMainDialog(QDialog, WorkspaceTabMixin, DatastoreTabMixin, StyleTabMixin):
    ...
    TABS = (
        ("Workspaces", "mIconFolder.svg", "_load_workspaces"),
        ("Datastores", "mIconDbSchema.svg", "_load_datastores"),
        ("Styles", "mIconRendererCategory.svg", "_load_styles"),
    )
```

Icons come from `QgsApplication.iconPath(name)` — pick an existing QGIS theme icon.
Prefix the mixin's method names with the resource (`_load_styles`, `_add_style`)
so nothing collides in the shared namespace.

## 4. Tests — `tests/qgis/test_tab_<resource>.py`

Headless, no server:

```python
from qgis.testing import start_app, unittest
from geoserver_manager.gui.dlg_main import GeoServerMainDialog
start_app()

class FakeGS:
    def get_styles(self, ws=None): return ([{"name": "a"}, {"name": "b"}], 200)

class TestStylesTab(unittest.TestCase):
    def test_loads_rows(self):
        dlg = GeoServerMainDialog(); dlg.gs = FakeGS()
        dlg._load_styles()
        self.assertEqual([r[0] for r in dlg._all_rows], ["a", "b"])
```

Cover at least: rows load, the pure `_form_values` prefill, and that an edit
payload preserves fields the form does not model. Run the test against the code
with the fix removed once to prove it fails.

## 5. Finish

- `docs/github_issue_roadmap.md`: tick the items; `CHANGELOG.md`: add under *Unreleased*.
- Run the `verify-plugin` skill before committing.
- Commit message: `feat: add <resource> tab` with a body explaining any workaround.
