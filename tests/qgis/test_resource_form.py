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
        from qgis.gui import QgsCodeEditorHTML
        from qgis.PyQt.Qsci import QsciScintilla

        dlg = ResourceFormDialog(
            title="t",
            fields=[
                {
                    "key": "body",
                    "label": "Definition",
                    "type": "textarea",
                    "wide": True,
                    "code": "xml",
                }
            ],
            values={"body": "<sld/>"},
        )
        label, _row = dlg._row_widgets["body"]
        self.assertTrue(label.isHidden())
        body = dlg.get_widget("body")
        # QGIS's editor: highlighted, the user's code colours and font.
        self.assertIsInstance(body, QgsCodeEditorHTML)
        self.assertEqual(body.wrapMode(), QsciScintilla.WrapMode.WrapNone)
        self.assertEqual(dlg.get_values()["body"], "<sld/>")
        dlg.set_values({"body": "<other/>"})
        self.assertEqual(dlg.get_values()["body"], "<other/>")

    def test_passwords_and_files_use_qgis_widgets(self):
        # A password can be checked with QGIS's eye toggle, and a file
        # dropped on its box is taken.
        from qgis.gui import QgsFileWidget, QgsPasswordLineEdit

        dlg = ResourceFormDialog(
            title="t",
            fields=[
                {"key": "pw", "label": "P", "type": "text", "echo_password": True},
                {"key": "f", "label": "F", "type": "file", "filter": "SLD (*.sld)"},
            ],
            values={"pw": "secret", "f": "/tmp/a.sld"},
        )
        self.assertIsInstance(dlg.get_widget("pw"), QgsPasswordLineEdit)
        self.assertIsInstance(dlg.get_widget("f"), QgsFileWidget)
        self.assertEqual(dlg.get_values(), {"pw": "secret", "f": "/tmp/a.sld"})


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


class TestKeyedOptions(unittest.TestCase):
    """A combo shows a label and hands back its value, so the label can be
    translated without breaking the code that compares it (#91)."""

    def test_the_value_comes_back_and_the_label_is_shown(self):
        seen = []
        dlg = ResourceFormDialog(
            title="t",
            fields=[
                {
                    "key": "source",
                    "label": "Source",
                    "type": "combo",
                    "options": [("Une table", "table"), ("Une couche", "qgis")],
                }
            ],
        )
        combo = dlg.get_widget("source")
        dlg.on_value_changed("source", seen.append)
        self.assertEqual(combo.currentText(), "Une table")
        self.assertEqual(dlg.get_values()["source"], "table")
        dlg.set_values({"source": "qgis"})
        self.assertEqual(combo.currentText(), "Une couche")
        self.assertEqual(seen, ["qgis"])

    def test_plain_options_still_hand_back_their_text(self):
        dlg = ResourceFormDialog(
            title="t",
            fields=[{"key": "t", "label": "T", "type": "combo", "options": ["a", "b"]}],
            values={"t": "b"},
        )
        self.assertEqual(dlg.get_values()["t"], "b")


