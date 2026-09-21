# Testing the plugin

Two suites, split by what they need:

| Folder | Needs | What lives there |
| :----- | :---- | :--------------- |
| `tests/unit` | plain Python | the pure helpers: REST payload shapes, SLD sniffing, QGIS export naming, the metadata contract |
| `tests/qgis` | the QGIS Python (headless is fine) | the dialog and every tab, driven through `qgis.testing.start_app()` |

```bash
python -m pip install -U -r requirements/testing.txt
```

## Run them

```bash
python -m pytest tests/unit

QT_QPA_PLATFORM=offscreen python -m pytest tests/qgis
```

`QT_QPA_PLATFORM=offscreen` is what lets the widget tests run without a
display; the same variable is how CI runs them, in the `qgis/qgis:3.40`
container. Without pytest, `unittest` works just as well:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m unittest discover -s tests/qgis -t .
QT_QPA_PLATFORM=offscreen PYTHONPATH=. python3 -m unittest tests.qgis.test_dlg_main
```

Changed a user-visible string? Re-extract before running the suite, or the
translation test fails on the string the `.ts` file lacks:

```bash
python scripts/update_translations.py
```

## How the tests are written

- **A fix ships with a test that fails without it.** Run the new test against
  the old code once to prove it does, rather than trusting that it would.
- **No server is required.** A tab's fetch is a plain function returning
  `(rows, failures)`, and `dlg.gs` is assigned a fake client. Only the things a
  fake cannot show you, such as how GeoServer encrypts a stored password or
  what a partial PUT merges, are confirmed against the
  [docker sandbox](environment.md).
- **Loads are asynchronous.** A whole loader is driven through
  `tests/qgis/sync_dialog.SyncDialog`, which runs the fetch inline. The
  threading itself is tested against the real dialog, so those tests fail if a
  load ever moves back onto the GUI thread.
- Tests may import the real `geoservercloud` models, because
  `tests/qgis/conftest.py` puts the bundled wheels on `sys.path`. That is how
  the payload shapes the plugin depends on stay locked to the library.
