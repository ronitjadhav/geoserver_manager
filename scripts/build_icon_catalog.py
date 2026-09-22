"""Build the icon gallery and inventory. Use --check to detect stale outputs."""

import argparse
import ast
import html
import re
import sys
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoserver_manager.toolbelt.icon_catalog import (  # noqa: E402
    RESOURCES,
    SOURCE_COLOURS,
    load_catalog,
)

GALLERY = Path("docs/static/icons/icon-catalog.html")
INVENTORY = Path("docs/development/icon-catalog.md")


def scan_usage(root=ROOT):
    """Find literal icon IDs in calls, navigation and row-action declarations."""
    usages = defaultdict(set)
    problems = []
    for path in sorted((root / "geoserver_manager").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else getattr(node.func, "attr", "")
                )
                if name in {"QIcon", "getThemeIcon", "iconPath"}:
                    if relative != "geoserver_manager/gui/icons.py":
                        problems.append(
                            f"{relative}:{node.lineno}: use a catalogued icon()"
                        )
                if name == "icon" and node.args:
                    value = node.args[0]
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        usages[value.value].add(relative)
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                name = (
                    target.id
                    if isinstance(target, ast.Name)
                    else getattr(target, "attr", "")
                )
                index = 1 if name == "TABS" else 0 if name == "_row_actions" else None
                if index is None or not isinstance(node.value, (ast.Tuple, ast.List)):
                    continue
                for item in node.value.elts:
                    if (
                        isinstance(item, (ast.Tuple, ast.List))
                        and len(item.elts) > index
                    ):
                        value = item.elts[index]
                        if isinstance(value, ast.Constant) and isinstance(
                            value.value, str
                        ):
                            usages[value.value].add(relative)
    for path in sorted((root / "geoserver_manager").rglob("*.ui")):
        if ET.parse(path).findall(".//iconset"):
            problems.append(
                f"{path.relative_to(root)}: assign icons through icon(), not the .ui"
            )
    return dict(usages), problems


def validate_catalog(catalog, usages, root=ROOT):
    """Report unregistered uses, missing artwork and untracked SVGs."""
    problems = []
    entries = catalog["icons"]
    resources = root / "geoserver_manager/resources"
    for name in sorted(set(usages) - entries.keys()):
        problems.append(
            f"Unregistered icon {name!r}: {', '.join(sorted(usages[name]))}"
        )
    assets = set()
    for name, entry in entries.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
            problems.append(f"Invalid icon ID: {name!r}")
        for field in ("label", "category", "purpose"):
            if not entry.get(field):
                problems.append(f"{name}: missing {field}")
        if entry["status"] == "needs-custom":
            if not entry.get("fallback", "").endswith(".svg") or not entry.get("notes"):
                problems.append(
                    f"{name}: needs-custom requires a fallback and design notes"
                )
            if entry.get("asset"):
                problems.append(f"{name}: a pending icon must not claim custom artwork")
            continue
        if entry["status"] != "custom":
            problems.append(f"{name}: status must be custom or needs-custom")
            continue
        asset = resources / entry.get("asset", "")
        if not asset.is_file() or asset.suffix != ".svg":
            problems.append(f"{name}: missing custom SVG {asset}")
            continue
        assets.add(asset.resolve())
        try:
            svg = ET.parse(asset).getroot()
        except ET.ParseError as error:
            problems.append(f"{name}: invalid SVG: {error}")
            continue
        if entry["category"] != "Brand":
            canvas = catalog["design"]["canvas"]
            if svg.get("viewBox") != f"0 0 {canvas} {canvas}":
                problems.append(f"{name}: use the catalogue's {canvas} px canvas")
            widths = {
                float(node.attrib["stroke-width"])
                for node in svg.iter()
                if "stroke-width" in node.attrib
            }
            if widths != {catalog["design"]["stroke_width"]}:
                problems.append(
                    f"{name}: stroke widths {widths} differ from the catalogue"
                )
        for export in entry.get("exports", []):
            if not (resources / export).is_file():
                problems.append(f"{name}: missing exported asset {export}")
    for asset in (resources / "icons").glob("*.svg"):
        if asset.resolve() not in assets:
            problems.append(f"Uncatalogued SVG: {asset.relative_to(resources)}")
    return problems


def svg_markup(entry):
    if entry["status"] != "custom":
        return '<span class="pending-symbol" aria-hidden="true">?</span>'
    svg = ET.parse(RESOURCES / entry["asset"]).getroot()
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    for node in svg.iter():
        node.attrib.pop("id", None)
        node.attrib.pop("aria-labelledby", None)
    svg.set("aria-hidden", "true")
    svg.attrib.pop("role", None)
    markup = ET.tostring(svg, encoding="unicode")
    replacements = dict(
        zip(
            SOURCE_COLOURS,
            ("var(--ink)", "var(--blue)", "var(--green)", "var(--danger)"),
        )
    )
    return re.sub(
        "|".join(SOURCE_COLOURS), lambda match: replacements[match.group()], markup
    )


