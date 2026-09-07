#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    # for whole tests
    python -m unittest tests.qgis.test_resource_form
    # for specific test
    python -m unittest tests.qgis.test_resource_form.TestResourceFormDialog.test_required_field_on_other_tab_blocks_save
"""

# standard library
from qgis.testing import start_app, unittest

# project
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog

start_app()

# ############################################################################
# ########## Classes #############
# ################################

FIELDS = [
    {"key": "name", "label": "Name", "type": "text", "required": True},
    # Second group -> rendered on a second tab, hidden while "General" is active
    {
        "key": "host",
        "label": "Host",
        "type": "text",
        "required": True,
        "group": "Connection",
    },
    {
        "key": "token",
        "label": "Token",
        "type": "text",
        "required": True,
        "visible": False,
        "group": "Connection",
    },
]


class TestResourceFormDialog(unittest.TestCase):
    """Validation must depend on what the form asks for, not on which tab is
    currently on screen: Qt reports every widget on an inactive tab as hidden.
    """

    def test_required_field_on_other_tab_blocks_save(self):
        dlg = ResourceFormDialog(title="New", fields=FIELDS)
        dlg.show()  # "General" is the active tab, "Connection" is not
        dlg.get_widget("name").setText("some-name")

        dlg._on_accept()  # host is empty and required
        self.assertFalse(dlg.result())

        dlg.get_widget("host").setText("localhost")
        dlg._on_accept()  # token is required but hidden -> not applicable
        self.assertTrue(dlg.result())

    def test_hidden_field_is_not_required(self):
        dlg = ResourceFormDialog(title="New", fields=FIELDS)
        dlg.show()
        dlg.get_widget("name").setText("some-name")
        dlg.get_widget("host").setText("localhost")

        dlg.set_field_visible("token", True)
        dlg._on_accept()  # now visible and empty -> blocked
        self.assertFalse(dlg.result())

        dlg.set_field_visible("token", False)
        dlg._on_accept()
        self.assertTrue(dlg.result())


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()
