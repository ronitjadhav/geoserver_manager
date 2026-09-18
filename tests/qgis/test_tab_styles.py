#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    python -m unittest tests.qgis.test_tab_styles
"""

# standard library
from unittest.mock import patch

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui import tab_styles
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_styles import GLOBAL
from tests.qgis.sync_dialog import SyncDialog

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
        if name == "brand_new":
            return ("<html>Not Found</html>", 404)
        fmt = "css" if name == "generic" else "sld"
        return ({"name": name, "format": fmt, "filename": "popshade.sld"}, 200)

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

    def test_upload_from_string_and_from_file(self):
        self.dlg._create_style_from_values(
            {
                "name": "brand_new",
                "workspace": GLOBAL,
                "source": "Paste SLD",
                "sld": SLD,
            }
        )
        self.assertEqual(self.dlg.gs.calls[-1], ("from_string", "brand_new", None, SLD))

        self.dlg._create_style_from_values(
            {
                "name": "brand_new",
                "workspace": "topp",
                "source": "From file",
                "file": "/tmp/x.sld",
            }
        )
        self.assertEqual(
            self.dlg.gs.calls[-1], ("from_file", "brand_new", "topp", "/tmp/x.sld")
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
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
