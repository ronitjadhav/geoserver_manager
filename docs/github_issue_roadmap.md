# Feature Roadmap — GeoServer Manager QGIS Plugin

Track all planned features for the GeoServer Manager plugin. The authoritative, up-to-date plan is the [GitHub milestones](https://github.com/ronitjadhav/geoserver_manager/milestones) (one issue per item below, plus `tech-debt` issues from the code audit); tick items here when they ship. Every feature listed is backed by the [`python-geoservercloud`](https://github.com/camptocamp/python-geoservercloud) library (v0.8.5).

---

## Connection & Settings

- [x] GeoServer URL + credential configuration (Settings page)
- [x] Encrypted credential storage via QgsAuthManager
- [x] Live connection verification on dialog open
- [x] GeoServer version display in status bar
- [ ] Multiple server profiles (save/switch connections)

## Workspaces

- [x] List all workspaces with search & pagination
- [x] Create workspace (name, isolated, set default)
- [x] Edit / rename workspace
- [x] Delete workspace (single + bulk)
- [x] View/edit workspace WMS settings

## Datastores

- [x] List all datastores across workspaces
- [x] Create PostGIS datastore
- [x] Create PostGIS (JNDI) datastore
- [x] Create PMTiles datastore
- [x] Edit datastore connection parameters
- [x] Delete datastore (single + bulk, with recurse)
- [x] Cross-navigation: click workspace name → open workspace detail

## Layers / Feature Types

- [x] List all feature types across workspaces/datastores
- [x] View feature type details (SRS, bounding box, title, keywords)
- [x] Publish a DB table as a new feature type
- [x] Delete feature type (single + bulk)

## Coverage Stores & Coverages

- [x] List coverage stores across workspaces
- [x] Create coverage store (ImageMosaic, GeoTIFF/COG)
- [x] Delete coverage store
- [x] List and view coverages within a store

## Styles

- [x] List styles (global + per-workspace)
- [x] View SLD/CSS style definition
- [x] Upload style from `.sld` file
- [x] Upload style from pasted string
- [x] Delete style
- [x] Set default style for a layer
- [x] Upload a style from a QGIS layer's symbology (Styles tab, and one click
      from the Layers tab: upload and assign)
- [x] Apply a server style to a QGIS project layer
- [x] Save a style to disk as `.sld`
- [x] Legend preview for a style (GetLegendGraphic, rendered by GeoServer)

## Layer Groups

- [x] List layer groups per workspace
- [x] Create layer group (select layers, styles, mode)
- [x] Delete layer group

## WMS / WMTS Stores (Cascaded Layers)

- [x] Create WMS store from external capabilities URL (Cascaded Stores tab,
      listed across workspaces)
- [x] Create/delete cascaded WMS layers (publish what the remote
      advertises, view one, delete one)
- [x] Create/delete WMTS stores — and their layers

## Layer Upload (QGIS → GeoServer)

- [x] Publish a QGIS vector layer — written to a GeoPackage and uploaded, which
      makes GeoServer create the store and configure the layer in one request
- [x] Publish a QGIS raster layer as a coverage store — written to a GeoTIFF
      (or sent as it is) and uploaded; GeoServer creates the store and
      publishes the coverage in one request
- [ ] Batch upload multiple layers
- [x] Upload associated SLD style with layer (and make it the layer's default)
- [x] Overwrite existing layer option
- [ ] CRS validation & auto-reprojection
- [ ] Progress bar during upload

## Load GeoServer Layer into QGIS

- [x] Add layer as WMS to QGIS project
- [x] Add layer as WFS to QGIS project
- [x] Add layer as WMTS to QGIS project

## GeoWebCache

- [ ] View GWC tile cache status for a layer
- [ ] Publish / un-publish layer to GWC
- [ ] Create custom gridsets

## User & Role Management

- [ ] List, create, update, delete users
- [ ] List, create, delete roles
- [ ] Assign / remove roles to users

## ACL Rules (GeoServer Cloud)

- [ ] View ACL data rules
- [ ] Create / delete ACL rules
- [ ] Create / delete admin rules

## Layer Preview

- [x] Preview a layer in a browser (GeoServer's OpenLayers page)
- [ ] Embedded OpenLayers map preview of WMS layers
- [ ] GetFeatureInfo on click

## UX & Infrastructure

- [x] Async/threaded API calls (prevent UI freezing) — every tab load and the
  connection probe run in a `QgsTask`, with progress and Cancel
- [x] Resource list caching with TTL — decided against. Every list is fetched
  on tab switch and Refresh, and the one cache that existed (workspace names)
  was removed because it left a stale picker behind. Refresh is the TTL
- [x] Keyboard shortcuts (F5 refresh, Del delete, Ctrl+F search, Esc clear)
- [x] Dark theme support — status and hint colours come from the palette
- [x] i18n / translation support — the tab mixins translate in their own
  context, so extraction and lookup agree; a starter French locale ships
- [x] Reusable resource form dialog (text, combo, checkbox, spinbox, tabs)
- [x] Persistent UI state (dialog geometry, splitter sizes)
