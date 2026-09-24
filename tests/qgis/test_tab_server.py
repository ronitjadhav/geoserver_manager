#! python3  # noqa E265

"""
The Server tab. Measured on 2.28.5: a service's settings merge a partial PUT,
but the global settings, the contact and the logging replace the stored
object, so those are sent whole.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_tab_server
"""

import copy
from unittest.mock import patch

from qgis.PyQt.QtWidgets import QDialog
from qgis.testing import start_app, unittest

from geoserver_manager.gui import tab_server
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_server import ServerTabMixin
from tests.qgis.sync_dialog import SyncDialog

start_app()

CONTACT = {
    "contactPerson": "Claudius Ptolomaeus",
    "contactOrganization": "OSGeo",
    "addressCity": "Alexandria",
    "welcome": "Hello",
}
GLOBAL = {
    "global": {
        "settings": {
            "id": "SettingsInfoImpl-1",
            "contact": CONTACT,
            "charset": "UTF-8",
            "numDecimals": 8,
            "verbose": False,
        },
        "jai": {"tileThreads": 7},
        "updateSequence": 42,
    }
}
WFS = {
    "wfs": {
        "enabled": True,
        "title": "GeoServer Web Feature Service",
        "abstrct": "The reference implementation",
        "keywords": {"string": ["WFS", "GEOSERVER"]},
        "maxFeatures": 1000000,
        "gml": {"entry": []},
    }
}
LOGGING = {
    "logging": {
        "level": "DEFAULT_LOGGING",
        "location": "logs/geoserver.log",
        "stdOutLogging": True,
    }
}


class Response:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return copy.deepcopy(self._payload)


class FakeGS:
    def __init__(self, broken=()):
        self.calls = []
        payloads = {
            "/rest/settings.json": GLOBAL,
            "/rest/settings/contact.json": {"contact": CONTACT},
            "/rest/logging.json": LOGGING,
            "/rest/services/wfs/settings.json": WFS,
            "/rest/services/wms/settings.json": {
                "wms": {"enabled": False, "title": "WMS"}
            },
            "/rest/services/wcs/settings.json": {"wcs": {"title": "WCS"}},
        }
        outer = self

        class Client:
            def get(inner, path, **kwargs):
                outer.calls.append(("GET", path, kwargs))
                if any(path.endswith(f"/{name}/settings.json") for name in broken):
                    return Response("boom", 500)
                return Response(
                    payloads.get(path, {}), 200 if path in payloads else 404
                )

            def put(inner, path, **kwargs):
                outer.calls.append(("PUT", path, kwargs))
                return Response("")

            def post(inner, path, **kwargs):
                outer.calls.append(("POST", path, kwargs))
                return Response("")

        class Endpoints:
            base_url = "/rest"

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

        self.rest_service = Rest()

    def puts(self):
        return [call for call in self.calls if call[0] == "PUT"]


