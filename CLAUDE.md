# GeoServer Manager — guide for coding agents

QGIS plugin that manages a GeoServer through the REST API, using the
[python-geoservercloud](https://github.com/camptocamp/python-geoservercloud)
library. Python 3.12 (QGIS ≥ 3.40), PyQt5 **and** PyQt6 via `qgis.PyQt`.
Read this file before touching code; it records what the code cannot tell you.

**The one rule above all others: python-geoservercloud first.** This plugin exists
partly to drive that library's maturity. Every GeoServer call goes through the
library; when the library lacks something, the gap is recorded in
[issue #50](https://github.com/ronitjadhav/geoserver_manager/issues/50) so it can be
implemented *there*, and only then worked around here. See Conventions.

Skills in `.claude/skills/` hold the step-by-step procedures:
`add-resource-tab`, `verify-plugin`, `release-plugin`.

## Layout

| Path | What lives there |
|---|---|
| `geoserver_manager/plugin_main.py` | QGIS entry point: `initGui` / `unload` / `run`. Shows the dialog, then connects. |
| `geoserver_manager/gui/dlg_main.py` | `GeoServerMainDialog(QDialog, WorkspaceTabMixin, DatastoreTabMixin)` — nav list, results table, search, pagination, and every helper the tabs share |
| `geoserver_manager/gui/tab_workspaces.py`, `tab_datastores.py` | One mixin per resource type: load / add / edit / delete |
| `geoserver_manager/gui/dlg_resource_form.py` | `ResourceFormDialog` — a modal form built from a list of field dicts (see its module docstring for the field spec) |
| `geoserver_manager/gui/dlg_settings.py` | Options page: URL + credentials (credentials go to `QgsAuthManager`, encrypted) |
| `geoserver_manager/toolbelt/` | `preferences` (QgsSettings + auth store), `log_handler`, `dependencies` (loads the bundled wheels), `env_var_parser` |
| `geoserver_manager/extras/*.whl` | Bundled `geoservercloud` (stripped, see below) and `xmltodict`, added to `sys.path` at startup |
| `tests/unit/` | Runs without QGIS. `tests/qgis/` needs the QGIS Python (headless via `qgis.testing.start_app()`) |
| `docs/github_issue_roadmap.md` | Feature backlog; GitHub milestones mirror it |
| `docker-compose.yml` | Throwaway GeoServer 2.28.5 (`:8080`, admin/geoserver) + PostGIS, for testing against a real server |

The `Inspiration/` folder is untracked reference code from another plugin. Never import from it.

## How the dialog works

- **Tabs are one registry.** `GeoServerMainDialog.TABS = ((label, icon, loader_name), …)`.
  `_setup_nav` builds the list from it and `_on_nav_changed` calls `getattr(self, loader)()`.
  A new resource type = one line in `TABS` + one mixin added to the class bases.
- **A loader** sets up the header buttons, `_name_click_callback`, `_extra_click_callbacks`,
  `_row_actions`, calls `_setup_table(columns)`, fetches, then `_populate_rows(rows)`.
  Rows are plain lists of display strings; column 0 is the resource name.
- **The table is paginated in Python** (`_page_size = 20`, `_all_rows` → `_filtered_rows` → one page).
  `_get_selected_rows()` maps a selected view row back through `_filtered_rows` by index.
- **Server calls go through the helpers on the dialog**, never hand-rolled in a mixin:

  | Helper | Use it for |
  |---|---|
  | `_run_action(fn, failure_message) -> bool` | any mutation: wait cursor, banner + QGIS log on failure |
  | `_fetch(fn, failure_message) -> value \| None` | any read the UI needs before continuing |
  | `_check((content, status))` | unwrap a geoservercloud tuple; raises on ≥ 400 |
  | `_fetch_list(api_method, *args)` | a list endpoint; `[]` when the payload is not a list |
  | `_resource_exists(getter, *args)` | pre-check before *Add* (the library upserts) |
  | `_raw_rest(method, path, **kw)` | endpoints the library lacks; raises with GeoServer's response body |
  | `_name_of(item)` | the name of a list entry (dict or str) |
  | `_get_workspace_names()` | workspace names for combos — a fresh GET every call, deliberately uncached |
  | `_fan_out(fn, items) -> [(result, error)]` | parallel per-item GETs; a failing item yields `(None, exc)` instead of aborting |
  | `_report_partial_failures([(label, exc)])` | one warning banner + log lines for what a listing could not fetch |
  | `_delete_many(kind, [(label, fn)], reload_fn, cascade=…)` | confirm + run + report one or many deletions |
  | `_reload_current_tab()` | after an action reachable from another tab |

- **Adding a layer to QGIS** (`LayerTabMixin._add_layer_to_qgis`): build the URI with `_layer_uri`
  (pure, tested), construct `QgsRasterLayer`/`QgsVectorLayer`, check `isValid()`, then
  `QgsProject.instance().addMapLayer()` — never `iface.addRasterLayer()`, which pops QGIS's own modal on
  failure instead of our banner. Credentials travel as `authcfg=<geoserver_auth_cfg_id>`, resolved by the
  providers from `QgsAuthManager`, so a saved project never contains a password. Note the plugin's TLS
  setting does not reach QGIS's providers; they use QGIS's own certificate handling.

## Invariants — do not break these

1. **Row cache and tab callbacks are reset together.** `_setup_table` clears `_all_rows`/`_filtered_rows`;
   `_reset_table_state` clears those *and* every callback and the pagination buttons. A loader that fails
   mid-fetch must leave an empty table, never the previous type's rows under the new type's Delete
   handler — that was a real wrong-target delete (`tests/qgis/test_dlg_main.py` guards it).
2. **Table sorting stays off** (`_setup_table` forces it). Rows are mapped back by index; a header click
   would make *Delete Selected* act on a different resource than the one highlighted.
3. **Edits merge onto what the server has.** GeoServer applies a datastore PUT by *replacing* the whole
   `connectionParameters` map. Never route an edit through the typed `create_*` helpers — use
   `_update_datastore_from_values`, which overlays only the form's own keys onto the fetched params and
   keeps the server's `type` and `enabled`.
4. **Add refuses an existing name.** `create_workspace` / `create_datastore` are upserts (POST, then PUT
   on 409). Check `_resource_exists` first or a live resource is silently reconfigured and reported "created".
5. **Never prefill or re-send a password.** GeoServer returns `passwd` encrypted (`crypt1:…`) or not at all;
   posting it back stores the ciphertext as the password. The field is blank and required on edit.
6. **No rename for datastores** (`name` is read-only in edit mode). A rename would upsert: duplicate the
   store, or overwrite whatever holds the new name.
7. **Delete confirmations name the cascade.** Both delete paths send `recurse=true`.
8. **`isVisible()` lies on inactive tab pages.** `ResourceFormDialog` tracks hidden fields in
   `_hidden_keys`; validation uses that, not Qt, and switches to the tab holding the offending field.
9. **Nav labels in `TABS` are logic keys as well as text.** The `tr("Actions")` column and the
   `tr("Workspace")` key in `_extra_click_callbacks` must match the header strings exactly.

## geoservercloud — facts the code relies on

- Every REST verb calls `raise_for_status()` **except** GET/DELETE on 404 and POST on 409. Those three come
  back as `(content, status)` — which is exactly why `_check` exists. `requests` exceptions all subclass
  `OSError`, so catch `HTTPError` *before* `OSError` (see `_probe`).
- `create_workspace` and `create_datastore` **upsert**. There is no `update_*`, no `delete_datastore`, no
  workspace rename, no "set default workspace" call (the `set_default_workspace=True` kwarg only sets a
  client-side attribute). Those are `_raw_rest` workarounds carrying `TODO(#50)`, each with a row in
  [issue #50](https://github.com/ronitjadhav/geoserver_manager/issues/50) — the library-first rule in
  Conventions says how new ones are handled.
- **GeoServer always has exactly one default workspace and it cannot be unset.** `GET
  /rest/workspaces/default.json` never 404s (with `default.xml` deleted it answers the first workspace),
  and the web UI's "Default Workspace" checkbox only *sets*: `WorkspaceEditPage` has
  `if (defaultWs) setDefaultWorkspace(ws)` with no else, so unchecking it and saving is a no-op. The
  plugin therefore shows the default read-only-and-checked, marks it in the Workspaces list, and reads it
  live from the server on every load and every edit dialog — if it looks "out of sync" with the web UI,
  the web UI is the one lying.
- The client strips trailing `/` from the URL itself. It has no timeout parameter (`TIMEOUT = 120` is a
  module constant). `verifytls` is the *Verify the server's TLS certificate* setting (default on);
  `_probe` catches `requests.exceptions.SSLError` before `OSError` so a private-CA server is reported as a
  certificate problem, not as "is the server running?".
- **Thread safety:** the REST methods are stateless `requests.*` calls and are safe to run through
  `_fan_out` (the datastore list does this). `self.wms` / `self.wmts` on the client are shared state —
  OWS calls must not be fanned out the same way.
- The bundled wheel is the upstream 0.8.5 with `geoserver_acceptance_tests/` removed (15 MB of fixtures):
  16 MB → 49 KB. On a version bump, strip the new wheel the same way — the procedure is in
  `toolbelt/dependencies.py` and the `release-plugin` skill. `GSC_REQUIRED` pins the version;
  `ensure_dependencies()` logs which copy was imported and from where, and pushes a warning when it is not
  the pin — an install in the QGIS profile still wins over the bundled wheel, the warning is how you notice.
  `tests/qgis/test_library_contract.py` asserts the pin equals the shipped wheel.
- Extracted library source, when you need to read it: unzip the wheel into a scratch dir; the plugin
  only uses `geoservercloud/geoservercloud.py`, `services/restclient.py`, `services/restservice.py`,
  `models/datastore.py`, `models/workspace.py`.

## Conventions

- **python-geoservercloud first — always.** Before writing any GeoServer call, look for the library
  method (`geoservercloud/geoservercloud.py` in the bundled wheel) and use it, even when a raw request
  would be shorter. If the method does not exist, or exists but cannot do what is needed:
  1. **Update [issue #50](https://github.com/ronitjadhav/geoserver_manager/issues/50) first** — add a row
     with the call site, the REST verb + path, and the library API you would want. That issue is the
     work list for maturing the library; a gap that is not in it will never be fixed upstream.
  2. Then, and only then, work around it here through `self._raw_rest(...)` (never a bare
     `rest_client` call) with a `TODO(#50)` comment at the call site.
  3. When the library gains the method and the bundled wheel is bumped, replace the workaround, drop the
     `TODO(#50)`, and tick the row.
  The same applies to behaviour the plugin has to paper over (`_check`, `_resource_exists`, the datastore
  merge): those are library gaps too, and they are listed in #50. We depend on this library; the fastest
  way to make the plugin better is to make the library better.
- **Nothing the dialog shows comes from a cache.** Lists are fetched on every tab switch and Refresh,
  edit dialogs fetch the object when they open, pickers fetch their options when the form opens. A
  workspace-name cache once survived a Refresh and left the datastore form's combo stale; it was removed
  rather than given a TTL. One extra GET is always cheaper than a stale view.
- **Smallest change that removes demonstrated friction.** No abstraction with one implementation, no
  config for a value that never changes. A service layer between GUI and library was proposed twice and
  rejected as premature — don't build it until a non-GUI caller needs the API.
- Deliberate shortcuts carry a `ponytail:` comment naming the ceiling and the upgrade path; library gaps
  carry `TODO(#50)` (see the first convention). Leave both in place until the condition they name is met.
- `self.tr()` inside the mixins **cannot** resolve translations: strings are extracted under the mixin's
  class name but looked up under `GeoServerMainDialog` (QDialog precedes the mixins in the MRO, so an
  override of `tr()` there is dead code). When the first real translation lands, switch those sites to
  `QCoreApplication.translate("<MixinClass>", …)`.
- Messages: user-facing outcomes go to the dialog's message bar (`show_*_message`); details go to the QGIS
  log (`self.log(..., log_level=Qgis.MessageLevel.Critical)`). `_run_action` does both.
- Qt6-compatible enums only: `Qt.CursorShape.WaitCursor`, `QDialog.DialogCode.Accepted`,
  `QMessageBox.StandardButton.Yes` — never the unscoped PyQt5 spellings. CI runs a PyQt6 checker.
- Every fix ships with a test that **fails without it** — run the test against the old code once to prove
  it. Headless GUI tests: `from qgis.testing import start_app, unittest; start_app()` then instantiate
  `GeoServerMainDialog()` directly and drive its methods. Fake the server by assigning `dlg.gs = FakeGS()`.
  `tests/qgis/conftest.py` puts the bundled wheels on `sys.path`, so tests may also import the real
  `geoservercloud` models to lock payload shapes (see `test_library_contract.py`).
- Commit messages: conventional prefix (`fix:`, `feat:`, `refactor:`, `chore:`, `ci:`, `docs:`), a body
  that says *why*. Pre-commit runs ruff, ruff-format, black, isort, flake8(+flake8-qgis) and the
  hygiene hooks on every commit; if black rewrites a file the commit aborts — re-add and commit again.

## Developing and verifying

```sh
python -m pip install -r requirements/development.txt -r requirements/testing.txt
pre-commit install

# lint + format exactly as CI does
pre-commit run -a
# tests (unit needs no QGIS; qgis needs the QGIS python, headless is fine)
python -m pytest tests/unit
QT_QPA_PLATFORM=offscreen python -m pytest tests/qgis
# build the zip qgis-plugin-ci would release (~125 KB, 23 files)
qgis-plugin-ci package 0.1.0 --allow-uncommitted-changes && rm geoserver_manager.0.1.0.zip
```

A real server to test against: `docker compose up -d` — GeoServer on :8080
(admin/geoserver) plus PostGIS, reachable *from GeoServer* as host `postgis`,
database / user / password `geoserver`. Use it for anything touching the library
contract: the `crypt1:` password encoding, the datastore edit merge and `enabled`
handling were all confirmed against it, and a fake server cannot show you those.

Load the plugin in QGIS by symlinking `geoserver_manager/` into a profile's `python/plugins/`
(`docs/development/environment.md`). Check which profile QGIS actually launches
(`profiles.ini` → `lastProfile`) before assuming `default`. The plugin is `experimental=True`, so
*Show also experimental plugins* must be on. `plugin_reloader` picks up code changes without a restart.

CI (`.github/workflows/`): linter (flake8 + PyQt6 check), tester (unit on 3.12, qgis suite in the
`qgis/qgis:3.40` container), documentation (Sphinx → GitHub Pages), package & release (zip on push to
main; publish on tag — never exercised yet, no tag exists).

## Where the work is

Open milestones on GitHub mirror `docs/github_issue_roadmap.md`. Issues labelled `tech-debt` are
audit findings that were verified but not fixed; each names the file, the mechanism and the fix.
