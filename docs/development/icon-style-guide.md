# Icon style guide

Use this guide when drawing or generating an interface icon for GeoServer
Manager. Start with the [icon catalogue](icon-catalog.md): reuse a symbol when
its meaning already matches. The catalogue tracks artwork and usage; this
page preserves the drawing rules and a reusable generation brief.

## Shape and weight

| Property | Rule |
| :------- | :--- |
| Canvas | `viewBox="0 0 24 24"`, with `width="24"` and `height="24"` |
| Stroke | **1.2 units**, including arrows, badges and internal details |
| Ends and corners | `stroke-linecap="round"`, `stroke-linejoin="round"` |
| Fill | `fill="none"`; a small filled dot may use a colour role |
| Display | 20 logical px in the dialog, giving a 1 px stroke |
| Small-size review | Check 16, 20 and 24 px; also check a screen at 2× scale |
| Padding | Usually keep path centres within 2–22 on both axes |
| Format | Plain SVG paths and basic shapes, with no external dependencies |

The light stroke is deliberate. Keep this weight when adding icons. Simplify
a crowded shape instead of thickening the lines or shrinking a detailed
illustration into the canvas. Use one recognisable object and, where needed,
one action marker. Leave roughly two units between unrelated strokes so
they remain separate when reduced to 16 px.

Centre the visible shape by eye. A diagonal brush or outward arrow may need
a small optical adjustment. Compare it beside existing icons at actual size,
not only at a large zoom. Give compact shapes enough area to feel as present
as the folder and layer stack. Do not add an enclosing square or circle
unless it contributes to the meaning, as it does for a browser window.

Avoid shadows, gradients, textures, embedded images, lettering, fonts,
filters and fixed white backgrounds. Do not outline strokes into filled
paths: editable strokes keep the family easy to maintain.

The **Ribbon G brand mark** is the exception to the interface grid and stroke
rules. Keep its original proportions and colours. Its source and generated
exports follow the [branding guide](../branding.md).

## Colour roles and states

Use these exact lowercase source colours. They are replacement tokens for
`geoserver_manager/gui/icons.py`, not fixed screen colours.

| SVG token | Use |
| :-------- | :-- |
| `#172f36` | Main outline and neutral detail |
| `#0099c0` | Server, connection or transfer accent |
| `#589632` | Layer, map or styling accent |
| `#b3261e` | Destructive action marker |

Start with the neutral outline and add an accent only where it helps. Follow
the nearest existing symbol when combining roles. Colour never carries the
meaning alone: an up arrow must still differ from a down arrow in monochrome.

The renderer maps neutral strokes to the widget's text colour. Accent colours
come from the catalogue's light and dark variants. Selected icons become the
highlighted text colour; disabled icons become the disabled text colour.
Pass the actual widget's palette because a sidebar can stay light inside a
dark dialog. Do not create separate light, dark or selected SVG files.

## Shared visual meanings

| Meaning | Symbol and reference ID |
| :------ | :---------------------- |
| Resource type | Folder `workspaces`, cylinder `datastores`, image `coverage-stores`, link `cascaded-stores` |
| Published content | Stack `layers`; enclosing brackets distinguish `layer-groups` |
| Add an existing server layer to QGIS | Stack with a plus, `add-to-qgis` |
| Publish on GeoServer | Stack with an up arrow, `publish-layer` |
| Inspect without adding to the project | Eye, `preview-map` |
| Open an external browser | Window with an outward arrow, `preview-browser` |
| Browse a store's contents | List, `browse-resources` |
| Choose a server style | Brush, `styles` |
| Send a style to GeoServer | Brush with an up arrow, `push-style` |
| Bring a style into QGIS | Brush with a down arrow, `apply-style` |
| Save a style on disk | Document with a down arrow, `save-style` |
| Clear tiles but keep caching configured | Tile grid with an eraser, `clear-cache` |
| Stop caching but keep the published layer | Tile grid with a minus, `remove-cache` |
| Delete a server resource | Bin, `delete` |

Reuse these component shapes from `geoserver_manager/resources/icons/` when
making a related icon. The noun distinguishes the resource and the marker
distinguishes the action. Keep transfer arrows on the right, following the
existing `push-style.svg` and `apply-style.svg`. Use a plus for adding and a
minus for removal. Keep the bin for deleting the underlying resource.

