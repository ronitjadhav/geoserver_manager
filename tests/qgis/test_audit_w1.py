#! python3  # noqa E265

"""
Audit fixes on the Workspaces, Datastores and Layer Groups tabs: each test
fails on the code before it.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_audit_w1
"""

import sys

from qgis.testing import start_app, unittest

from geoserver_manager.gui import tab_datastores, tab_layergroups
from geoserver_manager.gui.scope import GLOBAL
from geoserver_manager.toolbelt.dependencies import BUNDLED_WHLS
from tests.qgis.sync_dialog import SyncDialog

start_app()


def rows(text):
    """The group form's rows from a compact "layer = style" notation, one per line."""
    return [
        [name.strip(), style.strip()]
        for name, _, style in (line.partition("=") for line in text.splitlines())
        if name.strip()
    ]


# _put_workspace builds its payload with the library's Workspace model, so the
# bundled wheel has to be importable here too (conftest does this under pytest).
for whl in BUNDLED_WHLS:
    if str(whl) not in sys.path:
        sys.path.insert(0, str(whl))


class Response:
    status_code = 200
    text = ""

    def __init__(self, payload=None):
        self.payload = payload if payload is not None else {}

    def json(self):
        return self.payload


class RecordingGS:
    """Records every library call and raw request; nothing exists on it."""

    def __init__(self):
        self.calls = []
        outer = self

        class Client:
            def get(inner, path, **kwargs):
                outer.calls.append(("GET", path))
                return Response({})

            def put(inner, path, **kwargs):
                outer.calls.append(("PUT", path, kwargs))
                return Response()

            def post(inner, path, **kwargs):
                outer.calls.append(("POST", path, kwargs))
                return Response()

        class Endpoints:
            base_url = "/rest"

            def workspace(inner, name):
                return f"/rest/workspaces/{name}.json"

            def layergroups(inner, ws):
                return f"/rest/workspaces/{ws}/layergroups.json"

            def layergroup(inner, ws, name):
                return f"/rest/workspaces/{ws}/layergroups/{name}.json"

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

            def resource_exists(inner, path):
                return False

        self.rest_service = Rest()

    def get_workspace(self, name):
        return ("not found", 404)

    def get_datastore(self, workspace_name, name):
        return ("not found", 404)

    def get_style_definition(self, name, workspace_name=None):
        return ({"style": {"name": name}}, 200)

    def create_workspace(self, name, isolated=False):
        self.calls.append(("create_workspace", name, isolated))
        return ("", 201)

    def create_datastore(self, **kwargs):
        self.calls.append(("create_datastore", kwargs))
        return ("", 201)


