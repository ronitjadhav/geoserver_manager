# User guide

This page walks through the dialog, one tab at a time. New here? Start with
the [quick start](quickstart.md).

## The dialog

```{figure} ../static/screenshots/layers.png
:alt: The main dialog on the Layers tab, listing a server's layers with their workspace, type, store and default style
:width: 100%

The Layers tab of a connected dialog.
```

- **Left:** the list of resource types. Click one to open its tab.
- **Top:** the button that adds or publishes, *Delete Selected*, and the
  search box.
- **Middle:** the table. Every list loads in the background, so QGIS stays
  usable while it fills.
- **Right column:** the actions for each row. Frequent ones are buttons.
  The rest sit in the **More** menu (or **Actions**, when every action is in
  the menu).
- **Bottom:** page buttons, then *Refresh*, *Settings* and the connection
  status. With two or more saved profiles, a list beside the status switches
  to another server and reloads the open tab.

Working with a list:

- **Search** filters every column. Press Ctrl+F to jump there and Esc to clear.
- **Sort** by clicking a column header. Click again to reverse it.
- **Open** a resource by clicking its name, or by selecting the row and
  pressing Enter. The *Workspace* column jumps to that workspace.
- **Delete** the highlighted rows with *Delete Selected*, or the Del key.

Opening a form or a details view reads from the server first. If the server
is slow to answer, a *Waiting for GeoServer* box appears with *Cancel*. A
server that went away never freezes QGIS.

Every delete asks first and says what else goes with it. GeoServer deletes
recursively: a workspace takes its stores, layers and styles along.

## Workspaces

A workspace groups stores, layers and styles, like a folder.

```{figure} ../static/screenshots/workspaces.png
:alt: The Workspaces tab, listing the server's workspaces
:width: 100%
```

- **Add a Workspace:** give it a name, and optionally its namespace URI (the
  one WFS and GML qualify its features with; `http://name` otherwise). Make
  it isolated or the default if needed.
- **Click a name** to edit it: rename it, change its namespace URI or its
  isolation, make it the default, or give it service settings of its own on
  the *WMS*, *WFS*, *WCS* and *WMTS* tabs.

```{figure} ../static/screenshots/workspace-edit.png
:alt: The Edit Workspace form, with the name, namespace URI, isolation and default checkboxes, and WMS, WFS, WCS and WMTS tabs
:width: 420px

Editing a workspace.
```

GeoServer always has exactly one default workspace. So on the current default,
the box is read-only: make another workspace the default instead. Unticking
*Own settings* on a service's tab removes them, and the workspace uses the
global ones again. Ticked on a workspace that had none, the fields start from
the global settings, which the *Server* tab edits.

## Datastores

A datastore is where GeoServer reads vector data from: a database, or files
on the server.

```{figure} ../static/screenshots/datastores.png
:alt: The Datastores tab, listing datastores across every workspace
:width: 100%
```

**Add a Datastore** has a form for each common type:

| Type | What it connects to |
| :--- | :------------------ |
| PostGIS, PostGIS (JNDI) | a PostGIS database |
| Shapefile | one shapefile on the server |
| Directory of spatial files | a folder of shapefiles on the server |
| GeoPackage | a GeoPackage file on the server |
| PMTiles | a PMTiles archive |
| Web Feature Server (NG) | a remote WFS, whose feature types then publish like tables |
| Other... | any other type GeoServer has (Properties, CSV, Oracle...), typed by its name |

```{figure} ../static/screenshots/datastore-add.png
:alt: The Add a Datastore form, with name, workspace, type and description, and a Connection tab
:width: 420px

The connection details go on the *Connection* tab.
```

*Other...* and any type the plugin has no form for get a plain editor, one
`key = value` per line, exactly as GeoServer stores it.

**Click a name** to edit a store, or to enable or disable it. A few things to
know:

- A rename keeps its feature types, layers, layer groups and tile cache.
- The password field is always blank. GeoServer only returns it encrypted.
  Leave it empty to keep the stored password, or type a new one.
- The *Advanced* tab lists every other connection parameter (pool size,
  timeouts, Loose bbox...) as `key = value` lines. Change, add or remove a
  line there; a removed line removes the parameter.
- After a save, the plugin asks GeoServer to open the store. If it cannot (a
  wrong host, password or path), a warning says so at once, with GeoServer's
  reason.

Row action: **Reset** makes GeoServer re-read the store, after its tables or
files changed outside GeoServer.

## Coverage stores

A coverage store holds raster data, such as a GeoTIFF.

```{figure} ../static/screenshots/coverage-stores.png
:alt: The Coverage Stores tab, listing raster stores
:width: 100%
```

**Add a Coverage Store** takes one of these sources:

