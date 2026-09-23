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
  status.

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

- **Add a Workspace:** give it a name. Optionally make it isolated or the
  default.
- **Click a name** to edit it: rename it, change isolation, make it the
  default, or give it its own WMS service settings on the *WMS* tab.

```{figure} ../static/screenshots/workspace-edit.png
:alt: The Edit Workspace form, with the name, the isolation and default checkboxes, and a WMS tab
:width: 420px

Editing a workspace.
```

GeoServer always has exactly one default workspace. So on the current default,
the box is read-only: make another workspace the default instead. Unticking
*Own WMS settings* removes them, and the workspace uses the global WMS
settings again.

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

```{figure} ../static/screenshots/datastore-add.png
:alt: The Add a Datastore form, with name, workspace, type and description, and a Connection tab
:width: 420px

The connection details go on the *Connection* tab.
```

Any other type gets a plain editor, one `key = value` per line, exactly as
GeoServer stores it.

**Click a name** to edit a store, or to enable or disable it. A few things to
know:

- A datastore cannot be renamed.
- The password field is always blank. GeoServer only returns it encrypted.
  Leave it empty to keep the stored password, or type a new one.
- Whatever the form does not show is kept as the server has it.

## Coverage stores

A coverage store holds raster data, such as a GeoTIFF.

```{figure} ../static/screenshots/coverage-stores.png
:alt: The Coverage Stores tab, listing raster stores
:width: 100%
```

**Add a Coverage Store** takes one of these sources:

- a **GeoTIFF** path on the GeoServer machine;
- a **COG** (Cloud Optimized GeoTIFF) URL;
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

Row actions: **Coverages** lists what a store contains. **Publish a coverage**
turns one of them into a layer.

## Cascaded stores

A cascaded store shows another server's WMS or WMTS layers through your
GeoServer.

```{figure} ../static/screenshots/cascaded-store-add.png
:alt: The Add a Cascaded Store form, with type, workspace, name and capabilities URL
:width: 420px

Adding a cascaded store: the remote server's GetCapabilities URL is all it needs.
```

- **Add a Cascaded Store:** pick WMS or WMTS, the workspace, a name and the
  remote GetCapabilities URL.
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
GeoServer first: spaces and accents become `_`. A layer whose CRS has no EPSG
code is reprojected to EPSG:4326 on the way.

### Row actions

| Icon | Action | What it does |
| :--- | :----- | :----------- |
| Layers with a plus | **Add to QGIS** | Load the layer as WMS, WMTS or (for a vector) WFS. The password never lands in the project file. |
| Eye | **Preview** | Show the layer on a map inside QGIS, without adding it to the project. |
| Browser with an arrow | **Preview in a browser** | Open GeoServer's own preview page on the layer's extent. |
| Brush | **Set style** | Pick the default style from the server's styles. |
| Brush with an up arrow | **Push style from QGIS** | Upload a project layer's symbology and make it the default. |
| Bin | **Delete** | Remove the layer, after confirmation. |

The first two are buttons; the rest are in the **More** menu.

```{figure} ../static/screenshots/layer-preview.png
:alt: The preview window, showing the USA states layer on a map with a feature info panel beside it
:width: 100%

**Preview**: drag to pan, scroll to zoom, click a feature for its attributes.
```

### Layer details

Click a layer's name to see its details. They are read-only here; change them
in GeoServer's web interface.

```{figure} ../static/screenshots/layer-details.png
:alt: The details of the states layer, with its native name, workspace, datastore, SRS and title
:width: 420px
```

## Layer groups

A layer group publishes several layers as one.

```{figure} ../static/screenshots/layer-groups.png
:alt: The Layer Groups tab, listing global and per-workspace groups
:width: 100%
```

**Create a Layer Group:** give it a name, title, abstract and mode. Then add
the layers in order on the *Layers* tab, each with its style. GeoServer works
out the bounds.

```{figure} ../static/screenshots/layer-group-add.png
:alt: The Create a Layer Group form, with name, workspace, mode, title and abstract
:width: 420px
```

The *Workspace* column shows `(global)` for a group that belongs to no
workspace. **Add to QGIS** loads a group as a WMS layer. The details dialog is
read-only: to change a group, delete it and create it again.

## Styles

Styles decide how GeoServer draws a layer.

```{figure} ../static/screenshots/styles.png
:alt: The Styles tab, listing styles with their format and SLD version
:width: 100%
```

**Upload a Style** takes its definition from one of three sources:

- **Paste SLD:** paste the XML.
- **From file:** an `.sld`, an `.mbstyle`, or a `.zip` with an SLD and its
  images.
- **From a QGIS layer:** the layer's symbology, exported as SLD.

**Click a name** to view the style, with the legend GeoServer draws for it.
Edit the definition on the *Style* tab and save to replace it on the server.

```{figure} ../static/screenshots/style-edit.png
:alt: The style dialog for the population style, with its format, SLD version, file and rendered legend
:width: 420px

A style, with the legend as GeoServer renders it.
```

Row actions: **Apply to a QGIS layer** puts the server's style on a project
layer. **Save to disk** saves the definition. **Delete** removes the style;
GeoServer refuses while a layer still uses it.

## Tile cache

The tile cache (GeoWebCache) stores map tiles so they are drawn only once.

```{figure} ../static/screenshots/tile-cache.png
:alt: The Tile Cache tab, listing cached layers with their gridsets and formats
:width: 100%
```

**Click a name** to change how a layer is cached: on or off, its gridsets and
its image formats. Meta-tiling, gutter and expiry are on the *Advanced* tab.

```{figure} ../static/screenshots/tile-cache-edit.png
:alt: The tile cache settings of topp:states, with the enabled checkbox, gridsets and formats
:width: 420px
```

Row actions:

- **Truncate** (the eraser) deletes the cached tiles. They are drawn again
  when someone asks for them.
- **Remove from cache** (the minus) stops caching the layer. The layer itself
  stays published.

**Add a Layer to the Cache** offers the layers and groups not cached yet.

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
