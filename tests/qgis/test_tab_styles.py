#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    python -m unittest tests.qgis.test_tab_styles
"""

# standard library
from unittest.mock import patch

from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui import tab_styles
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.scope import GLOBAL
from geoserver_manager.gui.tab_styles import StyleTabMixin
from geoserver_manager.toolbelt.sld import SLD_1_1, layer_to_sld
from tests.qgis.sync_dialog import SyncDialog
from tests.qgis.test_sld import point_layer

start_app()

SLD = '<?xml version="1.0"?><StyledLayerDescriptor version="1.0.0"/>'

# ############################################################################
# ########## Fakes ###############
# ################################


class FakeGS:
    """Two global styles, one workspace with one style; a REST client that records."""

    _NONE = object()  # None is the *global* scope, so it cannot mean "nothing broken"

    def __init__(self, broken_workspace=_NONE):
        self.broken_workspace = broken_workspace
        self.calls = []
        outer = self

        class Response:
            status_code = 200
            content = SLD.encode()

            def json(inner):
                return {}

        class Client:
            def get(inner, path, **kwargs):
                outer.calls.append(("GET", path, kwargs))
                return Response()

            def put(inner, path, **kwargs):
                outer.calls.append(("PUT", path, kwargs))
                return Response()

            def delete(inner, path, **kwargs):
                outer.calls.append(("DELETE", path, kwargs))
                return Response()

        class Endpoints:
            def style(inner, name, workspace_name=None, format="json"):
                base = (
                    f"/rest/workspaces/{workspace_name}/styles/{name}"
                    if workspace_name
                    else f"/rest/styles/{name}"
                )
                return f"{base}.{format}"

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

            def create_style(inner, name, body, workspace_name=None, format="sld"):
                outer.calls.append(("PUT-body", name, workspace_name, format, body))
                return ("", 200)

        self.rest_service = Rest()

    def get_workspaces(self):
        return ([{"name": "topp"}, {"name": "empty"}], 200)

    def get_styles(self, workspace_name=None):
        if workspace_name == self.broken_workspace:
            raise RuntimeError("HTTP 500: boom")
        if workspace_name is None:
            return ([{"name": "population"}, {"name": "generic"}], 200)
        if workspace_name == "topp":
            return ([{"name": "roads_style"}], 200)
        return ([], 200)

    def get_style_definition(self, name, workspace_name=None):
        # Names that do not exist on this server yet.
        if name == "brand_new" or name.startswith("new_"):
            return ("<html>Not Found</html>", 404)
        fmt = "css" if name == "generic" else "sld"
        version = {"version": "1.1.0"} if name == "from_qgis" else {"version": "1.0.0"}
        return (
            {
                "name": name,
                "format": fmt,
                "filename": "popshade.sld",
                "languageVersion": version,
            },
            200,
        )

    def create_style_definition(self, name, filename, workspace_name=None):
        self.calls.append(("definition", name, filename, workspace_name))
        return ("", 201)

    def create_style_from_string(self, name, sld, workspace_name=None):
        self.calls.append(("from_string", name, workspace_name, sld))
        return ("", 201)

    def create_style_from_file(self, name, path, workspace_name=None):
        self.calls.append(("from_file", name, workspace_name, path))
        return ("", 201)


class Recording(ResourceFormDialog):
    opened = []

    def exec(self):
        Recording.opened.append(self)
        return QDialog.DialogCode.Rejected


# ############################################################################
# ########## Tests ###############
# ################################


class TestStylesTab(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.warnings = []
        self.dlg.show_warning_message = self.warnings.append
        self.dlg.show_error_message = lambda t: self.fail(f"unexpected error: {t}")
        self.dlg.show_success_message = lambda t: None
        Recording.opened.clear()

    def test_registered(self):
        loaders = {label: loader for label, _icon, loader in self.dlg.TABS}
        self.assertEqual(loaders["Styles"], "_load_styles")

    def test_lists_global_and_workspace_styles(self):
        self.dlg._load_styles()
        self.assertEqual(
            self.dlg._all_rows,
            [["population", GLOBAL], ["generic", GLOBAL], ["roads_style", "topp"]],
        )
        self.assertEqual(self.warnings, [])

    def test_one_unreadable_workspace_keeps_the_rest(self):
        self.dlg.gs = FakeGS(broken_workspace="topp")
        self.dlg._load_styles()
        self.assertEqual([r[0] for r in self.dlg._all_rows], ["population", "generic"])
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("topp", self.warnings[0])

    def test_scope_maps_the_global_label_to_none(self):
        self.assertIsNone(self.dlg._scope(GLOBAL))
        self.assertIsNone(self.dlg._scope(""))
        self.assertEqual(self.dlg._scope("topp"), "topp")

    def test_body_is_fetched_in_the_definitions_own_format(self):
        body = self.dlg._style_body("generic", None, "css")
        self.assertEqual(body, SLD)
        verb, path, _ = self.dlg.gs.calls[-1]
        self.assertEqual((verb, path), ("GET", "/rest/styles/generic.css"))

    def test_sld_dialog_is_editable_and_saves_only_the_body(self):
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._show_style_info(["population", GLOBAL])
        form = Recording.opened[0]
        self.assertFalse(form.get_widget("body").isReadOnly())
        self.assertEqual(form.get_widget("format").text(), "sld")
        self.assertEqual(form.get_widget("filename").text(), "popshade.sld")
        self.assertFalse(
            form._button_box.button(QDialogButtonBox.StandardButton.Ok).isHidden()
        )

        self.dlg._save_style_body("population", None, "sld", "<sld/>")
        self.assertEqual(
            self.dlg.gs.calls[-1], ("PUT-body", "population", None, "sld", b"<sld/>")
        )

    def test_css_dialog_is_read_only(self):
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._show_style_info(["generic", GLOBAL])
        form = Recording.opened[0]
        self.assertTrue(form.get_widget("body").isReadOnly())
        self.assertTrue(
            form._button_box.button(QDialogButtonBox.StandardButton.Ok).isHidden()
        )

    def test_upload_from_a_string_sends_the_body_with_its_own_content_type(self):
        self.dlg._create_style_from_values(
            {
                "name": "brand_new",
                "workspace": GLOBAL,
                "source": "Paste SLD",
                "sld": SLD,
            }
        )
        # the definition first, then the body — not create_style_from_string,
        # which would force the SLD 1.0 content type on any document
        self.assertEqual(
            self.dlg.gs.calls[0], ("definition", "brand_new", "brand_new.sld", None)
        )
        self.assertEqual(
            self.dlg.gs.calls[1],
            ("PUT-body", "brand_new", None, "sld", SLD.encode()),
        )
        self.assertFalse(any(c[0] == "from_string" for c in self.dlg.gs.calls))

    def test_upload_from_an_sld_file_reads_it_and_takes_the_same_path(self):
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".sld", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(SLD)
            path = handle.name
        self.dlg._create_style_from_values(
            {
                "name": "brand_new",
                "workspace": "topp",
                "source": "From file",
                "file": path,
            }
        )
        self.assertEqual(
            self.dlg.gs.calls[-1],
            ("PUT-body", "brand_new", "topp", "sld", SLD.encode()),
        )
        self.assertFalse(any(c[0] == "from_file" for c in self.dlg.gs.calls))

    def test_a_zip_or_mbstyle_file_still_goes_through_the_library(self):
        # Those are not SLD documents: the library packs and posts them.
        self.dlg._create_style_from_values(
            {
                "name": "brand_new",
                "workspace": "topp",
                "source": "From file",
                "file": "/tmp/bundle.zip",
            }
        )
        self.assertEqual(
            self.dlg.gs.calls[-1], ("from_file", "brand_new", "topp", "/tmp/bundle.zip")
        )

    def test_upload_refuses_an_existing_style(self):
        with self.assertRaises(ValueError):
            self.dlg._create_style_from_values(
                {
                    "name": "population",
                    "workspace": GLOBAL,
                    "source": "Paste SLD",
                    "sld": SLD,
                }
            )
        self.assertFalse(any(c[0].startswith("from_") for c in self.dlg.gs.calls))

    def test_upload_dialog_switches_between_paste_and_file(self):
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._add_style()
        form = Recording.opened[0]
        self.assertNotIn("sld", form._hidden_keys)
        self.assertIn("file", form._hidden_keys)
        form.get_widget("source").setCurrentText("From file")
        self.assertIn("sld", form._hidden_keys)
        self.assertNotIn("file", form._hidden_keys)
        self.assertEqual(
            [form.get_widget("workspace").itemText(i) for i in range(3)],
            [GLOBAL, "topp", "empty"],
        )

    def test_delete_purges_and_recurses(self):
        self.dlg._confirm_delete = lambda kind, labels, cascade="": True
        self.dlg._delete_selected_styles([["roads_style", "topp"], ["generic", GLOBAL]])
        deletes = [c for c in self.dlg.gs.calls if c[0] == "DELETE"]
        self.assertEqual(
            [(path, kw["params"]) for _, path, kw in deletes],
            [
                (
                    "/rest/workspaces/topp/styles/roads_style.json",
                    {"purge": "true", "recurse": "true"},
                ),
                ("/rest/styles/generic.json", {"purge": "true", "recurse": "true"}),
            ],
        )


class TestFileField(unittest.TestCase):
    """The form dialog's new 'file' type: a path edit plus Browse."""

    def test_round_trips_a_path_and_can_be_required(self):
        dlg = ResourceFormDialog(
            title="t",
            fields=[{"key": "file", "label": "File", "type": "file", "required": True}],
        )
        dlg.show()
        dlg._on_accept()
        self.assertFalse(dlg.result())  # empty + required -> blocked
        dlg.get_widget("file").path_edit.setText("/tmp/a.sld")
        self.assertEqual(dlg.get_values()["file"], "/tmp/a.sld")
        dlg._on_accept()
        self.assertTrue(dlg.result())