class TestListValues(unittest.TestCase):
    """What a list, key/value or table field hands back (review 2026-09-24)."""

    def form(self, fields, values=None):
        return ResourceFormDialog(title="t", fields=fields, values=values)

    def test_an_empty_row_is_not_a_keyword_named_null(self):
        from qgis.PyQt.QtWidgets import QToolButton

        dlg = self.form(
            [{"key": "k", "label": "K", "type": "list"}], {"k": ["roads", "  "]}
        )
        # + pressed, then Esc: QGIS's row holds a NULL, whose str() is "NULL"
        dlg.get_widget("k").findChild(QToolButton, "addButton").click()
        self.assertEqual(dlg.get_values()["k"], ["roads"])

    def test_a_value_never_typed_is_blank_not_none(self):
        from qgis.core import NULL

        dlg = self.form([{"key": "p", "label": "P", "type": "keyvalue"}])
        dlg.get_widget("p").setMap({"STYLES": NULL, "": "x"})
        self.assertEqual(dlg.get_values()["p"], {"STYLES": ""})

    def test_an_empty_parameter_opens_blank(self):
        # GeoServer writes one without a value; the library reads it as None.
        dlg = self.form(
            [{"key": "p", "label": "P", "type": "keyvalue"}],
            {"p": {"Session startup SQL": None, "max connections": 10}},
        )
        self.assertEqual(
            dlg.get_values()["p"],
            {"Session startup SQL": "", "max connections": "10"},
        )

    def test_a_name_picked_but_not_added_stops_save(self):
        dlg = self.form(
            [
                {
                    "key": "t",
                    "label": "Styles",
                    "type": "table",
                    "choices": ["a"],
                    "columns": [{"label": "Style"}],
                }
            ]
        )
        dlg.get_widget("t").picker.setCurrentText("a")
        dlg._on_accept()
        self.assertFalse(dlg.result())
        self.assertIn("'a' is picked in 'Styles'", dlg._validation_label.text())

    def test_a_unique_list_does_not_take_a_name_twice(self):
        dlg = self.form(
            [
                {
                    "key": "t",
                    "label": "T",
                    "type": "table",
                    "unique": True,
                    "columns": [{"label": "Gridset"}],
                }
            ],
            {"t": ["EPSG:4326"]},
        )
        table = dlg.get_widget("t")
        table.picker.setCurrentText("EPSG:4326")
        table._add_picked()
        self.assertEqual(table.rows(), ["EPSG:4326"])


class TestCrsPicker(unittest.TestCase):
    def test_the_button_fills_the_code_from_qgis_crs_picker(self):
        from unittest.mock import patch

        from qgis.core import QgsCoordinateReferenceSystem

        from geoserver_manager.gui import dlg_resource_form

        shown = []

        class Picker:
            def __init__(self, parent):
                pass

            def setCrs(self, crs):  # noqa: N802
                shown.append(crs.authid())

            def exec(self):
                return True

            def crs(self):
                return QgsCoordinateReferenceSystem("EPSG:3857")

        dlg = ResourceFormDialog(
            title="t",
            fields=[{"key": "srs", "label": "SRS", "type": "text", "crs": True}],
            values={"srs": "4326"},  # a bare code, as the publish form takes it
        )
        edit = dlg.get_widget("srs")
        (action,) = edit.actions()
        with patch.object(dlg_resource_form, "QgsProjectionSelectionDialog", Picker):
            action.trigger()
        self.assertEqual(shown, ["EPSG:4326"])  # opened on the current code
        self.assertEqual(dlg.get_values()["srs"], "EPSG:3857")

    def test_a_code_qgis_does_not_know_can_still_be_typed(self):
        dlg = ResourceFormDialog(
            title="t",
            fields=[{"key": "srs", "label": "SRS", "type": "text", "crs": True}],
            values={"srs": "EPSG:900913"},
        )
        self.assertEqual(dlg.get_values()["srs"], "EPSG:900913")


class TestExtentField(unittest.TestCase):
    def test_an_area_reads_as_its_corners_in_the_forms_crs(self):
        from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle
        from qgis.PyQt.QtWidgets import QLineEdit

        dlg = ResourceFormDialog(
            title="t", fields=[{"key": "area", "label": "Area", "type": "extent"}]
        )
        self.assertEqual(dlg.get_values()["area"], "")
        dlg.set_extent_crs("area", "EPSG:4326")
        self.assertEqual(dlg.get_widget("area").findChild(QLineEdit).text(), "")
        dlg.get_widget("area").setOutputExtentFromUser(
            QgsRectangle(1.5, 2, 3, 4), QgsCoordinateReferenceSystem("EPSG:4326")
        )
        self.assertEqual(dlg.get_values()["area"], "1.5, 2.0, 3.0, 4.0")


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
