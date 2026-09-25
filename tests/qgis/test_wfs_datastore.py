#! python3  # noqa E265

"""
A cascaded WFS store has a form of its own, and passwords on edit follow one
rule for every store type: blank keeps the stored one, typed replaces it.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_wfs_datastore
"""

from qgis.testing import start_app, unittest

from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_datastores import _TYPE_SPECIFIC_FIELDS
from tests.qgis.sync_dialog import SyncDialog

start_app()

WFS = "Web Feature Server (NG)"
K = "WFSDataStoreFactory:"
CAPS = "https://remote.example.org/wfs?service=WFS&request=GetCapabilities"


class RecordingGS:
    def __init__(self):
        self.created = []

    def get_datastore(self, workspace_name, datastore_name):
        return ("not found", 404)

    def create_datastore(self, **kwargs):
        self.created.append(kwargs)
        return ("ok", 201)


def form_values(**extra):
    values = {
        "wfs_url": CAPS,
        "wfs_user": "",
        "wfs_password": "",
        "wfs_timeout": 3000,
        "wfs_max_features": 0,
        "wfs_lenient": True,
    }
    values.update(extra)
    return values


class TestWfsParams(unittest.TestCase):
    """The parameter map GeoServer stores for a Web Feature Server (NG) store."""

    def test_a_public_service_sends_no_credentials(self):
        self.assertEqual(
            SyncDialog._wfs_params(form_values()),
            {
                K + "GET_CAPABILITIES_URL": CAPS,
                K + "TIMEOUT": "3000",
                K + "MAXFEATURES": "0",
                K + "LENIENT": "true",
            },
        )

    def test_credentials_travel_when_a_user_is_given(self):
        params = SyncDialog._wfs_params(form_values(wfs_user="bob", wfs_password="s3"))
        self.assertEqual(params[K + "USERNAME"], "bob")
        self.assertEqual(params[K + "PASSWORD"], "s3")

    def test_numbers_and_flags_are_geoserver_style_strings(self):
        params = SyncDialog._wfs_params(
            form_values(wfs_timeout=5000, wfs_max_features=100, wfs_lenient=False)
        )
        self.assertEqual(params[K + "TIMEOUT"], "5000")
        self.assertEqual(params[K + "MAXFEATURES"], "100")
        self.assertEqual(params[K + "LENIENT"], "false")

    def test_a_blank_password_on_edit_keeps_the_stored_ciphertext(self):
        stored = {K + "USERNAME": "bob", K + "PASSWORD": "crypt1:SECRET"}
        params = SyncDialog._wfs_params(form_values(wfs_user="bob"), stored)
        self.assertEqual(params[K + "PASSWORD"], "crypt1:SECRET")

    def test_a_typed_password_replaces_the_stored_one(self):
        stored = {K + "USERNAME": "bob", K + "PASSWORD": "crypt1:SECRET"}
        params = SyncDialog._wfs_params(
            form_values(wfs_user="bob", wfs_password="new"), stored
        )
        self.assertEqual(params[K + "PASSWORD"], "new")

    def test_without_a_user_there_are_no_credentials_at_all(self):
        params = SyncDialog._wfs_params(form_values(wfs_user="", wfs_password="x"))
        self.assertNotIn(K + "USERNAME", params)
        self.assertNotIn(K + "PASSWORD", params)