# ############################################################################
# ##### QGIS <-> GeoServer #######
# ################################

# QGIS writes 1.1; GeoServer's own styles are 1.0.
SLD_11 = (
    '<?xml version="1.0"?><StyledLayerDescriptor xmlns:se="http://www.opengis.net/se"'
    ' version="1.1.0"><NamedLayer/></StyledLayerDescriptor>'
)


class TestStoredVersionIsVisible(unittest.TestCase):
    """A 1.1 style is served as its 1.0 rendition — the dialog says so."""

    def setUp(self):
        Recording.opened.clear()
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")

    def test_the_version_is_read_from_the_definition(self):
        self.assertEqual(
            StyleTabMixin._language_version({"languageVersion": {"version": "1.1.0"}}),
            "1.1.0",
        )
        self.assertEqual(
            StyleTabMixin._language_version({"languageVersion": "1.0.0"}), "1.0.0"
        )
        self.assertEqual(StyleTabMixin._language_version({}), "")

    def test_a_1_1_style_explains_the_rendition(self):
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._show_style_info(["from_qgis", GLOBAL])
        form = Recording.opened[-1]
        self.assertEqual(form.get_widget("version").text(), "1.1.0")
        help_texts = [
            f.get("help")
            for f in self.dlg._style_fields(True, "1.1.0")
            if f["key"] == "version"
        ]
        self.assertIn("rendition", help_texts[0])

    def test_a_1_0_style_says_nothing_extra(self):
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._show_style_info(["population", GLOBAL])
        self.assertEqual(Recording.opened[-1].get_widget("version").text(), "1.0.0")
        version_field = [
            f for f in self.dlg._style_fields(True, "1.0.0") if f["key"] == "version"
        ][0]
        self.assertIsNone(version_field["help"])


