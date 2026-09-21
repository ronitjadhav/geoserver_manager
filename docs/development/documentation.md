# Documentation

This site is [Sphinx](https://www.sphinx-doc.org/) with the
[Furo](https://pradyunsg.me/furo/) theme, written in Markdown through the
[MyST parser](https://myst-parser.readthedocs.io/). Pages live in `docs/`,
the configuration in `docs/conf.py`.

There is no API reference generated from docstrings: the plugin cannot be
imported without QGIS, which the documentation job does not install. Every
page is written by hand, except the changelog and the code of conduct, which
are included from the repository root so they exist in one place only.

## Build it

```bash
python -m pip install -U -r requirements/documentation.txt

sphinx-build -b html -d docs/_build/cache -j auto -q docs docs/_build/html
```

Open `docs/_build/html/index.html`. While writing, let it rebuild on save:

```bash
sphinx-autobuild -b html docs/ docs/_build/html
```

Then open <http://127.0.0.1:8000>. A push to `main` builds and deploys the
site to GitHub Pages, and the same job publishes `plugins.xml`, the feed that
makes every commit installable from inside QGIS.

The build should be silent. A warning means something is broken: a link to a
page that moved, or a document no listed page points at.

## Keep it current

**Documentation is part of the change, not a follow-up.** A pull request that
changes what the user sees updates the pages that describe it, in the same
pull request:

| What changed | What to update |
| :----------- | :------------- |
| A tab, a button, a form or a message | the matching section of the [usage guide](../usage/guide.md), and `CHANGELOG.md` under *Unreleased* |
| The dialog's layout | the guide and the screenshot: `python3 scripts/capture_screenshot.py` against the [sandbox](environment.md) |
| A new resource type or tab | a section in the guide, a row in the feature table on the home page, and the roadmap ticked |
| How the plugin is installed or configured | [installation](../usage/installation.md) and the configuration section of `README.md` |
| A development step, a tool or a command | the page here that teaches it, and `CLAUDE.md` if an agent would get it wrong |
| The logo or any brand asset | `python3 scripts/export_branding.py`, never the exported files by hand |

Two conventions the whole repository follows, this site included: no em
dashes, and two short sentences in place of one long one.
