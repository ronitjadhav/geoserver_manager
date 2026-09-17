# CHANGELOG

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

### Added

- **Layer Groups tab**: the global layer groups and every workspace's, with
  mode and size; open one to see its layers in drawing order (with their
  styles and any nested group), title, abstract and bounds; create a group
  from an ordered list of layers — pick them from every published layer on
  the server, rasters included, and mix workspaces in a global group;
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