class TestNamesAreCheckedBeforeAnyRequest(unittest.TestCase):
    """A '/' or '#' in a name would send the request to another resource."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = RecordingGS()
        self.dlg.gs = self.gs

    def test_a_workspace(self):
        for bad in ("a/b", "a#b"):
            with self.assertRaises(ValueError):
                self.dlg._save_workspace(
                    {"name": bad, "isolated": False, "set_default": False}
                )
        self.assertEqual(self.gs.calls, [])
        # a rename to a bad name is refused too; a plain edit does not re-check
        with self.assertRaises(ValueError):
            self.dlg._save_workspace(
                {"name": "a?b", "isolated": False, "set_default": False}, old_name="ok"
            )

    def test_a_datastore(self):
        with self.assertRaises(ValueError):
            self.dlg._create_datastore_from_values(
                {
                    "workspace": "topp",
                    "name": "a/b",
                    "type": "PMTiles",
                    "pmtiles_url": "x",
                }
            )
        self.assertEqual(self.gs.calls, [])

    def test_a_layer_group(self):
        with self.assertRaises(ValueError):
            self.dlg._create_layer_group_from_values(
                {
                    "name": "a#b",
                    "workspace": GLOBAL,
                    "mode": "SINGLE",
                    "layers": rows("topp:states"),
                }
            )
        self.assertEqual(self.gs.calls, [])

    def test_a_global_group_path_is_quoted(self):
        self.assertEqual(
            self.dlg._group_path("my group", None), "/rest/layergroups/my%20group.json"
        )
        self.assertEqual(
            self.dlg._group_path("a?b", None), "/rest/layergroups/a%3Fb.json"
        )


class TestWorkspaceEdit(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = RecordingGS()
        self.dlg.gs = self.gs

    def test_an_edit_without_a_rename_is_one_put_not_a_post_that_409s(self):
        self.dlg._save_workspace(
            {"name": "topp", "isolated": True, "set_default": False}, old_name="topp"
        )
        verbs = [call[0] for call in self.gs.calls]
        self.assertEqual(verbs, ["PUT"])
        self.assertEqual(self.gs.calls[0][1], "/rest/workspaces/topp.json")
        self.assertIs(self.gs.calls[0][2]["json"]["workspace"]["isolated"], True)

    def test_the_help_and_the_cascade_say_what_is_true(self):
        fields = {f["key"]: f for f in self.dlg._workspace_fields()}
        self.assertIn("own URLs", fields["isolated"]["help"])
        self.assertNotIn("coexist", fields["isolated"]["help"])
        asked = []
        self.dlg._confirm_delete = (
            lambda question, labels=(), cascade="": asked.append(cascade) or False
        )
        self.dlg._delete_selected_workspaces([["topp", ""]])
        self.assertIn("coverage stores", asked[0])
        self.assertIn("cascaded stores", asked[0])
        self.assertFalse(asked[0].endswith("\n"))


class TestDatastoreEnabled(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = RecordingGS()
        self.dlg.gs = self.gs

    def test_the_checkbox_exists_only_when_editing(self):
        create = {f["key"] for f in self.dlg._datastore_fields(["topp"])}
        edit = {f["key"] for f in self.dlg._datastore_fields(["topp"], edit_mode=True)}
        self.assertNotIn("enabled", create)
        self.assertIn("enabled", edit)
        # Name, Workspace, Type: the order every other form uses
        self.assertEqual(
            [f["key"] for f in self.dlg._datastore_fields(["topp"])][:3],
            ["name", "workspace", "type"],
        )

    def test_the_prefill_reads_the_flag_and_the_form_can_flip_it(self):
        values = self.dlg._datastore_form_values(
            "topp", "pg", "PostGIS", {"enabled": False}, {"host": "db"}
        )
        self.assertIs(values["enabled"], False)
        values.update({"pg_password": "", "enabled": True})
        self.dlg._update_datastore_from_values(
            values,
            {"type": "PostGIS", "enabled": False},
            {"host": "db", "passwd": "crypt1:x"},
        )
        (call,) = self.gs.calls
        self.assertIs(call[1]["enabled"], True)

    def test_without_a_checkbox_the_servers_flag_is_kept(self):
        values = self.dlg._datastore_form_values(
            "topp", "pg", "PMTiles", {"enabled": False}, {}
        )
        values.pop("enabled")
        self.dlg._update_datastore_from_values(
            values, {"type": "PMTiles", "enabled": False}, {}
        )
        self.assertIs(self.gs.calls[0][1]["enabled"], False)

    def test_the_table_reads_yes_no_and_secrets_are_masked_wider(self):
        class GS:
            def get_datastore(inner, ws, name):
                return ({"type": "PostGIS", "enabled": False}, 200)

        self.dlg.gs = GS()
        self.assertEqual(self.dlg._datastore_summary("topp", "pg"), ("PostGIS", "No"))
        self.assertTrue(tab_datastores._is_secret("AWS Secret"))
        self.assertTrue(tab_datastores._is_secret("api_token"))
        self.assertFalse(tab_datastores._is_secret("Expose primary keys"))


class TestLayerGroupModesAndLayers(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = RecordingGS()
        self.dlg.gs = self.gs

    def test_the_form_shows_words_and_hands_back_the_enum(self):
        # The translated label was stored and read back to the enum (#91).
        from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

        options = [f for f in self.dlg._group_fields([], []) if f["key"] == "mode"][0]
        self.assertEqual(options["options"][0], ("Single", "SINGLE"))
        self.assertIn("Opaque Container", options["help"])
        form = ResourceFormDialog(title="t", fields=[options], values={"mode": "EO"})
        self.assertEqual(
            form.get_widget("mode").currentText(), "Earth Observation Tree"
        )
        self.assertEqual(form.get_values()["mode"], "EO")

    def test_the_payload_carries_the_enum_whatever_the_form_showed(self):
        self.dlg._create_layer_group_from_values(
            {
                "name": "g",
                "workspace": GLOBAL,
                "mode": "NAMED",
                "layers": rows("topp:states"),
            }
        )
        post = [call for call in self.gs.calls if call[0] == "POST"][0]
        self.assertEqual(post[2]["json"]["layerGroup"]["mode"], "NAMED")

    def test_a_layer_the_server_does_not_have_is_named_before_any_request(self):
        with self.assertRaises(ValueError) as caught:
            self.dlg._create_layer_group_from_values(
                {
                    "name": "g",
                    "workspace": "topp",
                    "mode": "SINGLE",
                    "layers": rows("states\nroadz"),
                },
                known_layers=["topp:states"],
            )
        self.assertIn("'topp:roadz'", str(caught.exception))
        self.assertEqual([c for c in self.gs.calls if c[0] == "POST"], [])

    def test_the_bounds_use_the_shared_format(self):
        values = self.dlg._group_form_values(
            {"bounds": {"minx": 1, "miny": 2, "maxx": 3, "maxy": 4}}, "g", GLOBAL
        )
        self.assertEqual(values["bounds"], "1, 2 → 3, 4")  # no crs: no empty parens

    def test_the_dead_copy_of_all_layer_names_is_gone(self):
        self.assertNotIn(
            "_all_layer_names", tab_layergroups.LayerGroupTabMixin.__dict__
        )
        self.assertNotIn("_unwrap", tab_layergroups.LayerGroupTabMixin.__dict__)


if __name__ == "__main__":
    unittest.main()