class TestContentTypeByVersion(unittest.TestCase):
    """The body's own SLD version decides how it is sent."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()

    def test_a_1_0_body_goes_through_the_library(self):
        self.dlg._put_sld_body("population", None, SLD)
        self.assertEqual(
            self.dlg.gs.calls[-1], ("PUT-body", "population", None, "sld", SLD.encode())
        )
        self.assertFalse([c for c in self.dlg.gs.calls if c[0] == "PUT"])

    def test_a_1_1_body_is_sent_with_the_symbology_encoding_content_type(self):
        # rest_service.create_style() can only send application/vnd.ogc.sld+xml,
        # under which GeoServer records a 1.1 body as languageVersion 1.0.0.
        self.dlg._put_sld_body("from_qgis", "topp", SLD_11)
        verb, path, kwargs = self.dlg.gs.calls[-1]
        self.assertEqual(verb, "PUT")
        self.assertEqual(path, "/rest/workspaces/topp/styles/from_qgis.sld")
        self.assertEqual(kwargs["headers"]["Content-Type"], SLD_1_1)
        self.assertEqual(kwargs["data"], SLD_11.encode())
        self.assertFalse([c for c in self.dlg.gs.calls if c[0] == "PUT-body"])

    def test_editing_an_sld_body_in_place_uses_the_same_rule(self):
        self.dlg._save_style_body("from_qgis", "topp", "sld", SLD_11)
        self.assertEqual(self.dlg.gs.calls[-1][0], "PUT")

    def test_a_non_sld_body_is_untouched_by_the_rule(self):
        self.dlg._save_style_body("basemap", None, "mbstyle", "{}")
        self.assertEqual(
            self.dlg.gs.calls[-1], ("PUT-body", "basemap", None, "mbstyle", b"{}")
        )


class TestStyleFromQgisLayer(unittest.TestCase):
    """Uploading the symbology of a layer in the current project."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        QgsProject.instance().removeAllMapLayers()
        self.layer = point_layer("towns", colour="#ff0000")
        QgsProject.instance().addMapLayer(self.layer)

    def tearDown(self):
        QgsProject.instance().removeAllMapLayers()

    def test_the_project_layer_becomes_a_style_with_the_1_1_content_type(self):
        self.dlg._create_style_from_values(
            {
                "name": "new_towns",
                "workspace": "topp",
                "source": "From a QGIS layer",
                "qgis_layer": "towns  (vector)",
            }
        )
        self.assertEqual(
            self.dlg.gs.calls[0],
            ("definition", "new_towns", "new_towns.sld", "topp"),
        )
        verb, _path, kwargs = self.dlg.gs.calls[-1]
        self.assertEqual(verb, "PUT")
        self.assertEqual(kwargs["headers"]["Content-Type"], SLD_1_1)
        self.assertIn(b"ff0000", kwargs["data"].lower())  # the symbology travelled

    def test_the_source_field_shows_the_projects_layers(self):
        field = [
            f for f in self.dlg._upload_fields(["topp"]) if f["key"] == "qgis_layer"
        ][0]
        self.assertEqual(field["options"], ["towns  (vector)"])
        self.assertFalse(field["visible"])  # hidden until that source is picked

    def test_picking_the_qgis_source_reveals_only_that_field(self):
        dlg = ResourceFormDialog(title="t", fields=self.dlg._upload_fields(["topp"]))
        self.dlg._on_style_source_changed(dlg, "From a QGIS layer")
        self.assertNotIn("qgis_layer", dlg._hidden_keys)
        self.assertIn("sld", dlg._hidden_keys)
        self.assertIn("file", dlg._hidden_keys)

    def test_a_layer_that_left_the_project_is_refused(self):
        with self.assertRaises(ValueError):
            self.dlg._create_style_from_values(
                {
                    "name": "new_gone",
                    "workspace": GLOBAL,
                    "source": "From a QGIS layer",
                    "qgis_layer": "not_in_the_project  (vector)",
                }
            )


