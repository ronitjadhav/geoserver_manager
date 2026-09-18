# CHANGELOG

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

### Fixed

- Acting on a table while the plugin was reconnecting crashed with
  `AttributeError: 'NoneType' object has no attribute 'get_workspaces'`. A
  refresh drops the connection immediately and re-probes in the background, so
  the rows and buttons on screen briefly belonged to a client that was gone.
  The header buttons are now disabled for that moment, and anything still
  clickable — row actions, link cells — says "Not connected to GeoServer" and
  does nothing.

### Added

- **Keyboard shortcuts**: F5 refreshes, Ctrl+F jumps to the search box, Esc
  clears the search (and still closes the dialog when there is nothing to
  clear), and Del deletes the selected resources — only while the table has the
  focus, so the same key still just erases a character in the search box. The
  shortcuts are named in the tooltips.
- **Readable on dark themes**: the connection status, the form hints and the
  invalid-field border take their colours from the widget palette instead of
  literal `red` / `green` / `gray`, which on QGIS's dark themes ranged from
  harsh to barely visible. The colours are checked against WCAG contrast in
  both themes by the tests.
- The dialog reopens on the tab it was closed on.
- **Translations work.** Every string in a tab mixin is now looked up in the
  context it is extracted under, so a translation can actually be found — until
  now none of them could be, because `self.tr()` in a mixin resolves against
  the host dialog's class. A starter French locale ships with the plugin
  (terminology very much open to review); anything untranslated falls back to
  English as usual.
- **Shapefile, directory-of-shapefiles and GeoPackage datastores have their own
  form**, next to PostGIS: a path on the server, the attribute charset, the
  spatial-index flag, and for a GeoPackage its read-only and expose-primary-keys
  switches. Creating and editing them was possible before only through the
  `key = value` editor. An edit still merges onto the parameters GeoServer
  holds, so a namespace, fetch size or memory-mapping setting the form does not
  show survives it.
- Saving credentials for a plain-HTTP server now says that the password
  travels unencrypted, and suggests `https://`. It saves them anyway — a
  server on a trusted network is a legitimate setup — and stays quiet for
  loopback addresses, because a warning on every local sandbox is a warning
  nobody reads.
- **Publish a QGIS layer to GeoServer.** The publish dialog on the Layers tab
  gained a source: a layer of the current project is written to a GeoPackage
  and uploaded, which makes GeoServer create the datastore and configure the
  layer — with its SRS, bounding box and attributes — in one request. Its
  symbology can travel with it as the layer's default style, the title,
  abstract and keywords are merged onto what GeoServer computed, and an
  existing layer of that name is only replaced when asked. The uploaded store
  is marked read-only — the recommended setting for a file-based store nobody
  writes to.
- A QGIS layer name is not a GeoServer layer name: "Rivière (2024)" is
  published as `Riviere_2024`. Accents are folded rather than replaced, a
  leading digit keeps its digit, and the suggested name stays editable. Style
  names pushed from QGIS go through the same rule.
- **Styles now travel both ways between QGIS and GeoServer.** Upload a style
  from the symbology of a layer in the current project (a third source in the
  upload dialog), or push it in one step from the Layers tab with *Style from
  QGIS*, which uploads the style into the layer's workspace and makes it the
  layer's default. In the other direction, *Apply to a QGIS layer* loads a
  server style into a project layer, and *Save as SLD* writes any style's body
  to disk.
- Every SLD upload now carries the content type its own version needs. QGIS
  writes SLD 1.1 (Symbology Encoding); sent as 1.0 — all the library can do —
  GeoServer accepts and renders it but records it as `languageVersion 1.0.0`.
  Pasted and file-based 1.1 documents were mislabelled the same way until now.
  The style dialog also shows the version GeoServer stored, and says when the
  body it displays is GeoServer's 1.0 rendition of a stored 1.1 document.
- **Workspace WMS settings**, as a second group of the workspace dialog: give a
  workspace its own WMS service or send it back to the global one, and edit the
  service title, abstract, keywords, advertised SRS list, maximum rendering time
  and errors, and default locale. Only the fields shown are sent, so everything
  else GeoServer keeps for that service — watermark, buffers, metadata links,
  interpolation — is left exactly as it was.
- **Coverage Stores tab**: every raster store across the workspaces with its
  type and how many coverages it publishes; open one for its URL, description
  and published coverages, or the *Coverages* action to read one coverage's
  SRS, native format, pixel size, bounds, keywords and bands. Create a store
  from a GeoTIFF, a COG URL, an ImageMosaic directory on the server or an
  ImageMosaic properties ZIP; *Publish a coverage* turns one into a layer;
  delete (single and bulk, recursing into the layers it published). A server
  that quietly drops the COG settings — no COG extension installed — now says
  so instead of leaving a store that reads whole files.
