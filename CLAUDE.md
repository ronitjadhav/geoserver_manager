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
| `geoserver_manager/gui/dlg_main.py` | `GeoServerMainDialog(QDialog, <one mixin per tab>)` — nav list, results table, search, pagination, and every helper the tabs share |
| `geoserver_manager/gui/tab_workspaces.py`, `tab_datastores.py`, `tab_coveragestores.py`, `tab_layers.py`, `tab_layergroups.py`, `tab_styles.py` | One mixin per resource type: load / add / edit / delete (layers also: publish, add to QGIS; layer groups also: add to QGIS; coverage stores also: publish a coverage) |
| `geoserver_manager/gui/dlg_resource_form.py` | `ResourceFormDialog` — a modal form built from a list of field dicts (see its module docstring for the field spec) |
| `geoserver_manager/gui/dlg_settings.py` | Options page: URL + credentials (credentials go to `QgsAuthManager`, encrypted) |
| `geoserver_manager/toolbelt/` | `preferences` (QgsSettings + auth store), `log_handler`, `dependencies` (loads the bundled wheels), `env_var_parser`, `sld` (QGIS ⇄ SLD, version sniffing), `qgis_export` (GeoServer-safe names, GeoPackage export) |
| `geoserver_manager/extras/*.whl` | Bundled `geoservercloud` (stripped, see below) and `xmltodict`, added to `sys.path` at startup |
| `tests/unit/` | Runs without QGIS. `tests/qgis/` needs the QGIS Python (headless via `qgis.testing.start_app()`) |
| `docs/github_issue_roadmap.md` | Feature backlog; GitHub milestones mirror it |
| `docker-compose.yml` | Throwaway GeoServer 2.28.5 (`:8080`, admin/geoserver) + PostGIS, for testing against a real server |

The `Inspiration/` folder is untracked reference code. Never import from it.

## How the dialog works

- **Tabs are one registry.** `GeoServerMainDialog.TABS = ((label, icon, loader_name), …)`.
  `_setup_nav` builds the list from it and `_on_nav_changed` calls `getattr(self, loader)()`.
  A new resource type = one line in `TABS` + one mixin added to the class bases.
- **A loader** sets up the header buttons, `_name_click_callback`, `_extra_click_callbacks`,
  `_row_actions`, calls `_setup_table(columns)` — and then hands a fetch function to
  `_start_load(failure_message, fetch)` and returns. Rows are plain lists of display strings;
  column 0 is the resource name.
- **Loads run off the GUI thread.** `_start_load` wraps the fetch in a `_FetchTask` (a
  `QgsTask`), so `_load_x()` returns before a single row exists: QGIS's task bar shows the
  progress, *Refresh* turns into *Cancel*, and `finished()` comes back on the GUI thread to
  render. A fetch is `_fetch_<x>_rows(task=None) -> (rows, failures)`; it runs in a worker,
  so it must not touch a widget, and it only gets at the task by passing it to `_fan_out`.
  Mutations (add / edit / delete) still run inline under `_run_action` — they are one request
  and the user is waiting for the dialog they just confirmed.
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
  | `_start_load(failure_message, fetch)` | a tab load: runs `fetch(task)` in a `QgsTask`, renders `(rows, failures)` when it lands |
  | `_run_in_task(failure_message, work, on_success)` | the same for anything that is not rows (the connection probe) |
  | `_cancel_load(user=False)` | stop the running load; `user=True` is the Cancel button, which also explains itself in a banner |
  | `_fan_out(fn, items, task=None) -> [(result, error)]` | parallel per-item GETs; a failing item yields `(None, exc)` instead of aborting. With the task: progress per item, and a cancel stops the loop |
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
2. **Qt's table sorting stays off** (`_setup_table` forces it); a header click sorts `_filtered_rows` itself
   (`_on_header_clicked`), so the order on screen *is* the order of the row cache. Rows are mapped back by
   index, and Qt reordering the items on its own would make *Delete Selected* act on a different resource
   than the one highlighted. The sort survives a reload of the same tab and is dropped when the columns change.
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
9. **A fetch never touches a widget.** It runs in a worker thread; everything it learns comes
   back as `(rows, failures)` and is rendered by `_render_rows` on the GUI thread. A cancelled
   or failed load renders nothing, which is safe only because the loader reset the table
   *before* starting the task — that is what keeps "no stale rows" true here too.
