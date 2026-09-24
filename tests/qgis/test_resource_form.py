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


class TestReadOnlyAndWideFields(unittest.TestCase):
    """Review of 2026-09-23: read-only boxes looked editable, and a style's
    definition sat squeezed beside its label."""

    def test_a_read_only_box_reads_as_text(self):
        from qgis.PyQt.QtWidgets import QPlainTextEdit

        dlg = ResourceFormDialog(
            title="t",
            fields=[
                {"key": "srs", "label": "SRS", "type": "text", "read_only": True},
                {
                    "key": "abstract",
                    "label": "Abstract",
                    "type": "textarea",
                    "read_only": True,
                },
                {"key": "name", "label": "Name", "type": "text"},
            ],
        )
        self.assertFalse(dlg.get_widget("srs").hasFrame())
        self.assertEqual(
            dlg.get_widget("abstract").frameShape(), QPlainTextEdit.Shape.NoFrame
        )
        self.assertTrue(dlg.get_widget("name").hasFrame())  # editable stays a box

    def test_a_wide_code_field_spans_the_form_without_wrapping(self):
        from qgis.PyQt.QtWidgets import QPlainTextEdit

        dlg = ResourceFormDialog(
            title="t",
            fields=[
                {
                    "key": "body",
                    "label": "Definition",
                    "type": "textarea",
                    "wide": True,
                    "code": True,
                }
            ],
        )
        label, _row = dlg._row_widgets["body"]
        self.assertTrue(label.isHidden())
        self.assertEqual(
            dlg.get_widget("body").lineWrapMode(), QPlainTextEdit.LineWrapMode.NoWrap
        )


# ############################################################################
# ####### Stand-alone run ########
# ################################
if __name__ == "__main__":
    unittest.main()


class TestResourceFormHeight(unittest.TestCase):
    """The form opens tall enough for its wrapped text."""

    def test_wrapped_help_text_is_not_clipped(self):
        # A top-level window ignores height-for-width, so a form whose
        # description and help text wrap opened too short and squeezed its rows.
        from qgis.PyQt.QtWidgets import QApplication

        help_text = "A hint long enough to wrap onto a second and a third line. " * 2
        fields = [
            {"key": "name", "label": "Name", "type": "text"},
            {"key": "a", "label": "Isolated", "type": "checkbox", "help": help_text},
            {"key": "b", "label": "Default", "type": "checkbox", "help": help_text},
            {"key": "own", "label": "Own", "type": "checkbox", "group": "WMS"},
        ] + [
            {"key": f"w{i}", "label": "Title", "type": "text", "group": "WMS"}
            for i in range(12)
        ]
        dlg = ResourceFormDialog(
            title="t", description="A description that wraps. " * 6, fields=fields
        )
        # The workspace form hides its WMS fields until "Own" is ticked.
        for i in range(12):
            dlg.set_field_visible(f"w{i}", False)
        # How short it opened depended on the scale factor; at 2x it was
        # clipped badly. Opening at the minimum size shows it at any scale.
        dlg.resize(dlg.minimumSizeHint())
        dlg.show()
        QApplication.processEvents()
        needed = dlg.layout().totalHeightForWidth(dlg.width())
        self.assertGreaterEqual(dlg.height(), needed)
        dlg.close()


class TestResourceFormResize(unittest.TestCase):
    """A resized form scrolls or grows; it never squeezes or overlaps."""

    def show(self, fields, size=None):
        from qgis.PyQt.QtWidgets import QApplication

        dlg = ResourceFormDialog(title="t", fields=fields)
        dlg.show()
        if size:
            dlg.resize(*size)
        QApplication.processEvents()
        self.addCleanup(dlg.close)
        return dlg

    def test_hidden_rows_leave_no_gap(self):
        # A datastore form hides the other types' parameters: Qt 5 kept
        # their row spacing, and the tab opened on a blank band.
        fields = [
            {"key": f"h{i}", "label": "Hidden", "type": "text", "visible": False}
            for i in range(10)
        ] + [{"key": "shown", "label": "Shown", "type": "text"}]
        dlg = self.show(fields)
        self.assertLess(dlg.get_widget("shown").parentWidget().y(), 20)

    def test_a_tall_form_scrolls_instead_of_squeezing(self):
        # Laid out straight in the dialog, it could not be shorter than all
        # its rows, and wrapped help was drawn over the next row.
        fields = [
            {"key": f"f{i}", "label": "Field", "type": "text", "help": "A hint"}
            for i in range(30)
        ]
        dlg = self.show(fields, size=(460, 300))
        page = dlg._field_page["f0"]
        self.assertEqual(dlg.height(), 300)
        self.assertGreater(page.verticalScrollBar().maximum(), 0)
        field = dlg.get_widget("f0")
        self.assertGreaterEqual(field.height(), field.sizeHint().height())

    def test_a_list_grows_with_the_dialog_and_keeps_its_help_close(self):
        fields = [
            {
                "key": "rows",
                "label": "Rows",
                "type": "table",
                "columns": [{"label": "Name"}],
                "help": "Uncapped: takes the height.",
            },
            {"key": "words", "label": "Words", "type": "list", "help": "Capped."},
        ]
        dlg = self.show(fields, size=(700, 900))
        table, words = dlg.get_widget("rows"), dlg.get_widget("words")
        self.assertGreater(table.height(), 300)
        wrapper = words.parentWidget().layout()
        help_label = wrapper.itemAt(1).widget()
        self.assertLess(help_label.y() - words.geometry().bottom(), 10)

    def test_a_long_choice_does_not_widen_the_form(self):
        # A long layer or style name once set the whole dialog's width.
        fields = [{"key": "c", "label": "C", "type": "combo", "options": ["x" * 300]}]
        dlg = self.show(fields)
        self.assertLess(dlg.minimumSizeHint().width(), 600)

    def test_a_missing_field_below_the_fold_is_scrolled_into_view(self):
        fields = [
            {"key": f"f{i}", "label": "Field", "type": "text"} for i in range(30)
        ] + [{"key": "last", "label": "Last", "type": "text", "required": True}]
        dlg = self.show(fields, size=(460, 300))
        page = dlg._field_page["last"]
        dlg._on_accept()
        last = dlg.get_widget("last")
        top = last.mapTo(page.viewport(), last.rect().topLeft()).y()
        self.assertTrue(0 <= top < page.viewport().height())


class TestLongTextOpensAtItsStart(unittest.TestCase):
    def test_a_long_value_shows_its_beginning(self):
        # A long title or URL used to open scrolled to its end.
        dlg = ResourceFormDialog(
            title="t",
            fields=[{"key": "url", "label": "URL", "type": "text"}],
            values={"url": "http://example.org/" + "x" * 300},
        )
        self.assertEqual(dlg.get_widget("url").cursorPosition(), 0)
        dlg.set_values({"url": "http://other.example.org/" + "y" * 300})
        self.assertEqual(dlg.get_widget("url").cursorPosition(), 0)
