#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    python -m unittest tests.qgis.test_tab_workspaces
"""

# standard library
import sys
from unittest.mock import patch

from qgis.PyQt.QtWidgets import QDialog
from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui import tab_workspaces
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.tab_workspaces import WorkspaceTabMixin
from geoserver_manager.toolbelt.dependencies import BUNDLED_WHLS
from tests.qgis.sync_dialog import SyncDialog

for _whl in BUNDLED_WHLS:  # conftest does this under pytest; unittest needs it too
    if str(_whl) not in sys.path:
        sys.path.insert(0, str(_whl))

start_app()

# One workspace's WMS settings as GeoServer really answers them: the abstract
# under "abstrct", keywords and SRS wrapped in {"string": …}, and the SRS codes
# as numbers. Everything the form does not model is here too, to prove it is
# left alone.
NE_WMS = {
    "workspace": {"name": "ne"},
    "name": "WMS",
    "enabled": True,
    "title": "GeoServer Natural Earth Maps",
    "abstrct": "Map images generated from Natural Earth data.",
    "keywords": {"string": ["WMS", "GEOSERVER"]},
    "srs": {"string": [4326, 3857]},
    "maxRenderingTime": 60,
    "maxRenderingErrors": 1000,
    "watermark": {"enabled": False, "position": "BOT_RIGHT"},
    "metadataLink": [{"type": "text/html"}],
    "interpolation": "Nearest",
}


# ############################################################################
# ########## Fakes ###############
# ################################


class FakeGS:
    """Workspace 'ne' has its own WMS settings, 'topp' does not."""

    def __init__(self):
        self.calls = []
        outer = self

        class Response:
            def __init__(self, payload=None, status_code=200):
                self._payload = payload if payload is not None else {}
                self.status_code = status_code
                self.text = str(self._payload)

            def json(self):
                return self._payload

        class Client:
            def get(inner, path, **kwargs):
                outer.calls.append(("GET", path, kwargs))
                if path.endswith("/workspaces/default.json"):
                    return Response({"workspace": {"name": "topp"}})
                if path == "/rest/services/wfs/workspaces/ne/settings.json":
                    return Response(
                        {"wfs": {"title": "NE features", "maxFeatures": 50}}
                    )
                if "/workspaces/" in path and path.startswith(
                    ("/rest/services/wfs", "/rest/services/wcs", "/rest/services/wmts")
                ):
                    return Response("No such settings", 404)
                if path == "/rest/services/wfs/settings.json":
                    return Response(
                        {"wfs": {"title": "Global WFS", "maxFeatures": 1000000}}
                    )
                if path.startswith("/rest/namespaces/"):
                    name = path.rsplit("/", 1)[1][: -len(".json")]
                    return Response({"namespace": {"uri": f"http://{name}.org"}})
                return Response({"wms": NE_WMS})

            def put(inner, path, **kwargs):
                outer.calls.append(("PUT", path, kwargs))
                return Response()

            def delete(inner, path, **kwargs):
                outer.calls.append(("DELETE", path, kwargs))
                return Response()

        class Endpoints:
            base_url = "/rest"

            def workspace(inner, name):
                return f"/rest/workspaces/{name}.json"

            def workspace_wms_settings(inner, name):
                return f"/rest/services/wms/workspaces/{name}/settings.json"

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

            def resource_exists(inner, path):
                return Client().get(path).status_code == 200

        self.rest_service = Rest()

    def get_workspaces(self):
        return ([{"name": "ne"}, {"name": "topp"}], 200)

    def get_workspace(self, name):
        return ({"name": name, "isolated": False}, 200)

    def get_workspace_wms_settings(self, workspace_name):
        # The facade is what answers "does this workspace have its own
        # settings"; its payload is missing the fields the form edits.
        self.calls.append(("get_workspace_wms_settings", workspace_name))
        if workspace_name == "ne":
            return ({"enabled": True, "name": "WMS"}, 200)
        return ("No such settings", 404)

    def create_workspace(self, name, isolated=False):
        self.calls.append(("create_workspace", name, isolated))
        return ("", 200)


class Recording(ResourceFormDialog):
    opened = []

    def exec(self):
        Recording.opened.append(self)
        return QDialog.DialogCode.Rejected


# ############################################################################
# ########## Tests ###############
# ################################


class TestWmsFormValues(unittest.TestCase):
    """Reading the settings GeoServer stores, spelling included."""

    def test_reads_the_abstract_from_geoservers_typo_key(self):
        values = WorkspaceTabMixin._wms_form_values(NE_WMS)
        # GeoServer's JSON says "abstrct"; reading "abstract" gives nothing
        self.assertEqual(
            values["wms_abstract"], "Map images generated from Natural Earth data."
        )
        self.assertEqual(values["wms_title"], "GeoServer Natural Earth Maps")
        self.assertTrue(values["wms_own"])
        self.assertTrue(values["wms_enabled"])

    def test_string_lists_are_flattened_for_the_form(self):
        values = WorkspaceTabMixin._wms_form_values(NE_WMS)
        self.assertEqual(values["wms_keywords"], ["WMS", "GEOSERVER"])
        # the codes come back as numbers, and must still read as codes
        self.assertEqual(values["wms_srs"], ["4326", "3857"])

    def test_limits_are_integers_for_the_spinboxes(self):
        values = WorkspaceTabMixin._wms_form_values(NE_WMS)
        self.assertEqual(values["wms_max_rendering_time"], 60)
        self.assertEqual(values["wms_max_rendering_errors"], 1000)

    def test_a_single_keyword_is_not_split_into_letters(self):
        values = WorkspaceTabMixin._wms_form_values(
            {"keywords": {"string": "solo"}, "srs": 4326}
        )
        self.assertEqual(values["wms_keywords"], ["solo"])
        self.assertEqual(values["wms_srs"], ["4326"])

    def test_no_settings_means_the_workspace_uses_the_global_ones(self):
        values = WorkspaceTabMixin._wms_form_values(None)
        self.assertFalse(values["wms_own"])
        self.assertEqual(values["wms_title"], "")
        self.assertEqual(values["wms_max_rendering_time"], 0)
        self.assertTrue(values["wms_enabled"])  # the default for a new one


class TestApplyWmsSettings(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()

    def sent(self, verb):
        return [call for call in self.dlg.gs.calls if call[0] == verb]

    def base_values(self, **overrides):
        values = {
            "wms_own": True,
            "wms_enabled": True,
            "wms_title": "Topp WMS",
            "wms_abstract": "Per-workspace service",
            "wms_keywords": "topp, wms",
            "wms_srs": "4326, 3857",
            "wms_max_rendering_time": 60,
            "wms_max_rendering_errors": 1000,
            "wms_default_locale": "en",
        }
        values.update(overrides)
        return values

    def test_the_put_carries_the_form_fields_and_geoservers_spelling(self):
        self.dlg._apply_wms_settings("topp", self.base_values(), existed=False)
        _verb, path, kwargs = self.sent("PUT")[0]
        self.assertEqual(path, "/rest/services/wms/workspaces/topp/settings.json")
        wms = kwargs["json"]["wms"]
        self.assertEqual(wms["title"], "Topp WMS")
        self.assertEqual(wms["abstrct"], "Per-workspace service")
        self.assertNotIn("abstract", wms)  # the key GeoServer would ignore
        self.assertEqual(wms["keywords"], {"string": ["topp", "wms"]})
        self.assertEqual(wms["srs"], {"string": ["4326", "3857"]})
        self.assertEqual(wms["maxRenderingTime"], 60)
        self.assertEqual(wms["maxRenderingErrors"], 1000)
        self.assertEqual(wms["defaultLocale"], "en")
        self.assertEqual(wms["workspace"], {"name": "topp"})
        # only the modelled fields: GeoServer merges, so sending a template
        # would be the way to wipe the watermark and the metadata links
        self.assertNotIn("watermark", wms)
        self.assertNotIn("metadataLink", wms)

    def test_an_empty_list_field_clears_it(self):
        self.dlg._apply_wms_settings(
            "topp", self.base_values(wms_srs="", wms_keywords=" , "), existed=True
        )
        wms = self.sent("PUT")[0][2]["json"]["wms"]
        self.assertEqual(wms["srs"], {"string": []})
        self.assertEqual(wms["keywords"], {"string": []})

    def test_an_empty_locale_is_sent_as_an_empty_string_never_null(self):
        """A null defaultLocale NPEs in GeoServer's LocaleConverter (500)."""
        self.dlg._apply_wms_settings(
            "topp", self.base_values(wms_default_locale="  "), existed=True
        )
        self.assertEqual(self.sent("PUT")[0][2]["json"]["wms"]["defaultLocale"], "")

    def test_unticking_own_settings_removes_them(self):
        self.dlg._apply_wms_settings(
            "ne", self.base_values(wms_own=False), existed=True
        )
        self.assertEqual(
            [path for _verb, path, _kw in self.sent("DELETE")],
            ["/rest/services/wms/workspaces/ne/settings.json"],
        )
        self.assertEqual(self.sent("PUT"), [])

    def test_a_workspace_that_never_had_its_own_is_left_alone(self):
        self.dlg._apply_wms_settings(
            "topp", self.base_values(wms_own=False), existed=False
        )
        self.assertEqual(self.sent("PUT"), [])
        self.assertEqual(self.sent("DELETE"), [])

    def test_existence_is_asked_of_the_library(self):
        self.assertIsNone(self.dlg._wms_settings("topp"))  # 404 -> no settings
        self.assertIn(("get_workspace_wms_settings", "topp"), self.dlg.gs.calls)
        self.assertEqual(self.dlg._wms_settings("ne"), NE_WMS)

    def test_a_rename_moves_the_settings_to_the_new_name(self):
        values = self.base_values(name="ne_renamed", isolated=False, set_default=False)
        with patch.object(type(self.dlg), "_put_workspace", lambda *a: None):
            self.dlg._save_workspace_and_wms(values, old_name="ne", had_wms=True)
        _verb, path, _kwargs = self.sent("PUT")[-1]
        self.assertIn("/workspaces/ne_renamed/settings.json", path)


