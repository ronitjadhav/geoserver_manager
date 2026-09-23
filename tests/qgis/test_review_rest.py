#! python3  # noqa E265

"""
The review's remaining correctness and UX findings: each test failed on the
code before its fix.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_review_rest
"""

import sys
from unittest.mock import patch

from qgis.PyQt.QtWidgets import QDialog
from qgis.testing import start_app, unittest

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.toolbelt.dependencies import BUNDLED_WHLS
from geoserver_manager.toolbelt.rest import PartlySaved
from tests.qgis.sync_dialog import SyncDialog

for _whl in BUNDLED_WHLS:  # conftest does this under pytest; unittest needs it too
    if str(_whl) not in sys.path:
        sys.path.insert(0, str(_whl))

start_app()


def boom(*args, **kwargs):
    raise RuntimeError("HTTP 500: boom")


class TestPartlySaved(unittest.TestCase):
    """A save whose first step happened and a later one failed said only
    "Failed", and a retry then met "already exists"."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.messages = []
        self.dlg.show_warning_message = lambda t: self.messages.append(("warning", t))
        self.dlg.show_error_message = lambda t: self.messages.append(("error", t))
        self.reloaded = []
        self.dlg._reload_current_tab = lambda: self.reloaded.append(1)

    def test_it_is_a_warning_and_the_tab_reloads(self):
        def action():
            raise PartlySaved("Workspace 'w' created, but its namespace URI was not.")

        self.assertFalse(self.dlg._run_action(action, "Failed to create 'w'"))
        self.assertEqual(self.messages[0][0], "warning")
        self.assertEqual(self.reloaded, [1])

    def test_a_workspace_whose_uri_fails_is_reported_created(self):
        class GS:
            def get_workspace(self, name):
                return ("no", 404)

            def create_workspace(self, name, isolated=False):
                return ("", 201)

        self.dlg.gs = GS()
        self.dlg._put_namespace_uri = boom
        with self.assertRaises(PartlySaved) as caught:
            self.dlg._save_workspace(
                {"name": "w", "isolated": False, "set_default": False, "uri": "x:y"}
            )
        self.assertIn("created", str(caught.exception))

    def test_a_cascaded_store_whose_credentials_fail_is_reported_created(self):
        self.dlg._cascaded_store_exists = lambda *args: False
        self.dlg._put_cascaded_store = boom

        class GS:
            def create_wms_store(self, ws, name, url):
                return ("", 201)

        self.dlg.gs = GS()
        with self.assertRaises(PartlySaved) as caught:
            self.dlg._create_cascaded_store_from_values(
                {
                    "workspace": "topp",
                    "name": "remote",
                    "type": "WMS",
                    "capabilities_url": "https://example.org/wms",
                    "user": "bob",
                    "password": "secret",
                }
            )
        self.assertIn("created", str(caught.exception))

    def test_a_renamed_datastore_whose_save_fails_says_it_was_renamed(self):
        self.dlg._rename_datastore = lambda *args: None

        class GS:
            create_datastore = staticmethod(boom)

        self.dlg.gs = GS()
        with self.assertRaises(PartlySaved) as caught:
            self.dlg._update_datastore_from_values(
                {"workspace": "topp", "name": "new", "type": "Other..."},
                {"type": "Properties", "enabled": True},
                {"directory": "file:x"},
                old_name="old",
            )
        self.assertIn("renamed to 'new'", str(caught.exception))


class TestBlankFieldsClear(unittest.TestCase):
    def test_a_blank_charset_removes_the_stored_one(self):
        # The merge kept ISO-8859-1, and the banner said "updated".
        dlg = SyncDialog()
        sent = []

        class GS:
            def create_datastore(self, **kwargs):
                sent.append(kwargs)
                return ("", 200)

        dlg.gs = GS()
        dlg._update_datastore_from_values(
            {
                "workspace": "topp",
                "name": "shp",
                "file_url": "file:x.shp",
                "charset": "",
            },
            {"type": "Shapefile", "enabled": True},
            {"url": "file:x.shp", "charset": "ISO-8859-1"},
        )
        self.assertNotIn("charset", sent[0]["connection_parameters"])

    def test_an_emptied_namespace_uri_goes_back_to_the_default(self):
        dlg = SyncDialog()
        put = []
        dlg._save_workspace = lambda values, old_name=None: None
        dlg._put_namespace_uri = lambda name, uri: put.append(uri)
        dlg._apply_wms_settings = lambda *args: None
        dlg._save_workspace_and_wms(
            {"name": "w", "uri": "", "wms_own": False}, "w", False, {}, "http://old"
        )
        self.assertEqual(put, ["http://w"])


class TestStyles(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()

    def test_an_sld_1_1_style_is_copied_as_its_stored_file(self):
        # {style}.sld serves the 1.0 rendition; the copy was stored as 1.0.
        dlg = self.dlg
        dlg._style_with_body = lambda name, ws: (
            {"filename": "towns.sld", "languageVersion": {"version": "1.1.0"}},
            "sld",
            "<rendition 1.0/>",
        )
        paths = []

        class Reply:
            content = b"<stored 1.1/>"

        def raw_rest(verb, path, **kwargs):
            paths.append(path)
            return Reply()

        dlg._raw_rest = raw_rest

        class GS:
            class rest_service:
                class rest_endpoints:
                    base_url = "/rest"

        dlg.gs = GS()
        _definition, _format, body = dlg._style_as_stored("towns", "topp")
        self.assertEqual(body, "<stored 1.1/>")
        self.assertEqual(paths, ["/rest/resource/workspaces/topp/styles/towns.sld"])

    def test_a_taken_name_is_refused_before_the_body_is_saved(self):
        # The new body was live on every layer, and the save "failed".
        from geoserver_manager.gui import tab_styles

        dlg = self.dlg
        saved = []
        dlg._style_with_body = lambda name, ws: ({}, "sld", "<old/>")
        dlg._save_style_body = lambda *args: saved.append(args)
        dlg._refuse_taken_style = boom
        dlg._load_legend = lambda *args: None
        dlg.show_error_message = lambda text: None

        class Accepting(ResourceFormDialog):
            def exec(inner):
                return QDialog.DialogCode.Accepted

            def get_values(inner):
                return {"name": "taken", "body": "<new/>"}

        with patch.object(tab_styles, "ResourceFormDialog", Accepting):
            dlg._show_style_info(["population", "(global)"])
        self.assertEqual(saved, [])

    def test_one_unreadable_group_does_not_fail_used_by(self):
        dlg = self.dlg
        dlg._all_layer_names = lambda: []
        dlg._all_group_names = lambda: ["good", "bad"]

        def detail(name, ws):
            if name == "bad":
                raise RuntimeError("HTTP 500: boom")
            return {"styles": {"style": {"name": "roads"}}}

        dlg._group_detail = detail
        users = dlg._style_users("roads", None)
        self.assertEqual(users[0], "good (layer group)")
        self.assertIn("bad (could not be read", users[1])


class TestServer(unittest.TestCase):
    def test_zero_decimals_is_shown_as_zero(self):
        from geoserver_manager.gui.tab_server import ServerTabMixin

        values = ServerTabMixin._server_form_values("global", {"numDecimals": 0})
        self.assertEqual(values["num_decimals"], 0)

    def test_a_log_outside_the_data_directory_is_said_not_requested(self):
        dlg = SyncDialog()
        warnings = []
        dlg.show_warning_message = warnings.append
        dlg._fetch = lambda *args, **kwargs: self.fail("no request")
        dlg._show_server_log("/var/log/geoserver.log")
        self.assertIn("outside GeoServer's data directory", warnings[0])


class TestForms(unittest.TestCase):
    def test_a_bad_url_keeps_the_dialog_open(self):
        form = ResourceFormDialog(
            title="t",
            fields=[{"key": "url", "label": "URL", "type": "text", "url": True}],
            values={"url": "ftp://example.org"},
        )
        form._on_accept()
        self.assertNotEqual(form.result(), QDialog.DialogCode.Accepted)
        self.assertIn("http://", form._validation_label.text())

    def test_secrets_are_masked_whatever_the_key_looks_like(self):
        from geoserver_manager.gui.tab_datastores import _is_secret

        for key in ("s3.secret-access-key", "azure.account.key", "io.token"):
            self.assertTrue(_is_secret(key), key)
        self.assertFalse(_is_secret("Expose primary keys"))


if __name__ == "__main__":
    unittest.main()