class TestServerTab(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS(broken=("wmts",))
        self.warnings = []
        self.dlg.show_warning_message = self.warnings.append

    def test_registered_without_add_or_delete(self):
        loaders = [loader for _label, _icon, loader in self.dlg.TABS]
        self.assertIn("_load_server", loaders)
        self.dlg._load_server()
        self.assertTrue(self.dlg.btn_add.isHidden())
        self.assertTrue(self.dlg.btn_delete_selected.isHidden())

    def test_one_row_per_section_and_an_unreadable_one_costs_one_warning(self):
        self.dlg._load_server()
        rows = {row[0]: row[1] for row in self.dlg._all_rows}
        self.assertEqual(
            list(rows),
            [
                "Contact",
                "Global settings",
                "WMS",
                "WFS",
                "WCS",
                "WMTS",
                "Logging",
                "Catalog",
            ],
        )
        self.assertEqual(rows["Contact"], "Claudius Ptolomaeus, OSGeo")
        self.assertEqual(rows["Global settings"], "No proxy base URL")
        self.assertEqual(rows["WMS"], "Off: WMS")
        self.assertEqual(rows["WFS"], "On: GeoServer Web Feature Service")
        self.assertEqual(rows["WMTS"], "-")
        self.assertEqual(rows["Logging"], "DEFAULT_LOGGING")
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("WMTS", self.warnings[0])


class TestServerSaves(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()

    def edit(self, kind, **changes):
        settings = self.dlg._server_read(kind)
        before = ServerTabMixin._server_form_values(kind, settings)
        after = dict(before, **changes)
        return self.dlg._save_server_section(kind, before, after)

    def test_a_service_sends_only_what_changed(self):
        self.assertTrue(self.edit("wfs", title="Features", keywords="A\nB\n"))
        ((_verb, path, kwargs),) = self.dlg.gs.puts()
        self.assertEqual(path, "/rest/services/wfs/settings.json")
        self.assertEqual(
            kwargs["json"],
            {"wfs": {"title": "Features", "keywords": {"string": ["A", "B"]}}},
        )

    def test_a_service_without_max_features_never_sends_one(self):
        self.edit("wms", title="Maps")
        self.assertNotIn("maxFeatures", self.dlg.gs.puts()[0][2]["json"]["wms"])

    def test_the_global_settings_go_back_whole_with_the_edit(self):
        # A PUT of the proxy URL alone wiped the contact and the charset.
        self.edit("global", proxy_base_url="https://maps.example.org/geoserver")
        ((_verb, path, kwargs),) = self.dlg.gs.puts()
        self.assertEqual(path, "/rest/settings.json")
        sent = kwargs["json"]["global"]
        self.assertEqual(
            sent["settings"]["proxyBaseUrl"], "https://maps.example.org/geoserver"
        )
        self.assertEqual(sent["settings"]["contact"], CONTACT)
        self.assertEqual(sent["settings"]["charset"], "UTF-8")
        self.assertEqual(sent["jai"], {"tileThreads": 7})

    def test_a_blank_proxy_url_unsets_it(self):
        self.dlg.gs = FakeGS()
        GLOBAL["global"]["settings"]["proxyBaseUrl"] = "https://old.example.org"
        try:
            self.edit("global", proxy_base_url="")
        finally:
            del GLOBAL["global"]["settings"]["proxyBaseUrl"]
        sent = self.dlg.gs.puts()[0][2]["json"]["global"]["settings"]
        self.assertIsNone(sent["proxyBaseUrl"])

    def test_the_contact_goes_back_whole(self):
        # A PUT of the person alone cleared the city.
        self.edit("contact", person="Hypatia")
        sent = self.dlg.gs.puts()[0][2]["json"]["contact"]
        self.assertEqual(sent["contactPerson"], "Hypatia")
        self.assertEqual(sent["addressCity"], "Alexandria")
        self.assertEqual(sent["welcome"], "Hello")

    def test_the_logging_goes_back_whole(self):
        # A PUT of the level alone switched standard-output logging off.
        self.edit("logging", level="VERBOSE_LOGGING")
        sent = self.dlg.gs.puts()[0][2]["json"]["logging"]
        self.assertEqual(sent["level"], "VERBOSE_LOGGING")
        self.assertIs(sent["stdOutLogging"], True)

    def test_nothing_changed_sends_nothing(self):
        for kind in ("wfs", "global", "contact", "logging"):
            self.assertFalse(self.edit(kind))
        self.assertEqual(self.dlg.gs.puts(), [])


class TestLogAndCatalog(unittest.TestCase):
    def test_the_log_keeps_only_its_end(self):
        class Streamed:
            status_code = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def iter_content(self, size):
                for number in range(5000):
                    yield f"line {number}\n".encode()

        class Client:
            url, auth, verifytls = "http://gs", ("u", "p"), True

        with patch.object(tab_server.requests, "get", return_value=Streamed()) as get:
            tail = ServerTabMixin._log_tail(Client(), "/rest/resource/x", 2000, 10)
        self.assertEqual(tail.splitlines()[-1], "line 4999")
        self.assertEqual(len(tail.splitlines()), 10)
        self.assertTrue(get.call_args.kwargs["stream"])

    def test_reload_and_reset_post_to_their_endpoint(self):
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        dlg.show_success_message = lambda text: None
        for choice, endpoint in (("reload", "/rest/reload"), ("reset", "/rest/reset")):

            class Choosing(ResourceFormDialog):
                def exec(inner):
                    return QDialog.DialogCode.Accepted

                def get_values(inner, choice=choice):
                    return {"action": choice}

            with patch.object(tab_server, "ResourceFormDialog", Choosing):
                dlg._reload_or_reset_catalog()
            self.assertEqual(dlg.gs.calls[-1][:2], ("POST", endpoint))


if __name__ == "__main__":
    unittest.main()
