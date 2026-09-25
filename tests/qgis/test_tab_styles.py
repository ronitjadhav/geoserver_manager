#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    python -m unittest tests.qgis.test_tab_styles
"""

# standard library
import tempfile
from unittest.mock import patch

from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui import tab_styles
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.scope import GLOBAL
from geoserver_manager.gui.tab_styles import StyleTabMixin
from geoserver_manager.toolbelt.sld import SLD_1_0, SLD_1_1, layer_to_sld
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

            def post(inner, path, **kwargs):
                outer.calls.append(("POST", path, kwargs))
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
                # As the library: an extension for these three formats only
                # (test_library_contract pins it).
                if format in ("json", "sld", "mbstyle"):
                    return f"{base}.{format}"
                return base

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
            [
                ["population", GLOBAL, "sld", "1.0.0"],
                ["generic", GLOBAL, "css", "1.0.0"],
                ["roads_style", "topp", "sld", "1.0.0"],
            ],
        )
        self.assertEqual(self.warnings, [])

    def test_one_unreadable_workspace_keeps_the_rest(self):
        self.dlg.gs = FakeGS(broken_workspace="topp")
        self.dlg._load_styles()
        self.assertEqual([r[0] for r in self.dlg._all_rows], ["population", "generic"])
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("topp", self.warnings[0])

    def test_scope_maps_the_global_label_to_none(self):
        from geoserver_manager.gui.scope import scope

        self.assertIsNone(scope(GLOBAL))
        self.assertIsNone(scope(""))
        self.assertEqual(scope("topp"), "topp")

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

    def test_a_css_style_is_editable_and_renamable(self):
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._show_style_info(["generic", GLOBAL])
        form = Recording.opened[0]
        self.assertFalse(form.get_widget("body").isReadOnly())
        self.assertFalse(form.get_widget("name").isReadOnly())
        self.assertFalse(
            form._button_box.button(QDialogButtonBox.StandardButton.Ok).isHidden()
        )

    def test_a_css_body_is_put_with_its_own_content_type(self):
        # The library's create_style() has no CSS content type at all, and
        # its path builder no .css: the bare path is a 500 "No such style
        # handler".
        self.dlg._save_style_body("generic", None, "css", "* { stroke: red; }")
        verb, path, kwargs = self.dlg.gs.calls[-1]
        self.assertEqual((verb, path), ("PUT", "/rest/styles/generic.css"))
        self.assertEqual(
            kwargs["headers"], {"Content-Type": "application/vnd.geoserver.geocss+css"}
        )

    def test_a_ysld_body_is_put_to_its_own_extension_in_a_workspace(self):
        self.dlg._save_style_body("roads_style", "topp", "ysld", "feature-styles: []")
        verb, path, _kwargs = self.dlg.gs.calls[-1]
        self.assertEqual(
            (verb, path), ("PUT", "/rest/workspaces/topp/styles/roads_style.ysld")
        )

    def test_saving_only_the_body_reloads_the_list(self):
        # The Version cell follows the body: a 1.0 body replaced by a 1.1
        # one is recorded as 1.1, and the row kept 1.0.0 until F5.
        class Editing(ResourceFormDialog):
            def exec(self):
                self.get_widget("body").setText("<sld version='1.1.0'/>")
                return QDialog.DialogCode.Accepted

        reloads = []
        self.dlg._load_styles = lambda: reloads.append(1)
        with patch.object(tab_styles, "ResourceFormDialog", Editing):
            self.dlg._show_style_info(["population", GLOBAL])
        self.assertEqual(reloads, [1])
        self.assertEqual(self.dlg.gs.calls[-1][:2], ("PUT-body", "population"))

    def test_the_no_image_fallback_translates(self):
        from tests.qgis.test_i18n import Spy

        spy = Spy(["StyleTabMixin"])
        from qgis.PyQt.QtCore import QCoreApplication

        QCoreApplication.installTranslator(spy)
        self.addCleanup(QCoreApplication.removeTranslator, spy)
        self.assertEqual(
            StyleTabMixin._ogc_exception_text(""),
            "[StyleTabMixin] GeoServer returned no image",
        )

    def test_upload_from_a_string_sends_the_body_with_its_own_content_type(self):
        self.dlg._create_style_from_values(
            {
                "name": "brand_new",
                "workspace": GLOBAL,
                "source": "Paste",
                "sld": SLD,
            }
        )
        # One POST with the body's own content type: a definition created first
        # stayed behind, empty, when GeoServer refused the body.
        creates = [c for c in self.dlg.gs.calls if c[0] in ("POST", "definition")]
        ((verb, path, kwargs),) = creates
        self.assertEqual((verb, path), ("POST", "/rest/styles.json"))
        self.assertEqual(kwargs["params"], {"name": "brand_new"})
        self.assertEqual(kwargs["headers"]["Content-Type"], SLD_1_0)
        self.assertEqual(kwargs["data"], SLD.encode())
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
        verb, path, kwargs = self.dlg.gs.calls[-1]
        self.assertEqual((verb, path), ("POST", "/rest/workspaces/topp/styles.json"))
        self.assertEqual(kwargs["data"], SLD.encode())
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
                    "source": "Paste",
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
        self.dlg._confirm_delete = lambda question, labels=(), cascade="": True
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


class TestStyleDialogLayout(unittest.TestCase):
    def test_the_definition_is_the_first_tab(self):
        """It is the one thing the dialog edits; it hid on a second tab."""
        fields = SyncDialog()._style_fields(editable=True)
        self.assertEqual(fields[0]["key"], "body")
        self.assertEqual(fields[0]["group"], "Definition")
        self.assertTrue(fields[0]["wide"] and fields[0]["code"])
        self.assertTrue(all(f.get("group") == "Details" for f in fields[1:]))


class TestFileField(unittest.TestCase):
    """The form dialog's 'file' type: QGIS's file widget."""

    def test_round_trips_a_path_and_can_be_required(self):
        dlg = ResourceFormDialog(
            title="t",
            fields=[{"key": "file", "label": "File", "type": "file", "required": True}],
        )
        dlg.show()
        dlg._on_accept()
        self.assertFalse(dlg.result())  # empty + required -> blocked
        dlg.get_widget("file").setFilePath("/tmp/a.sld")
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
    """A 1.1 style is served as its 1.0 rendition; the dialog says so."""

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
        """Through the Upload form, the one path there is: the export runs on
        the GUI thread, then the SLD is uploaded as a pasted one."""
        layer = self.layer

        class Uploading(ResourceFormDialog):
            def exec(self):
                self.set_values(
                    {"name": "new_towns", "workspace": "topp", "source": "Paste"}
                )
                self.set_values({"source": tab_styles._SOURCE_QGIS})
                self.get_widget("qgis_layer").setLayer(layer)
                return QDialog.DialogCode.Accepted

        self.dlg.show_error_message = lambda text: self.fail(text)
        with patch.object(tab_styles, "ResourceFormDialog", Uploading):
            self.dlg._add_style()
        posts = [call for call in self.dlg.gs.calls if call[0] == "POST"]
        self.assertFalse(any(c[0] == "definition" for c in self.dlg.gs.calls))
        ((_verb, path, kwargs),) = posts
        self.assertEqual(path, "/rest/workspaces/topp/styles.json")
        self.assertEqual(kwargs["params"], {"name": "new_towns"})
        self.assertEqual(kwargs["headers"]["Content-Type"], SLD_1_1)
        self.assertIn(b"ff0000", kwargs["data"].lower())  # the symbology travelled

    def test_the_source_field_shows_the_projects_layers(self):
        dlg = ResourceFormDialog(title="t", fields=self.dlg._upload_fields(["topp"]))
        self.assertIs(dlg.get_widget("qgis_layer").currentLayer(), self.layer)
        self.assertIn("qgis_layer", dlg._hidden_keys)  # until that source is picked

    def test_picking_the_qgis_source_reveals_only_that_field(self):
        dlg = ResourceFormDialog(title="t", fields=self.dlg._upload_fields(["topp"]))
        self.dlg._on_style_source_changed(dlg, "From a QGIS layer")
        self.assertNotIn("qgis_layer", dlg._hidden_keys)
        self.assertIn("sld", dlg._hidden_keys)
        self.assertIn("file", dlg._hidden_keys)

    def test_a_layer_that_leaves_the_project_is_no_longer_offered(self):
        # A picked label used to outlive its layer and fail on Save; QGIS's
        # combo follows the project.
        dlg = ResourceFormDialog(title="t", fields=self.dlg._upload_fields(["topp"]))
        QgsProject.instance().removeAllMapLayers()
        self.assertIsNone(dlg.get_values()["qgis_layer"])


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

    def test_a_css_style_is_read_as_geoservers_sld_rendition(self):
        QgsProject.instance().addMapLayer(point_layer("towns"))
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._apply_style_to_qgis(["generic", GLOBAL])  # the fake's CSS style
        self.assertEqual(len(Recording.opened), 1)
        self.assertIn(
            "/rest/styles/generic.sld", [call[1] for call in self.dlg.gs.calls]
        )

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

    def test_the_bytes_are_written_as_stored_whatever_their_encoding(self):
        # Decoded with replacement characters and written back as UTF-8, an
        # ISO-8859-1 style lost its accents under its own declaration.
        import tempfile
        from pathlib import Path

        stored = (
            '<?xml version="1.0" encoding="ISO-8859-1"?>'
            '<StyledLayerDescriptor version="1.0.0"><Title>caf\xe9</Title>'
            "</StyledLayerDescriptor>"
        ).encode("latin-1")

        class Response:
            status_code = 200
            content = stored

        dlg = SyncDialog()
        dlg.gs = FakeGS()
        dlg.gs.rest_service.rest_client.get = lambda path, **kwargs: Response()
        dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        target = Path(tempfile.mkdtemp()) / "population.sld"
        with patch.object(
            tab_styles.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "")
        ):
            dlg._save_style_to_disk(["population", GLOBAL])
        self.assertEqual(target.read_bytes(), stored)

    def test_cancelling_the_file_dialog_writes_nothing(self):
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        dlg.show_success_message = lambda text: self.fail("nothing should be saved")
        with patch.object(
            tab_styles.QFileDialog, "getSaveFileName", lambda *a, **k: ("", "")
        ):
            dlg._save_style_to_disk(["population", GLOBAL])


# ############################################################################
# ###### Legend preview ##########
# ################################

EXCEPTION_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<ServiceExceptionReport version="1.1.1"><ServiceException code="StyleNotDefined">'
    "\n      No such style: nope\n</ServiceException></ServiceExceptionReport>"
)


def png_bytes():
    """A real PNG, made by Qt itself."""
    from qgis.PyQt.QtCore import QBuffer, QIODevice
    from qgis.PyQt.QtGui import QPixmap

    pixmap = QPixmap(3, 2)
    pixmap.fill()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


class LegendFakeGS(FakeGS):
    """Published layers to draw with, and a GetLegendGraphic that answers a PNG
    or an OGC exception (HTTP 200 with XML, as GeoServer does)."""

    def __init__(self, layers=("tiger:poi", "topp:states"), exception=None):
        super().__init__()
        self.layers = list(layers)
        self.exception = exception
        self.legend_calls = []
        outer = self

        class Response:
            status_code = 200
            content = SLD.encode()

            def __init__(inner, payload=None):
                inner._payload = payload or {}

            def json(inner):
                return inner._payload

        class Client:
            def get(inner, path, **kwargs):
                outer.calls.append(("GET", path, kwargs))
                if path == "/rest/layers.json":
                    layer = [{"name": name} for name in outer.layers]
                    return Response({"layers": {"layer": layer} if layer else ""})
                if path.startswith("/rest/workspaces/") and path.endswith(
                    "/layers.json"
                ):
                    workspace = path.split("/")[3]
                    layer = [
                        {"name": name.split(":", 1)[1]}
                        for name in outer.layers
                        if name.startswith(f"{workspace}:")
                    ]
                    return Response({"layers": {"layer": layer} if layer else ""})
                return Response()

        class Endpoints(type(self.rest_service.rest_endpoints)):
            base_url = "/rest"  # the real one has no layers path, only base_url

        self.rest_service.rest_client = Client()
        self.rest_service.rest_endpoints = Endpoints()

    def get_legend_graphic(
        self, layer, format="image/png", language=None, style=None, workspace_name=None
    ):
        self.legend_calls.append((layer, style, workspace_name))

        class Legend:
            pass

        response = Legend()
        if self.exception:
            response.headers = {
                "Content-Type": "application/vnd.ogc.se_xml;charset=UTF-8"
            }
            response.text = self.exception
            response.content = self.exception.encode()
        else:
            response.headers = {"Content-Type": "image/png"}
            response.text = ""
            response.content = png_bytes()
        return response


class TestImageField(unittest.TestCase):
    """The form dialog's 'image' type: a picture set later, never a value."""

    def dialog(self):
        return ResourceFormDialog(
            title="t",
            fields=[
                {
                    "key": "legend",
                    "label": "Legend",
                    "type": "image",
                    "placeholder": "Loading…",
                    "max_height": 100,
                },
                {"key": "name", "label": "Name", "type": "text"},
            ],
        )

    def test_placeholder_then_a_picture_scaled_to_the_cap(self):
        from qgis.PyQt.QtGui import QPixmap

        dlg = self.dialog()
        label = dlg.get_widget("legend")
        self.assertEqual(label.text(), "Loading…")
        tall = QPixmap(20, 300)
        tall.fill()
        dlg.set_image("legend", tall)
        self.assertEqual(label.text(), "")
        self.assertEqual(label.pixmap().height(), 100)

    def test_a_picture_landing_after_show_gets_its_full_height(self):
        # The legend lands while the form is open. The label was laid out for
        # one line of placeholder text and kept that height, so only the first
        # row of a legend showed.
        from qgis.PyQt.QtGui import QPixmap
        from qgis.PyQt.QtWidgets import QApplication

        dlg = self.dialog()
        dlg.show()
        QApplication.processEvents()
        legend = QPixmap(20, 80)
        legend.fill()
        dlg.set_image("legend", legend)
        QApplication.processEvents()
        self.assertGreaterEqual(dlg.get_widget("legend").height(), 80)
        dlg.close()

    def test_no_picture_means_an_explanation(self):
        dlg = self.dialog()
        dlg.set_image("legend", None, "No such style")
        self.assertEqual(dlg.get_widget("legend").text(), "No such style")

    def test_it_is_not_a_value(self):
        dlg = self.dialog()
        dlg.get_widget("name").setText("x")
        self.assertEqual(dlg.get_values(), {"name": "x"})