def render_gallery(catalog, usages):
    cards = []
    for name, entry in catalog["icons"].items():
        esc = html.escape
        status = entry["status"]
        status_text = "Custom SVG" if status == "custom" else "Needs custom artwork"
        used = (
            ", ".join(Path(path).name for path in sorted(usages.get(name, ())))
            or "Not used yet"
        )
        svg = svg_markup(entry)
        samples = "".join(
            f'<div class="sample {mode}"><div class="glyph">{svg}</div><span>{mode.title()}</span></div>'
            for mode in ("normal", "selected", "disabled")
        )
        asset = entry.get("asset", entry.get("fallback", ""))
        notes = (
            f'<p class="notes">{esc(entry["notes"])}</p>' if entry.get("notes") else ""
        )
        search = esc(
            f"{name} {entry['label']} {entry['category']} {entry['purpose']} {used}".casefold()
        )
        cards.append(
            f"""<article class="card {"brand" if entry["category"] == "Brand" else ""}" data-status="{status}" data-search="{search}">
<div class="card-top"><span class="category">{esc(entry["category"])}</span><span class="badge {status}">{status_text}</span></div>
<div class="samples">{samples}</div><h2>{esc(entry["label"])}</h2><code>{esc(name)}</code>
<p>{esc(entry["purpose"])}</p>{notes}<details><summary>Usage and source</summary><p>{esc(used)}</p><code>{esc(asset)}</code></details></article>"""
        )
    custom = sum(entry["status"] == "custom" for entry in catalog["icons"].values())
    pending = len(cards) - custom
    light, dark = catalog["accents"]["light"], catalog["accents"]["dark"]
    page = TEMPLATE.replace("{{CARDS}}", "\n".join(cards))
    for key, value in {
        "CUSTOM": custom,
        "PENDING": pending,
        "TOTAL": len(cards),
        "STROKE": catalog["design"]["stroke_width"],
        "SIZE": catalog["design"]["display_size"],
        "LIGHT_BLUE": light["blue"],
        "LIGHT_GREEN": light["green"],
        "DARK_BLUE": dark["blue"],
        "DARK_GREEN": dark["green"],
    }.items():
        page = page.replace("{{" + key + "}}", str(value))
    return page