- a **GeoTIFF** path on the GeoServer machine;
- a **COG** (Cloud Optimized GeoTIFF) URL;
- an **ArcGrid** or a **WorldImage** (a PNG, JPEG or GIF with its world file) URL;
- an **ImageMosaic**: a folder on the server, or a properties ZIP to upload;
- **a raster layer from this QGIS project**.

```{figure} ../static/screenshots/coverage-store-add.png
:alt: The Add a Coverage Store form, with name, workspace, source type and path
:width: 420px
```

The last source uploads your raster. It is written to a compressed GeoTIFF
first, unless it already is a plain local GeoTIFF. GeoServer then creates the
store, the coverage and the layer in one request. Tick *Replace it if it
already exists* to overwrite an earlier upload. A layer without an EPSG code
is refused before anything is sent.

**Click a name** to edit a store: its name, URL, description, and whether it
is enabled. A rename keeps its coverages and layers. After a save, a warning
says so at once if GeoServer cannot read the file.

Row actions: **Coverages** lists the coverages a store publishes, with their
details. **Publish a coverage** turns one it holds but does not publish yet
into a layer. **Reset** makes GeoServer re-read the store, after its file was
replaced or a mosaic changed.

## Cascaded stores

A cascaded store shows another server's WMS or WMTS layers through your
GeoServer.

```{figure} ../static/screenshots/cascaded-store-add.png
:alt: The Add a Cascaded Store form, with name, workspace, type and GetCapabilities URL, and a Connection tab
:width: 420px

Adding a cascaded store: the remote server's GetCapabilities URL, plus
credentials on the *Connection* tab when it needs them.
```

- **Add a Cascaded Store:** give it a name, pick the workspace and WMS or
  WMTS, and paste the remote GetCapabilities URL. The *Connection* tab takes a
  user name and password for a remote that asks for them, the number of
  connections, and the timeouts.
- **Click a name** to edit a store: its URL, credentials, limits, and whether
  it is enabled. The password field is always blank: leave it empty to keep
  it, type a new one to replace it, or clear the user name and the password
  to stop authenticating. A cascaded store cannot be renamed (GeoServer
  refuses). After a save, a warning says so at once if GeoServer cannot read
  the remote capabilities.
- **Publish a layer:** pick one of the layers the remote server advertises.
  GeoServer reads its title, SRS and bounds from the remote capabilities.
- **Cascaded layers:** the layers already published from this store.

The remote server is never changed.

## Layers

Every layer on the server, whatever its type: vector, raster, cascaded WMS or
WMTS.

### Publish a layer

**Publish a Layer** has two sources:

- **A table in a datastore:** pick the workspace, datastore and table. Give
  the EPSG code of its SRS, then optionally a title, an abstract and keywords.
- **A layer from this QGIS project:** a vector is uploaded as a GeoPackage, a
  raster as a GeoTIFF. GeoServer creates the store and the layer in one go.
  A vector's QGIS symbology becomes its default style.

```{figure} ../static/screenshots/layer-publish.png
:alt: The Publish a Layer form, with source, workspace, datastore and table
:width: 420px

Publishing a table. The *Table* list only offers tables not published yet.
```

The upload runs as a QGIS task. The task bar shows its progress, and the
*Refresh* button turns into *Cancel*. The layer name is made safe for
GeoServer first: spaces and accents become `_`. A vector whose CRS has no EPSG
code is reprojected to EPSG:4326 on the way. A raster in such a CRS is refused
instead, because rasters are uploaded as they are: reproject it in QGIS first.

### Row actions

| Icon | Action | What it does |
| :--- | :----- | :----------- |
| Layers with a plus | **Add to QGIS** | Load the layer as WMS, WMTS or (for a vector) WFS. The password never lands in the project file. |
| Eye | **Preview** | Show the layer on a map inside QGIS, without adding it to the project. |
| Browser with an arrow | **Preview in a browser** | Open GeoServer's own preview page on the layer's extent. |
| Brush | **Set style** | Pick the default style, and the other styles a client may ask for. |
| Brush with an up arrow | **Push style from QGIS** | Upload a project layer's symbology and make it the default. |
| Arrow around a database | **Update from the data** | After the table gained a column or the file was replaced: GeoServer re-reads the data and recomputes the bounds. |
| Bin | **Delete** | Remove the layer, after confirmation. |

The first two are buttons; the rest are in the **More** menu.

```{figure} ../static/screenshots/layer-preview.png
:alt: The preview window, showing the USA states layer on a map with a feature info panel beside it
:width: 100%

**Preview**: drag to pan, scroll to zoom, click a feature for its attributes.
```

### Edit a layer

Click a layer's name to edit it. The first tab holds what you can change:

- **Layer name**: renaming keeps the data, and GeoServer updates the layer
  groups and the tile cache that use it. Clients that ask for the old name
  stop finding it.
