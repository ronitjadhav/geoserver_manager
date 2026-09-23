#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    python -m unittest tests.qgis.test_tab_layergroups
"""

# standard library
import json
from unittest.mock import patch

from qgis.PyQt.QtWidgets import QDialog
from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui import tab_layergroups
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.scope import GLOBAL
from geoserver_manager.gui.tab_layergroups import LayerGroupTabMixin
from tests.qgis.sync_dialog import SyncDialog

start_app()

# A group as GeoServer really answers it: the abstract under "abstractTxt",
# per-publishable styles parallel to the publishables, computed bounds.
TASMANIA = {
    "name": "tasmania",
    "mode": "SINGLE",
    "title": "Tasmania",
    "abstractTxt": "Tasmania from the Digital Chart of the World.",
    "publishables": {
        "published": [
            {"@type": "layer", "name": "topp:tasmania_state_boundaries"},
            {"@type": "layer", "name": "topp:tasmania_roads"},
        ]
    },
    "styles": {"style": ["", {"name": "simple_roads"}]},
    "bounds": {
        "minx": 143.83,
        "maxx": 148.47,
        "miny": -43.64,
        "maxy": -39.57,
        "crs": "EPSG:4326",
    },
}

# GeoServer unwraps a single entry into a bare object instead of a one-item list.
SOLO = {
    "name": "solo",
    "mode": "NAMED",
    "publishables": {"published": {"@type": "layerGroup", "name": "tasmania"}},
    "styles": {"style": ""},
}

ROADS_GROUP = {
    "name": "roads_group",
    "mode": "CONTAINER",
    "workspace": {"name": "topp"},
    "publishables": {"published": [{"@type": "layer", "name": "topp:tasmania_roads"}]},
}


EO_GROUP = {
    "name": "eo_group",
    "mode": "EO",
    "publishables": {"published": {"@type": "layer", "name": "nurc:mosaic"}},
    "styles": {"style": ""},
    "rootLayer": {"name": "topp:tasmania_roads"},
    "rootLayerStyle": {"name": "simple_roads"},
}


# ############################################################################
# ########## Fakes ###############
# ################################


class FakeGS:
    """Two global groups, one in a workspace, and a REST client that records."""

    def __init__(self, broken_workspace=None, exists=False):
        self.broken_workspace = broken_workspace
        self.exists = exists
        self.calls = []
        outer = self

        class Response:
            def __init__(self, payload, status_code=200):
                self._payload = payload
                self.status_code = status_code
                self.text = json.dumps(payload)

            def json(self):
                return self._payload

        class Client:
            def get(inner, path, **kwargs):
                outer.calls.append(("GET", path, kwargs))
                return Response(outer.payload_for(path))

            def post(inner, path, **kwargs):
                outer.calls.append(("POST", path, kwargs))
                return Response({}, 201)

            def put(inner, path, **kwargs):
                outer.calls.append(("PUT", path, kwargs))
                return Response({})

            def delete(inner, path, **kwargs):
                outer.calls.append(("DELETE", path, kwargs))
                return Response({})

        class Endpoints:
            base_url = "/rest"

            def layergroups(inner, workspace_name):
                return f"/rest/workspaces/{workspace_name}/layergroups.json"

            def layergroup(inner, workspace_name, layergroup_name):
                return (
                    f"/rest/workspaces/{workspace_name}"
                    f"/layergroups/{layergroup_name}.json"
                )

        class Rest:
            rest_client = Client()
            rest_endpoints = Endpoints()

            def resource_exists(inner, path):
                outer.calls.append(("EXISTS", path, {}))
                return outer.exists

        self.rest_service = Rest()

    def payload_for(self, path):
        if path == "/rest/layergroups.json":
            return {
                "layerGroups": {
                    "layerGroup": [
                        {"name": "solo", "href": "…"},
                        {"name": "tasmania", "href": "…"},
                        {"name": "eo_group", "href": "…"},
                    ]
                }
            }
        if path == "/rest/layers.json":
            return {
                "layers": {
                    "layer": [{"name": "topp:tasmania_roads"}, {"name": "nurc:mosaic"}]
                }
            }
        for group in (TASMANIA, SOLO, ROADS_GROUP, EO_GROUP):
            if path.endswith(f"/layergroups/{group['name']}.json"):
                return {"layerGroup": group}
        raise AssertionError(f"unexpected GET {path}")

    def get_workspaces(self):
        return ([{"name": "topp"}, {"name": "empty"}], 200)

    def get_layer_groups(self, workspace_name):
        if workspace_name == self.broken_workspace:
            raise RuntimeError("HTTP 500: boom")
        if workspace_name == "topp":
            return ([{"name": "roads_group"}], 200)
        return ([], 200)

    def get_style_definition(self, name, workspace_name=None):
        self.calls.append(("get_style_definition", name, workspace_name))
        if name in ("simple_roads", "disputed"):
            return ({"name": name, "format": "sld"}, 200)
        return ("<html>Not Found</html>", 404)

    def delete_layer_group(self, workspace_name, name):
        self.calls.append(("delete_layer_group", workspace_name, name))
        return ("", 200)


class Recording(ResourceFormDialog):
    opened = []

    def exec(self):
        Recording.opened.append(self)
        return QDialog.DialogCode.Rejected


# ############################################################################
# ########## Tests ###############
# ################################


class TestLayerGroupsTab(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.warnings = []
        self.dlg.show_warning_message = self.warnings.append
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        self.dlg.show_success_message = lambda text: None
        Recording.opened.clear()

    def test_registered_as_a_tab(self):
        loaders = {label: loader for label, _icon, loader in self.dlg.TABS}
        self.assertEqual(loaders["Layer Groups"], "_load_layer_groups")
        self.assertTrue(hasattr(self.dlg, "_load_layer_groups"))

    def test_lists_global_and_workspace_groups_with_mode_and_size(self):
        self.dlg._load_layer_groups()
        self.assertEqual(
            self.dlg._all_rows,
            [
                # GeoServer's own words for the modes, not the enum
                ["eo_group", GLOBAL, "Earth Observation Tree", "1"],
                ["solo", GLOBAL, "Named Tree", "1"],
                ["tasmania", GLOBAL, "Single", "2"],
                ["roads_group", "topp", "Container Tree", "1"],
            ],
        )
        self.assertEqual(self.warnings, [])

    def test_one_unreadable_workspace_keeps_the_rest(self):
        self.dlg.gs = FakeGS(broken_workspace="topp")
        self.dlg._load_layer_groups()
        self.assertEqual(
            [row[0] for row in self.dlg._all_rows], ["eo_group", "solo", "tasmania"]
        )
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("topp", self.warnings[0])


class TestGroupDetail(unittest.TestCase):
    """The detail view reads what GeoServer actually stores."""

    def test_prefill_keeps_the_abstract_the_order_and_the_styles(self):
        values = LayerGroupTabMixin._group_form_values(TASMANIA, "tasmania", GLOBAL)
        # GeoServer writes "abstractTxt"; the library's model reads "abstract"
        # and so loses it; this would be empty if the detail came from there.
        self.assertEqual(
            values["abstract"], "Tasmania from the Digital Chart of the World."
        )
        self.assertEqual(values["title"], "Tasmania")
        self.assertEqual(values["mode"], "Single")
        self.assertEqual(values["workspace"], GLOBAL)
        self.assertEqual(
            values["layers"].splitlines(),
            [
                "topp:tasmania_state_boundaries",
                "topp:tasmania_roads = simple_roads",
            ],
        )
        self.assertIn("143.83, -43.64 → 148.47, -39.57", values["bounds"])
        self.assertIn("EPSG:4326", values["bounds"])

    def test_a_single_publishable_and_a_nested_group_are_not_lost(self):
        values = LayerGroupTabMixin._group_form_values(SOLO, "solo", GLOBAL)
        # The edit form's own syntax: a group is named like a layer.
        self.assertEqual(values["layers"].splitlines(), ["tasmania"])
        self.assertEqual(values["bounds"], "")
        self.assertEqual(values["abstract"], "")

    def test_internationalised_text_is_readable(self):
        values = LayerGroupTabMixin._group_form_values(
            {"internationalTitle": {"en": "Roads", "fr": "Routes"}}, "g", GLOBAL
        )
        self.assertEqual(values["title"], "en: Roads; fr: Routes")

    def test_the_dialog_edits_everything_but_the_name(self):
        # GeoServer answers 403 to a layer group rename.
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        with patch.object(tab_layergroups, "ResourceFormDialog", Recording):
            dlg._show_layer_group_info(["tasmania", GLOBAL])
        form = Recording.opened[-1]
        self.assertFalse(form.get_widget("layers").isReadOnly())
        self.assertTrue(form.get_widget("mode").isEnabled())
        self.assertTrue(form.get_widget("name").isReadOnly())  # copyable, not greyed
        # The group itself is not offered as one of its own members.
        pick = form.get_widget("pick")
        offered = [pick.itemText(i) for i in range(pick.count())]
        self.assertIn("solo", offered)
        self.assertNotIn("tasmania", offered)

    def test_an_earth_observation_group_keeps_its_mode(self):
        # Every way of clearing the root layer is refused by GeoServer.
        dlg = SyncDialog()
        dlg.gs = FakeGS()
        with patch.object(tab_layergroups, "ResourceFormDialog", Recording):
            dlg._show_layer_group_info(["eo_group", GLOBAL])
        form = Recording.opened[-1]
        self.assertFalse(form.get_widget("mode").isEnabled())
        self.assertIn("root_layer", form.get_values())


class TestCreateLayerGroup(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()

    def posted(self):
        return [call for call in self.dlg.gs.calls if call[0] == "POST"]

    def test_global_group_payload(self):
        self.dlg._create_layer_group_from_values(
            {
                "name": "new_group",
                "workspace": GLOBAL,
                "mode": "SINGLE",
                "title": "New",
                "abstract": "Why it exists",
                "layers": "topp:tasmania_roads\nnurc:mosaic\n",
            }
        )
        (_verb, path, kwargs) = self.posted()[0]
        self.assertEqual(path, "/rest/layergroups.json")
        group = kwargs["json"]["layerGroup"]
        self.assertEqual(group["name"], "new_group")
        self.assertEqual(group["mode"], "SINGLE")
        self.assertEqual(
            group["publishables"]["published"],
            [
                {"@type": "layer", "name": "topp:tasmania_roads"},
                {"@type": "layer", "name": "nurc:mosaic"},
            ],
        )
        # GeoServer drops an "abstract" key, which is what the library sends.
        self.assertEqual(group["abstractTxt"], "Why it exists")
        self.assertNotIn("abstract", group)
        # Bounds omitted on purpose: GeoServer computes the layers' union, while
        # the library would write a world bbox from its EPSG table.
        self.assertNotIn("bounds", group)
        self.assertNotIn("styles", group)
        self.assertNotIn("workspace", group)

    def test_workspace_group_qualifies_a_bare_layer_name(self):
        self.dlg._create_layer_group_from_values(
            {
                "name": "ws_group",
                "workspace": "topp",
                "mode": "NAMED",
                "layers": "tasmania_roads\ntopp:states",
            }
        )
        (_verb, path, kwargs) = self.posted()[0]
        self.assertEqual(path, "/rest/workspaces/topp/layergroups.json")
        group = kwargs["json"]["layerGroup"]
        self.assertEqual(group["workspace"], {"name": "topp"})
        self.assertEqual(
            [item["name"] for item in group["publishables"]["published"]],
            ["topp:tasmania_roads", "topp:states"],
        )

    def test_a_workspace_group_refuses_another_workspaces_layer(self):
        # GeoServer answers a bare 500 for it, after the form has closed.
        with self.assertRaises(ValueError) as caught:
            self.dlg._create_layer_group_from_values(
                {
                    "name": "ws_group",
                    "workspace": "topp",
                    "mode": "NAMED",
                    "layers": "tasmania_roads\nne:coastlines",
                }
            )
        self.assertIn("ne:coastlines", str(caught.exception))
        self.assertEqual(self.posted(), [])

    def test_a_style_per_layer_is_sent_parallel_to_the_layers(self):
        self.dlg._create_layer_group_from_values(
            {
                "name": "styled",
                "workspace": GLOBAL,
                "mode": "SINGLE",
                "layers": (
                    "topp:tasmania_state_boundaries\n"
                    "topp:tasmania_roads = simple_roads\n"
                    "ne:coastlines = ne:disputed"
                ),
            }
        )
        group = self.posted()[0][2]["json"]["layerGroup"]
        self.assertEqual(
            [item["name"] for item in group["publishables"]["published"]],
            ["topp:tasmania_state_boundaries", "topp:tasmania_roads", "ne:coastlines"],
        )
        # "" is what GeoServer itself stores for "the layer's own default style"
        self.assertEqual(
            group["styles"]["style"],
            ["", {"name": "simple_roads"}, {"name": "ne:disputed"}],
        )
        # a workspace-qualified style is looked up in its own workspace
        self.assertIn(("get_style_definition", "disputed", "ne"), self.dlg.gs.calls)

    def test_a_style_that_does_not_exist_is_refused_not_dropped(self):
        # GeoServer answers 201 and silently drops an unknown style, which would
        # leave the group rendering with default styles and look like a success.
        with self.assertRaises(ValueError) as caught:
            self.dlg._create_layer_group_from_values(
                {
                    "name": "styled",
                    "workspace": GLOBAL,
                    "mode": "SINGLE",
                    "layers": "topp:tasmania_roads = no_such_style",
                }
            )
        self.assertIn("no_such_style", str(caught.exception))
        self.assertEqual(self.posted(), [])

    def test_parsing_keeps_the_order_and_qualifies_bare_names(self):
        layers, styles = self.dlg._parse_group_layers(" b:two = s2 \n\none\n", "topp")
        self.assertEqual(layers, ["b:two", "topp:one"])
        self.assertEqual(styles, ["s2", ""])

    def test_refuses_an_existing_name(self):
        self.dlg.gs = FakeGS(exists=True)
        with self.assertRaises(ValueError):
            self.dlg._create_layer_group_from_values(
                {
                    "name": "tasmania",
                    "workspace": GLOBAL,
                    "mode": "SINGLE",
                    "layers": "topp:tasmania_roads",
                }
            )
        self.assertEqual(self.posted(), [])

    def test_refuses_an_empty_layer_list(self):
        with self.assertRaises(ValueError):
            self.dlg._create_layer_group_from_values(
                {
                    "name": "empty_group",
                    "workspace": GLOBAL,
                    "mode": "SINGLE",
                    "layers": "  \n\n",
                }
            )
        self.assertEqual(self.posted(), [])

    def test_the_picker_appends_to_the_ordered_list(self):
        dlg = ResourceFormDialog(
            title="t", fields=self.dlg._group_fields(["topp"], ["a:one", "b:two"])
        )
        dlg.get_widget("pick").currentTextChanged.connect(
            lambda choice: self.dlg._append_group_layer(dlg, choice)
        )
        dlg.get_widget("pick").setCurrentText("b:two")
        dlg.get_widget("pick").setCurrentText("b:two")  # same layer twice
        dlg.get_widget("pick").setCurrentText("a:one")
        self.assertEqual(
            dlg.get_values()["layers"].splitlines(), ["b:two", "b:two", "a:one"]
        )
        self.assertEqual(dlg.get_widget("pick").currentIndex(), 0)


class TestEditLayerGroup(unittest.TestCase):
    """Measured on 2.28.5: a partial PUT merges, a new layer list needs one
    style per entry, and the bounds are never recomputed on a PUT."""

    LAYERS = ["topp:tasmania_roads", "nurc:mosaic"]
    GROUPS = ["solo", "tasmania", "topp:roads_group"]

    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.before = LayerGroupTabMixin._group_form_values(
            TASMANIA, "tasmania", GLOBAL
        )

    def save(self, **changes):
        after = dict(self.before, **changes)
        with patch.object(
            LayerGroupTabMixin, "_group_bounds", return_value={"crs": "EPSG:4326"}
        ) as bounds:
            saved = self.dlg._save_layer_group(
                "tasmania", None, self.before, after, self.LAYERS, self.GROUPS
            )
        puts = [call for call in self.dlg.gs.calls if call[0] == "PUT"]
        return saved, puts, bounds

    def test_a_title_edit_sends_only_the_title(self):
        saved, puts, bounds = self.save(title="Tassie", enabled=False)
        self.assertTrue(saved)
        ((_verb, path, kwargs),) = puts
        self.assertEqual(path, "/rest/layergroups/tasmania.json")
        self.assertEqual(
            kwargs["json"], {"layerGroup": {"title": "Tassie", "enabled": False}}
        )
        bounds.assert_not_called()

    def test_nothing_changed_sends_nothing(self):
        saved, puts, _bounds = self.save(layers=self.before["layers"] + "\n\n")
        self.assertFalse(saved)
        self.assertEqual(puts, [])

    def test_new_layers_carry_a_style_each_and_fresh_bounds(self):
        _saved, puts, bounds = self.save(layers="nurc:mosaic\nsolo")
        group = puts[0][2]["json"]["layerGroup"]
        self.assertEqual(
            group["publishables"]["published"],
            [
                {"@type": "layer", "name": "nurc:mosaic"},
                {"@type": "layerGroup", "name": "solo"},
            ],
        )
        self.assertEqual(group["styles"], {"style": ["", ""]})
        self.assertEqual(group["bounds"], {"crs": "EPSG:4326"})
        bounds.assert_called_once()

    def test_an_unknown_name_is_refused_since_geoserver_drops_it(self):
        with self.assertRaises(ValueError) as caught:
            self.save(layers="topp:tasmania_roads\nno_such_group")
        self.assertIn("no_such_group", str(caught.exception))
        self.assertEqual([call for call in self.dlg.gs.calls if call[0] == "PUT"], [])

    def test_turning_into_earth_observation_sends_the_root(self):
        _saved, puts, _bounds = self.save(
            mode="Earth Observation Tree",
            root_layer="topp:tasmania_roads",
            root_style="simple_roads",
        )
        group = puts[0][2]["json"]["layerGroup"]
        self.assertEqual(group["mode"], "EO")
        self.assertEqual(
            group["rootLayer"], {"@type": "layer", "name": "topp:tasmania_roads"}
        )
        self.assertEqual(group["rootLayerStyle"], {"name": "simple_roads"})

    def test_earth_observation_needs_a_root_layer(self):
        with self.assertRaises(ValueError):
            self.save(mode="Earth Observation Tree", root_layer="(pick a layer)")

    def test_a_projected_box_is_reprojected_to_lon_lat(self):
        # spearfish, as GeoServer stores it: EPSG:26713, UTM zone 13N.
        rect = LayerGroupTabMixin._box_in(
            {
                "minx": 589425.9,
                "maxx": 609518.7,
                "miny": 4913959.2,
                "maxy": 4928082.9,
                "crs": {"@class": "projected", "$": "EPSG:26713"},
            },
            tab_layergroups.QgsCoordinateReferenceSystem("EPSG:4326"),
        )
        self.assertAlmostEqual(rect.xMinimum(), -103.87, places=1)
        self.assertAlmostEqual(rect.yMaximum(), 44.5, places=1)

    def test_a_zero_box_counts_as_no_box(self):
        # What GeoServer stores after "bounds": null.
        self.assertIsNone(
            LayerGroupTabMixin._box_in(
                {"minx": 0, "maxx": 0, "miny": 0, "maxy": 0},
                tab_layergroups.QgsCoordinateReferenceSystem("EPSG:4326"),
            )
        )


class TestCreateNestedAndEarthObservation(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()

    def create(self, **values):
        base = {"name": "g", "workspace": GLOBAL, "mode": "Single"}
        self.dlg._create_layer_group_from_values(
            dict(base, **values), ["topp:tasmania_roads"], ["tasmania"]
        )
        return [c for c in self.dlg.gs.calls if c[0] == "POST"][0][2]["json"][
            "layerGroup"
        ]

    def test_a_nested_group_is_sent_with_its_type_and_styles(self):
        # Without styles, GeoServer answers 500 for a group holding a group.
        group = self.create(layers="tasmania\ntopp:tasmania_roads")
        self.assertEqual(
            [item["@type"] for item in group["publishables"]["published"]],
            ["layerGroup", "layer"],
        )
        self.assertEqual(group["styles"], {"style": ["", ""]})

    def test_a_blank_root_style_takes_the_root_layers_default(self):
        with patch.object(
            self.dlg, "_layer_summary", return_value=("VECTOR", "s", "simple_roads")
        ):
            group = self.create(
                mode="Earth Observation Tree",
                layers="topp:tasmania_roads",
                root_layer="topp:tasmania_roads",
                root_style="",
            )
        self.assertEqual(group["rootLayerStyle"], {"name": "simple_roads"})

    def test_a_root_layer_without_a_default_style_asks_for_one(self):
        # A cascaded layer has no default style: "-" is no style name.
        with patch.object(self.dlg, "_layer_summary", return_value=("WMS", "s", "-")):
            with self.assertRaises(ValueError) as caught:
                self.create(
                    mode="Earth Observation Tree",
                    layers="topp:tasmania_roads",
                    root_layer="topp:tasmania_roads",
                    root_style="",
                )
        self.assertIn("no default style", str(caught.exception))


class TestDeleteAndAddToQgis(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.dlg._confirm_delete = lambda kind, labels, cascade="", **kwargs: True
        self.dlg.show_success_message = lambda text: None
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")
        self.dlg._load_layer_groups = lambda: None

    def test_a_name_with_a_hash_is_quoted_in_both_scopes(self):
        """ "a#b" went out as ".../layergroups/a", another group's path."""
        self.dlg._delete_selected_layer_groups([["a#b", "topp", "SINGLE", "1"]])
        self.assertIn(("delete_layer_group", "topp", "a%23b"), self.dlg.gs.calls)
        self.assertIn("/layergroups/a%23b.json", self.dlg._group_path("a#b", "topp"))

    def test_workspace_group_deletes_through_the_library_global_through_rest(self):
        self.dlg._delete_selected_layer_groups(
            [["roads_group", "topp", "CONTAINER", "1"], ["tasmania", GLOBAL, "", "2"]]
        )
        self.assertIn(("delete_layer_group", "topp", "roads_group"), self.dlg.gs.calls)
        self.assertIn(
            ("DELETE", "/rest/layergroups/tasmania.json", {}), self.dlg.gs.calls
        )

    def test_add_to_qgis_uses_the_qualified_name_and_wms(self):
        built = []

        class Settings:
            geoserver_url = "http://gs.example.org/geoserver"
            geoserver_auth_cfg_id = "abc123"

        class PlgSettings:
            def get_plg_settings(inner):
                return Settings()

        class FakeLayer:
            def __init__(inner, uri, name, provider):
                built.append((uri, name, provider))

            def isValid(inner):
                return True

        self.dlg.plg_settings = PlgSettings()
        with (
            patch.object(tab_layergroups, "QgsRasterLayer", FakeLayer),
            patch.object(tab_layergroups.QgsProject, "instance") as instance,
        ):
            self.dlg._add_group_to_qgis(["tasmania", GLOBAL, "SINGLE", "2"])
            self.dlg._add_group_to_qgis(["roads_group", "topp", "CONTAINER", "1"])
        self.assertEqual(instance.call_count, 2)
        self.assertIn("layers=tasmania&", built[0][0])  # global: the bare name
        self.assertIn("layers=topp:roads_group&", built[1][0])
        self.assertIn("authcfg=abc123", built[0][0])
        self.assertEqual([provider for _uri, _name, provider in built], ["wms", "wms"])


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()


