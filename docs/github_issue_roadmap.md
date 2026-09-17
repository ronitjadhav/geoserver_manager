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
- [ ] View/edit workspace WMS settings

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

- [ ] List coverage stores across workspaces
- [ ] Create coverage store (ImageMosaic, GeoTIFF/COG)
- [ ] Delete coverage store
- [ ] List and view coverages within a store

## Styles

- [ ] List styles (global + per-workspace)
- [ ] View SLD/CSS style definition
- [ ] Upload style from `.sld` file
- [ ] Upload style from pasted string
- [ ] Delete style
- [ ] Set default style for a layer

## Layer Groups

- [ ] List layer groups per workspace
- [ ] Create layer group (select layers, styles, mode)
- [ ] Delete layer group

## WMS / WMTS Stores (Cascaded Layers)

- [ ] Create WMS store from external capabilities URL
- [ ] Create/delete cascaded WMS layers
- [ ] Create/delete WMTS stores

## Layer Upload (QGIS → GeoServer)

- [ ] Publish selected QGIS vector layer (auto-detect format)
- [ ] Batch upload multiple layers
- [ ] Upload associated SLD style with layer
- [ ] Overwrite existing layer option
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

- [ ] Embedded OpenLayers map preview of WMS layers
- [ ] GetFeatureInfo on click

## UX & Infrastructure

- [ ] Async/threaded API calls (prevent UI freezing) — partial: the datastore
  list fans its per-store GETs out over a thread pool, but the call still
  blocks the GUI thread
- [ ] Resource list caching with TTL — partial: workspace names are cached
  until the next refresh, no TTL
- [ ] Keyboard shortcuts (F5 refresh, Del delete, Ctrl+F search)
- [ ] Dark theme support
- [ ] i18n / translation support — scaffolded but not functional: strings in
  the tab mixins are extracted under a context that is never used at runtime
- [x] Reusable resource form dialog (text, combo, checkbox, spinbox, tabs)
- [x] Persistent UI state (dialog geometry, splitter sizes)