class TestWorkspaceDialog(unittest.TestCase):
    def setUp(self):
        Recording.opened.clear()  # class-level: order must not matter
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        self.dlg.show_success_message = lambda text: None

    def open_for(self, workspace_name):
        with patch.object(tab_workspaces, "ResourceFormDialog", Recording):
            self.dlg._show_workspace_info([workspace_name])
        return Recording.opened[-1]

    def test_the_wms_group_is_prefilled_and_visible(self):
        form = self.open_for("ne")
        self.assertTrue(form.get_widget("wms_own").isChecked())
        self.assertEqual(
            form.get_widget("wms_title").text(), "GeoServer Natural Earth Maps"
        )
        self.assertEqual(form.get_widget("wms_srs").list(), ["4326", "3857"])
        self.assertEqual(form.get_widget("wms_max_rendering_time").value(), 60)
        self.assertNotIn("wms_title", form._hidden_keys)

    def test_without_its_own_settings_the_wms_fields_are_out_of_the_way(self):
        form = self.open_for("topp")
        self.assertFalse(form.get_widget("wms_own").isChecked())
        for key in ("wms_enabled", "wms_title", "wms_srs"):
            self.assertIn(key, form._hidden_keys)

    def test_ticking_own_settings_reveals_the_fields(self):
        form = self.open_for("topp")
        form.get_widget("wms_own").setChecked(True)
        self.assertNotIn("wms_title", form._hidden_keys)
        form.get_widget("wms_own").setChecked(False)
        self.assertIn("wms_title", form._hidden_keys)

    def test_creating_a_workspace_offers_no_wms_group(self):
        # The settings can only be PUT once the workspace exists.
        keys = [field["key"] for field in self.dlg._workspace_fields()]
        self.assertEqual(keys, ["name", "uri", "isolated", "set_default"])
        with_wms = [field["key"] for field in self.dlg._workspace_fields(with_wms=True)]
        self.assertIn("wms_own", with_wms)

    def test_the_default_workspace_checkbox_still_locks_itself(self):
        form = self.open_for("topp")  # the fake's default workspace
        self.assertTrue(form.get_widget("set_default").isChecked())
        self.assertFalse(form.get_widget("set_default").isEnabled())


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()


