# GeoServer Manager

**GeoServer, inside QGIS.**

Manage a GeoServer through its REST API without leaving QGIS: workspaces,
datastores, coverage stores, cascaded WMS and WMTS stores, layers, layer
groups, styles and the tile cache. Publish a table or a layer of the open
project, and bring what the server has back in as WMS, WFS or WMTS.

```{image} static/screenshot-layers.png
:alt: The Layers tab, listing a server's layers with their workspace, type, store and default style
```

::::{grid} 1 1 3 3
:gutter: 3

:::{grid-item-card} {octicon}`download;1.5em` Install
:link: usage/installation
:link-type: doc

Get the plugin into QGIS, from a release zip or from the development feed.
:::

:::{grid-item-card} {octicon}`book;1.5em` Use it
:link: usage/guide
:link-type: doc

Connect to a server, then what every tab does and what each button means.
:::

:::{grid-item-card} {octicon}`git-pull-request;1.5em` Contribute
:link: development/contribute
:link-type: doc

Set up an environment, run the tests, and find the work that is waiting.
:::

::::

## What it does

| Tab | In one line |
| :-- | :---------- |
| Workspaces | create, rename, isolate, set the default, edit the WMS service settings |
| Datastores | PostGIS, shapefiles, GeoPackage, PMTiles and cascaded WFS, created and edited across every workspace |
| Coverage stores | GeoTIFF, COG and ImageMosaic, or a raster of the open project uploaded and published in one request |
| Cascaded stores | the WMS and WMTS stores that proxy another server, with the layers they advertise |
| Layers | every layer whatever its type, published, restyled, previewed and added back to QGIS |
| Layer groups | global and per workspace, built from ordered layers with their styles |
| Styles | pasted, uploaded or made from a QGIS layer's symbology, edited beside the legend GeoServer renders |
| Tile cache | what GeoWebCache holds, its gridsets and formats, truncated or reconfigured |

Every list loads in the background, and is searchable, sortable and paginated.
Credentials live in the QGIS authentication database, never in a project file.
Every request goes through
[python-geoservercloud](https://github.com/camptocamp/python-geoservercloud):
the plugin exists partly to drive that library's maturity.

:::{note}
The plugin is experimental and not on the QGIS plugin repository yet.
See [installation](usage/installation.md) for how to get it today.
:::

## At a glance

| | |
| :-- | :-- |
| Latest released version | {{ release_version }} |
| Development version | {{ version }} |
| QGIS | {{ qgis_version_min }} to {{ qgis_version_max }}, Qt5 and Qt6 |
| Author | {{ author }} |
| Source code | {{ repo_url }} |
| Licence | GPLv2+ |
| This page built | {{ date_update }} |

```{toctree}
---
caption: Use it
maxdepth: 1
hidden:
---
Installation <usage/installation>
Using the plugin <usage/guide>
```

```{toctree}
---
caption: Develop it
maxdepth: 1
hidden:
---
Contributing <development/contribute>
Environment <development/environment>
Testing <development/testing>
Translations <development/translation>
Documentation <development/documentation>
Packaging and release <development/packaging>
Changelog <development/history>
Roadmap <github_issue_roadmap>
```

```{toctree}
---
caption: Project
maxdepth: 1
hidden:
---
Branding <branding>
Code of conduct <development/code_of_conduct>
```