class TestLegendPreview(unittest.TestCase):
    """The style dialog shows the legend GeoServer renders, a layer as context."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = LegendFakeGS()
        self.dlg.show_error_message = lambda t: self.fail(f"unexpected error: {t}")
        self.dlg.show_warning_message = lambda t: None
        Recording.opened.clear()

    def test_a_layer_of_the_styles_workspace_first_then_any(self):
        self.assertEqual(self.dlg._legend_layer("topp"), "topp:states")
        # the workspace's own collection was asked, not the whole server's
        self.assertIn(
            "/rest/workspaces/topp/layers.json",
            [call[1] for call in self.dlg.gs.calls if call[0] == "GET"],
        )
        self.assertEqual(self.dlg._legend_layer("nurc"), "tiger:poi")
        self.assertEqual(self.dlg._legend_layer(None), "tiger:poi")
        self.dlg.gs = LegendFakeGS(layers=())
        self.assertIsNone(self.dlg._legend_layer("topp"))

    def test_the_legend_lands_in_the_open_dialog(self):
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._show_style_info(["roads_style", "topp"])
        label = Recording.opened[0].get_widget("legend")
        self.assertIsNotNone(label.pixmap())
        self.assertFalse(label.pixmap().isNull())
        self.assertEqual(
            self.dlg.gs.legend_calls, [("topp:states", "topp:roads_style", None)]
        )

    def test_a_global_style_is_asked_for_by_its_bare_name(self):
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._show_style_info(["population", GLOBAL])
        self.assertEqual(self.dlg.gs.legend_calls, [("tiger:poi", "population", None)])

    def test_an_ogc_exception_becomes_a_sentence_not_a_broken_picture(self):
        self.dlg.gs = LegendFakeGS(exception=EXCEPTION_XML)
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._show_style_info(["population", GLOBAL])
        label = Recording.opened[0].get_widget("legend")
        self.assertIn("No such style: nope", label.text())

    def test_no_layer_at_all_is_explained_without_asking(self):
        self.dlg.gs = LegendFakeGS(layers=())
        with patch.object(tab_styles, "ResourceFormDialog", Recording):
            self.dlg._show_style_info(["population", GLOBAL])
        label = Recording.opened[0].get_widget("legend")
        self.assertIn("No published layer", label.text())
        self.assertEqual(self.dlg.gs.legend_calls, [])

    def test_a_dialog_closed_or_gone_before_the_legend_lands_is_left_alone(self):
        from qgis.PyQt import sip

        captured = {}

        class Capturing(SyncDialog):
            def _run_quietly(self, failure_message, work, on_success):
                captured["work"], captured["landed"] = work, on_success

        dlg = Capturing()
        dlg.gs = LegendFakeGS()
        form = ResourceFormDialog(title="t", fields=dlg._style_fields(False))
        dlg._load_legend(form, "population", None)
        form.reject()  # closed before the picture arrives
        captured["landed"](captured["work"](None))
        self.assertEqual(
            form.get_widget("legend").text(), "Asking GeoServer for the legend…"
        )

        form = ResourceFormDialog(title="t", fields=dlg._style_fields(False))
        dlg._load_legend(form, "population", None)
        result = captured["work"](None)
        sip.delete(form)  # the C++ dialog is gone
        captured["landed"](result)  # must not raise


class TestFormatAndVersionColumns(unittest.TestCase):
    """The table says what each style is, because Apply needs SLD."""

    def test_rows_carry_the_format_and_the_sld_version(self):
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        dlg._load_styles()  # the page's details fill as it shows
        by_name = {row[0]: row for row in dlg._all_rows}
        self.assertEqual(by_name["population"], ["population", GLOBAL, "sld", "1.0.0"])
        self.assertEqual(by_name["generic"][2], "css")
        self.assertEqual(by_name["roads_style"][:2], ["roads_style", "topp"])
        dlg._load_styles()
        headers = [
            dlg.resultsTable.horizontalHeaderItem(i).text()
            for i in range(dlg.resultsTable.columnCount())
        ]
        self.assertEqual(headers[:4], ["Name", "Workspace", "Format", "Version"])


class TestNamesInPaths(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = FakeGS()
        self.dlg.gs = self.gs

    def test_an_upload_name_the_paths_cannot_carry_is_refused_first(self):
        for bad in ("a/b", "new#style", "a%b"):
            with self.assertRaises(ValueError, msg=bad):
                self.dlg._create_style_from_values(
                    {
                        "name": bad,
                        "workspace": GLOBAL,
                        "source": "Paste",
                        "sld": SLD,
                    }
                )
        self.assertEqual([c for c in self.gs.calls if c[0] == "definition"], [])

    def test_a_style_name_from_the_server_is_quoted_into_its_paths(self):
        self.dlg._style_body("my style", "my ws", "sld")
        self.dlg._do_delete_style("a#b", None)
        paths = [call[1] for call in self.gs.calls if call[0] in ("GET", "DELETE")]
        self.assertIn("/rest/workspaces/my%20ws/styles/my%20style.sld", paths)
        self.assertIn("/rest/styles/a%23b.json", paths)


class TestWording(unittest.TestCase):
    def test_row_actions_say_what_they_do(self):
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        dlg._load_styles()
        labels = [action[1] for action in dlg._row_actions]
        self.assertIn("Save to disk", labels)
        self.assertNotIn("Save as SLD", labels)
        tooltips = [action[3] for action in dlg._row_actions if len(action) > 3]
        self.assertTrue(any("layer tree" in tip for tip in tooltips), tooltips)


class TestRenameCopyAndUsage(unittest.TestCase):
    """Measured on 2.28.5: a PUT of the name renames a style and its users
    follow; other formats are created by a POST with their content type."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()

    def calls(self, verb):
        return [call for call in self.dlg.gs.calls if call[0] == verb]

    def test_a_rename_is_a_put_of_the_name_and_nothing_else(self):
        # Its caller checked the name before the body PUT; a second
        # get_style_definition here was one GET per rename for nothing.
        reads = []
        definition = self.dlg.gs.get_style_definition
        self.dlg.gs.get_style_definition = lambda *args: reads.append(args) or (
            definition(*args)
        )
        self.dlg._rename_style("population", None, "new_population")
        ((_verb, path, kwargs),) = self.calls("PUT")
        self.assertEqual(path, "/rest/styles/population.json")
        self.assertEqual(kwargs["json"], {"style": {"name": "new_population"}})
        self.assertEqual(reads, [])

    def test_a_rename_onto_a_taken_name_sends_nothing(self):
        class Renaming(ResourceFormDialog):
            def exec(self):
                self.get_widget("name").setText("generic")
                return QDialog.DialogCode.Accepted

        errors = []
        self.dlg.show_error_message = errors.append
        with patch.object(tab_styles, "ResourceFormDialog", Renaming):
            self.dlg._show_style_info(["population", GLOBAL])
        self.assertEqual(self.calls("PUT"), [])
        self.assertEqual(len(errors), 1)
        self.assertIn("already exists", errors[0])

    def test_a_pasted_css_style_is_posted_with_its_content_type(self):
        self.dlg._create_style_from_values(
            {
                "name": "new_css",
                "workspace": GLOBAL,
                "source": "Paste",
                "format": "CSS",
                "sld": "* { stroke: red; }",
            }
        )
        ((_verb, path, kwargs),) = self.calls("POST")
        self.assertEqual(path, "/rest/styles.json")
        self.assertEqual(kwargs["params"], {"name": "new_css"})
        self.assertEqual(
            kwargs["headers"], {"Content-Type": "application/vnd.geoserver.geocss+css"}
        )

    def test_a_ysld_file_is_read_as_ysld(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as handle:
            handle.write("feature-styles: []")
        self.dlg._create_style_from_values(
            {
                "name": "new_ysld",
                "workspace": "topp",
                "source": "From file",
                "file": handle.name,
            }
        )
        ((_verb, path, kwargs),) = self.calls("POST")
        self.assertEqual(path, "/rest/workspaces/topp/styles.json")
        self.assertEqual(
            kwargs["headers"], {"Content-Type": "application/vnd.geoserver.ysld+yaml"}
        )

    def test_a_copy_keeps_the_format_and_lands_in_the_target_workspace(self):
        self.dlg._copy_style_to("generic", None, "new_generic", "topp")
        ((_verb, path, kwargs),) = self.calls("POST")
        self.assertEqual(path, "/rest/workspaces/topp/styles.json")
        self.assertEqual(kwargs["params"], {"name": "new_generic"})
        self.assertIn("geocss", kwargs["headers"]["Content-Type"])

    def test_a_copy_onto_a_taken_name_sends_nothing(self):
        with self.assertRaises(ValueError):
            self.dlg._copy_style_to("generic", None, "population", None)
        self.assertEqual(self.calls("POST"), [])

    def test_users_are_found_by_default_other_style_and_group(self):
        layers = {
            "topp:roads": {"defaultStyle": {"name": "topp:roads_style"}},
            "topp:rivers": {
                "defaultStyle": {"name": "line"},
                "styles": {"style": {"name": "topp:roads_style"}},
            },
            "sf:streams": {"defaultStyle": {"name": "roads_style"}},  # global one
        }

        class Reply:
            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return {"layer": self.payload}

        def raw_rest(_verb, path, **_kwargs):
            qualified = path.rsplit("/", 1)[1][: -len(".json")]
            if qualified == "ne:broken":
                raise RuntimeError("HTTP 500: boom")
            return Reply(layers[qualified])

        self.dlg._raw_rest = raw_rest
        self.dlg._layers_url = lambda qualified: f"/rest/layers/{qualified}.json"
        self.dlg._all_layer_names = lambda: [*layers, "ne:broken"]
        self.dlg._all_group_names = lambda: ["tasmania"]
        self.dlg._group_detail = lambda name, ws: {
            "styles": {"style": ["", {"name": "topp:roads_style"}]}
        }
        users = self.dlg._style_users("roads_style", "topp")
        self.assertEqual(
            users[:2], ["topp:roads (default style)", "topp:rivers (other style)"]
        )
        # A layer that could not be read is said, never silently skipped.
        self.assertIn("ne:broken (could not be read", users[2])
        self.assertEqual(users[3], "tasmania (layer group)")
        self.assertEqual(len(users), 4)

        # Cancelled, each fan-out stops after the round in flight: the
        # waiting box's Cancel used to leave every remaining GET to run.
        from types import SimpleNamespace

        cancelled = SimpleNamespace(isCanceled=lambda: True, setProgress=lambda v: None)
        self.assertEqual(
            self.dlg._style_users("roads_style", "topp", cancelled),
            ["topp:roads (default style)", "tasmania (layer group)"],
        )

    def test_used_by_hands_the_waiting_box_a_stop_event(self):
        import threading

        captured = {}

        def fetch(action, failure, **kwargs):
            captured.update(kwargs)
            return None

        self.dlg._fetch = fetch
        self.dlg._show_style_users(["roads_style", "topp"])
        self.assertIsInstance(captured.get("stop"), threading.Event)


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