class TestNamespaceAndOtherServices(unittest.TestCase):
    """Measured on 2.28.5: per-workspace WFS/WCS/WMTS settings behave like
    WMS (404 without, PUT creates or merges, DELETE falls back), and a PUT of
    the namespace URI alone merges."""

    def setUp(self):
        Recording.opened.clear()
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        self.dlg.show_success_message = lambda text: None

    def open_for(self, workspace_name):
        with patch.object(tab_workspaces, "ResourceFormDialog", Recording):
            self.dlg._show_workspace_info([workspace_name])
        return Recording.opened[-1]

    def calls(self, verb):
        return [call for call in self.dlg.gs.calls if call[0] == verb]

    def test_own_settings_are_prefilled_and_shown(self):
        form = self.open_for("ne")
        self.assertEqual(form.get_widget("uri").text(), "http://ne.org")
        self.assertTrue(form.get_widget("wfs_own").isChecked())
        self.assertEqual(form.get_widget("wfs_title").text(), "NE features")
        self.assertEqual(form.get_widget("wfs_max_features").value(), 50)
        self.assertFalse(form.get_widget("wcs_own").isChecked())
        self.assertIn("wcs_title", form._hidden_keys)

    def test_without_own_settings_the_form_starts_from_the_global_ones(self):
        # A fresh WFS override would otherwise start at maxFeatures 0.
        form = self.open_for("topp")
        self.assertFalse(form.get_widget("wfs_own").isChecked())
        self.assertEqual(form.get_widget("wfs_title").text(), "Global WFS")
        self.assertEqual(form.get_widget("wfs_max_features").value(), 1000000)

    def save(self, workspace_name, had, **changes):
        values = {"name": workspace_name, "isolated": False, "set_default": False}
        values.update({"uri": "http://ne.org", "wms_own": False})
        for service in tab_workspaces.OTHER_SERVICES:
            values.update(
                {
                    f"{service}_own": False,
                    f"{service}_enabled": True,
                    f"{service}_title": "",
                    f"{service}_abstract": "",
                    f"{service}_keywords": "",
                }
            )
        values["wfs_max_features"] = 0
        values.update(changes)
        self.dlg._save_workspace_and_wms(
            values, workspace_name, False, had, "http://ne.org"
        )

    def test_ticking_own_puts_them_and_unticking_deletes_them(self):
        self.save("topp", {}, wcs_own=True, wcs_title="Coverages", wcs_keywords="a, b")
        (put,) = [c for c in self.calls("PUT") if "/services/" in c[1]]
        self.assertEqual(put[1], "/rest/services/wcs/workspaces/topp/settings.json")
        self.assertEqual(put[2]["json"]["wcs"]["title"], "Coverages")
        self.assertEqual(put[2]["json"]["wcs"]["keywords"], {"string": ["a", "b"]})
        self.dlg.gs.calls.clear()
        self.save("ne", {"wfs": True})
        self.assertEqual(
            [c[1] for c in self.calls("DELETE")],
            ["/rest/services/wfs/workspaces/ne/settings.json"],
        )

    def test_a_changed_uri_is_put_and_an_unchanged_one_is_not(self):
        self.save("ne", {})
        self.assertFalse([c for c in self.calls("PUT") if "/namespaces/" in c[1]])
        self.save("ne", {}, uri="http://example.org/ne")
        (put,) = [c for c in self.calls("PUT") if "/namespaces/" in c[1]]
        self.assertEqual(
            put[2]["json"], {"namespace": {"uri": "http://example.org/ne"}}
        )
