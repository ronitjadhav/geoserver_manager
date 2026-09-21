"""Capture a screenshot of the main dialog, connected to the local sandbox.

Start the sandbox first, so the shot shows GeoServer's demo data:

    docker compose up -d
    QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 python3 scripts/capture_screenshot.py

The dialog is grabbed off screen, so nothing else on the desktop lands in the
image and the result is the same on every machine. `QT_SCALE_FACTOR=2` renders
it at twice the size, which stays sharp on a high-resolution display. The PNG
is reduced to 256 colours afterwards: a flat interface looks the same and the
file stays under pre-commit's 500 KB ceiling.

Loads run in a task in the real dialog, so this uses the tests' `SyncDialog`,
which runs the same fetch on the calling thread. The widget is the real one.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "docs/static/screenshot-layers.png"
DEFAULT_URL = "http://localhost:8080/geoserver"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="geoserver")
    parser.add_argument("--tab", type=int, default=4, help="index in TABS, 4 = Layers")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    return parser.parse_args()


def main():
    args = parse_args()

    from qgis.testing import start_app

    app = start_app()

    from geoserver_manager.toolbelt.dependencies import ensure_dependencies

    ensure_dependencies()

    from geoserver_manager.toolbelt.preferences import PlgSettingsStructure
    from tests.qgis.sync_dialog import SyncDialog

    class ScreenshotDialog(SyncDialog):
        """The real dialog, with the credentials passed in rather than stored."""

        def _build_client(self, settings):
            from geoservercloud import GeoServerCloud

            return GeoServerCloud(url=args.url, user=args.user, password=args.password)

    dialog = ScreenshotDialog()
    dialog.plg_settings.get_plg_settings = lambda: PlgSettingsStructure(
        geoserver_url=args.url, geoserver_auth_cfg_id="screenshot"
    )
    dialog.resize(args.width, args.height)
    dialog.show()
    app.processEvents()
    dialog.refresh_ui()
    dialog.navList.setCurrentRow(args.tab)
    for _ in range(5):
        app.processEvents()

    if dialog.gs is None:
        raise SystemExit(f"Not connected to {args.url}. Is the sandbox running?")
    print(f"{dialog.lbl_status.text()}, {len(dialog._all_rows)} rows")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    dialog.grab().save(str(args.output))

    from PIL import Image

    with Image.open(args.output) as shot:
        flat = shot.convert("RGB").quantize(colors=256, dither=Image.NONE)
        flat.save(args.output, optimize=True)
    print(f"{args.output} ({args.output.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