class TestApplyStyleToQgis(unittest.TestCase):
    """Pulling a server style onto a project layer."""

    def setUp(self):
        Recording.opened.clear()
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.messages = {"warning": [], "success": []}
        self.dlg.show_warning_message = self.messages["warning"].append
        self.dlg.show_success_message = self.messages["success"].append
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        QgsProject.instance().removeAllMapLayers()

    def tearDown(self):
        QgsProject.instance().removeAllMapLayers()

    def test_the_style_lands_on_the_chosen_layer(self):
        target = point_layer("towns", colour="#0000ff")
        QgsProject.instance().addMapLayer(target)
        red = layer_to_sld(point_layer("source", colour="#ff0000"))

        class Accepting(ResourceFormDialog):
            def exec(inner):
                return QDialog.DialogCode.Accepted

        with (
            patch.object(tab_styles, "ResourceFormDialog", Accepting),
            patch.object(type(self.dlg), "_style_body", lambda *a: red),
        ):
            self.dlg._apply_style_to_qgis(["population", GLOBAL])
        self.assertEqual(target.renderer().symbol().color().name(), "#ff0000")
        self.assertIn("towns", self.messages["success"][0])

    def test_a_css_style_is_refused_before_any_dialog(self):
        QgsProject.instance().addMapLayer(point_layer("towns"))
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._apply_style_to_qgis(["generic", GLOBAL])  # the fake's CSS style
        self.assertEqual(Recording.opened, [])
        self.assertIn("QGIS can only read SLD", self.messages["warning"][0])

    def test_an_empty_project_is_a_banner_not_a_dialog(self):
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._apply_style_to_qgis(["population", GLOBAL])
        self.assertEqual(Recording.opened, [])
        self.assertIn("no vector or raster layer", self.messages["warning"][0])

    def test_what_qgis_cannot_read_is_a_warning_not_a_success(self):
        QgsProject.instance().addMapLayer(point_layer("towns"))

        class Accepting(ResourceFormDialog):
            def exec(inner):
                return QDialog.DialogCode.Accepted

        with (
            patch.object(tab_styles, "ResourceFormDialog", Accepting),
            patch.object(type(self.dlg), "_style_body", lambda *a: "<not-a-style/>"),
        ):
            self.dlg._apply_style_to_qgis(["population", GLOBAL])
        self.assertEqual(self.messages["success"], [])
        self.assertIn("could not read", self.messages["warning"][0])


class TestSaveStyleToDisk(unittest.TestCase):
    def test_the_body_is_written_where_the_user_pointed(self):
        import tempfile
        from pathlib import Path

        dlg = SyncDialog()
        dlg.gs = FakeGS()
        saved = []
        dlg.show_success_message = saved.append
        dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        target = Path(tempfile.mkdtemp()) / "population.sld"

        with patch.object(
            tab_styles.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "")
        ):
            dlg._save_style_to_disk(["population", GLOBAL])

        self.assertEqual(target.read_text(), SLD)
        self.assertIn("population.sld", saved[0])
        self.assertIn("1.0.0", saved[0])  # the version it wrote, for the record

    def test_cancelling_the_file_dialog_writes_nothing(self):
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        dlg.show_success_message = lambda text: self.fail("nothing should be saved")
        with patch.object(
            tab_styles.QFileDialog, "getSaveFileName", lambda *a, **k: ("", "")
        ):
            dlg._save_style_to_disk(["population", GLOBAL])


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
