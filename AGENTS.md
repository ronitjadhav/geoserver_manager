# GeoServer Manager: a guide for coding agents

QGIS plugin that manages a GeoServer through the REST API, using the
[python-geoservercloud](https://github.com/camptocamp/python-geoservercloud)
library. Python 3.12 (QGIS ≥ 3.40), PyQt5 **and** PyQt6 via `qgis.PyQt`.
Read this file before touching code; it records what the code cannot tell you.

**The one rule above all others: python-geoservercloud first.** This plugin exists
partly to drive that library's maturity. Every GeoServer call goes through the
library; when the library lacks something, the gap is recorded in
[issue #50](https://github.com/ronitjadhav/geoserver_manager/issues/50) so it can be
implemented *there*, and only then worked around here. See Conventions.

The step-by-step procedures (`add-resource-tab`, `verify-plugin`, `release-plugin`) are
skills kept in the maintainer's private knowledge repository, linked into a clone as
`.claude/skills/` by its `link-project.sh`. They are not tracked here.

## Layout

| Path | What lives there |
|---|---|
| `geoserver_manager/plugin_main.py` | QGIS entry point: `initGui` / `unload` / `run`. Shows the dialog, then connects. |
| `geoserver_manager/gui/dlg_main.py` | `GeoServerMainDialog(QDialog, <one mixin per tab>)`: nav list, results table, search, pagination, and every helper the tabs share |
| `geoserver_manager/gui/tab_workspaces.py`, `tab_datastores.py`, `tab_coveragestores.py`, `tab_cascaded.py`, `tab_layers.py`, `tab_layergroups.py`, `tab_styles.py`, `tab_gwc.py` | One mixin per resource type: load / add / edit / delete (layers also: publish, add to QGIS, preview; layer groups also: add to QGIS; coverage stores also: publish a coverage; cascaded stores also: publish / view / delete a remote layer; tile cache: configure, truncate, stop caching) |
| `geoserver_manager/gui/dlg_resource_form.py` | `ResourceFormDialog`, a modal form built from a list of field dicts (see its module docstring for the field spec) |
| `geoserver_manager/gui/dlg_preview.py` | `LayerPreviewDialog`, a `QgsMapCanvas` showing one WMS layer of the server, with GetFeatureInfo on click; non-modal, nothing reaches the project |
| `geoserver_manager/gui/dlg_settings.py` | Options page: URL + credentials (credentials go to `QgsAuthManager`, encrypted) and *Test connection*, which probes the fields as typed |
| `geoserver_manager/gui/layer_tree.py` | `LayerTreeMenu`, the *GeoServer Manager* submenu of the layer tree's context menu: push / apply the clicked layer's style through the main dialog's connection and its `_push_qgis_style` / `_style_body`; outcomes go to `iface.messageBar()` |
| `geoserver_manager/toolbelt/` | `preferences` (QgsSettings + auth store), `log_handler`, `dependencies` (loads the bundled wheels), `env_var_parser`, `probe` (the bounded connection check the dialog and Settings share), `rest` (the raw REST call, `summarise_body` for banners, the streaming upload body; no QGIS import), `payload` (GeoServer's collection shapes, pure), `sld` and `qgis_export` (QGIS ↔ GeoServer conversions, pure) |
| `geoserver_manager/extras/*.whl` | Bundled `geoservercloud` (stripped, see below) and `xmltodict`, added to `sys.path` at startup |
| `tests/unit/` | Runs without QGIS. `tests/qgis/` needs the QGIS Python (headless via `qgis.testing.start_app()`) |
| `docs/` | The site: Sphinx + MyST + Furo, deployed to GitHub Pages on every push to main. `usage/` is written for the user, `development/` for a contributor, `github_issue_roadmap.md` is the feature backlog that GitHub milestones mirror. **`development/geoserver-notes.md` holds the measured GeoServer and library facts this plugin depends on** |
| `scripts/` | `update_translations.py` (pylupdate6), `export_branding.py` (every brand asset from one SVG), `capture_screenshot.py` (the screenshot the README and guide show, grabbed from the real dialog) |
| `docker-compose.yml` | Throwaway GeoServer 2.28.5 (`:8080`, admin/geoserver) + PostGIS, for testing against a real server |

The `Inspiration/` folder is untracked reference code. Never import from it.

## How the dialog works

- **Tabs are one registry.** `GeoServerMainDialog.TABS = ((label, icon, loader_name), …)`.
  `_setup_nav` builds the list from it and `_on_nav_changed` calls `getattr(self, loader)()`.
  A new resource type = one line in `TABS` + one mixin added to the class bases.
- **A loader** sets up the header buttons, `_name_click_callback`, `_extra_click_callbacks`,
  `_row_actions`, calls `_setup_table(columns)`, then hands a fetch function to
  `_start_load(failure_message, fetch)` and returns. Rows are plain lists of display strings;
  column 0 is the resource name. A `_row_actions` entry is `(icon, label, callback)`, plus an
  optional fourth element when the icon-only button's tooltip must say more than the label
  (the browser preview's login note).
- **Loads run off the GUI thread.** `_start_load` wraps the fetch in a `_FetchTask` (a
  `QgsTask`), so `_load_x()` returns before a single row exists: QGIS's task bar shows the
  progress, *Refresh* turns into *Cancel*, and `finished()` comes back on the GUI thread to
  render. A fetch is `_fetch_<x>_rows(task=None) -> (rows, failures)`; it runs in a worker,
  so it must not touch a widget, and it only gets at the task by passing it to `_fan_out`.
  Mutations (add / edit / delete) still run inline under `_run_action`: they are one request
  and the user is waiting for the dialog they just confirmed. The exception is an upload
  (`_run_upload`): its body is a `toolbelt.rest.ProgressReader`, which moves the task bar from each
  `read()` and raises on Cancel so `requests` drops the connection mid-body. The work gets the REST
  client as an argument, because a Refresh clears `self.gs` while it runs (`toolbelt.rest.raw_rest`
  is `_raw_rest` for a client you hold).
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
  | `_get_workspace_names()` | workspace names for combos: a fresh GET every call, deliberately uncached |
  | `_start_load(failure_message, fetch)` | a tab load: runs `fetch(task)` in a `QgsTask`, renders `(rows, failures)` when it lands |
  | `_run_in_task(failure_message, work, on_success, on_cancel=…, busy_text=…)` | the same for anything that is not rows (the connection probe, the deletes) |
  | `_run_quietly(failure_message, work, on_success)` | a side fetch (a dialog's legend) in its own slot: never supersedes a load, never turns Refresh into Cancel |
  | `_run_upload(failure_message, work, on_success, on_cancel)` | a long PUT: streams in its own task slot (`_upload`) with progress and Cancel; a load never supersedes it and it never touches the table: `on_success` reloads through `_reload_current_tab()`, `on_cancel` says what the server kept |
  | `_upload_file(failure_message, client, url, source, params, headers, on_success, on_cancel, folder=…, after=…)` | the one way a file leaves this machine: streams `source` through `_run_upload`, removes `folder` however it ends, runs `after(client)` in the worker for a follow-up PUT. Check `_upload_slot_free()` *before* exporting. `_report_cancelled_upload(kind, tab, exists, name)` is its `on_cancel` |
  | `_cancel_load(user=False)` | stop the running load; `user=True` is the Cancel button, which also explains itself in a banner |
  | `_fan_out(fn, items, task=None) -> [(result, error)]` | parallel per-item GETs; a failing item yields `(None, exc)` instead of aborting. With the task: progress per item, and a cancel stops the loop |
  | `_report_partial_failures([(label, exc)])` | one warning banner + log lines for what a listing could not fetch |
  | `_delete_many(kind, [(label, fn)], reload_fn, cascade=…, verb=…, done=…)` | confirm + run in a task with progress + report one or many deletions; `verb`/`done` for a tab whose action is not a delete ("stop caching" / "removed from the cache") |
  | `_require_safe_name(name)` | every Add form, before any request: refuses `/ ? # %` and edge spaces; `requests` sends `datastores/a#b.json` as `datastores/a` |
  | `_yes_no(value)` | a boolean cell, translated, never Python's `True` / `False` |
  | `_unwrap` / `_as_list` / `_name_of` | GeoServer's collection shapes, from `toolbelt/payload.py`; no tab keeps its own copy |
  | `_reload_current_tab()` | after an action reachable from another tab |

- **Adding a layer to QGIS** (`LayerTabMixin._add_layer_to_qgis`): build the URI with `_layer_uri`
  (pure, tested), construct `QgsRasterLayer`/`QgsVectorLayer`, check `isValid()`, then
  `QgsProject.instance().addMapLayer()`. Never `iface.addRasterLayer()`, which pops QGIS's own modal on
  failure instead of our banner. Credentials travel as `authcfg=<geoserver_auth_cfg_id>`, resolved by the
  providers from `QgsAuthManager`, so a saved project never contains a password. Note the plugin's TLS
  setting does not reach QGIS's providers; they use QGIS's own certificate handling.

## Invariants: do not break these

1. **Row cache and tab callbacks are reset together.** `_setup_table` clears `_all_rows`/`_filtered_rows`;
   `_reset_table_state` clears those *and* every callback and the pagination buttons. A loader that fails
   mid-fetch must leave an empty table, never the previous type's rows under the new type's Delete
   handler. That was a real wrong-target delete (`tests/qgis/test_dlg_main.py` guards it).
2. **Qt's table sorting stays off** (`_setup_table` forces it); a header click sorts `_filtered_rows` itself
   (`_on_header_clicked`), so the order on screen *is* the order of the row cache. Rows are mapped back by
   index, and Qt reordering the items on its own would make *Delete Selected* act on a different resource
   than the one highlighted. The sort survives a reload of the same tab and is dropped when the columns change.
3. **Edits merge onto what the server has.** GeoServer applies a datastore PUT by *replacing* the whole
   `connectionParameters` map. Never route an edit through the typed `create_*` helpers. Use
   `_update_datastore_from_values`, which overlays only the form's own keys onto the fetched params and
   keeps the server's `type`; `enabled` is the edit form's checkbox when it has one, else the server's.
   GeoServer ignores `enabled: false` on a POST (the store is created enabled, measured on 2.28.5). Only a
   PUT disables one, which is why the checkbox exists in edit mode only.
4. **Add refuses an existing name.** `create_workspace` / `create_datastore` are upserts (POST, then PUT
   on 409). Check `_resource_exists` first or a live resource is silently reconfigured and reported "created".
5. **Never show a password.** GeoServer returns `passwd` and `WFSDataStoreFactory:PASSWORD` encrypted (`crypt1:…`) or
   not at all; prefilled, the ciphertext would read as the password and get edited into garbage. GeoServer *does*
   accept its own ciphertext back (measured on 2.28.5: a PostGIS store still listed its tables after the round
   trip, and stopped doing so with a wrong plaintext). So on edit the field is blank. Blank means **keep** (the stored
   value is sent back) and typed means **replace**. The encryption is randomised: the same plaintext saves as a
   different `crypt1:` value every time, so ciphertexts cannot be compared.
6. **No rename for datastores** (`name` is read-only in edit mode). A rename would upsert: duplicate the
   store, or overwrite whatever holds the new name.
7. **Delete confirmations name the cascade.** Both delete paths send `recurse=true`.
8. **`isVisible()` lies on inactive tab pages.** `ResourceFormDialog` tracks hidden fields in
   `_hidden_keys`; validation uses that, not Qt, and switches to the tab holding the offending field.
9. **A fetch never touches a widget.** It runs in a worker thread; everything it learns comes
   back as `(rows, failures)` and is rendered by `_render_rows` on the GUI thread. A cancelled
   or failed load renders nothing, which is safe only because the loader reset the table
   *before* starting the task. That is what keeps "no stale rows" true here too. An upload's
   `work(task)` is held to the same rule: the file, the paths and the REST client are arguments
   captured on the GUI side, and progress goes through `task.setProgress`.
10. **A loaded table outlives its connection.** `refresh_ui()` clears `self.gs` at once and re-probes in a
   task, so for up to `PROBE_TIMEOUT` the rows on screen and their buttons belong to a client that is gone.
   Every user-triggered action therefore passes `_require_connection()`, and that check lives at the five
   places actions are dispatched: the Add button, Delete Selected, the row-action buttons, the link-cell
   click and the Del key (a selection change re-enables the button while the probe runs). It never lives in
   the twenty methods behind them, so a new tab cannot forget it. A refresh also disables the
   header buttons immediately; the loader re-arms them. This was a reported crash:
   `AttributeError: 'NoneType' object has no attribute 'get_workspaces'` from *Publish a Layer*.
11. **Nav labels in `TABS` are logic keys as well as text.** The `tr("Actions")` column and the
   `tr("Workspace")` key in `_extra_click_callbacks` must match the header strings exactly.

## geoservercloud and GeoServer: the measured facts

They live in **`docs/development/geoserver-notes.md`**, not here, because they
are needed when touching one tab's server calls and not in every session.
**Read that file before writing or changing any GeoServer call.** What is in it:

- Which verbs raise, which return `(content, status)`, and why `_check` exists.
- Which library methods upsert, which are missing, and what goes through `_raw_rest`.
- Per resource type: layers of every type, legends and previews, coverages,
  cascaded WMS and WMTS stores, layer groups, workspace WMS settings, the tile
  cache and its XML-only writes, file-based and cascaded WFS datastores.
- Publishing from QGIS: what a GeoPackage or GeoTIFF upload actually creates,
  what a cancelled upload leaves behind, and how SLD versions pick a content type.
- The bundled wheel: why it is stripped, and what to do on a version bump.

## Conventions

- **python-geoservercloud first, always.** Before writing any GeoServer call, look for the library
  method (`geoservercloud/geoservercloud.py` in the bundled wheel) and use it, even when a raw request
  would be shorter. If the method does not exist, or exists but cannot do what is needed:
  1. **Update [issue #50](https://github.com/ronitjadhav/geoserver_manager/issues/50) first**: add a row
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
  titled with the same words; `tests/qgis/test_ux.py` sweeps every tab for both rules.
- **An empty table says why.** `_empty_state_text()` distinguishes a fruitless filter ("Nothing matches 'x'.
  Esc clears the filter."), an empty resource type ("Nothing here yet. Start with 'Add a Workspace' above.") and
  the plain fallback. It reads `btn_add.isHidden()`, not `isVisible()`; see invariant 8.
- **Colours come from the palette**, never from a literal: `gui/theme.py` maps "ok" / "error" / "busy" and
  the hint and invalid-field colours onto the widget's own palette, choosing a light- or dark-background
  variant. `tests/qgis/test_ux.py` asserts each one clears WCAG's 3:1 contrast floor against the window
  colour in both themes, so a prettier colour that cannot be read fails the suite.
- **Every hook into QGIS is undone in `unload()`.** `LayerTreeMenu` connects
  `QgsLayerTreeView.contextMenuAboutToShow` in `initGui` and disconnects it in `unload()` *before* the dialog
  is destroyed: plugin_reloader is how this repo is developed, and a hook left behind fires into the dead
  plugin on the next reload. `tests/qgis/test_layer_tree.py` drives `initGui` → `unload` on a fake `iface`
  and checks the menu stops appearing. The menu never acts silently: pushing confirms target and style name,
  pulling picks when there are several styles. It also disables its entries with the reason when the
  dialog has no connection, rather than opening a form that complains.
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
  rejected as premature; don't build it until a non-GUI caller needs the API.
- Deliberate shortcuts carry a `ponytail:` comment naming the ceiling and the upgrade path; library gaps
  carry `TODO(#50)` (see the first convention). Leave both in place until the condition they name is met.
- **Strings in a tab mixin use `translate("<MixinClass>", "…")`**, never `self.tr()`: `self.tr` in a mixin
  is `QObject.tr` with the *instance's* context, `GeoServerMainDialog`, while `pylupdate` extracts under the
  mixin's own class, so every lookup missed. Each mixin file aliases `translate = QCoreApplication.translate`
  and repeats its context at the call site, because `pylupdate` only understands a literal context. A wrapper
  function is not extracted at all (measured, not assumed). `GeoServerMainDialog`, `ResourceFormDialog` and
  the settings page are real QObject subclasses and keep `self.tr()`; a toolbelt module translates under its
  own literal context (`ConnectionProbe`, `QgisExport`), listed in `test_i18n.py`'s known contexts. A string
  that is *compared* rather than only displayed must come from one place: the row-actions column label is
  `self.actions_column_label()` on the dialog, so `_setup_table`'s comparison cannot drift from the header
  once a locale is installed.
  `tests/qgis/test_i18n.py` fails if a mixin goes back to `self.tr()`, if a `translate()` call names another
  file's context, if a new `tab_*.py` appears without being covered, or if the code has a string the
  `.ts` lacks. Extraction is `python scripts/update_translations.py` (pylupdate6, `pip install PyQt6`);
  run it after changing a user-visible string. Never pylupdate5: it silently skipped every `translate()`
  black wrapped onto several lines or wrote as adjacent literals: 65 of 455 strings when measured.
- **Every plugin icon goes through the catalogue.** Use registered IDs from
  `resources/icons/catalog.json` in `gui/icons.py`, `TABS` and `_row_actions`.
  Do not call `QIcon`, `QgsApplication.getThemeIcon` or `iconPath` elsewhere.
  Before drawing or generating artwork, read the
  [icon style guide](docs/development/icon-style-guide.md) for the thin-stroke
  rules, shared symbols, SVG starter and reusable generation brief. If artwork is
  pending, register `status: needs-custom`, a QGIS `fallback` filename and design
  `notes` first. Run `python scripts/build_icon_catalog.py` after icon or usage
  changes. Review `docs/static/icons/icon-catalog.html` at 16, 20 and 24 px in
  light/dark and selected/disabled states. `tests/unit/test_icon_catalog.py`
  checks that uses, SVGs and the generated catalogue stay in sync. The full
  workflow and inventory are in the [icon catalogue](docs/development/icon-catalog.md).
- **The icon and the screenshots are generated, never hand-edited.**
  `scripts/export_branding.py` renders every brand asset from
  `resources/images/geoserver_manager.svg`, including the
  `resources/images/default_icon.png` that `metadata.txt` points at, and the website's
  logo and favicon; `docs/branding.md` is the guide. `scripts/capture_screenshot.py`
  regrabs the README and usage-guide screenshot from the real dialog against the docker
  sandbox, off screen. Re-run it when the dialog's layout changes, or the screenshot
  quietly starts showing an interface that no longer exists.
- Messages: user-facing outcomes go to the dialog's message bar (`show_*_message`); details go to the QGIS
  log (`self.log(..., log_level=Qgis.MessageLevel.Critical)`). `_run_action` does both. Errors and warnings
  **stay until closed** (duration 0): they say what to do next, and were gone in 5 s before. Success fades.
  A response body reaches a banner only through `toolbelt.rest.summarise_body` (first line, 300 chars, markup
  reduced to its title): a Tomcat error page or a proxy login page is not an explanation.
- **Reopening after Close must work.** `closeEvent` sets `_closing` so a late task finish stays away from dying
  widgets; `refresh_ui()` resets it and stops the running load *before* dropping `self.gs`, and a finished task
  frees its slot even while closing. Without that the dialog worked once per QGIS session; `test_audit_fixes.py`
  closes and reopens.
- **Tab labels get a tooltip** from `_tab_help()` (GeoServer's words: "WMS and WMTS stores that proxy another
  server's layers"); the label itself stays a logic key (invariant 11).
- Qt6-compatible enums only: `Qt.CursorShape.WaitCursor`, `QDialog.DialogCode.Accepted`,
  `QMessageBox.StandardButton.Yes`; never the unscoped PyQt5 spellings. CI runs a PyQt6 checker.
- Every fix ships with a test that **fails without it**. Run the test against the old code once to prove
  it. Headless GUI tests: `from qgis.testing import start_app, unittest; start_app()` then instantiate
  `GeoServerMainDialog()` directly and drive its methods. Fake the server by assigning `dlg.gs = FakeGS()`.
  `tests/qgis/conftest.py` puts the bundled wheels on `sys.path`, so tests may also import the real
  `geoservercloud` models to lock payload shapes (see `test_library_contract.py`).
- **Testing a load.** What is loaded: call the seam, `rows, failures = dlg._fetch_x_rows()`.
  A whole loader: use `tests/qgis/sync_dialog.SyncDialog`, which runs the fetch inline, so
  `dlg._load_x(); dlg._all_rows` still works. The threading itself: the real dialog plus
  `spin_until()` from `test_dlg_main.py` (`TestBackgroundLoading`): those tests all fail if
  a load ever goes back to running on the GUI thread.
- Commit messages: conventional prefix (`fix:`, `feat:`, `refactor:`, `chore:`, `ci:`, `docs:`), a body
  that says *why*. Pre-commit runs ruff, ruff-format, black, isort, flake8(+flake8-qgis) and the
  hygiene hooks on every commit; if black rewrites a file the commit aborts. Re-add and commit again.
- **Documentation ships with the change, in the same commit.** The docs are not a
  follow-up task; a change that reaches the user and leaves them stale is unfinished.
  What to touch:

  | Changed | Update |
  |---|---|
  | A tab, button, form or message | the matching section of `docs/usage/guide.md`, and `CHANGELOG.md` under *Unreleased* |
  | The dialog's layout | the guide, plus `python3 scripts/capture_screenshot.py` against the sandbox (the README and the guide show that image) |
  | A new resource type or tab | a guide section, a row in the feature tables of `README.md` and `docs/index.md`, and the roadmap ticked |
  | Install or configuration | `docs/usage/installation.md` and the README's Configuration section |
  | A dev step, tool or command | the page under `docs/development/` that teaches it, and this file if an agent would get it wrong |
  | The logo or a brand asset | `python3 scripts/export_branding.py`, never the exported files by hand |
  | A dependency or a workflow path filter | `.github/dependabot.yml` explains which workflow must see each requirements file; keep that mapping true |

  The site build must stay silent: `sphinx-build -b html -q docs docs/_build/html`
  prints nothing when it is healthy, so a warning is a broken link or an orphan page.
  There is no API reference and there cannot be one: the plugin does not import
  without QGIS, which the documentation job does not install.
- **No em dashes, and prefer short sentences.** In code, comments, docstrings, docs, commit messages and
  every user-facing string, use commas, periods, colons, semicolons or parentheses instead of an em dash.
  Split a long sentence into two rather than joining two clauses with a dash.

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

Run `docker compose up -d` for a real server to test against: GeoServer on :8080
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
main; publish on tag, never exercised yet since no tag exists).

## Where the work is

Open milestones on GitHub mirror `docs/github_issue_roadmap.md`. Issues labelled `tech-debt` are
audit findings that were verified but not fixed; each names the file, the mechanism and the fix.
