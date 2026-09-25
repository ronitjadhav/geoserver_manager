# CHANGELOG

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- **Edit coverage stores and cascaded stores** instead of going to
  GeoServer's web interface: a coverage store's name, URL, description and
  state; a cascaded store's URL, credentials, connections, timeouts and
  state. A cascaded store can be created with credentials too, so a remote
  that asks for a login can be cascaded at all.
- **A saved store is checked at once:** after a create or an edit, the
  plugin asks GeoServer to open it, and a warning gives GeoServer's reason
  when it cannot (a wrong host, password, path or URL).
- **Reset** on datastores and coverage stores makes GeoServer re-read them.
- **Preview a layer group** on a map of its own, as the Layers tab previews a
  layer, opened on the group's bounds.
- **Workspaces:** set the namespace URI, and give a workspace its own WFS,
  WCS and WMTS settings (on or off, title, abstract, keywords; WFS maximum
  features), as it already could for WMS. New own settings start from the
  global ones.
- **Server tab:** the contact details, the global settings (proxy base URL,
  character set, decimals, verbosity), each service's settings (on or off,
  title, abstract, keywords; WFS maximum features) with its capabilities URL,
  the logging profile with a view of the log's last lines, and the catalog's
  reload and reset. Each row opens GeoServer's own page for it too.
- **Seed, reseed and truncate** part of a layer's tile cache: one gridset,
  format and zoom range, optionally one area or one parameter value. A task
  list follows the progress and can stop the tasks.
- **Zoom levels and parameter filters** of a cached layer are editable: each
  gridset has a zoom range, and the filters (STYLES, CQL_FILTER, TIME...)
  are edited as GeoWebCache's XML.
- **CSS and YSLD styles** can be created, edited and copied, like SLD and
  MBStyle (each needs its GeoServer extension). *Apply to a QGIS layer*
  reads any format, through GeoServer's own conversion to SLD.
- **Rename a style**, keeping the layers and groups that use it. **Copy** a
  style under a new name or into another workspace. **Used by** lists the
  layers and groups that use a style.
- **Edit a layer group**: its mode, title, abstract, layers, order and
  styles, its enabled and advertised flags, and an Earth Observation root
  layer. Its bounds are recomputed when the layers change, since GeoServer
  keeps the old ones. A group can now nest other groups, and an Earth
  Observation group can be created (it needs a root layer).
- **Rename a datastore**: its feature types, layers, layer groups and tile
  cache follow. Its other connection parameters (pool, timeouts, Loose
  bbox...) are editable on the new *Advanced* tab.
- **Any datastore type** through *Other...*: type GeoServer's name for it and
  its parameters. ArcGrid and WorldImage coverage stores can be added too.
- **Edit a layer** instead of going to GeoServer's web interface: rename it,
  change its title, abstract, keywords, SRS and projection policy, turn it
  on or off, hide it from the capabilities, and filter it with CQL (vector
  layers). Save sends only what changed; a rename carries the layer groups
  and the tile cache along. Vector and raster layers; a cascaded layer stays
  read-only, since GeoServer's REST API cannot edit one.
- **Update from the data** (Layers tab): GeoServer re-reads the table or file
  behind a layer and recomputes its bounds.
- **Set style** also manages the other styles a layer offers to clients.
- **Server profiles.** The settings page keeps several connections (dev,
  staging, prod…), each with its own credentials in the QGIS authentication
  database. With two or more, the dialog shows a list beside its status line
  that switches server and reloads the open tab. A connection saved before
  profiles existed becomes the first profile, named after its host.
- **Publish to GeoServer…** in a layer's *GeoServer Manager* context menu.
  It opens the Publish form with that layer already chosen as the source,
  over the Layers tab where the upload reports its progress.
- Several selected layers publish in one go: **Publish 3 layers to
  GeoServer…** asks once for the workspace, *Replace* and the style, then
  uploads them one after another. A failed layer is skipped, *Cancel* stops
  the rest, and a summary names what was and was not published.
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

### Changed

- **The rest of the interface can be translated.** The tab names, a
  datastore's "Other..." type, "(global)" in the style and group forms, the
  coverage store and style formats, the catalog's Reload and Reset, file
  filters and the map preview's messages were fixed English. Delete
  confirmations and their banners are whole sentences now, so a translation
  can agree them ("supprimée" for a layer), instead of "delete" + "layer" +
  the name glued in English order. A locale the plugin has no translation
  for falls back to English's plural forms, not "layer(s)".