## Drawing and registering an icon

This starter uses the same attributes as the current family. Replace the
sample paths with the intended symbol; the example itself is `browse-resources`.

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
  <g fill="none" stroke="#172f36" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
    <rect x="3" y="3" width="18" height="18" rx="2"/>
    <path d="M10 7h7M10 12h7M10 17h7"/>
    <path d="M7 7h.01M7 12h.01M7 17h.01" stroke="#0099c0"/>
  </g>
</svg>
```

Save artwork as `geoserver_manager/resources/icons/<meaning>.svg`. Choose a
stable ID that describes the meaning, rather than a screen position or colour.
Add it to the `icons` object in `resources/icons/catalog.json`:

```json
"new-feature": {
  "label": "Human-readable action",
  "category": "Layers and stores",
  "purpose": "What this action does and how the symbol expresses it.",
  "status": "custom",
  "asset": "icons/new-feature.svg"
}
```

Use the registered ID in Python:

```python
from geoserver_manager.gui.icons import icon

button.setIcon(icon("new-feature", button.palette()))
```

For an action used only in a menu, pass `for_menu=True`. Qt uses its Active
icon mode for a highlighted menu item and for a hovered toolbar button. The
flag gives the menu its selection colour without making button hover icons
vanish against a light background. Leave it off for shared toolbar actions.

Navigation entries and row-action tuples take the same ID. Existing row
buttons already set their tooltip and accessible name from the action label.
For a new icon-only control, provide both. Keep labels for less familiar
concepts; an icon should help recognition rather than require memorisation.

When artwork is pending, register `status: needs-custom`, a QGIS `fallback`
filename and design `notes` before using the ID. The [catalogue workflow](icon-catalog.md)
shows that entry format. Replace the fallback when the SVG is ready.

## Reusable generation brief

Give a drawing agent the intended action, nearby references and this brief.
Replace the bracketed fields before using it.

```text
Create one original SVG interface icon for GeoServer Manager.
Action: [what the user does and what changes]
Meaning to communicate: [object plus action marker]
Distinguish it from: [nearby actions the user could confuse]
Reference SVGs: [two or three paths from resources/icons/]

Read docs/development/icon-style-guide.md and inspect the reference SVGs
and docs/static/icons/icon-catalog.html before drawing.
Use a 24 by 24 viewBox, 1.2-unit strokes, round caps and round joins.
Use no fill except a small meaningful dot. Keep path centres mostly within
2–22. Match the references' optical size and simple component shapes.
Use only the exact lowercase colour tokens from the guide.
The icon must remain understandable in monochrome and at 16, 20 and 24 px.
Use editable vector geometry. Do not produce or trace a raster image.
Avoid text, gradients, shadows, filters, decorative borders and tiny details.

Deliver the SVG, a catalogue entry with a clear purpose, and regenerated
catalogue previews. Inspect normal, selected and disabled states in light
and dark themes. Register a needs-custom fallback if artwork is unfinished.
```

## Review and update

1. Compare the new symbol beside its nearest siblings at **16, 20 and 24 px**.
   Check that arrows and small markers remain separate and recognisable.
2. Inspect **light, dark, selected and disabled** previews in the gallery.
   Check the actual QGIS control too, including selection and a theme change.
   Verify normal and 2× display scaling. Keep the clickable area unchanged.
3. Regenerate the inventory and run its checks from the repository root:

   ```sh
   python scripts/build_icon_catalog.py
   python scripts/build_icon_catalog.py --check
   python -m pytest tests/unit/test_icon_catalog.py
   QT_QPA_PLATFORM=offscreen python -m pytest tests/qgis/test_icons.py
   ```

4. Update the usage guide and changelog if a user-facing symbol changes.
   Regenerate the real dialog screenshot when the shown interface changes.
   Follow the repository's normal verification for any runtime code changes.

Edit the SVG and registry, then regenerate. Do not edit the generated inventory
or HTML by hand. If the family itself changes, update this guide, the catalogue's
`design` values, the existing artwork and the previews together.