class TestPreviewInBrowser(unittest.TestCase):
    """The group's own bounds, global groups without a prefix."""

    def setUp(self):
        class Settings:
            geoserver_url = "http://gs/geoserver"

        class PlgSettings:
            def get_plg_settings(inner):
                return Settings()

        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.dlg.plg_settings = PlgSettings()
        self.dlg.show_error_message = lambda text: self.fail(f"unexpected: {text}")

    def opened(self, row):
        from geoserver_manager.gui import tab_layers

        urls = []
        with patch.object(
            tab_layers.QDesktopServices,
            "openUrl",
            lambda url: urls.append(url.toString()) or True,
        ):
            self.dlg._preview_group_in_browser(row)
        return urls

    def test_a_global_group_previews_without_a_prefix(self):
        (url,) = self.opened(["tasmania", GLOBAL, "SINGLE", "2"])
        self.assertTrue(url.startswith("http://gs/geoserver/wms?"), url)
        self.assertIn("layers=tasmania&", url)

    def test_a_workspace_group_goes_through_its_virtual_service(self):
        (url,) = self.opened(["roads_group", "topp", "CONTAINER", "1"])
        self.assertTrue(url.startswith("http://gs/geoserver/topp/wms?"), url)
        self.assertIn("layers=topp:roads_group", url)

    def test_the_groups_own_bounds_frame_the_map(self):
        self.dlg._group_detail = lambda name, ws: {
            "bounds": {
                "minx": 143.0,
                "miny": -44.0,
                "maxx": 149.0,
                "maxy": -40.0,
                "crs": "EPSG:4326",
            }
        }
        (url,) = self.opened(["tasmania", GLOBAL, "SINGLE", "2"])
        self.assertIn("bbox=143.0,-44.0,149.0,-40.0", url)
        self.assertIn("width=768&height=512", url)

    def test_the_action_is_offered_and_explains_the_login(self):
        self.dlg.show_warning_message = lambda t: None
        self.dlg._load_layer_groups()
        labels = [action[1] for action in self.dlg._row_actions]
        self.assertEqual(labels, ["Add to QGIS", "Preview in a browser", "Delete"])
        self.assertIn("log in", self.dlg._row_actions[1][3])