- **One way to say things:** edit forms are titled by what they show
  ("Datastore 'x'", no "Edit"), a store or a style is named "ws:name" in a
  confirmation, as layers are, a style's name field is "Name", formats read
  SLD, CSS, YSLD and MBStyle, a locked field has no asterisk, and a batch
  offers to "Replace those that already exist". Titles and help text follow
  QGIS's font size. A row whose details could not be read says so instead of
  "Unsupported layer type '-'".
- **Every label can be translated, and the tables read in words.** A form's
  choices ("A layer from this QGIS project", "From file", "(global)",
  "(pick a layer)", the seed task and the coverage store types) were also
  the keys the code compared, so a French interface showed them in
  English; each now has a label apart from its value. The Layers tab's
  Type column says *Vector*, *Raster*, *Cascaded WMS* or *Cascaded WMTS*
  instead of GeoServer's VECTOR or WMS. The Tile Cache names a layer
  without its workspace, which the column beside it shows. A table filters
  and sorts on what it shows.
- **A datastore's connection fields are on the form's first page,** under
  its type: on a *Connection* tab of their own, picking PostGIS meant going
  to look for them.
- **QGIS's own widgets where it has one.** A style's definition and the
  cache's parameter filters open in QGIS's code editor: line numbers,
  folding, highlighting for SLD, CSS and MBStyle. Password boxes, in the
  forms and in *Settings*, have QGIS's eye to show what was typed. File
  fields take a file dropped on them. A QGIS layer is picked from QGIS's
  layer list, with icons, and two layers of one name are two entries (a
  picker of labels had handed over the first). An SRS box has a button that
  looks the code up in QGIS's CRS picker, and still takes a code QGIS does
  not know. The area to seed is typed or taken from the map view, a layer or
  a bookmark, in the gridset's CRS, instead of four numbers in a text box.
- **Lists are edited as lists, not typed into text boxes.** A layer group's
  layers are rows picked from the server's layers and groups, each with a
  style picker, reordered with arrows; a cached layer's gridsets and formats
  are picked the same way, with the zoom range as two spinboxes. Keywords
  and the WMS SRS list use QGIS's own list editor, and connection and seed
  parameters its key and value table. The `name = style`, `= 0-12` and
  `key = value` syntaxes are gone.
- **Tabs load much faster on a large server.** A tab used to fetch every
  row's details (type, enabled, format, mode…) before showing any, one
  request per row. The names now show at once, and the details follow for
  the page on screen only: 147 styles took 158 requests, and now take 31.
- Every row action has a tooltip saying what it does, and every edit ends
  in "… saved."; layer groups are named `workspace:group` in delete
  confirmations, like layers.
- Contributor documentation now uses public instructions throughout. Removed
  private workflow references and corrected stale installation and setup guidance.

- Error banners read "HTTP 500: GeoServer's reason" instead of the
  library's "500 Server Error: for url: <the whole request URL>".
- Refusing a CSS or MBStyle style for QGIS (*Apply to a QGIS layer*) is an
  error banner now, with the same explanation, where it was a warning: the
  Styles tab and the layer tree share one SLD fetch.
- Read-only details (layers, styles, the tile cache) read as text: no input
  boxes that invite typing. A layer's abstract gets several lines, Enabled
  and Advertised say Yes or No, and the labels are in sentence case.
- The style dialog opens on its definition, in a fixed font over the whole
  width, with its format, version and legend on a *Details* tab. *Upload a
  Style* fits on one page.
- *Publish a Layer* asks for the SRS on its first tab instead of bouncing to
  *Metadata*, and hides "upload its symbology" for a raster, which ignores it.
- *Add a Coverage Store* is one page, names its first field "Name", and says
  up front when there is no workspace to put it in.
- Tables: no row numbers restarting on every page, "(global)" is no longer
  drawn as a link that goes nowhere, and a cell cut short shows its whole
  text on hover. The Workspaces *Default* column reads Yes or No.
- The settings page says which profile is active and what Save will change;
  *Remove* says it waits for Save, and warnings name their profile.
- Wording: cascaded stores say "GetCapabilities URL" everywhere, and two
  read-only dialogs no longer advise "create it again", which Add refuses.