10. **A loaded table outlives its connection.** `refresh_ui()` clears `self.gs` at once and re-probes in a
   task, so for up to `_PROBE_TIMEOUT` the rows on screen and their buttons belong to a client that is gone.
   Every user-triggered action therefore passes `_require_connection()`, and that check lives at the four
   places actions are dispatched — the Add button, Delete Selected, the row-action buttons and the link-cell
   click — never in the twenty methods behind them, so a new tab cannot forget it. A refresh also disables the
   header buttons immediately; the loader re-arms them. This was a reported crash:
   `AttributeError: 'NoneType' object has no attribute 'get_workspaces'` from *Publish a Layer*.
11. **Nav labels in `TABS` are logic keys as well as text.** The `tr("Actions")` column and the
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
- The client strips trailing `/` from the URL itself. It has no timeout parameter at all
  (`TIMEOUT = 120` is a module constant and `RestClient.get` takes no `timeout`), which is why
  `_probe` is the one call that uses `requests` directly — a dead host must cost 10 s, not two
  minutes (row 20 of #50). `verifytls` is the *Verify the server's TLS certificate* setting (default on);
  `_probe` catches `requests.exceptions.SSLError` before `OSError` so a private-CA server is reported as a
  certificate problem, not as "is the server running?".
- **Thread safety:** the REST methods are stateless `requests.*` calls and are safe to run through
  `_fan_out` (the datastore list does this). `self.wms` / `self.wmts` on the client are shared state —
  OWS calls must not be fanned out the same way.
- **File-based datastores** (row 30 of #50): the library's typed creators stop at PostGIS, JNDI and PMTiles,
  so Shapefile, *Directory of spatial files (shapefiles)* and GeoPackage forms build their parameter map and
  go through the generic `create_datastore`. Two things that map has to get right: a GeoPackage store must
  carry **`dbtype: geopkg`** — that is how GeoServer picks the factory — and an empty `charset` is omitted
  rather than sent blank, because blank is not "use your default". GeoServer fills in `namespace` itself, and
  the edit merge keeps it along with everything else the form does not show.
- **Publishing a QGIS layer** (rows 28–29 of #50) uploads a GeoPackage: `PUT
  .../datastores/{name}/file.gpkg?update=overwrite`. GeoServer then creates the store *and* configures one
  feature type per table in the file, with the SRS, bounding box and attributes read from the data — so the
  layer is published by that one request, and the table name inside the GeoPackage is the layer's name. Three
  things follow from that: metadata is added with a **partial** feature-type PUT, which merges (a
  `create_feature_type()` template would replace the computed values); the store is marked `read_only` by
  merging onto its own parameters (the recommended setting for a file store nobody writes to), best-effort,
  because the data is already published by then and a flag must not fail the publish; and deleting the store later **leaves the
  uploaded file** in the data directory. A QGIS layer name must pass `toolbelt/qgis_export.geoserver_name()`
  first — it becomes a WFS type name, so it has to be an XML NCName.
- **SLD versions decide the content type** (row 27 of #50). GeoServer picks its SLD parser from the request's
  content type, not from the document: `application/vnd.ogc.sld+xml` for 1.0, `application/vnd.ogc.se+xml` for
  1.1. `rest_service.create_style()` only sends the former, so `toolbelt/sld.py` sniffs the version
  (`StyledLayerDescriptor/@version`, else the `se:` namespace) and `_put_sld_body()` raw-PUTs the 1.1 case —
  every SLD write in the plugin goes through it. Facts behind that: `QgsMapLayer.saveSldStyle()` always writes
  **SLD 1.1** on QGIS 3.40, even for a single-symbol renderer; a 1.1 body sent as 1.0 is accepted and rendered
  but recorded as `languageVersion 1.0.0`; and `GET {style}.sld` returns GeoServer's **1.0 rendition** of a
  stored 1.1 document, so the editor shows converted text and says so. Exporting or applying a style touches a
  live QGIS layer, so it happens on the GUI thread before any upload (invariant 9).
- **Workspace WMS settings** (rows 25–26 of #50): `WmsSettings` models none of the service metadata
  (`title`, `abstrct`, `keywords`, `srs`, …) and there is no delete, so `tab_workspaces.py` GETs, PUTs and
  DELETEs the settings path itself. GeoServer facts behind that code: the abstract's JSON key is **`abstrct`**;
  a partial PUT **merges**, so sending only the form's fields is what keeps the watermark and metadata links
  intact (a full template would overwrite them); the settings are **created with PUT** (POST answers 405) and
  removed with DELETE; and `defaultLocale` must be `""` when empty — `null` makes GeoServer's `LocaleConverter`
  throw an NPE (500). The library's `unset_default_locale_for_service()` silently does nothing at all.
- **Coverages** (rows 21–24 of #50): there is no `get_coverage_stores(ws)` at all; `get_coverages` hardcodes
  `list=all`, so "what is published" needs its own call (`list=configured`) — the difference is what the
  *Publish* action offers; `CoverageStore` drops the store's description and its `put_payload()` raises
  `NotImplementedError` (no store edit anywhere); `Coverage.asdict()` drops the bounding boxes and keywords.
  Two GeoServer facts the tab depends on: a grid range's `high` is the **exclusive** bound (size = high − low,
  checked against gdalinfo), and store metadata GeoServer does not understand — `CogSettings.Key` without the
  COG extension — is dropped silently, so the create warns when it comes back missing.
- **Layer groups** are the biggest library gap so far (rows 16–19 of #50): every layer-group call requires a
  `workspace_name`, so the *global* groups are unreachable; `create_layer_group` re-qualifies every layer with
  the group's own workspace (no cross-workspace and no nested group), always sends a world bbox from a
  three-entry `EPSG_BBOX` table — GeoServer computes the real union when `bounds` is omitted — and writes the
  abstract as `abstract`, which GeoServer drops (its key is `abstractTxt`, which the model also fails to read).
  Hence `tab_layergroups.py` builds its own payload and GETs the group itself; it still uses the facade for the
  per-workspace listing and delete.
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
- The global-or-workspace scope (`GLOBAL` label + `scope()`) lives in `gui/scope.py`, now that styles, layer
  groups and the dialog's own workspace-link helper all need it. `_layer_uri()` is still reached from
  `tab_layers.py` through the shared dialog class; lift it the same way when a third caller appears.
- **One `_open_workspace_from_row()` on the dialog** serves every tab's Workspace column (column 1) and skips
  the global label. Tabs point their `_extra_click_callbacks` at it rather than writing their own.
- **A form's primary button says what it does.** `ResourceFormDialog(..., ok_label="Create" | "Publish" |
  "Upload" | "Apply" | "Set style")`; only an *edit* keeps the default "Save". Add-button labels start with a
  verb and never say "New" (`Add a Workspace`, `Publish a Layer`, `Upload a Style`), and the dialog they open is
  titled with the same words — `tests/qgis/test_ux.py` sweeps every tab for both rules.
- **An empty table says why.** `_empty_state_text()` distinguishes a fruitless filter ("Nothing matches 'x' —
  Esc clears the filter"), an empty resource type ("Nothing here yet — start with 'Add a Workspace' above") and
  the plain fallback. It reads `btn_add.isHidden()`, not `isVisible()` — see invariant 8.
- **Colours come from the palette**, never from a literal: `gui/theme.py` maps "ok" / "error" / "busy" and
  the hint and invalid-field colours onto the widget's own palette, choosing a light- or dark-background
  variant. `tests/qgis/test_ux.py` asserts each one clears WCAG's 3:1 contrast floor against the window
  colour in both themes, so a prettier colour that cannot be read fails the suite.
- **Keyboard: F5 / Ctrl+F / Esc / Del** live in `GeoServerMainDialog.keyPressEvent`, not in `QShortcut`,
  because each one has to know where the focus is: Del may only delete when the *table* has focus (the same
  key erases a character in the search box), and Esc clears the search only when there is one, so it still
  closes the dialog otherwise.
- **Nothing the dialog shows comes from a cache.** Lists are fetched on every tab switch and Refresh,
  edit dialogs fetch the object when they open, pickers fetch their options when the form opens. A
  workspace-name cache once survived a Refresh and left the datastore form's combo stale; it was removed
  rather than given a TTL. One extra GET is always cheaper than a stale view.
- **Smallest change that removes demonstrated friction.** No abstraction with one implementation, no
  config for a value that never changes. A service layer between GUI and library was proposed twice and
  rejected as premature — don't build it until a non-GUI caller needs the API.
- Deliberate shortcuts carry a `ponytail:` comment naming the ceiling and the upgrade path; library gaps
  carry `TODO(#50)` (see the first convention). Leave both in place until the condition they name is met.
- **Strings in a tab mixin use `translate("<MixinClass>", "…")`**, never `self.tr()`: `self.tr` in a mixin
  is `QObject.tr` with the *instance's* context, `GeoServerMainDialog`, while `pylupdate` extracts under the
  mixin's own class — so every lookup missed. Each mixin file aliases `translate = QCoreApplication.translate`
  and repeats its context at the call site, because `pylupdate` only understands a literal context (a wrapper
  function is not extracted at all — measured, not assumed). `GeoServerMainDialog`, `ResourceFormDialog` and
  the settings page are real QObject subclasses and keep `self.tr()`. A string that is *compared* rather than
  only displayed must come from one place: the row-actions column label is `self.actions_column_label()` on
  the dialog, so `_setup_table`'s comparison cannot drift from the header once a locale is installed.
  `tests/qgis/test_i18n.py` fails if a mixin goes back to `self.tr()`, if a `translate()` call names another
  file's context, if a new `tab_*.py` appears without being covered — or if the code has a string the
  `.ts` lacks. Extraction is `python scripts/update_translations.py` (pylupdate6, `pip install PyQt6`);
  run it after changing a user-visible string. Never pylupdate5: it silently skipped every `translate()`
  black wrapped onto several lines or wrote as adjacent literals — 65 of 455 strings when measured.
- Messages: user-facing outcomes go to the dialog's message bar (`show_*_message`); details go to the QGIS
  log (`self.log(..., log_level=Qgis.MessageLevel.Critical)`). `_run_action` does both.
- Qt6-compatible enums only: `Qt.CursorShape.WaitCursor`, `QDialog.DialogCode.Accepted`,
  `QMessageBox.StandardButton.Yes` — never the unscoped PyQt5 spellings. CI runs a PyQt6 checker.
- Every fix ships with a test that **fails without it** — run the test against the old code once to prove
  it. Headless GUI tests: `from qgis.testing import start_app, unittest; start_app()` then instantiate
  `GeoServerMainDialog()` directly and drive its methods. Fake the server by assigning `dlg.gs = FakeGS()`.
  `tests/qgis/conftest.py` puts the bundled wheels on `sys.path`, so tests may also import the real
  `geoservercloud` models to lock payload shapes (see `test_library_contract.py`).
- **Testing a load.** What is loaded: call the seam, `rows, failures = dlg._fetch_x_rows()`.
  A whole loader: use `tests/qgis/sync_dialog.SyncDialog`, which runs the fetch inline, so
  `dlg._load_x(); dlg._all_rows` still works. The threading itself: the real dialog plus
  `spin_until()` from `test_dlg_main.py` (`TestBackgroundLoading`) — those tests all fail if
  a load ever goes back to running on the GUI thread.
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
# after changing any user-visible string (needs pip install PyQt6); test_i18n fails otherwise
python scripts/update_translations.py
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
