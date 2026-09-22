# CHANGELOG

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

### Fixed

- A workspace, datastore or layer-group name with `/`, `?`, `#` or `%` is
  refused before any request: `requests` would have sent
  `datastores/a#b.json` as `datastores/a` (another store's path), and a
  global layer group's raw path is URL-quoted.
- The *Isolated Workspace* help described something else; it says what
  isolation does (layers served only under the workspace's own URLs, so
  another workspace may share the namespace URI). The workspace delete
  confirmation lists coverage stores and cascaded stores among what goes.
- A layer-group line naming a layer the server does not have is refused
  with that name, instead of coming back as GeoServer's HTTP error.
- Editing a workspace without renaming it is one PUT; it used to POST,
  collect a 409 and PUT.
- A style, cascaded store, cascaded layer or tile-cache name with `/`, `?`,
  `#` or `%` is refused before any request, and names the server already
  holds are URL-quoted on their way into this plugin's REST paths:
  `requests` sent `styles/a#b.json` as `styles/a`, a different style.
- The style dialog's legend picks its context layer from the style's own
  workspace listing instead of the whole server's layer list.
- The cascaded-layers dialog was a viewer whose primary button, Enter,
  deleted the selected layer. It is a viewer; a cascaded layer is deleted
  from the Layers tab, like any other.
- A coverage store or a published coverage could be given a name with `/`,
  `?`, `#` or `%`, which `requests` then read as part of the URL: the request
  went to a *different* resource. Such names are refused before any request,
  and a workspace name is quoted in the browser preview's URL.
- Two project layers with the same name and kind showed as one entry in the
  pickers, and the second always resolved to the first, so the wrong layer's
  data or symbology went up. Duplicates carry the tail of their layer id.
- *Push style from QGIS* (Layers tab and layer tree) and a publish with its
  style replaced an existing server style without a word, and every layer
  sharing that style changed. It asks first: "Style 'x' already exists in
  'ws'. Replace it? Every layer that uses it will render differently." Keeping
  it is reported as such, not as an upload.
- *Publish a Layer → A layer from this QGIS project* listed raster layers and
  then tried to write them as a GeoPackage. A raster picked there now goes the
  way the Coverage Stores tab sends it (a GeoTIFF, uploaded and published as
  a coverage) with the same *Replace* rule; the form says which kind becomes
  what. A WMS or XYZ raster, which has no file to send, is refused in words.
- An ImageMosaic *properties ZIP* was read into memory and sent under the
  wait cursor; it streams in a task like the other uploads, with progress and
  Cancel. All three uploads share one helper (`_upload_file`) and one cancel
  report.
- Starting a second upload while one ran exported the layer first, minutes
  for a big raster, then refused and left the exported file in the temp
  folder. It refuses before exporting.

- The Layers tab listed only the feature types it found by walking the
  datastores, so a raster layer (including one just published from QGIS)
  and a cascaded WMS or WMTS layer never appeared there. It now shows
  GeoServer's own layer list, every type included, with the type, the store
  and the default style; the detail view, *Add to QGIS* (no WFS for a raster
  or a cascaded layer), *Preview in a browser* and *Delete* follow the type.
- Acting on a table while the plugin was reconnecting crashed with
  `AttributeError: 'NoneType' object has no attribute 'get_workspaces'`. A
  refresh drops the connection immediately and re-probes in the background, so
  the rows and buttons on screen briefly belonged to a client that was gone.
  The header buttons are now disabled for that moment, and anything still
  clickable (row actions, link cells) says "Not connected to GeoServer" and
  does nothing.
- The generic connection-parameter editor masked only a key *named*
  `password`, so a WFS store's `WFSDataStoreFactory:PASSWORD` showed its
  ciphertext. Any key ending in `password` or `passwd` is masked now.
- About one string in seven never reached the translation files: `pylupdate5`
  silently skips a `translate()` call that black wrapped onto several lines, or
  whose text is written as adjacent literals. Extraction now uses `pylupdate6`
  (`scripts/update_translations.py`), and a test checks every string in the
  code against the `.ts`.

### Changed

- Row actions now keep frequent controls visible and put secondary actions in
  labelled More or Actions menus. Destructive actions appear last, separated
  from other menu entries. Larger click targets, palette-based hover and focus
  states, and keyboard access make the thin custom icons easier to use.

- Refined the thin icon family for small controls: fuller brush tips, larger
  chain links, separate full-height style-transfer arrows and a clearer cache
  eraser. The 1.2-unit stroke weight is unchanged.
- All plugin icons now use custom SVG artwork: navigation, row actions,
  settings, help and layer-tree actions. Thin strokes and shared symbols keep
  them consistent. Preview, publish, style transfer and cache operations have
  distinct symbols; colours follow light, dark, selected and disabled states.
  Row buttons also have accessible names.
- A central icon registry tracks custom artwork and pending fallbacks, with
  checks for missing or unregistered icons. A short style guide keeps future
  additions consistent. The visual gallery is generated locally on demand;
  generated previews and inventories are not tracked in the repository.

- Layer-group modes read as GeoServer's web admin names them (Single,
  Opaque Container, Named Tree, Container Tree, Earth Observation Tree)
  in the table, the detail and the create form, which also explains what
  an Opaque Container is. The first column of the Workspaces, Datastores
  and Layer Groups tables is *Name*; the datastore form lists Name,
  Workspace, Type like every other form; Enabled cells read Yes / No.