- The documentation has a quick start, and the user guide is rewritten in
  plainer words with a screenshot of every tab and main form. The capture
  script grabs them all from the sandbox, so they stay current.

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
- A coverage store's *Enabled* reads Yes / No instead of True / False.
- Editing a PostGIS store no longer demands the password again: leave the
  field empty to keep the stored one, type to replace it. GeoServer accepts
  its own encrypted value back (measured, a store still connected after the
  round trip), so re-typing bought nothing but friction.

- The bundled `geoservercloud` wheel is stripped of its acceptance-test
  fixtures: 16 MB -> 49 KB.
- The datastore list fetches store details in parallel. Workspace names are
  fetched when a form opens to reflect changes made on the server.

### Fixed

- **A save abandoned at the waiting box holds off Refresh and the profile
  switch until it ends.** Its remaining requests read the connection, so a
  switch meanwhile sent the rest of the save to the other server.
- **An upload the server redirects is sent again in full.** The redirected
  request announced its length and sent nothing, until the server gave up.
- A warning or an error is logged without reading the settings first; every
  log line read the whole block to learn whether debug mode was on.
- **Switching to another saved profile applies its TLS setting.** Saved
  untouched, the profile connected with the previous profile's setting,
  which was then written into it.
- Editing the URL of a profile whose password could not be decrypted
  (master password declined) no longer forgets its credentials.
- **The plugin loads on a PyQt6 QGIS.** It watched a palette signal that
  PyQt6 no longer has, and failed while setting up its menu.
- A click on the toolbar button brings an open, connected dialog forward;
  it used to reconnect and reload the tab every time.
- The help menu's documentation entry and the missing-library message's
  title translate.
- Clicking the Actions header keeps the page shown; it went back to the
  first one.
- A password keeps the spaces at its edges; every text field's were
  trimmed, a password's included.
- **A PostGIS, JNDI or PMTiles store gets its workspace's namespace.** In a
  workspace with its own namespace URI, the store was created serving
  `http://{workspace}` instead.
- Forms are freed once closed; each one opened used to stay in memory for
  the whole QGIS session, its layer lists still following the project.
- **Saving a layer group's layers is faster:** the plugin reads the members'
  bounds in parallel, instead of two requests one after another per member.
