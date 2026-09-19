---
name: release-plugin
description: Cut a release of the GeoServer Manager QGIS plugin, bump the version, finish the changelog, re-strip the bundled geoservercloud wheel if the library was bumped, tag, and let CI publish to GitHub Releases and plugins.qgis.org. Use for any version bump or when updating the bundled geoservercloud dependency.
---

# Release the plugin

Releases are driven by `qgis-plugin-ci` from `.github/workflows/package_and_release.yml`:
a push to `main` builds the zip; a **tag** creates the GitHub Release and publishes to
plugins.qgis.org using the `OSGEO_USER` / `OSGEO_PASSWORD` repository secrets.
No tag has been pushed yet, so the tag path has never run; the first release is a
first for the pipeline too. Watch it.

## 0. Only if `geoservercloud` is being bumped: strip the new wheel

The upstream wheel is 16 MB because it ships `geoserver_acceptance_tests/data/sampledata.tgz`
(15 MB of test fixtures the plugin never imports). The bundled copy is 49 KB. A plain
download silently reintroduces the 16 MB.

```sh
pip download geoservercloud==<v> --no-deps -d /tmp/gsc
cd /tmp/gsc && zip -d geoservercloud-<v>-py3-none-any.whl 'geoserver_acceptance_tests/*'
python3 - <<'EOF'
import zipfile, os
whl = [f for f in os.listdir(".") if f.endswith(".whl")][0]
rec = [n for n in zipfile.ZipFile(whl).namelist() if n.endswith("dist-info/RECORD")][0]
z = zipfile.ZipFile(whl); names = set(z.namelist())
kept = [l for l in z.read(rec).decode().splitlines() if l.split(",")[0] in names or not l.strip()]
z.close()
zin = zipfile.ZipFile(whl)
with zipfile.ZipFile(whl + ".tmp", "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == rec: data = ("\n".join(kept) + "\n").encode()
        zout.writestr(item, data)
zin.close(); os.replace(whl + ".tmp", whl)
EOF
ls -la *.whl        # expect tens of KB
```

Then: copy it into `geoserver_manager/extras/`, delete the old wheel, update the
filename in `toolbelt/dependencies.py` (`BUNDLED_WHLS`), and re-check every
library fact in `CLAUDE.md` (`raise_for_status` per verb, which `create_*` upsert,
which methods are still missing) against the new source; the plugin's
`_raw_rest` workarounds ride on private attributes. Verify the import path:

```sh
python3 -c "import sys; sys.path[:0]=['geoserver_manager/extras/xmltodict-1.0.4-py3-none-any.whl','geoserver_manager/extras/geoservercloud-<v>-py3-none-any.whl']; import geoservercloud; print('ok')"
```

`check-added-large-files --maxkb=500` in pre-commit will refuse an unstripped wheel.

## 1. Version and changelog

- `geoserver_manager/metadata.txt`: `version=X.Y.Z`. Leave `experimental=True` until the
  layers/styles tabs exist. `qgisMinimumVersion=3.40`.
- `CHANGELOG.md`: rename `## Unreleased` to `## X.Y.Z - YYYY-MM-DD` (Keep a Changelog format;
  `qgis-plugin-ci` reads it for the release notes and the plugin's `changelog` field).
- `docs/github_issue_roadmap.md`: tick what shipped.

## 2. Verify

Run the `verify-plugin` skill in full, including the zip build. Confirm the zip is
~125 KB with both `extras/*.whl` inside.

## 3. Commit, push, watch CI

```sh
git commit -am "chore(release): X.Y.Z"
git push origin main
gh run list --branch main --limit 4        # all four green before tagging
```

## 4. Tag

```sh
git tag -a X.Y.Z -m "X.Y.Z"
git push origin X.Y.Z
gh run watch                               # the "🚀 Release on tag" job
```

The release job downloads the compiled translations from the `translation` job,
creates the GitHub Release with generated notes, and runs
`qgis-plugin-ci release X.Y.Z --create-plugin-repo --osgeo-username … --osgeo-password …`.

## 5. After the first publish

Set the plugin ID in `docs/conf.py` (`official_repository_id`) and update
`docs/usage/installation.md`; it currently says the plugin is not yet on
plugins.qgis.org. Then close the `0.1.0 — first release` milestone (its exact
title on GitHub; the milestone name is not this repo's prose to rewrite).

## If it fails

- **Release job fails on secrets**: `OSGEO_USER` / `OSGEO_PASSWORD` must be set in the repo.
- **Zip is huge**: unstripped wheel, see step 0.
- **`qgis-plugin-ci` complains about the slug**: `setup.cfg` `[qgis-plugin-ci]`: `project_slug` /
  `github_organization_slug` must match the repo.
- **Translations job fails**: it uses `pyqt5-tools`, proven only on Python 3.9 (`PYTHON_VERSION`).
- **Packaging job fails on `pip install`**: `qgis-plugin-ci >= 2.10` needs Python ≥ 3.10; the packaging
  and release jobs use `PYTHON_VERSION_PACKAGING` (3.12) for that reason. A requirements bump merged by
  dependabot broke this once because the workflow does not run on PRs (issue #30).
