# CHANGELOG

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## Unreleased

### Fixed

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
