# GeoServer Manager — QGIS Plugin

Browse and manage GeoServer instances from inside QGIS: list, create, edit and
delete workspaces and datastores without switching to the GeoServer web admin.

Built on [`python-geoservercloud`](https://github.com/camptocamp/python-geoservercloud).

> **Status:** experimental. Workspaces and datastores are implemented; layers,
> styles and layer upload are on the [roadmap](docs/github_issue_roadmap.md).

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Imports: isort](https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336)](https://pycqa.github.io/isort/)
[![flake8](https://img.shields.io/badge/linter-flake8-green)](https://flake8.pycqa.org/)

## Features

| Resource | Supported |
| :------- | :-------- |
| Workspaces | list, search, create, rename, toggle isolation, set default, delete (single + bulk) |
| Datastores | list across all workspaces, create PostGIS / PostGIS (JNDI) / PMTiles, edit, delete (single + bulk, recursive) |
| Connection | URL + credentials, credentials encrypted in the QGIS authentication database, live connection check with GeoServer version |

Results are searchable and paginated (20 per page); the datastore list links
back to its workspace.

## Requirements

- QGIS 3.40 or newer (Qt5 or Qt6)
- Network access to a GeoServer REST API, with an account allowed to read and
  write the resources you want to manage

`geoservercloud` and `xmltodict` ship with the plugin — QGIS's Python
environment often cannot see system site-packages, so both are bundled as
wheels in `geoserver_manager/extras/` and added to `sys.path` at startup.
`owslib` and `requests` come with QGIS.

## Installation

Until the plugin is published on <https://plugins.qgis.org>:

1. Download the latest `geoserver_manager.*.zip` from the
   [releases page](https://github.com/ronitjadhav/geoserver_manager/releases).
2. In QGIS: *Plugins → Manage and Install Plugins → Install from ZIP*.

For a development install, see
[docs/development/environment.md](docs/development/environment.md).

## Configuration

*Settings → Options → GeoServer Manager*, or the plugin menu's *Settings* entry:

| Field | Example |
| :---- | :------ |
| GeoServer URL | `https://example.com/geoserver` (must start with `http://` or `https://`) |
| Username / Password | stored encrypted via `QgsAuthManager` — QGIS will ask for its master password |

Then open the plugin from the toolbar. The status line shows the connected
server and its version; connection, authentication and HTTP errors are reported
in the dialog's message bar and in the QGIS log panel (*GeoServer Manager* tab).

## Development

```sh
# see docs/development/environment.md for the full setup
python -m pip install -U -r requirements/development.txt
pre-commit install

pre-commit run -a                       # lint + format
python -m pytest tests/unit             # no QGIS needed
python -m pytest tests/qgis             # needs a QGIS Python environment
```

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and the
[contribution guide](docs/development/contribute.md).

## Documentation

Written in Markdown under `docs/`, built with Sphinx + myst-parser and
published to <https://ronitjadhav.github.io/geoserver_manager/>.

## License

Distributed under the terms of the [`GPLv2+` license](LICENSE).
