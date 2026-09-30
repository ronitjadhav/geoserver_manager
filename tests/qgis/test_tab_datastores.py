#! python3  # noqa E265

"""
Datastore edits: a rename is a PUT on the old path, the parameters a typed
form does not own stay editable, and any other store type can be created.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_tab_datastores
"""

import copy
import sys
from unittest import mock

from qgis.PyQt.QtWidgets import QDialog
from qgis.testing import start_app, unittest

from geoserver_manager.gui import tab_datastores
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_datastores import _MASKED, _OTHER
from geoserver_manager.toolbelt.dependencies import BUNDLED_WHLS
from tests.qgis.sync_dialog import SyncDialog

for _whl in BUNDLED_WHLS:  # conftest does this under pytest; unittest needs it too
    if str(_whl) not in sys.path:
        sys.path.insert(0, str(_whl))

start_app()

STORED = {
    "dbtype": "postgis",
    "host": "db",
    "port": "5432",
    "database": "gis",
    "user": "u",
    "passwd": "crypt1:PG",
    "schema": "public",
    "namespace": "http://topp",
    "Loose bbox": "true",
    "max connections": "10",
}
PG_VALUES = {
    "workspace": "topp",
    "name": "pg",
    "type": "PostGIS",
    "pg_host": "db",
    "pg_port": 5432,
    "pg_db": "gis",
    "pg_user": "u",
    "pg_password": "",
    "pg_schema": "public",
}


class RecordingGS:
    def __init__(self, taken=()):
        self.taken = set(taken)
        self.created = []
        self.rest_service = mock.MagicMock()
        self.rest_service.rest_endpoints.datastore = (
            lambda ws, name: f"/rest/workspaces/{ws}/datastores/{name}.json"
        )

    def get_datastore(self, workspace_name, datastore_name):
        return ({}, 200 if datastore_name in self.taken else 404)

    def create_datastore(self, **kwargs):
        self.created.append(kwargs)
        return ("ok", 201)


class TestAddFormChecksFirst(unittest.TestCase):
    def test_a_taken_name_keeps_the_add_form_open(self):
        # Refused after the form closed, the whole form had to be typed again.
        from qgis.PyQt.QtWidgets import QDialog

        from geoserver_manager.gui import tab_datastores

        dlg = SyncDialog()
        dlg.gs = RecordingGS(taken={"pg"})
        dlg._get_workspace_names = lambda: ["topp"]
        seen = {}

        class Filling(ResourceFormDialog):
            def exec(inner):
                inner.set_values({"type": "PostGIS"})
                for key, text in (
                    ("name", "pg"),
                    ("pg_host", "db"),
                    ("pg_db", "d"),
                    ("pg_user", "u"),
                    ("pg_password", "secret"),
                ):
                    inner.get_widget(key).setText(text)
                inner._on_accept()
                seen["open"] = not inner.result()
                seen["said"] = inner._validation_label.text()
                return QDialog.DialogCode.Rejected

        with mock.patch.object(tab_datastores, "ResourceFormDialog", Filling):
            dlg._add_datastore()
        self.assertTrue(seen["open"])
        self.assertIn("already exists", seen["said"])
        self.assertEqual(dlg.gs.created, [])


class TestNamespaceFollowsTheWorkspace(unittest.TestCase):
    """The library's PostGIS, JNDI and PMTiles creates send
    namespace=http://{ws}: a workspace with its own URI got a store serving
    another namespace (measured on 2.28.5, review 2026-09-24)."""

    def setUp(self):
        created, saved, gets = [], [], []

        class GS:
            def get_datastore(inner, ws, name):
                gets.append(name)
                if not created:
                    return ("not found", 404)
                return (
                    {
                        "type": "PostGIS",
                        "enabled": True,
                        "description": "d",
                        "connectionParameters": {
                            "entry": {"passwd": "crypt1:x", "namespace": f"http://{ws}"}
                        },
                    },
                    200,
                )

            def create_pg_datastore(inner, **kwargs):
                created.append(kwargs)
                return ("", 201)

            def create_datastore(inner, **kwargs):
                saved.append(kwargs)
                return ("", 200)

        self.dlg = SyncDialog()
        self.dlg.gs = GS()
        self.saved, self.gets = saved, gets
        self.values = dict(PG_VALUES, name="pg_new", workspace="topp")

    def test_a_workspace_with_its_own_uri_gets_it_on_the_store(self):
        self.dlg._namespace_uri = lambda ws: "http://example.org/topp"
        self.dlg._create_datastore_from_values(self.values)
        (save,) = self.saved
        self.assertEqual(
            save["connection_parameters"]["namespace"], "http://example.org/topp"
        )
        self.assertEqual(save["connection_parameters"]["passwd"], "crypt1:x")
        self.assertEqual(save["description"], "d")

    def test_nothing_more_is_sent_when_the_uri_already_matches(self):
        self.dlg._namespace_uri = lambda ws: f"http://{ws}"
        self.dlg._create_datastore_from_values(self.values)
        self.assertEqual(self.saved, [])
        # The store was read before the URI was compared: one GET for nothing.
        self.assertEqual(self.gets, ["pg_new"])  # the Add check only