- Long cells (a layer's gridsets) keep their full text on hover once the page
  fills them, and the search box is described as it works: it matches the
  columns loaded so far.
- **A refused form keeps what was typed.** A name that is taken, a layer or
  style not on the server, a zoom range with one end, filters that are not
  XML or an SRS that is not an EPSG code were refused after the form
  closed: a whole PostGIS form, its password included, had to be typed
  again. They are checked on Save, and the form stays open with the reason.
- **Enter in a list's picker adds the name**, and no longer saves the form.
  Enter in the search box goes to the results instead of opening the Add
  form.
- **Scrolling a form no longer changes its fields:** the wheel changed a
  combo or a spin box the cursor passed over (a layer's projection policy,
  which Save then sent).
- **Fields shown after a type switch are not cut off** at the right (a
  datastore's WFS or Other..., a coverage store's ImageMosaic ZIP).
- **Esc or Cancel asks before throwing an edit away**, and a form opens with
  the cursor in its first field.
- Parameter names are no longer cut off in key/value tables. *Push style
  from QGIS* picks no layer when none matches, instead of an unrelated one.
  *Truncate* from the seed form asks first, like the row action. The seed
  area's help gives the order QGIS reads a typed area in. The Settings page
  no longer overlaps at its minimum height, and Tab starts at the profile.
- **The dialog opened from the layer tree dropped every result.** Closed
  once, then reopened by *Publish to GeoServer*, it never drew its table,
  skipped the upload's title, keywords and style, and stopped a batch after
  its first layer.
- **Cancel acts at once.** It waited for a hung request to return, up to two
  minutes. A load cancelled from QGIS's task bar says so, instead of an
  empty table reading "Nothing here yet".
- **A save no longer freezes QGIS:** starting, stopping or truncating a
  seed, saving or adding a cached layer, uploading or copying a style and
  publishing a cascaded layer or a coverage ran on the interface thread.
  A save whose waiting box was cancelled says it may still be applied, and
  the tab reloads once GeoServer answers.
- **Paging or sorting during a Refresh** no longer marks healthy rows as
  failed, and Cancel on a sort by a detail column stops its requests.
- **A sign-in page mid-session** (an expired SSO session) is named as such,
  not shown as raw markup or "Expecting value: line 1 column 1".
- A sort by a detail column is dropped after a reload, instead of an arrow
  on a column that sorts nothing.
- **Editing a datastore no longer breaks it.** An empty connection parameter
  (a PostGIS store's "Session startup SQL", say) was saved as the text
  "None", which GeoServer then ran on every connection, and the store
  stopped loading. A parameter left as it was is now sent back exactly as
  stored.
- **An empty row is not saved.** A keyword row added and left empty was
  saved as "NULL", and a seed parameter with no value was sent as "None".
- **A layer's CQL filter shows in its edit form, and can be cleared.** It
  opened empty, so a filtered layer looked unfiltered.
- **A publish whose data landed says so** when its title, keywords or style
  could not be set, instead of "Failed to publish" (a retry then said the
  store exists).
- **A stored number beyond a field's range is kept:** 200 cascaded
  connections were saved back as 128 by an unrelated edit.
- **A name picked but not added stops Save** with a message, instead of
  being dropped. A gridset, format or style cannot be listed twice; a second
  gridset row was dropped with its zoom range.
- **Forms resize properly.** A form that is too tall for the screen, or a
  dialog made smaller, now scrolls. Before, the help text overlapped the
  next field, and a tall form could not shrink to fit a laptop screen. A
  bigger dialog now gives the extra height to its tables and lists, not to
  a blank area below them. A datastore form no longer opens on a blank
  band left by the other types' hidden fields. A long layer or
  style name no longer widens the whole form. At the window's minimum
  width, the tab list on the left no longer gets a horizontal scroll bar.
- A save that did its first step and failed a later one (a workspace
  created but its namespace URI refused, a datastore renamed but not saved, a
  cascaded store created without its credentials) now says what was saved,
  as a warning, and reloads the table. It used to say only "Failed", and a
  retry met "already exists".
- Clearing a Shapefile's charset, or a workspace's namespace URI (back to
  `http://name`), now takes effect.
- Copy and Save to disk keep an SLD 1.1 style as it is stored, not as its
  1.0 rendition.
- Renaming a style to a taken name is refused before the new body is saved.
- An SLD file in another encoding than UTF-8 uploads as it is.
- *Used by* lists a layer group it cannot read instead of failing whole.
- A translated layer group title or abstract stays read-only in its form, so
  a save no longer flattens it into every language.
- A workspace layer group refuses another workspace's layer before GeoServer
  answers with a bare error; its picker offers only its own.
- One workspace whose groups cannot be listed no longer breaks creating and
  editing every layer group.
- Pushing the style of a layer removed from the project meanwhile is an error
  banner, not a Python traceback.
- A failed symbology export no longer leaves the temporary GeoPackage behind.
- A bad GetCapabilities URL keeps the form open with the reason.
- Secret-looking connection parameters (access keys, account keys, tokens)
  are masked under *Other parameters*.
- A stored "Decimals" of 0 no longer shows as 8, and a log file outside the
  data directory is said, not requested.
- The plugin zip no longer carries the translation sources, a third of its
  installed size: QGIS reads only the compiled files.
- The seed task list updates on a slow server too: it asked again every
  2 seconds and dropped each answer that took longer, and a dead server
  collected a new pending request each time. *Stop all* now says it worked.
- A Cancel pressed just after an upload completed no longer reports it
  cancelled, with a false "data file removed" warning.
- An upload that finishes after the dialog was closed says in the QGIS log
  which of its last steps were not applied.
- A cancelled delete batch still reports the deletes that failed before it.
- Cancelling the connection check says "Not connected" instead of staying on
  "Connecting…" with the old rows; a delete that ends during a Refresh no
  longer cancels the check.
- A failed load no longer leaves a "Resources loaded." banner for later.
- Saving a workspace, a datastore, a cascaded store, a coverage store or a
  layer group, publishing, and pushing a style no longer freeze QGIS when the
  server stops answering: their requests run off the GUI thread, with Cancel.
- QGIS's task bar no longer labels running work "Failed to …".
- A profile switch or a Refresh while a delete batch or an upload ran sent
  the rest of it to the other server. The connection now waits, and says so.
- A resource whose name holds `/`, `?`, `#` or `%` (made outside the plugin)
  could not be addressed: deleting "a#b" deleted "a", and its edit form showed
  "a". Such rows are now refused with a reason.
- Pressing OK in QGIS Options after dismissing the master password prompt no
  longer deletes the stored GeoServer credentials.
- Publishing a layer whose name another store's layer already had styled
  that other layer and reported success; with Replace over a PostGIS store,
  GeoServer tried to import the file into the database. Both are refused.
- A layer with exactly one other style showed it as "name" and "href", so
  Set style could not save, and the layer tree never offered that style.
- An untouched save no longer rewrites what the form could not show: a
  parametrised PostGIS port, a custom logging profile, meta-tiles or a gutter
  beyond the spinbox range. A workspace's new own WMS settings start from the
  global ones.
- The cascaded WMS store form shows the stored user and limits, so
  authentication can be removed.
- A style GeoServer refuses is no longer left behind empty, blocking a retry.
- A long value in a form (a title, a URL) opens at its beginning, not
  scrolled to its end.
- An error GeoServer reports on its HTML error page now shows GeoServer's
  reason ("Invalid style: … (line 1, column 18)") instead of only the
  page's title, which says nothing more than the status code.
- The row *Actions* button is no longer clipped to its column header's width
  in QGIS.
- *Publish a Layer* from a table works for any EPSG code, and the layer gets
  its real extent. It used to fail before sending anything for every code but
  2056, 4326 and 3857 (a table in EPSG:25832, say), and gave those three a
  world bounding box. GeoServer now computes both boxes from the data.
- A batch delete is no longer stopped half way, without a word, by a tab
  switch or F5. Deletes run on their own, Cancel still stops them, and the
  table reloads only if you are still on the tab they started from.
- *Push style* and *Apply style* in the layer tree read from the server in
  the background, with Cancel, instead of freezing QGIS against a dead
  server. Their warnings and errors now stay until closed.
- Server profiles: naming a first connection with *Add…* keeps what was
  typed; removing another profile no longer switches the active one; *Reset*
  asks before deleting every profile's stored password.
- Publishing a QGIS raster keeps the keywords typed in the form.
- Clearing a datastore's description clears it; it used to stay as it was.
- A coverage store whose details cannot be read keeps its row, so it can
  still be deleted. A raster layer's details say Yes or No, not True or
  False, and a failed coverage load no longer shows "Enabled: Yes".
- *Add a Layer to the Cache* offers a workspace's own layer groups too.
- A layer-group name with `#` or `?` is quoted in its workspace path, so it
  cannot reach another group.
- The toolbar button explains again why the plugin cannot start when its
  library failed to load, instead of doing nothing.
- The status under the table says "Uploading…" or "Working…" while only an
  upload or a delete is still running, instead of "Loading…".
- Counts read naturally: "3 workspaces deleted" instead of "3 workspace(s)
  deleted", in the delete confirmations, their result banners and the
  "could not be listed" warning. Each locale gets its own plural forms,
  French included. A failed batch delete now says "Could not delete:",
  followed by each item and its reason.
- Opening a form, a detail view, a preview or *Add to QGIS* no longer
  freezes QGIS when the server is slow or gone. Each of those reads now runs
  in a worker thread. After 0.3 s a *Waiting for GeoServer* box appears, and
  its *Cancel* works; before, QGIS hung for up to the library's 120 s
  timeout. The Publish form's datastore and table pickers work the same way.
- A form whose description or help text wraps opens tall enough to show it.
  On a high-DPI screen the rows were squeezed and the help text cut off.
- The style dialog shows the whole legend. It arrives after the dialog opens,
  and only its first row used to fit.
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
- Delete confirmations now state what the cascade takes with it (both delete
  paths send `recurse=true`).
- The first, blocking connection attempt no longer runs before the window is on
  screen, which made an unreachable host look like a hung QGIS.

- Bulk delete now uses the sorted row cache, so it acts on the selected resources
  after sorting or pagination.
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

## 0.1.0 - 2026-03-27

- First release
- Generated with the [QGIS Plugins templater](https://oslandia.gitlab.io/qgis/template-qgis-plugin/)
- Placeholder, never released: packaging needs one version here. The first
  real release will replace this entry.
