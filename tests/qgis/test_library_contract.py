#! python3  # noqa E265

"""
Lock the parts of geoservercloud's behaviour the plugin relies on, using the
bundled wheel itself — no server needed.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_library_contract
"""

# standard library
import inspect
import re
import sys

from qgis.testing import unittest

# project
from geoserver_manager.toolbelt.dependencies import BUNDLED_WHLS, GSC_REQUIRED

for _whl in BUNDLED_WHLS:  # conftest does this under pytest; unittest needs it too
    if str(_whl) not in sys.path:
        sys.path.insert(0, str(_whl))

from geoservercloud import GeoServerCloud  # noqa: E402
from geoservercloud.models.datastore import DataStore  # noqa: E402
from geoservercloud.models.workspace import Workspace  # noqa: E402

# ############################################################################
# ########## Classes #############
# ################################


class TestBundledVersion(unittest.TestCase):
    def test_pin_matches_the_bundled_wheel(self):
        """dependencies.GSC_REQUIRED must be the version actually shipped."""
        wheel = [w for w in BUNDLED_WHLS if w.name.startswith("geoservercloud-")][0]
        self.assertTrue(wheel.exists(), wheel)
        version = re.match(r"geoservercloud-([\d.]+)-", wheel.name).group(1)
        self.assertEqual(version, GSC_REQUIRED)


class TestDatastoreUpdateContract(unittest.TestCase):
    """_update_datastore_from_values merges onto the fetched parameters and
    hands the result to create_datastore(). These assertions fail if the
    library changes the shape that merge relies on.
    """

    def test_create_datastore_accepts_what_the_plugin_passes(self):
        params = inspect.signature(GeoServerCloud.create_datastore).parameters
        for name in (
            "workspace_name",
            "datastore_name",
            "datastore_type",
            "connection_parameters",
            "description",
            "enabled",
        ):
            self.assertIn(name, params)

    def test_put_payload_sends_the_whole_parameter_map_and_enabled(self):
        merged = {"host": "h", "max connections": "20", "Loose bbox": "false"}
        payload = DataStore("ws", "store", merged, type="PostGIS", enabled=False)
        body = payload.put_payload()["dataStore"]

        # GeoServer replaces connectionParameters wholesale, so every key we
        # merged must be present in what is sent…
        sent = {e["@key"]: e["$"] for e in body["connectionParameters"]["entry"]}
        self.assertEqual(sent, merged)
        # …and a disabled store must be sent as disabled, not dropped/defaulted.
        self.assertIs(body["enabled"], False)
        self.assertEqual(body["type"], "PostGIS")

    def test_workspace_rename_payload_shape(self):
        """_rename_workspace PUTs Workspace(new_name, isolated).put_payload()."""
        self.assertEqual(
            Workspace("new", True).put_payload(),
            {"workspace": {"name": "new", "isolated": True}},
        )


class TestRestClientPolicy(unittest.TestCase):
    """_check exists because these statuses are *not* raised by the library."""

    def test_which_statuses_pass_through(self):
        from geoservercloud.services import restclient

        src = inspect.getsource(restclient.RestClient)
        self.assertIn("if response.status_code != 404:", src)  # GET / DELETE
        self.assertIn("if response.status_code != 409:", src)  # POST
        self.assertTrue(hasattr(restclient, "TIMEOUT"))
        self.assertNotIn("timeout", inspect.signature(restclient.RestClient).parameters)


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