class TestDatastoreEdit(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = RecordingGS(taken={"other"})
        self.dlg._raw_rest = mock.MagicMock()

    def update(self, old_name=None, **extra):
        values = dict(PG_VALUES, **extra)
        self.dlg._update_datastore_from_values(
            values, {"type": "PostGIS", "enabled": True}, STORED, old_name=old_name
        )
        return self.dlg.gs.created[-1]

    def test_a_rename_is_a_put_on_the_old_path_before_the_save(self):
        call = self.update(old_name="pg_old")
        self.dlg._raw_rest.assert_called_once_with(
            "put",
            "/rest/workspaces/topp/datastores/pg_old.json",
            json={"dataStore": {"name": "pg"}},
        )
        # The save then goes to the new name, not a second store at the old one.
        self.assertEqual(call["datastore_name"], "pg")

    def test_a_rename_onto_a_taken_name_sends_nothing(self):
        with self.assertRaises(ValueError):
            self.update(old_name="pg_old", name="other")
        self.dlg._raw_rest.assert_not_called()
        self.assertEqual(self.dlg.gs.created, [])

    def test_an_unchanged_name_is_no_rename(self):
        self.update(old_name="pg")
        self.dlg._raw_rest.assert_not_called()

    def test_every_store_path_is_quoted(self):
        # The delete built its path from the raw names while the rename and
        # the reset quoted theirs.
        self.dlg._do_delete_datastore("a b", "c#d")
        self.dlg._raw_rest.assert_called_once_with(
            "delete",
            "/rest/workspaces/a%20b/datastores/c%23d.json",
            params={"recurse": "true"},
        )

    def test_other_parameters_list_what_the_form_does_not_own(self):
        self.assertEqual(
            self.dlg._other_params("PostGIS", STORED),
            {"Loose bbox": "true", "max connections": "10"},
        )

    def test_other_parameters_edit_remove_and_keep_owned_keys(self):
        # max connections changed, Loose bbox removed, a new key added, and a
        # line naming an owned key is ignored: the typed field wins.
        merged = self.update(
            other_params={"max connections": "20", "fetch size": "500", "host": "evil"}
        )["connection_parameters"]
        self.assertEqual(merged["max connections"], "20")
        self.assertEqual(merged["fetch size"], "500")
        self.assertNotIn("Loose bbox", merged)
        self.assertEqual(merged["host"], "db")
        self.assertEqual(merged["namespace"], "http://topp")
        self.assertEqual(merged["passwd"], "crypt1:PG")

    def test_an_untouched_row_goes_back_as_stored(self):
        # An empty parameter came back as "None", which GeoServer then ran as
        # the session startup SQL of every connection; a number became text.
        stored = dict(STORED, **{"Session startup SQL": None, "max connections": 10})
        form = ResourceFormDialog(
            title="t",
            fields=[{"key": "p", "label": "P", "type": "keyvalue"}],
            values={"p": self.dlg._other_params("PostGIS", stored)},
        )
        pairs = form.get_values()["p"]
        merged = self.dlg._merge_other_params(dict(stored), stored, "PostGIS", pairs)
        self.assertIsNone(merged["Session startup SQL"])
        self.assertEqual(merged["max connections"], 10)
        pairs["Session startup SQL"] = "SET search_path TO x"  # an edit is sent
        merged = self.dlg._merge_other_params(dict(stored), stored, "PostGIS", pairs)
        self.assertEqual(merged["Session startup SQL"], "SET search_path TO x")

    def test_a_masked_other_parameter_keeps_the_stored_value(self):
        stored = dict(STORED, **{"proxy password": "crypt1:X"})
        shown = self.dlg._other_params("PostGIS", stored)
        self.assertEqual(shown["proxy password"], _MASKED)
        merged = self.dlg._merge_other_params(dict(stored), stored, "PostGIS", shown)
        self.assertEqual(merged["proxy password"], "crypt1:X")

    def test_a_secret_typed_in_the_table_keeps_its_edge_spaces(self):
        # The typed password fields kept them; the key/value tables did not.
        stored = dict(STORED, **{"proxy password": "crypt1:X"})
        pairs = {" proxy password ": " new pass ", " fetch size ": " 500 "}
        merged = self.dlg._merge_other_params(dict(stored), stored, "PostGIS", pairs)
        self.assertEqual(merged["proxy password"], " new pass ")
        self.assertEqual(merged["fetch size"], "500")
        self.assertEqual(
            self.dlg._parse_params({"s3.secret-access-key": " k "}),
            {"s3.secret-access-key": " k "},
        )

    def test_an_on_off_flag_is_shown_even_when_its_key_reads_as_a_secret(self):
        # PMTiles stores carry these two, always "true" or "false".
        flags = {
            "io.tileverse.rangereader.s3.use-default-credentials-provider": "false",
            "io.tileverse.rangereader.gcs.default-credentials-chain": "true",
            "io.tileverse.rangereader.s3.aws-secret-access-key": "crypt1:S",
        }
        shown = self.dlg._other_params("PMTiles", dict(flags, pmtiles="s3://b/x"))
        self.assertEqual(
            shown,
            {
                "io.tileverse.rangereader.s3.use-default-credentials-provider": "false",
                "io.tileverse.rangereader.gcs.default-credentials-chain": "true",
                "io.tileverse.rangereader.s3.aws-secret-access-key": _MASKED,
            },
        )


class TestOtherType(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = RecordingGS()

    def test_the_typed_name_and_parameters_go_to_the_library(self):
        self.dlg._create_datastore_from_values(
            {
                "workspace": "topp",
                "name": "props",
                "type": _OTHER,
                "custom_type": " Properties ",
                "raw_params": {"directory": "file:data/props"},
                "description": "",
            }
        )
        (call,) = self.dlg.gs.created
        self.assertEqual(call["datastore_type"], "Properties")
        self.assertEqual(
            call["connection_parameters"], {"directory": "file:data/props"}
        )

    def test_a_blank_type_name_is_refused(self):
        with self.assertRaises(ValueError):
            self.dlg._create_datastore_from_values(
                {
                    "workspace": "topp",
                    "name": "props",
                    "type": _OTHER,
                    "custom_type": "",
                    "raw_params": {},
                    "description": "",
                }
            )
        self.assertEqual(self.dlg.gs.created, [])


class TestDatastoreForm(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()

    def test_other_shows_the_type_name_and_the_parameter_editor(self):
        fields = self.dlg._datastore_fields(["topp"])
        form = ResourceFormDialog(title="t", fields=fields)
        self.dlg._on_type_changed(form, _OTHER)
        self.assertNotIn("custom_type", form._hidden_keys)
        self.assertNotIn("raw_params", form._hidden_keys)
        self.dlg._on_type_changed(form, "PostGIS")
        self.assertIn("raw_params", form._hidden_keys)

    def test_the_advanced_tab_is_for_editing_only(self):
        # In Add it would be an empty tab: a new store has no other parameters.
        add = {f["key"] for f in self.dlg._datastore_fields(["topp"])}
        edit = {f["key"] for f in self.dlg._datastore_fields(["topp"], edit_mode=True)}
        self.assertNotIn("other_params", add)
        self.assertIn("other_params", edit)

    def test_the_generic_editor_does_not_list_the_parameters_twice(self):
        keys = {
            f["key"]
            for f in self.dlg._datastore_fields(["topp"], edit_mode=True, typed=False)
        }
        self.assertIn("raw_params", keys)
        self.assertNotIn("other_params", keys)

    def test_a_type_without_a_form_opens_on_one_page(self):
        # The Advanced tab held one hidden field: an empty page to click on.
        from qgis.PyQt.QtWidgets import QDialog

        from geoserver_manager.gui import tab_datastores

        class GS:
            def get_datastore(inner, ws, name):
                detail = {
                    "type": "Properties",
                    "enabled": True,
                    "connectionParameters": {"entry": {"directory": "file:data/p"}},
                }
                return (detail, 200)

        self.dlg.gs = GS()
        opened = []

        class Recording(ResourceFormDialog):
            def exec(inner):
                opened.append(inner)
                return QDialog.DialogCode.Rejected

        with mock.patch.object(tab_datastores, "ResourceFormDialog", Recording):
            self.dlg._show_datastore_info(["props", "topp", "Properties"])
        (form,) = opened
        self.assertIsNone(form._tabs)
        self.assertIsNone(form.get_widget("other_params"))
        self.assertNotIn("raw_params", form._hidden_keys)


class TestEditFormChecksFirst(unittest.TestCase):
    def test_a_rename_onto_a_taken_name_keeps_the_edit_form_open(self):
        # Refused after the form closed, the whole edit was lost.
        from qgis.PyQt.QtWidgets import QDialog

        from geoserver_manager.gui import tab_datastores

        dlg = SyncDialog()
        dlg.gs = RecordingGS(taken={"pg", "other"})
        seen = {}

        class Filling(ResourceFormDialog):
            def exec(inner):
                for key, text in (
                    ("name", "other"),
                    ("pg_host", "db"),
                    ("pg_db", "d"),
                    ("pg_user", "u"),
                ):
                    inner.get_widget(key).setText(text)
                inner._on_accept()
                seen["open"] = not inner.result()
                seen["said"] = inner._validation_label.text()
                return QDialog.DialogCode.Rejected

        with mock.patch.object(tab_datastores, "ResourceFormDialog", Filling):
            dlg._show_datastore_info(["pg", "topp", "PostGIS"])
        self.assertTrue(seen["open"])
        self.assertIn("already exists", seen["said"])
        self.assertEqual(dlg.gs.created, [])


# A directory store as get_datastore() hands it back.
DIRECTORY = {
    "name": "shp",
    "type": "Directory of spatial files (shapefiles)",
    "enabled": True,
    "description": "old text",
    "workspace": "topp",
    "connectionParameters": {
        "entry": {
            "url": "file:data/sf",
            "charset": "ISO-8859-1",
            "memory mapped buffer": "false",
            "namespace": "http://topp",
        }
    },
}


class LiveGS:
    """One store, which another client edits or deletes while the form is open."""

    def __init__(self):
        self.stored = copy.deepcopy(DIRECTORY)  # None once deleted
        self.created = []

    def get_datastore(self, workspace_name, datastore_name):
        if self.stored is None:
            return ("No such datastore: topp,shp", 404)
        return (copy.deepcopy(self.stored), 200)

    def create_datastore(self, **kwargs):
        # The library POSTs a new store when its GET answers 404.
        self.created.append(kwargs)
        return ("", 200)


class TestEditMeetsTheServerAsItIsNow(unittest.TestCase):
    """Measured on 2.28.5 (review 2026-09-29): the save sent the snapshot the
    form opened with, which reverted another client's edits and recreated a
    store deleted meanwhile, empty, reported as saved."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = self.dlg.gs = LiveGS()
        self.errors, self.successes = [], []
        self.dlg.show_error_message = self.errors.append
        self.dlg.show_success_message = self.successes.append
        self.dlg._warn_if_reaches_nothing = lambda values: None
        self.dlg._load_datastores = lambda: None

    def edit(self, meanwhile, **typed):
        """Open the store's form, let another client change it, type, Save."""
        gs = self.gs

        class Editing(ResourceFormDialog):
            def exec(inner):
                meanwhile(gs)
                for key, text in typed.items():
                    inner.get_widget(key).setText(text)
                return QDialog.DialogCode.Accepted

        with mock.patch.object(tab_datastores, "ResourceFormDialog", Editing):
            self.dlg._show_datastore_info(["shp", "topp", DIRECTORY["type"]])
        return gs.created

    def test_a_store_deleted_meanwhile_is_refused_not_recreated(self):
        def delete(gs):
            gs.stored = None

        self.assertEqual(self.edit(delete, description="new text"), [])
        self.assertIn("no longer on the server", self.errors[0])
        self.assertEqual(self.successes, [])

    def test_what_another_client_changed_meanwhile_survives_the_save(self):
        def reconfigure(gs):
            gs.stored["enabled"] = False
            gs.stored["connectionParameters"]["entry"].update(
                {
                    "charset": "UTF-8",
                    "memory mapped buffer": "true",
                    "cache and reuse memory maps": "true",
                }
            )

        (sent,) = self.edit(reconfigure, description="new text")
        params = sent["connection_parameters"]
        self.assertIs(sent["enabled"], False)
        self.assertEqual(params["charset"], "UTF-8")
        self.assertEqual(params["memory mapped buffer"], "true")
        self.assertEqual(params["cache and reuse memory maps"], "true")
        self.assertEqual(sent["description"], "new text")

    def test_only_what_the_user_changed_is_applied(self):
        def reconfigure(gs):
            gs.stored["description"] = "their text"
            gs.stored["connectionParameters"]["entry"]["charset"] = "UTF-8"

        (sent,) = self.edit(reconfigure, file_url="file:data/other")
        self.assertEqual(sent["connection_parameters"]["url"], "file:data/other")
        self.assertEqual(sent["connection_parameters"]["charset"], "UTF-8")
        # Left out of the PUT, so GeoServer keeps theirs.
        self.assertIsNone(sent["description"])


# GET /rest/workspaces/sf/datastores/sf.json on 2.27: no "type" at all.
UNTYPED = {
    "dataStore": {
        "name": "sf",
        "enabled": True,
        "workspace": {"name": "sf", "href": "http://gs/rest/workspaces/sf.json"},
        "connectionParameters": {
            "entry": [
                {"@key": "url", "$": "file:data/sf"},
                {"@key": "namespace", "$": "http://www.openplans.org/spearfish"},
            ]
        },
    }
}


class UntypedGS:
    """The bundled library over a store GeoServer writes without a type."""

    def __init__(self):
        self.created = []

        class Reply:
            status_code, history = 200, ()
            text = str(UNTYPED)

            def json(inner):
                return copy.deepcopy(UNTYPED)

        class Client:
            def get(inner, path, **kwargs):
                return Reply()

        class Endpoints:
            base_url = "/rest"

            def datastore(inner, ws, name):
                return f"/rest/workspaces/{ws}/datastores/{name}.json"

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

            def resource_exists(inner, path):
                return False  # no layer of that name

        self.rest_service = Rest()

    def get_datastore(self, workspace_name, datastore_name):
        from geoservercloud.models.datastore import DataStore

        # What the library does with that payload: KeyError('type').
        store = DataStore.from_get_response_payload(copy.deepcopy(UNTYPED))
        return store.asdict(), 200

    def create_datastore(self, **kwargs):
        self.created.append(kwargs)
        return ("", 200)


class TestStoreWithoutAType(unittest.TestCase):
    """4 of the 5 demo stores on 2.27, or one POSTed without a type: it
    works, but the library's model raised KeyError('type') on every read."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = self.dlg.gs = UntypedGS()

    def test_it_is_listed_with_no_type(self):
        self.assertEqual(self.dlg._datastore_summary("sf", "sf"), ("-", "Yes"))

    def test_its_name_is_taken_for_a_new_store_and_a_publish(self):
        with self.assertRaises(ValueError) as caught:
            self.dlg._check_new_datastore(
                {"workspace": "sf", "name": "sf", "type": "Shapefile"}
            )
        self.assertIn("already exists", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            self.dlg._refuse_vector_clash("sf", "sf", {"replace": False})
        self.assertIn("already exists", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            self.dlg._refuse_vector_clash("sf", "sf", {"replace": True})
        self.assertIn(
            "Replace only overwrites a GeoPackage store", str(caught.exception)
        )

    def test_it_opens_in_the_parameter_editor_and_saves_without_a_type(self):
        self.dlg._warn_if_reaches_nothing = lambda values: None
        self.dlg._load_datastores = lambda: None
        errors = []
        self.dlg.show_error_message = errors.append
        opened = []

        class Editing(ResourceFormDialog):
            def exec(inner):
                opened.append(inner)
                inner.get_widget("description").setText("Spearfish")
                return QDialog.DialogCode.Accepted

        with mock.patch.object(tab_datastores, "ResourceFormDialog", Editing):
            self.dlg._show_datastore_info(["sf", "sf", "-"])
        self.assertEqual(errors, [])
        (form,) = opened
        self.assertNotIn("raw_params", form._hidden_keys)
        (sent,) = self.gs.created
        # The PUT carries a null type, which GeoServer keeps as none (measured).
        self.assertIsNone(sent["datastore_type"])
        self.assertEqual(sent["connection_parameters"]["url"], "file:data/sf")
        self.assertEqual(sent["description"], "Spearfish")


if __name__ == "__main__":
    unittest.main()