class TestWfsCreateAndEdit(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.gs = RecordingGS()
        self.dlg.gs = self.gs

    def values(self, **extra):
        values = {"workspace": "topp", "name": "remote", "type": WFS, "description": ""}
        values.update(form_values(**extra))
        return values

    def test_create_goes_through_the_generic_creator_with_the_wfs_type(self):
        self.dlg._create_datastore_from_values(self.values())
        (call,) = self.gs.created
        self.assertEqual(call["datastore_type"], WFS)
        self.assertEqual(
            call["connection_parameters"][K + "GET_CAPABILITIES_URL"], CAPS
        )

    def test_edit_keeps_namespace_the_stored_password_and_the_enabled_flag(self):
        stored = {
            K + "GET_CAPABILITIES_URL": CAPS,
            K + "USERNAME": "bob",
            K + "PASSWORD": "crypt1:SECRET",
            K + "TIMEOUT": "3000",
            K + "MAXFEATURES": "0",
            K + "LENIENT": "true",
            "namespace": "http://topp",
        }
        self.dlg._update_datastore_from_values(
            self.values(wfs_user="bob", wfs_timeout=9000),
            {"type": WFS, "enabled": False},
            stored,
        )
        (call,) = self.gs.created
        merged = call["connection_parameters"]
        self.assertEqual(merged["namespace"], "http://topp")
        self.assertEqual(merged[K + "PASSWORD"], "crypt1:SECRET")
        self.assertEqual(merged[K + "TIMEOUT"], "9000")
        self.assertIs(call["enabled"], False)

    def test_clearing_the_user_drops_both_credentials(self):
        stored = {
            K + "GET_CAPABILITIES_URL": CAPS,
            K + "USERNAME": "bob",
            K + "PASSWORD": "crypt1:SECRET",
        }
        self.dlg._update_datastore_from_values(
            self.values(wfs_user=""), {"type": WFS, "enabled": True}, stored
        )
        merged = self.gs.created[0]["connection_parameters"]
        self.assertNotIn(K + "USERNAME", merged)
        self.assertNotIn(K + "PASSWORD", merged)

    def test_a_postgis_edit_with_a_blank_password_keeps_the_stored_one(self):
        stored = {
            "dbtype": "postgis",
            "host": "db",
            "port": "5432",
            "database": "gis",
            "user": "u",
            "passwd": "crypt1:PG",
            "schema": "public",
        }
        values = {
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
        self.dlg._update_datastore_from_values(
            values, {"type": "PostGIS", "enabled": True}, stored
        )
        merged = self.gs.created[0]["connection_parameters"]
        self.assertEqual(merged["passwd"], "crypt1:PG")


class TestWfsForm(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()

    def test_the_type_is_offered_and_shows_only_its_fields(self):
        fields = self.dlg._datastore_fields(["topp"])
        options = [
            value
            for field in fields
            if field["key"] == "type"
            for _label, value in field["options"]
        ]
        self.assertIn(WFS, options)
        form = ResourceFormDialog(title="t", fields=fields)
        self.dlg._on_type_changed(form, WFS)
        shown = {
            field["key"]
            for field in fields
            if field["key"] in _TYPE_SPECIFIC_FIELDS
            and field["key"] not in form._hidden_keys
        }
        self.assertEqual(
            shown,
            {
                "wfs_url",
                "wfs_user",
                "wfs_password",
                "wfs_timeout",
                "wfs_max_features",
                "wfs_lenient",
            },
        )
        self.dlg._on_type_changed(form, "PostGIS")
        self.assertIn("wfs_url", form._hidden_keys)

    def test_a_password_is_required_only_when_creating_a_postgis_store(self):
        create = {f["key"]: f for f in self.dlg._datastore_fields(["topp"])}
        edit = {
            f["key"]: f for f in self.dlg._datastore_fields(["topp"], edit_mode=True)
        }
        self.assertTrue(create["pg_password"]["required"])
        self.assertFalse(edit["pg_password"]["required"])
        self.assertFalse(create["wfs_password"].get("required", False))

    def test_the_prefill_never_carries_the_password_and_parses_the_numbers(self):
        stored = {
            K + "GET_CAPABILITIES_URL": CAPS,
            K + "USERNAME": "bob",
            K + "PASSWORD": "crypt1:SECRET",
            K + "TIMEOUT": "7000",
            K + "MAXFEATURES": "not a number",
            K + "LENIENT": "false",
        }
        values = self.dlg._datastore_form_values("topp", "remote", WFS, {}, stored)
        self.assertEqual(values["wfs_url"], CAPS)
        self.assertEqual(values["wfs_user"], "bob")
        self.assertEqual(values["wfs_password"], "")
        self.assertEqual(values["wfs_timeout"], 7000)
        self.assertEqual(values["wfs_max_features"], 0)
        self.assertFalse(values["wfs_lenient"])

    def test_the_generic_editor_masks_a_prefixed_password_too(self):
        """Before: only a key *named* password was masked, so a WFS store's
        `WFSDataStoreFactory:PASSWORD` showed its ciphertext in the editor."""
        values = self.dlg._datastore_form_values(
            "topp",
            "x",
            "Oracle NG",
            {},
            {K + "PASSWORD": "crypt1:SECRET", "passwd": "crypt1:PG", "user": "u"},
        )
        self.assertNotIn("crypt1", "".join(values["raw_params"].values()))
        self.assertEqual(values["raw_params"]["user"], "u")


if __name__ == "__main__":
    unittest.main()