- Styles, Cascaded Stores and Tile Cache: the first column is *Name*, an
  *Enabled* cell reads Yes / No rather than Python's `True` / `False`, and
  the style row actions say what they do: *Save to disk* (the body, whatever
  its format, not only SLD) and a tooltip on *Apply to a QGIS layer* that
  names the layer tree's *Apply style from GeoServer* as the same thing from
  the other end. The style editor's description says what Save does.
- Layers tab: the row actions read *Add to QGIS · Preview · Preview in a
  browser · Set style · Push style from QGIS · Delete*: the in-QGIS preview
  before the browser one, "Push style from QGIS" instead of "Style from QGIS"
  (the same word the layer tree uses), and every icon-only button has a
  tooltip saying what it does and how it differs from its neighbour; the
  Coverage Stores tab likewise. The first column is "Name" on both tabs.
- *Add to QGIS* proposes WFS for a vector layer (the features themselves) and
  WMS for the rest; the WMTS URI no longer carries a `crs=EPSG:4326` that made
  QGIS reproject every EPSG:900913 tile on the fly (measured).
- *Publish a table*: the declared SRS has no default any more (4326 was
  usually wrong for a projected table), and must be an EPSG number; the help
  says where to look it up.
- A coverage store's *Enabled* reads Yes / No instead of True / False; its
  read-only note no longer blames GeoServer's REST API (which does update
  stores) for what is a library gap: "Read-only in this version. Edit it in
  GeoServer's web UI."
- Editing a PostGIS store no longer demands the password again: leave the
  field empty to keep the stored one, type to replace it. GeoServer accepts
  its own encrypted value back (measured, a store still connected after the
  round trip), so re-typing bought nothing but friction.

### Added

- The documentation site was rebuilt: a landing page that shows the plugin,
  a modern theme with a dark mode, and pages for testing, packaging and
  documentation that describe this repository rather than the template it
  started from.
- A visual identity: the Ribbon G logo, used as the plugin's icon in the
  toolbar, menus and plugin manager, and on the documentation website.
  `docs/branding.md` explains it and links a brand kit;
  `scripts/export_branding.py` regenerates every export from one SVG.
- **Enable or disable a datastore** from its edit form. GeoServer disables
  a store itself when its connection fails at startup; this is the switch
  back (measured: a disabled PostGIS store re-enabled through the form and
  listed its tables again, every other parameter kept).
- The Styles table shows each style's **format** (SLD, CSS, MBStyle) and
  **SLD version**: what *Apply to a QGIS layer* can take is SLD only.
- **Web Feature Server (NG) datastores**, a remote WFS cascaded as a
  datastore, get a form of their own: capabilities URL, optional
  credentials, timeout, max features, lenient parsing. Its feature types then
  publish like any table (*Publish a Layer → a table in a datastore*).
- **GeoServer Manager in the layer tree's context menu**: right-click a vector
  or raster layer for *Push style to GeoServer…* (its symbology becomes the
  matching server layer's style, after a confirmation that names the target)
  and *Apply style from GeoServer…* (the server layer's style, with a picker
  when it has several). A layer loaded from the server is matched through its
  source; any other by name. Without a connection the entries are disabled and
  say so, next to an entry that opens the plugin.
- **Uploads run in the background**: publishing a layer of the project
  (vector or raster) streams the file in a QGIS task. The task bar shows the progress, the
  dialog stays usable, and *Cancel* (the Refresh button while it runs) aborts
  the transfer instead of waiting for it. The cancel message says what
  GeoServer kept: nothing for a new store; for a *Replace*, the store and its
  layer without their data file, which GeoServer removes before the upload
  ends (measured on 2.28.5). A tab switch, F5 or closing the dialog let an
  upload finish.
- **CRS checks before publishing**: a layer without a CRS is refused before
  anything is sent; a vector whose CRS has no EPSG code (GeoServer could not
  declare it) is reprojected to EPSG:4326 on export, a raster with one is
  refused, since rasters are uploaded as they are.
- **Preview** on the Layers tab: the layer on a map of its own inside QGIS,
  a WMS layer built like *Add to QGIS* builds one, but nothing reaches the
  project. Drag to pan, wheel to zoom, click for the feature info GeoServer
  returns at that point. A layer that does not load says so in place of the
  map.
- **Cascaded Stores tab**: the WMS and WMTS stores that proxy another
  server, listed across every workspace. Create one from a GetCapabilities
  URL, publish the layers the remote advertises (under the remote name or
  one of your own), inspect and delete the cascaded layers, delete the
  store; the remote server is never touched.
- **Tile Cache tab**: what GeoWebCache caches, with each layer's gridsets and
  formats. Edit a layer's cache configuration (enabled, gridsets, formats,
  meta-tiling, expiry), truncate its tiles, stop caching it, or add a layer
  whose cache was removed; GeoServer caches new layers by itself.