def render_inventory(catalog, usages):
    custom = sum(entry["status"] == "custom" for entry in catalog["icons"].values())
    pending = len(catalog["icons"]) - custom
    rows = []
    for name, entry in catalog["icons"].items():
        used = (
            ", ".join(f"`{Path(path).name}`" for path in sorted(usages.get(name, ())))
            or "Not used yet"
        )
        status = "Custom" if entry["status"] == "custom" else "**Needs custom artwork**"
        label = entry["label"].replace("|", "/")
        rows.append(f"| `{name}` | {label} | {status} | {used} |")
    return (
        GUIDE.replace("{{CUSTOM}}", str(custom))
        .replace("{{PENDING}}", str(pending))
        .replace("{{ROWS}}", "\n".join(rows))
    )


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>GeoServer Manager icon catalogue</title>
<style>
:root{color-scheme:light;--bg:#f6f7f8;--surface:#fff;--text:#172f36;--muted:#60717a;--line:#dce3e7;--ink:#202020;--blue:{{LIGHT_BLUE}};--green:{{LIGHT_GREEN}};--danger:#b3261e;--highlight:#2980b9;--disabled:#999;--size:{{SIZE}}px}
body.dark{color-scheme:dark;--bg:#191d21;--surface:#23292e;--text:#eff0f1;--muted:#a7b4bc;--line:#3d4850;--ink:#eff0f1;--blue:{{DARK_BLUE}};--green:{{DARK_GREEN}};--danger:#ff8a80;--disabled:#899198}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,sans-serif}main{max-width:1240px;margin:auto;padding:36px 24px 48px}
.eyebrow{color:var(--blue);font-size:12px;font-weight:650;letter-spacing:.09em;text-transform:uppercase}h1{font-size:30px;line-height:1.2;margin:8px 0 12px;font-weight:650}header p{max-width:780px;color:var(--muted);margin:8px 0}.summary{font-size:13px;margin:18px 0 22px}.summary b{color:var(--green)}
.controls{display:flex;gap:12px;flex-wrap:wrap;align-items:end;margin-bottom:18px}label{display:grid;gap:5px;font-size:12px;color:var(--muted)}label.search{flex:1;min-width:230px}input,select,button{font:inherit;color:var(--text);background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:8px 11px}input{width:100%}button{cursor:pointer;min-height:38px}button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
#count{margin:8px 0 16px;color:var(--muted);font-size:12px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(255px,1fr));gap:16px}.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;display:flex;flex-direction:column;min-width:0}.card[hidden]{display:none}.card-top{display:flex;gap:8px;justify-content:space-between;align-items:center;min-height:32px}.category{font-size:11px;color:var(--muted)}.badge{font-size:10px;font-weight:650;white-space:nowrap;padding:3px 7px;border:1px solid var(--line);border-radius:4px}.badge.custom{color:var(--green)}.badge.needs-custom{color:var(--danger)}
.samples{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin:18px 0}.sample{display:grid;gap:7px;text-align:center;font-size:10px;color:var(--muted)}.glyph{height:52px;display:flex;align-items:center;justify-content:center;border-radius:5px;background:var(--bg)}.sample.selected .glyph{background:var(--highlight);--ink:#fff;--blue:#fff;--green:#fff;--danger:#fff}.sample.disabled .glyph{--ink:var(--disabled);--blue:var(--disabled);--green:var(--disabled);--danger:var(--disabled)}.brand .normal .glyph{--blue:#0099c0;--green:#589632}.glyph svg{width:var(--size);height:var(--size);display:block}.pending-symbol{display:grid;place-items:center;width:var(--size);height:var(--size);border:1px dashed var(--muted);color:var(--muted)}
h2{font-size:15px;line-height:1.35;margin:0 0 5px;font-weight:650}code{font:11px/1.4 ui-monospace,monospace;color:var(--muted);overflow-wrap:anywhere}.card p{font-size:12px;margin:11px 0;color:var(--muted)}details{margin-top:auto;padding-top:12px}summary{font-size:11px;cursor:pointer;color:var(--blue)}details p{font-size:11px}.notes{border-left:2px solid var(--danger);padding-left:9px}footer{margin-top:28px;font-size:12px;color:var(--muted)}#empty{padding:32px;border:1px dashed var(--line);border-radius:8px;text-align:center}
</style></head><body><main>
<header><div class="eyebrow">GeoServer Manager / design reference</div><h1>Icon catalogue</h1>
<p>One inventory for every icon the plugin supplies. Compare silhouettes at their actual display size, check theme contrast, and find artwork still needed for new features.</p>
<p class="summary"><b>{{CUSTOM}} custom</b> · {{PENDING}} need artwork · {{STROKE}}-unit strokes on a 24 px grid</p></header>
<div class="controls"><label class="search">Find an icon<input id="search" type="search" placeholder="Search by action, icon name, or file"></label>
<label>Artwork<select id="status"><option value="all">All icons</option><option value="custom">Custom SVG</option><option value="needs-custom">Needs custom artwork</option></select></label>
<label>Display size<select id="size"><option>16</option><option selected>20</option><option>24</option><option>32</option></select></label>
<button id="theme" type="button" aria-pressed="false">Dark theme</button></div>
<p id="count" aria-live="polite">{{TOTAL}} icons shown</p><section class="grid" aria-label="Icon previews">{{CARDS}}</section>
<p id="empty" hidden>No icons match these filters. All current plugin icons have custom artwork when the pending count is zero.</p>
<footer>Edit <code>geoserver_manager/resources/icons/catalog.json</code>, then run <code>python scripts/build_icon_catalog.py</code>. Palette previews use the default light and dark colours; QGIS uses each widget's own text and selection colours. The brand mark keeps its original proportions and stroke.</footer>
</main><script>
const cards = [...document.querySelectorAll('.card')];
const search = document.getElementById('search');
const status = document.getElementById('status');
function filter() {
  const query = search.value.toLowerCase().trim();
  let visible = 0;
  for (const card of cards) {
    card.hidden = !card.dataset.search.includes(query) || (status.value !== 'all' && card.dataset.status !== status.value);
    if (!card.hidden) visible++;
  }
  document.getElementById('count').textContent = `${visible} of ${cards.length} icons shown`;
  document.getElementById('empty').hidden = visible > 0;
}
search.addEventListener('input', filter);status.addEventListener('change', filter);
document.getElementById('size').addEventListener('change', event => document.body.style.setProperty('--size', `${event.target.value}px`));
const theme = document.getElementById('theme');
function setTheme(dark) {
  document.body.classList.toggle('dark', dark);theme.setAttribute('aria-pressed', String(dark));theme.textContent = dark ? 'Light theme' : 'Dark theme';
}
theme.addEventListener('click', () => setTheme(!document.body.classList.contains('dark')));
setTheme(window.matchMedia('(prefers-color-scheme: dark)').matches);
</script></body></html>
"""

GUIDE = """# Icon catalogue

This page and its gallery are generated from
`geoserver_manager/resources/icons/catalog.json` and the plugin's icon usage.
**{{CUSTOM}} icons have custom artwork; {{PENDING}} still need it.**

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
{{ROWS}}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    catalog = load_catalog()
    usages, problems = scan_usage()
    problems += validate_catalog(catalog, usages)
    if problems:
        raise SystemExit("\n".join(problems))
    outputs = {
        GALLERY: render_gallery(catalog, usages),
        INVENTORY: render_inventory(catalog, usages),
    }
    for relative, text in outputs.items():
        path = ROOT / relative
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                raise SystemExit(
                    f"Stale {relative}. Run python scripts/build_icon_catalog.py"
                )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    pending = sum(
        entry["status"] == "needs-custom" for entry in catalog["icons"].values()
    )
    print(
        f"Icon catalogue: {len(catalog['icons'])} registered, {pending} need custom artwork."
    )


if __name__ == "__main__":
    main()
