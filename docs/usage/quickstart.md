# Quick start

Five minutes from a fresh install to your first published layer.

## 1. Install the plugin

Follow [installation](installation.md). When it is done, QGIS shows the
GeoServer Manager icon in its toolbar.

## 2. Tell it where your GeoServer is

Open *Settings → Options → GeoServer Manager*. You can also use the
*Settings* entry of the plugin menu.

```{figure} ../static/screenshots/settings.png
:alt: The settings page, with fields for the base URL, username and password, a TLS checkbox and a Test connection button
:width: 560px

The settings page, inside the QGIS options.
```

1. Type the **Base URL**, for example `https://example.com/geoserver`.
2. Type the **Username** and **Password** of a GeoServer administrator.
3. Click **Test connection**. It checks the fields as typed, without saving.
4. Click **OK** to save.

The password is stored encrypted in the QGIS authentication database, never
in a project file. QGIS may ask for its master password the first time.

:::{tip}
Leave **Verify the server's TLS certificate** ticked. Untick it only for a
private or self-signed certificate that you trust.
:::

## 3. Open the dialog

Click the toolbar icon. The plugin connects in the background. The line at
the bottom turns green and reads *Connected*, with the server's version.

```{figure} ../static/screenshots/workspaces.png
:alt: The main dialog on the Workspaces tab, connected to a local GeoServer
:width: 100%

Connected. The list on the left picks what to manage.
```

If the line says something else, see
[when the connection fails](guide.md#when-the-connection-fails).

## 4. Publish a layer from your project

1. Open a project with a vector layer in it.
2. In the dialog, click **Layers**, then **Publish a Layer**.
3. Set **Source** to *A layer from this QGIS project*, then pick it under **QGIS layer**.
4. Pick the target **Workspace** and click **Publish**.

The plugin uploads the layer as a GeoPackage. GeoServer creates the store and
the layer in one go, and your QGIS symbology becomes the layer's style.

## 5. Bring it back into QGIS

Find the new layer in the list and click its **Add to QGIS** button (the
layers icon with a plus). Pick WMS, WFS or WMTS. The layer joins your project,
served by GeoServer.

That is the whole loop. The [user guide](guide.md) covers every tab.