- **Title**, **Abstract** and **Keywords**: what the capabilities show.
- **SRS** and **Projection policy**: changing either recomputes the bounds.
- **Enabled**: off stops GeoServer serving the layer, and keeps it.
- **Advertised**: off leaves it out of the capabilities, but it is still
  served to whoever names it.
- **CQL filter** (vector layers): only matching features are served.

*Save* sends only what you changed, so everything else the layer has stays as
it is. The *Data* tab shows the native name, store, bounds and attributes (or
a raster's size and bands).

```{figure} ../static/screenshots/layer-details.png
:alt: The edit form of the states layer, with its name, title, abstract, keywords, SRS, projection policy and the enabled and advertised flags
:width: 420px
```

A cascaded layer stays read-only: GeoServer's REST API cannot change one, so
its web interface is the place for that.

## Layer groups

A layer group publishes several layers as one.

```{figure} ../static/screenshots/layer-groups.png
:alt: The Layer Groups tab, listing global and per-workspace groups
:width: 100%
```

**Create a Layer Group:** give it a name, title, abstract and mode. Then add
the layers in order on the *Layers* tab, each with its style. A line can also
name another group, to nest it. GeoServer works out the bounds. An *Earth
Observation Tree* also needs a root layer, and its style (the layer's default
when left blank).

```{figure} ../static/screenshots/layer-group-add.png
:alt: The Create a Layer Group form, with name, workspace, mode, title and abstract
:width: 420px
```

The *Workspace* column shows `(global)` for a group that belongs to no
workspace. **Preview** shows a group on a map of its own, with feature info
on a click, and leaves the project alone. **Add to QGIS** loads it as a WMS
layer.

**Click a name** to edit a group: its mode, title, abstract, layers, order
and styles, whether it is enabled and advertised, and an Earth Observation
group's root layer. When the layers change, the plugin recomputes the group's
bounds, which GeoServer does not do on an edit. Two things GeoServer does not
allow: renaming a group, and taking an Earth Observation group out of that
mode.

```{figure} ../static/screenshots/layer-group-edit.png
:alt: Editing the tasmania layer group, its Layers tab listing the layers in drawing order with their styles
:width: 420px

One line per layer or group, bottom first; `= style` overrides a layer's own.
```

## Styles

Styles decide how GeoServer draws a layer.

```{figure} ../static/screenshots/styles.png
:alt: The Styles tab, listing styles with their format and SLD version
:width: 100%
```

**Upload a Style** takes its definition from one of three sources:

- **Paste:** paste the document, and pick its format: SLD, CSS, YSLD or
  MBStyle.
- **From file:** an `.sld`, `.css`, `.ysld`, `.mbstyle`, or a `.zip` with an
  SLD and its images.
- **From a QGIS layer:** the layer's symbology, exported as SLD.

CSS, YSLD and MBStyle need their GeoServer extension. Without it, GeoServer
refuses the style and the message says so.

**Click a name** to view the style, with the legend GeoServer draws for it.
The dialog opens on the *Definition* tab: edit it and save to replace the
style on the server. If GeoServer cannot read it, the message gives the
line and column. The *Details* tab holds its format, version and legend,
and its name: rename a style there, and the layers and groups using it keep
it.

```{figure} ../static/screenshots/style-edit.png
:alt: The style dialog for the population style, open on its SLD definition, with a Details tab beside it
:width: 420px

A style opens on its definition; the legend is on the *Details* tab.
```

Row actions:

- **Apply to a QGIS layer** puts the server's style on a project layer. A
  CSS or YSLD style arrives as GeoServer converts it to SLD.
- **Save to disk** saves the definition.
- **Copy** makes a new style from the same definition, under another name or
  in another workspace.
- **Used by** lists the layers and layer groups that use the style, before
  you edit or delete it.
- **Delete** removes the style and its file; layers that used it fall back
  to GeoServer's default style.

## Tile cache

The tile cache (GeoWebCache) stores map tiles so they are drawn only once.

```{figure} ../static/screenshots/tile-cache.png
:alt: The Tile Cache tab, listing cached layers with their gridsets and formats
:width: 100%
```

**Click a name** to change how a layer is cached: on or off, its gridsets and
its image formats. Add `= 0-12` to a gridset line to serve only those zoom
levels. Meta-tiling, gutter and expiry are on the *Advanced* tab. The
*Parameter filters* tab holds GeoWebCache's filters as XML: which STYLES,
CQL_FILTER or TIME values get a cache of their own.

```{figure} ../static/screenshots/tile-cache-edit.png
:alt: The tile cache settings of topp:states, with the enabled checkbox, gridsets and formats
:width: 420px
```

Row actions:

- **Seed or truncate…** renders the missing tiles (*Seed*), renders them all
  again (*Reseed*) or deletes them (*Truncate*), for one gridset, format and
  zoom range. On the *Advanced* tab, limit it to an area, or to one
  parameter value such as `STYLES = population`. GeoWebCache runs it in the
  background, and the task list opens.
- **Tasks** shows the layer's running tasks, refreshed every two seconds,
  with how many tiles are done. *Stop all* ends them.
- **Truncate** (the eraser) deletes all the cached tiles, in every gridset
  and format. They are drawn again when someone asks for them.
- **Remove from cache** (the minus) stops caching the layer. The layer itself
  stays published.

**Add a Layer to the Cache** offers the layers and groups not cached yet.

```{figure} ../static/screenshots/tile-cache-seed.png
:alt: The Seed or Truncate form for topp:states, with task, gridset, format, zoom levels and threads
:width: 420px

Each zoom level has four times the tiles of the one before.
```

## Server

The settings that belong to the whole GeoServer, one row each. Click a row to
change it; *Open in the web interface* opens GeoServer's own page for it.

```{figure} ../static/screenshots/server.png
:alt: The Server tab, with rows for the contact, global settings, the four services, logging and the catalog
:width: 100%
```

- **Contact:** the person, organization and address that the capabilities
  documents and GeoServer's home page show.
- **Global settings:** the proxy base URL GeoServer writes into capabilities
  when it sits behind a proxy, the character set, the number of decimals, and
  verbose output.
- **WMS, WFS, WCS, WMTS:** each service on or off, its title, abstract,
  keywords and contact lines, and for WFS the maximum features per request.
  The form also gives the capabilities URL, the address to connect QGIS to.
- **Logging:** the logging profile and the log file. *Show the log* opens the
  last 500 lines.
- **Catalog:** *Reload* reads the whole configuration from the data directory
  again, after it changed outside GeoServer. *Reset* drops the caches of
  stores, feature types and styles.

```{figure} ../static/screenshots/server-service.png
:alt: The WFS service settings, with enabled, capabilities URL, title, abstract, keywords and maximum features
:width: 420px
```

## From the layer tree

Right-click a layer in the QGIS *Layers* panel to find the
**GeoServer Manager** submenu:

- **Push style to GeoServer…** sends the layer's symbology to the matching
  server layer. You confirm the target and the style name first.
- **Apply style from GeoServer…** puts the server layer's style on the QGIS
  layer.
- **Publish to GeoServer…** opens the plugin on the Layers tab, with the
  *Publish a Layer* form set to this layer. Pick the workspace, check the
  name, and publish. The upload shows its progress there, and the new layer
  appears in the table when it lands.
- With several layers selected, the entry reads **Publish 3 layers to
  GeoServer…**. One short form asks for the workspace, *Replace* and the
  style, and lists the name each layer gets. The layers then upload one
  after another. A layer that fails is reported and skipped. *Cancel* stops
  the rest, and a closing message says what was published and what was not.
  Two layers that would get the same GeoServer name are refused before
  anything is sent: rename one in QGIS first.

For the two style entries, a layer loaded from the server is matched through
its source. Any other layer is matched by name.

## Keyboard shortcuts

| Key | Does |
| :-- | :--- |
| F5 | refresh: reconnect and reload the open tab |
| Ctrl+F | jump to the search box |
| Esc | clear the search; if it is empty, close the dialog |
| Enter | open the selected row |
| Del | delete the selected rows |
| Tab, then Enter or Space | use a row's button |

## When the connection fails

The status line at the bottom of the dialog says what went wrong:

| Status | Meaning | What to do |
| :----- | :------ | :--------- |
| Not configured | no URL or credentials saved | open *Settings* |
| Server unreachable | nothing answers at that address (after 10 s at most) | check the URL, the network, and that GeoServer runs |
| Certificate not trusted | this machine does not trust the TLS certificate | fix the certificate, or untick the check for one you trust |
| Authentication failed | GeoServer refused the username or password | check them in *Settings* |
| HTTP error *N* | something answered, but not the REST API | check the URL; it usually ends in `/geoserver` |
| Not a GeoServer REST endpoint | a web page came back, such as a proxy login | check the URL, or the proxy in front of GeoServer |

The full details go to the QGIS log panel, on the *GeoServer Manager* tab.

## Good to know

- Nothing is cached. Every tab switch and every *Refresh* fetches the list
  again.
- Deleting a store created from an upload leaves the uploaded file in
  GeoServer's data directory.
- The plugin's TLS setting does not reach QGIS's own WMS and WFS layers. A
  layer added to QGIS uses QGIS's certificate handling.
- Over plain `http://` to a remote server, the password travels unencrypted.
  The plugin warns once, when you save the settings.
- The interface follows the QGIS theme, dark ones included. A partial French
  translation exists; [contributions are welcome](../development/translation.md).