- **Publish a QGIS raster layer** as a coverage store: the Coverage Stores
  tab's Add form takes a raster layer of the project, writes it to a tiled,
  compressed GeoTIFF (or uploads the file as it is when it already is one)
  and uploads it; GeoServer creates the store and publishes the coverage in the
  same request. Title and abstract go on the coverage, *Replace* overwrites an
  existing store. The coverage viewer now shows a coverage's abstract rather
  than GeoServer's "Generated from …" note when both exist.
- **Preview in a browser** on the Layers and Layer Groups tabs: opens
  GeoServer's own OpenLayers page for the layer, framed on its extent. It is
  the browser's session, not the plugin's, so a secured server asks it to log
  in; the tooltip says so.
- **Legend in the style dialog**: the picture GeoServer renders for the style
  (GetLegendGraphic), fetched in the background while the dialog is open; a
  problem is explained in its place instead of a broken image.
- **Test connection** in Settings: tries the URL and credentials as typed,
  without saving them, and reports the outcome in the same words the main
  dialog uses. The URL placeholder is a plain `http://localhost:8080/geoserver`.
- **Sortable columns**: click a header to sort by it, again to reverse; the
  arrow shows the order. The sort is applied to the rows themselves, so
  *Delete Selected*, Enter and the link cells act on exactly the row that is
  highlighted, and it survives a refresh of the same tab.
- **Keyboard shortcuts**: F5 refreshes, Ctrl+F jumps to the search box, Esc
  clears the search (and still closes the dialog when there is nothing to
  clear), and Del deletes the selected resources, only while the table has the
  focus, so the same key still just erases a character in the search box. The
  shortcuts are named in the tooltips.
- **Readable on dark themes**: the connection status, the form hints and the
  invalid-field border take their colours from the widget palette instead of
  literal `red` / `green` / `gray`, which on QGIS's dark themes ranged from
  harsh to barely visible. The colours are checked against WCAG contrast in
  both themes by the tests.
- The dialog reopens on the tab it was closed on.
- **Translations work.** Every string in a tab mixin is now looked up in the
  context it is extracted under, so a translation can actually be found. Until
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
  travels unencrypted, and suggests `https://`. It saves them anyway (a
  server on a trusted network is a legitimate setup) and stays quiet for
  loopback addresses, because a warning on every local sandbox is a warning
  nobody reads.
- **Publish a QGIS layer to GeoServer.** The publish dialog on the Layers tab
  gained a source: a layer of the current project is written to a GeoPackage
  and uploaded, which makes GeoServer create the datastore and configure the
  layer, with its SRS, bounding box and attributes, in one request. Its
  symbology can travel with it as the layer's default style, the title,
  abstract and keywords are merged onto what GeoServer computed, and an
  existing layer of that name is only replaced when asked. The uploaded store
  is marked read-only, the recommended setting for a file-based store nobody
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
  writes SLD 1.1 (Symbology Encoding); sent as 1.0 (all the library can do),
  GeoServer accepts and renders it but records it as `languageVersion 1.0.0`.
  Pasted and file-based 1.1 documents were mislabelled the same way until now.
  The style dialog also shows the version GeoServer stored, and says when the
  body it displays is GeoServer's 1.0 rendition of a stored 1.1 document.
- **Workspace WMS settings**, as a second group of the workspace dialog: give a
  workspace its own WMS service or send it back to the global one, and edit the
  service title, abstract, keywords, advertised SRS list, maximum rendering time
  and errors, and default locale. Only the fields shown are sent, so everything
  else GeoServer keeps for that service (watermark, buffers, metadata links,
  interpolation) is left exactly as it was.
- **Coverage Stores tab**: every raster store across the workspaces with its
  type and how many coverages it publishes; open one for its URL, description
  and published coverages, or the *Coverages* action to read one coverage's
  SRS, native format, pixel size, bounds, keywords and bands. Create a store
  from a GeoTIFF, a COG URL, an ImageMosaic directory on the server or an
  ImageMosaic properties ZIP; *Publish a coverage* turns one into a layer;
  delete (single and bulk, recursing into the layers it published). A server
  that quietly drops the COG settings (no COG extension installed) now says
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
  from an ordered list of layers, pick them from every published layer on
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
  tab's delete handler, so Delete could act on the wrong resource.
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
