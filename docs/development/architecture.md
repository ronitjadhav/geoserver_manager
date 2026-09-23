# Architecture

How the plugin is put together, and the helpers every tab goes through. Read
this and the [invariants](invariants.md) before changing code: they record
what the code cannot tell you. Python 3.12 (QGIS 3.40 and newer), PyQt5
**and** PyQt6 through `qgis.PyQt`.

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
| `geoserver_manager/extras/*.whl` | Bundled `geoservercloud` (stripped, see the [GeoServer notes](geoserver-notes.md)) and `xmltodict`, added to `sys.path` at startup |
| `tests/unit/` | Runs without QGIS. `tests/qgis/` needs the QGIS Python (headless via `qgis.testing.start_app()`) |
| `docs/` | The site: Sphinx + MyST + Furo, deployed to GitHub Pages on every push to main. `usage/` is written for the user, `development/` for a contributor, `github_issue_roadmap.md` is the feature backlog that GitHub milestones mirror. **`development/geoserver-notes.md` holds the measured GeoServer and library facts this plugin depends on** |
| `scripts/` | `update_translations.py` (pylupdate6), `export_branding.py` (every brand asset from one SVG), `capture_screenshot.py` (every screenshot the README and the guide show, grabbed from the real dialog) |
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
  optional fourth element when the action's tooltip must say more than the label
  (the browser preview's login note).
  `_make_action_widget` keeps up to two frequent actions visible (add to QGIS,
  preview, browse and publish). Other actions get labels in a More or Actions
  menu, with destructive actions last and separated when needed. Both paths
  check the connection at activation and capture the row from the page render.
  Keep this grouping central; tabs only declare their existing action tuples.
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
  | `_fetch(fn, failure_message) -> value \| None` | any read the UI needs before continuing: runs `fn` in a worker thread and waits behind an application-modal *Waiting for GeoServer* box (after 0.3 s) with Cancel, so a dead server cannot freeze QGIS. `in_worker=False` for work on a live QGIS layer. A map layer `fn` builds comes back moved to the GUI thread |
  | `_wait_for(fn) -> value` | the same wait without the reporting, for a read inside a handler that does its own (the Publish form's combo refills) |
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
  | `_upload_file(failure_message, client, url, source, params, headers, on_success, on_cancel, folder=…, after=…, on_done=…)` | the one way a file leaves this machine: streams `source` through `_run_upload`, removes `folder` however it ends, runs `after(client)` in the worker for a follow-up PUT. Check `_upload_slot_free()` *before* exporting. `_report_cancelled_upload(kind, tab, exists, name)` is its `on_cancel`. `on_done(outcome)` runs once at the end with "done", "failed" or "cancelled": the batch publish (`_publish_layers`) starts its next layer from it, since only one upload runs at a time. Returns False when nothing started |
  | `_cancel_load(user=False)` | stop the running load; `user=True` is the Cancel button, which also explains itself in a banner |
  | `_fan_out(fn, items, task=None) -> [(result, error)]` | parallel per-item GETs; a failing item yields `(None, exc)` instead of aborting. With the task: progress per item, and a cancel stops the loop |
  | `_report_partial_failures([(label, exc)])` | one warning banner + log lines for what a listing could not fetch |
  | `_delete_many(kind, [(label, fn)], reload_fn, counted, cascade=…, verb=…, done=…)` | confirm + run in a task with progress + report one or many deletions; `counted` is the tab's `n -> translate(ctx, "%n layer(s)", None, n)`, so each locale gets its plural forms ([translations](translation.md)); `verb`/`done` for a tab whose action is not a delete ("stop caching" / "removed from the cache") |
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

## The server and the library

They are on their own page, [GeoServer and library notes](geoserver-notes.md), because they
are needed when touching one tab's server calls and not for every change.
**Read it before writing or changing any GeoServer call.** What is in it:

- Which verbs raise, which return `(content, status)`, and why `_check` exists.
- Which library methods upsert, which are missing, and what goes through `_raw_rest`.
- Per resource type: layers of every type, legends and previews, coverages,
  cascaded WMS and WMTS stores, layer groups, workspace WMS settings, the tile
  cache and its XML-only writes, file-based and cascaded WFS datastores.
- Publishing from QGIS: what a GeoPackage or GeoTIFF upload actually creates,
  what a cancelled upload leaves behind, and how SLD versions pick a content type.
- The bundled wheel: why it is stripped, and what to do on a version bump.
