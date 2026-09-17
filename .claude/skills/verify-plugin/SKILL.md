---
name: verify-plugin
description: Run the full verification for the GeoServer Manager QGIS plugin — lint/format as pre-commit does, unit and headless QGIS tests, an end-to-end smoke against a fake GeoServer, the release zip build, and (optionally) a real QGIS load through the profile symlink. Use before every commit and whenever asked whether "everything works".
---

# Verify the plugin

Work from the repo root. Report what actually ran and what it printed — never
summarise a step you skipped as passing.

## 1. Lint and format — exactly what pre-commit will enforce

```sh
pre-commit run -a
```

No `pre-commit`? Then the same tools by hand (versions pinned in
`.pre-commit-config.yaml`: ruff 0.13.3, black 25.9.0, isort 6.1.0):

```sh
ruff format --line-length=88 --target-version=py39 geoserver_manager/ tests/ scripts/
isort --profile black geoserver_manager/ tests/ scripts/
ruff check --target-version=py39 geoserver_manager/ tests/ scripts/
black --check --target-version=py39 geoserver_manager/ tests/ scripts/
flake8 geoserver_manager --config=setup.cfg --select=E9,F63,F7,F82,QGS101,QGS102,QGS103,QGS104,QGS106
```

Known gotcha: ruff-format and black occasionally disagree on one construct; a
commit then fails with "files were modified by this hook". Re-add and commit again.

## 2. Tests

```sh
python -m pytest tests/unit                          # no QGIS needed
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python -m pytest tests/qgis    # needs QGIS python
# without pytest:
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m unittest discover -s tests/qgis -t .
```

Expect every test green. A new fix must come with a test that fails without it —
verify that claim by temporarily reverting the fix once, not by reading the test.

**Run `tests/unit` in an interpreter that has no `qgis`** (a plain venv), because
that is what the CI unit job is. Your system Python probably has QGIS installed, so
it will happily pass a test whose import chain pulls in `qgis.core` — CI won't. The
`toolbelt` package init is kept empty for exactly this reason; do not add re-exports
to it.

## 3. End-to-end smoke against a fake GeoServer

The library is imported lazily inside `_build_client`, so inject a fake module
and drive the real dialog. Template (adapt the fake's methods to the flows you touched):

```python
import sys, types, requests
from qgis.testing import start_app; start_app()
from qgis.PyQt.QtWidgets import QMessageBox
from geoserver_manager.gui.dlg_main import GeoServerMainDialog

fake = types.ModuleType("geoservercloud")
class FakeGS:
    behaviour = None
    def __init__(self, **kw): pass
    def get_workspaces(self):
        if FakeGS.behaviour == "auth":
            r = requests.Response(); r.status_code = 401
            raise requests.exceptions.HTTPError("401", response=r)
        if FakeGS.behaviour == "down": raise requests.exceptions.ConnectionError()
        if FakeGS.behaviour == "notfound": return ("<html/>", 404)
        return ([{"name": "ws1"}], 200)
    def get_version(self): return ({}, 200)
fake.GeoServerCloud = FakeGS; sys.modules["geoservercloud"] = fake

class Settings:
    geoserver_url = "http://localhost:8080/geoserver"
    def has_credentials(self): return True
    def get_credentials(self): return ("admin", "geoserver")
class Prefs:
    def get_plg_settings(self): return Settings()
    def get_value_from_key(self, *a, **k): return None
    def set_value_from_key(self, *a, **k): return True

dlg = GeoServerMainDialog(); dlg.plg_settings = Prefs()
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)  # auto-confirm deletes
for b in ("auth", "down", "notfound", None):
    FakeGS.behaviour = b; dlg.refresh_ui(); print(b, "->", dlg.lbl_status.text())
```

Check, at minimum:

| Path | Expected |
|---|---|
| 401 | status *Authentication failed* — not "unreachable" |
| connection refused | *Server unreachable* |
| 404 | *HTTP error 404* — never "Connected" |
| 200 with HTML body | *Not a GeoServer REST endpoint* — a proxy login page is not "Connected" |
| one workspace's `get_datastores` raises | rows for the others still render, exactly one warning names it |
| healthy | *Connected — <url>* |
| loader raises after `_setup_table` | `dlg._all_rows == []`, table empty, cursor restored |
| delete of N rows | N server calls, one success banner |
| Add with an existing name | no create call, "already exists" banner |

## 4. Release zip

```sh
qgis-plugin-ci package 0.1.0 --allow-uncommitted-changes
unzip -l geoserver_manager.0.1.0.zip | tail -1     # ~23 files, ~125 KB; both extras/*.whl present
rm geoserver_manager.0.1.0.zip
```

If the zip is suddenly megabytes, someone re-downloaded the upstream
`geoservercloud` wheel without stripping it — see the `release-plugin` skill.

## 5. Real QGIS (when a GUI change is involved)

Symlink `geoserver_manager/` into `~/.local/share/QGIS/QGIS3/profiles/<profile>/python/plugins/`
— **the profile QGIS actually launches**: read `profiles.ini` → `lastProfile`, or
`lsof -p <qgis pid> | grep profiles/`. Then in QGIS: Plugin Manager → Settings →
*Show also experimental plugins* → enable *GeoServer Manager*. Reload with
`plugin_reloader` after edits. If QGIS is running, do not edit its `QGIS3.ini`;
it is rewritten on exit.

## 6. CI, after pushing

```sh
gh run list --branch main --limit 6
```

Four workflows must be green: Linter (flake8 + PyQt6 checker), Tester (unit +
qgis container), Documentation, Package & Release. A `cancelled` Documentation
run alongside a newer `success` is the concurrency group, not a failure.
