# Icon catalogue

This page and its gallery are generated from
`geoserver_manager/resources/icons/catalog.json` and the plugin's icon usage.
**24 icons have custom artwork; 0 still need it.**

Before drawing or generating artwork, read the [icon style guide](icon-style-guide.md).
It holds the drawing rules, shared symbols, SVG starter and generation brief.

```{raw} html
<iframe src="../_static/icon-catalog.html" title="Interactive icon catalogue" style="width:100%;height:850px;border:0" loading="lazy"></iframe>
```

The gallery filters by purpose, source file and artwork status. Switch between
light and dark previews, or inspect the same glyph at 16, 20, 24 and 32 px.
Each card shows normal, selected and disabled states. The gallery also works
as a standalone file at `docs/static/icons/icon-catalog.html`.

## Adding an icon with a feature

1. Reuse an existing ID when its meaning matches. Pass that ID to `icon()`,
   the navigation registry or the row-action tuple. Do not call `QIcon`,
   `getThemeIcon` or `iconPath` directly outside the shared renderer.
2. For a new meaning, add an entry to `resources/icons/catalog.json` with a
   stable ID, label, category and purpose. Add the SVG under `resources/icons/`
   and set `status` to `custom` with its resource-relative `asset` path.
3. If artwork is not ready, register it immediately as `needs-custom` with a
   QGIS `fallback` filename and `notes` describing the intended symbol. Omit
   `asset`. It stays visible in the gallery's **Needs custom artwork** filter.
4. Follow the [icon style guide](icon-style-guide.md) when drawing the SVG.
   Keep a visible label or a clear tooltip and accessible name. The existing
   brand mark keeps its original proportions and stroke.
5. Regenerate this inventory and the gallery, then inspect the new icon at
   16, 20 and 24 px in light and dark themes and in selected and disabled states:

   ```sh
   python scripts/build_icon_catalog.py
   python scripts/build_icon_catalog.py --check
   ```

The unit suite checks for unregistered uses, direct QGIS icon lookups, missing
assets, untracked SVGs, inconsistent stroke widths and stale generated files.
A registered fallback is allowed and remains explicitly marked as unfinished.
Qt's own message-box symbols, checkboxes, disclosure arrows and window controls
belong to QGIS or the platform and are outside this plugin icon inventory.

A temporary entry looks like this:

```json
"new-feature": {
  "label": "New feature",
  "category": "Utilities",
  "purpose": "Describe the action and the intended visual metaphor.",
  "status": "needs-custom",
  "fallback": "mActionHelpContents.svg",
  "notes": "Replace the temporary help symbol with artwork for this action."
}
```

When the SVG is ready, change the status to `custom`, add its `asset` path,
remove `fallback` and `notes`, then regenerate. Never leave an unrecorded
stock icon in a new feature.

## Inventory

Usage is collected from the source code when this page is regenerated.

| ID | Meaning | Artwork | Used in |
| :-- | :------ | :------ | :------ |
| `plugin` | GeoServer Manager | Custom | `dlg_settings.py`, `layer_tree.py`, `plugin_main.py` |
| `workspaces` | Workspaces | Custom | `dlg_main.py` |
| `datastores` | Datastores | Custom | `dlg_main.py` |
| `coverage-stores` | Coverage stores | Custom | `dlg_main.py` |
| `cascaded-stores` | Cascaded stores | Custom | `dlg_main.py` |
| `layers` | Layers | Custom | `dlg_main.py` |
| `layer-groups` | Layer groups | Custom | `dlg_main.py` |
| `styles` | Styles / set style | Custom | `dlg_main.py`, `tab_layers.py` |
| `tile-cache` | Tile cache | Custom | `dlg_main.py` |
| `add-to-qgis` | Add to QGIS | Custom | `tab_layergroups.py`, `tab_layers.py` |
| `preview-map` | Preview in QGIS | Custom | `tab_layers.py` |
| `preview-browser` | Preview in browser | Custom | `tab_layergroups.py`, `tab_layers.py` |
| `browse-resources` | Browse store contents | Custom | `tab_cascaded.py`, `tab_coveragestores.py` |
| `publish-layer` | Publish a layer | Custom | `tab_cascaded.py`, `tab_coveragestores.py` |
| `push-style` | Push style to GeoServer | Custom | `layer_tree.py`, `tab_layers.py` |
| `apply-style` | Apply style to QGIS | Custom | `layer_tree.py`, `tab_styles.py` |
| `save-style` | Save style to disk | Custom | `tab_styles.py` |
| `clear-cache` | Truncate cached tiles | Custom | `tab_gwc.py` |
| `remove-cache` | Stop caching | Custom | `tab_gwc.py` |
| `delete` | Delete resource | Custom | `tab_cascaded.py`, `tab_coveragestores.py`, `tab_datastores.py`, `tab_layergroups.py`, `tab_layers.py`, `tab_styles.py`, `tab_workspaces.py` |
| `settings` | Settings | Custom | `plugin_main.py` |
| `help` | Help | Custom | `dlg_settings.py`, `plugin_main.py` |
| `report-issue` | Report an issue | Custom | `dlg_settings.py` |
| `reset-settings` | Reset settings | Custom | `dlg_settings.py` |
