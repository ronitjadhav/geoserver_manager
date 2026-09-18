#! python3  # noqa E265

"""
Keyboard shortcuts, theme-safe colours and the remembered tab.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_ux
"""

from unittest.mock import patch

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication
from qgis.testing import start_app, unittest

from geoserver_manager.gui import dlg_main
from geoserver_manager.gui.theme import (
    contrast_ratio,
    hint_colour,
    is_dark,
    status_colour,
)
from tests.qgis.sync_dialog import SyncDialog

start_app()


def palette_for(window, text):
    """A palette with the given window and text colours."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(window))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(text))
    return palette


LIGHT = palette_for("#f0f0f0", "#202020")
DARK = palette_for("#232629", "#eff0f1")  # roughly QGIS's Night Mapping


class FakeGS:
    """Enough for a tab to load with no rows."""

    def get_workspaces(self):
        return ([], 200)

    def get_styles(self, workspace_name=None):
        return ([], 200)


class TestThemeColours(unittest.TestCase):
    """Literal red / green / gray is what this replaces."""

    def test_dark_and_light_palettes_are_told_apart(self):
        self.assertTrue(is_dark(DARK))
        self.assertFalse(is_dark(LIGHT))

    def test_every_status_colour_is_readable_on_its_background(self):
        # 3:1 is WCAG's floor for large or bold text, which the status line is.
        for palette, name in ((LIGHT, "light"), (DARK, "dark")):
            background = palette.color(QPalette.ColorRole.Window)
            for kind in ("ok", "error", "busy"):
                colour = status_colour(kind, palette)
                ratio = contrast_ratio(colour, background)
                self.assertGreaterEqual(
                    ratio, 3.0, f"{kind} on {name}: {colour} is {ratio:.1f}:1"
                )

    def test_the_colours_differ_between_the_two_themes(self):
        """A single pair cannot serve both, which was the bug."""
        for kind in ("ok", "error", "busy"):
            self.assertNotEqual(status_colour(kind, LIGHT), status_colour(kind, DARK))

    def test_ok_and_error_stay_distinguishable_from_each_other(self):
        for palette in (LIGHT, DARK):
            self.assertNotEqual(
                status_colour("ok", palette), status_colour("error", palette)
            )

    def test_neutral_leaves_the_palette_alone(self):
        self.assertIsNone(status_colour("neutral", LIGHT))
        self.assertIsNone(status_colour("anything else", DARK))

    def test_hint_text_is_visible_without_shouting(self):
        for palette, name in ((LIGHT, "light"), (DARK, "dark")):
            background = palette.color(QPalette.ColorRole.Window)
            ratio = contrast_ratio(hint_colour(palette), background)
            self.assertGreater(ratio, 1.5, f"hint on {name} is {ratio:.1f}:1")

    def test_contrast_ratio_matches_the_wcag_extremes(self):
        self.assertAlmostEqual(contrast_ratio("#000000", "#ffffff"), 21.0, places=1)
        self.assertAlmostEqual(contrast_ratio("#777777", "#777777"), 1.0, places=1)


class TestStatusLine(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()

    def test_a_kind_becomes_a_stylesheet_colour(self):
        self.dlg._set_status("Connected — http://gs", "ok")
        self.assertIn("Connected", self.dlg.lbl_status.text())
        expected = status_colour("ok", self.dlg.palette())
        self.assertIn(expected, self.dlg.lbl_status.styleSheet())

    def test_neutral_clears_the_stylesheet_rather_than_guessing(self):
        self.dlg._set_status("something", "ok")
        self.dlg._set_status("plain", "neutral")
        self.assertEqual(self.dlg.lbl_status.styleSheet(), "")


class TestKeyboardShortcuts(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = FakeGS()
        self.dlg.show_warning_message = lambda text: None
        self.dlg.show_error_message = lambda text: None
        self.dlg.show_success_message = lambda text: None
        self.refreshed = []
        self.dlg.refresh_ui = lambda show_message=False: self.refreshed.append(
            show_message
        )
        self.dlg.show()
        # Offscreen, a window is not active until it is told to be, and an
        # inactive window's widgets never report focus.
        QApplication.setActiveWindow(self.dlg)
        QApplication.processEvents()

    def tearDown(self):
        self.dlg.close()

    def table_with_rows(self, callback):
        """A loaded table, the way a tab loader leaves it."""
        self.dlg._setup_table(["Name", self.dlg.actions_column_label()])
        self.dlg._populate_rows([["ws1"], ["ws2"]])
        self.dlg._setup_delete_selected_button(callback)

    def test_f5_refreshes(self):
        QTest.keyClick(self.dlg, Qt.Key.Key_F5)
        self.assertEqual(self.refreshed, [True])

    def test_ctrl_f_jumps_to_the_search_box_and_selects_what_is_there(self):
        self.dlg.searchBox.setText("roads")
        self.dlg.resultsTable.setFocus()
        QApplication.processEvents()
        QTest.keyClick(self.dlg, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        self.assertTrue(self.dlg.searchBox.hasFocus())
        self.assertEqual(self.dlg.searchBox.selectedText(), "roads")

    def test_escape_clears_a_search_but_still_closes_an_empty_dialog(self):
        self.dlg.searchBox.setText("roads")
        QTest.keyClick(self.dlg, Qt.Key.Key_Escape)
        self.assertEqual(self.dlg.searchBox.text(), "")
        self.assertTrue(self.dlg.isVisible())  # cleared, not closed

        QTest.keyClick(self.dlg, Qt.Key.Key_Escape)
        self.assertFalse(self.dlg.isVisible())  # nothing to clear: Esc closes

    def test_delete_deletes_the_selection_when_the_table_has_focus(self):
        deleted = []
        self.table_with_rows(deleted.append)
        self.dlg.resultsTable.selectRow(1)
        self.dlg.resultsTable.setFocus()
        QApplication.processEvents()
        self.assertTrue(self.dlg.btn_delete_selected.isEnabled())

        QTest.keyClick(self.dlg.resultsTable, Qt.Key.Key_Delete)
        self.assertEqual(deleted, [[["ws2"]]])

    def test_delete_while_typing_in_the_search_box_deletes_nothing(self):
        """The dangerous one: Del must not reach the resources from a text field."""
        deleted = []
        self.table_with_rows(deleted.append)
        self.dlg.resultsTable.selectRow(0)
        self.dlg.searchBox.setText("ws")
        self.dlg.searchBox.setFocus()
        QApplication.processEvents()
        self.assertTrue(self.dlg.btn_delete_selected.isEnabled())  # a row is selected

        # Sent to the dialog, as it would arrive if the line edit let it
        # through: the handler itself has to refuse, not the line edit.
        QTest.keyClick(self.dlg, Qt.Key.Key_Delete)
        self.assertEqual(deleted, [])

        # And the ordinary path: the line edit consumes it to erase a character.
        QTest.keyClick(self.dlg.searchBox, Qt.Key.Key_Delete)
        self.assertEqual(deleted, [])

    def test_delete_does_nothing_when_the_button_is_disabled(self):
        deleted = []
        self.table_with_rows(deleted.append)
        self.dlg.resultsTable.clearSelection()
        self.dlg.resultsTable.setFocus()
        QApplication.processEvents()
        self.assertFalse(self.dlg.btn_delete_selected.isEnabled())

        QTest.keyClick(self.dlg.resultsTable, Qt.Key.Key_Delete)
        self.assertEqual(deleted, [])

    def test_the_shortcuts_are_written_in_the_tooltips(self):
        self.assertIn("F5", self.dlg.btn_refresh.toolTip())
        self.assertIn("Del", self.dlg.btn_delete_selected.toolTip())
        self.assertIn("Ctrl+F", self.dlg.searchBox.toolTip())


class TestRememberedTab(unittest.TestCase):
    """The dialog reopens where it was left, when that tab still exists."""

    class Settings:
        def __init__(self, stored=None):
            self.stored = stored or {}

        def get_value_from_key(self, key, default=None, exp_type=None):
            return self.stored.get(key, default)

        def set_value_from_key(self, key, value):
            self.stored[key] = value
            return True

        def get_plg_settings(self):
            raise AssertionError("not needed for this test")

        def save_from_object(self, settings):
            return True

    def dialog_with(self, stored):
        """A dialog built the way the plugin builds it, on stubbed settings.

        The settings have to be in place *during* __init__, which is when the
        navigation is built — assigning them afterwards would test nothing.
        """
        with patch.object(dlg_main, "PlgOptionsManager", lambda: self.Settings(stored)):
            return SyncDialog()

    def test_it_opens_on_the_remembered_tab(self):
        dlg = self.dialog_with({"last_tab": 3})
        self.assertEqual(dlg.navList.currentRow(), 3)

    def test_a_tab_that_no_longer_exists_falls_back_to_the_first(self):
        dlg = self.dialog_with({"last_tab": 99})
        self.assertEqual(dlg.navList.currentRow(), 0)

    def test_nonsense_in_the_settings_is_not_a_crash(self):
        for value in ("not a number", None, "", [1]):
            dlg = self.dialog_with({"last_tab": value})
            self.assertEqual(dlg.navList.currentRow(), 0, repr(value))

    def test_closing_writes_the_current_tab_down(self):
        dlg = self.dialog_with({})
        dlg.navList.setCurrentRow(2)
        dlg._store_settings()
        self.assertEqual(dlg.plg_settings.stored["last_tab"], 2)


if __name__ == "__main__":
    unittest.main()
