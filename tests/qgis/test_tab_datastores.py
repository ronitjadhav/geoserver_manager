#! python3  # noqa E265

"""
Datastore edits: a rename is a PUT on the old path, the parameters a typed
form does not own stay editable, and any other store type can be created.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_tab_datastores
"""

from unittest import mock

from qgis.testing import start_app, unittest

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_datastores import _MASKED, _OTHER
from tests.qgis.sync_dialog import SyncDialog

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
        form = ResourceFormDialog(
            title="t", fields=self.dlg._datastore_fields(["topp"], edit_mode=True)
        )
        self.dlg._show_generic_editor(form, "Properties")
        self.assertNotIn("raw_params", form._hidden_keys)
        self.assertIn("other_params", form._hidden_keys)


if __name__ == "__main__":
    unittest.main()