- **Loading no longer freezes QGIS.** Every tab load and the connection probe
  run in a `QgsTask`: the dialog paints and stays usable while requests are in
  flight, QGIS's task bar shows progress, and *Refresh* becomes *Cancel* for as
  long as a load is running. A server that accepts the connection and never
  answers now costs 10 seconds and a "Server unreachable" banner instead of two
  minutes of a frozen window.
- **Layer Groups tab**: the global layer groups and every workspace's, with
  mode and size; open one to see its layers in drawing order (with their
  styles and any nested group), title, abstract and bounds; create a group
  from an ordered list of layers — pick them from every published layer on
  the server, rasters included, mix workspaces in a global group, and give a
  layer a style other than its default with `layer = style`;
  **Add to QGIS** loads a group as a single WMS layer; delete (single and
  bulk). GeoServer computes the group's bounds from its layers.
- **Styles tab**: global and per-workspace styles; open one to see its
  definition and body, and edit the body of SLD/MBStyle styles in place;
  upload a style from pasted SLD or from an `.sld` / `.zip` / `.mbstyle` file;
  delete (single and bulk, purging the file and clearing references).
- **Set style** on the Layers tab: pick a layer's default style among the
  global styles and its workspace's own; nothing else on the layer is touched.
- The form dialog gained a `file` field type (path + Browse).
- **Add to QGIS** from the Layers tab: load any GeoServer layer into the current
  project as WMS, WFS (the actual features) or WMTS (via GeoWebCache). The layer
  source carries the plugin's QGIS authentication config id, never a password.
- **Layers tab**: every feature type on the server, with its workspace,
  datastore, SRS and enabled flag; search and pagination; a detail view with
  native name, projection policy, title, abstract, keywords, bounding box and
  attributes; **publish a table** (workspace → datastore → not-yet-published
  tables, with declared SRS, title, abstract, keywords); delete (single and
  bulk).
- Error banners now include GeoServer's own explanation. A failed delete used
  to read "500 Server Error: for url: …"; it now says, for example, "Unable to
  delete layer referenced by layer group 'tasmania'".
- Any datastore type can be edited. Types without a dedicated form (Shapefile,
  GeoPackage, …) get a `key = value` editor for their connection parameters;
  the save merges onto the server's stored map exactly as the typed forms do.
- *Verify the server's TLS certificate* setting (default on); a private-CA or
  self-signed server is now reported as a certificate problem, not as
  "is the server running?".
- The Workspaces list shows GeoServer's default workspace; rows are selectable
  on every tab, so *Delete Selected* works everywhere.
- `docker-compose.yml`: a throwaway GeoServer 2.28.5 plus PostGIS for local
  development and for testing the library contract against a real server.

### Fixed

- The workspace-name list used by the datastore forms was cached and survived a
  Refresh on the Workspaces tab, so a workspace created elsewhere showed in the
  list but not in the combo. Nothing the dialog shows is cached any more.
- The Workspaces list shows which workspace is GeoServer's default, read from the
  server on every load, and the edit form explains that GeoServer always has
  exactly one default that cannot be unset (unchecking it in the GeoServer web
  UI is a no-op there).
- A tab load that failed mid-fetch left the previous resource type's rows in the
  table cache, reachable through search and pagination and wired to the new
  tab's delete handler — Delete could act on the wrong resource.
- Editing a datastore replaced its whole connection-parameter map, discarding
  pool settings, `Loose bbox`, `preparedStatements` and the real namespace,
  resetting a PMTiles store's range-reader provider to `file`, and re-enabling
  disabled stores. Edits now merge onto what the server holds.
- "Add a New Workspace/Datastore" silently overwrote an existing resource of the
  same name and reported it as created; both now refuse a taken name.
- A datastore cannot be renamed from the edit form any more: it would either
  duplicate the store or overwrite whatever already held the new name.
- Delete confirmations now state what the cascade takes with it (both delete
  paths send `recurse=true`).
- The first, blocking connection attempt no longer runs before the window is on
  screen, which made an unreachable host look like a hung QGIS.

- Bulk delete acted on the wrong rows once a column was sorted; table sorting is
  now disabled, since rows are paginated client-side.
- A wrong password or an HTTP error was reported as "server unreachable", and a
  404 from the configured URL was reported as a successful connection.
- Required form fields on an inactive tab were never validated, so datastores
  could be submitted without host, database, user or password.
- Editing a workspace from the datastore list repainted the table with the wrong
  resource type.
- A malformed GeoServer URL in the settings page silently discarded the
  credentials entered alongside it.
- Failures to write to the QGIS authentication database are now reported instead
  of leaving the plugin silently unconfigured.
- Editing a PostGIS datastore no longer sends GeoServer's encrypted password
  back as the new password; it has to be re-entered.

### Changed

- The bundled `geoservercloud` wheel is stripped of its acceptance-test
  fixtures: 16 MB -> 49 KB.
- The datastore list fetches store details in parallel (~5x faster) and caches
  workspace names between dialogs.

## 0.1.0 - 2026-03-27

- First release
- Generated with the [QGIS Plugins templater](https://oslandia.gitlab.io/qgis/template-qgis-plugin/)
