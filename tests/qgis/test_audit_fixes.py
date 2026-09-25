#! python3  # noqa E265

"""
Fixes from the September 2026 audit: each test fails on the code before it.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_audit_fixes
"""

import sys
import time
import types
from unittest.mock import patch

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QMessageBox
from qgis.testing import start_app, unittest

from geoserver_manager.gui import tab_gwc
from geoserver_manager.gui.dlg_main import GeoServerMainDialog
from geoserver_manager.gui.dlg_resource_form import ResourceFormDialog
from geoserver_manager.gui.dlg_settings import ConfigOptionsPage
from tests.qgis.sync_dialog import SyncDialog

start_app()


def spin_until(condition, timeout_ms=8000):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(20)
        waited += 20
    return condition()


class FakeGS:
    def __init__(self, **kwargs):
        pass

    def get_workspaces(self):
        return ([{"name": "ws1"}], 200)

    def get_version(self):
        return ({}, 200)

    class rest_service:
        class rest_client:
            auth = ("a", "b")
            verifytls = True


class Settings:
    geoserver_url = "http://localhost:8080/geoserver"
    geoserver_verify_tls = True

    def has_credentials(self):
        return True

    def get_credentials(self):
        return ("admin", "geoserver")


class Prefs:
    def get_plg_settings(self):
        return Settings()

    def get_profiles(self):
        return []

    def active_profile_name(self):
        return ""

    def get_value_from_key(self, *args, **kwargs):
        return None

    def set_value_from_key(self, *args, **kwargs):
        return True


def connected_dialog():
    """A real dialog whose connection lands through a fake client module."""
    fake = types.ModuleType("geoservercloud")
    fake.GeoServerCloud = FakeGS
    sys.modules["geoservercloud"] = fake
    dlg = GeoServerMainDialog()
    dlg.plg_settings = Prefs()
    dlg._probe = lambda gs, url: None
    dlg.show_error_message = dlg.show_warning_message = lambda text: None
    dlg.show_success_message = lambda text: None
    return dlg


class TestReopenAfterClose(unittest.TestCase):
    """The dialog used to work exactly once per QGIS session: closeEvent set
    _closing and nothing reset it, so the second connection never landed."""

    def test_close_then_reopen_connects_again(self):
        dlg = connected_dialog()
        dlg.show()
        dlg.refresh_ui()
        self.assertTrue(spin_until(lambda: dlg.gs is not None))
        dlg.close()
        QTest.qWait(50)
        dlg.show()
        dlg.refresh_ui()
        self.assertTrue(spin_until(lambda: dlg.gs is not None), "never reconnected")
        self.assertTrue(spin_until(lambda: dlg._task is None))
        self.assertEqual(dlg.btn_refresh.text(), "Refresh")
        dlg._closing = True
        dlg._cancel_load(user=True)


class TestDelKeyIsGuarded(unittest.TestCase):
    """The fifth dispatch point: Del while a Refresh has no client yet."""

    def test_del_with_no_connection_refuses_instead_of_crashing(self):
        dlg = SyncDialog()
        dlg.gs = None
        called = []
        warnings = []
        dlg.show_warning_message = warnings.append
        dlg._delete_selected_callback = called.append
        dlg.btn_delete_selected.setEnabled(True)  # a selection change re-enables it
        dlg.show()
        QApplication.setActiveWindow(dlg)
        dlg.resultsTable.setFocus()
        QTest.keyClick(dlg, Qt.Key.Key_Delete)
        self.assertEqual(called, [])
        self.assertTrue(warnings, "the refusal must say so")
        dlg.close()


class TestBannersStay(unittest.TestCase):
    """An error explains what to do; it must not vanish before it is read."""

    def test_errors_and_warnings_are_sticky_success_fades(self):
        dlg = SyncDialog()
        durations = {}
        dlg.message_bar.pushMessage = lambda title, text, level, duration: (
            durations.__setitem__(title, duration)
        )
        dlg.show_error_message("x")
        dlg.show_warning_message("y")
        dlg.show_success_message("z")
        self.assertEqual(durations["Error"], 0)
        self.assertEqual(durations["Warning"], 0)
        self.assertEqual(durations["Success"], 5)


class TestQuietTask(unittest.TestCase):
    """A dialog's legend fetch must not turn the main Refresh into Cancel."""

    def test_run_quietly_leaves_the_loading_state_alone(self):
        dlg = connected_dialog()
        landed = []

        def work(task):
            time.sleep(0.2)
            return "png"

        dlg._run_quietly("legend", work, landed.append)
        self.assertIsNotNone(dlg._side)
        self.assertEqual(dlg.btn_refresh.text(), "Refresh")
        self.assertFalse(dlg._loading())
        self.assertTrue(spin_until(lambda: landed == ["png"]))
        self.assertIsNone(dlg._side)


class TestEmptyStateWhenDisconnected(unittest.TestCase):
    def test_the_table_says_not_connected_instead_of_no_results(self):
        dlg = SyncDialog()
        dlg.gs = None
        dlg._reset_table_state()
        self.assertIn("Not connected", dlg.lbl_page_info.text())
        dlg._on_nav_changed(0)
        self.assertIn("Not connected", dlg.lbl_page_info.text())


class TestSafeNames(unittest.TestCase):
    def test_path_breaking_characters_are_refused_before_any_request(self):
        dlg = SyncDialog()
        for bad in ("a/b", "a?b", "a#b", "a%b", " a", "a ", ""):
            with self.assertRaises(ValueError, msg=bad):
                dlg._require_safe_name(bad)
        for ok in ("states", "my store", "roads_2024", "a.b-c", "Straße"):
            dlg._require_safe_name(ok)


class TestConfirmationVerbs(unittest.TestCase):
    """The Tile Cache tab stops caching; its confirmation must not say delete."""

    def setUp(self):
        self.dlg = SyncDialog()
        self.dlg.gs = type("GS", (), {"delete_workspace": lambda s, n: ("", 200)})()
        self.dlg._load_workspaces = self.dlg._load_gwc_layers = lambda: None
        self.asked = []
        self.banners = []
        self.dlg.show_success_message = self.banners.append
        self.dlg.show_error_message = self.banners.append

    def ask(self, run):
        def warning(parent, title, text, buttons, default):
            self.asked.append(text)
            return QMessageBox.StandardButton.Yes

        with patch.object(QMessageBox, "warning", staticmethod(warning)):
            run()

    def test_a_delete_reads_as_before(self):
        self.ask(lambda: self.dlg._delete_selected_workspaces([["topp", "uri"]]))
        self.assertIn("delete workspace 'topp'?", self.asked[0])
        self.assertIn("This action cannot be undone.", self.asked[0])
        self.assertNotIn("\n\n\n", self.asked[0])  # one separator, in one place
        self.assertEqual(self.banners, ["Workspace 'topp' deleted."])

    def test_the_tab_can_say_what_it_really_does(self):
        self.dlg._do_remove_gwc_layer = lambda name: None
        self.ask(
            lambda: self.dlg._remove_selected_gwc_layers([["topp:states", "topp"]])
        )
        self.assertIn("stop caching layer 'topp:states'?", self.asked[0])
        self.assertNotIn("delete", self.asked[0].split("This action")[0])
        self.assertEqual(self.banners, ["Layer 'topp:states' removed from the cache."])

    def test_the_sentences_are_whole_so_a_translation_can_agree(self):
        # Glued from "delete", "workspace" and the name, French could not
        # agree its words or order them (review 2026-09-24).
        words = dict(
            ask=self.dlg._one_or_many("Supprimer l'espace '{}' ?", lambda n: f"{n} ?"),
            done=self.dlg._one_or_many("Espace '{}' supprimé.", lambda n: f"{n}."),
        )
        self.ask(
            lambda: self.dlg._delete_many(
                [("topp", lambda: None)], lambda: None, **words
            )
        )
        self.assertTrue(self.asked[0].startswith("Supprimer l'espace 'topp' ?"))
        self.assertEqual(self.banners, ["Espace 'topp' supprimé."])

    def test_failures_name_the_item_and_the_reason(self):
        def boom():
            raise RuntimeError("HTTP 403: referenced by layer group 'x'")

        self.dlg.gs = type(
            "GS",
            (),
            {"delete_workspace": lambda s, n: boom() if n == "a" else ("", 200)},
        )()
        self.ask(lambda: self.dlg._delete_selected_workspaces([["a", ""], ["b", ""]]))
        self.assertEqual(len(self.banners), 1)
        self.assertIn("a: HTTP 403: referenced by layer group 'x'", self.banners[0])

    def test_several_resources_are_counted_by_the_tab_not_with_s(self):
        """Issue #60: "3 workspace(s)" cannot be right in any locale; each tab
        hands in its own plural sentence, translated with the count.
        """
        self.dlg.gs = type("GS", (), {"delete_workspace": lambda s, n: ("", 200)})()
        self.ask(
            lambda: self.dlg._delete_selected_workspaces(
                [["a", ""], ["b", ""], ["c", ""]]
            )
        )
        self.assertIn("  • a\n  • b\n  • c", self.asked[0])
        self.assertTrue(self.banners[0].startswith("3 workspace"))


WORDS = dict(
    ask=GeoServerMainDialog._one_or_many("Delete '{}'?", lambda n: f"Delete {n}?"),
    done=GeoServerMainDialog._one_or_many(
        "'{}' deleted.", lambda n: f"{n} styles deleted."
    ),
)


class TestDeletesRunInATask(unittest.TestCase):
    def test_the_requests_leave_the_gui_thread(self):
        dlg = connected_dialog()
        dlg.gs = object()
        dlg._confirm_delete = lambda *args, **kwargs: True
        reloaded = []
        dlg._delete_many(
            [("a", lambda: time.sleep(0.2))], lambda: reloaded.append(1), **WORDS
        )
        self.assertIsNotNone(dlg._delete)  # still running when the call returned
        self.assertTrue(spin_until(lambda: reloaded == [1]))

    def start(self, count=5, pause=0.1):
        dlg = connected_dialog()
        dlg.gs = object()
        dlg._confirm_delete = lambda *args, **kwargs: True
        self.done, self.reloaded, self.said = [], [], []
        dlg.show_success_message = dlg.show_warning_message = self.said.append
        dlg._delete_many(
            [
                (f"s{i}", lambda i=i: time.sleep(pause) or self.done.append(i))
                for i in range(count)
            ],
            lambda: self.reloaded.append(1),
            **WORDS,
        )
        return dlg

    def test_a_tab_switch_or_refresh_does_not_stop_it(self):
        """A load supersedes the load slot; a delete used to sit in it and
        stopped half way with no banner and no log line."""
        dlg = self.start()
        dlg._start_load("load failed", lambda task: ([], []))  # what a tab switch does
        self.assertTrue(spin_until(lambda: dlg._delete is None))
        self.assertEqual(self.done, [0, 1, 2, 3, 4])
        self.assertIn("5 styles deleted.", self.said)

    def test_it_reloads_only_the_tab_it_started_from(self):
        dlg = self.start(count=2)
        dlg.navList.blockSignals(True)
        dlg.navList.setCurrentRow(dlg.navList.currentRow() + 1)
        dlg.navList.blockSignals(False)
        self.assertTrue(spin_until(lambda: dlg._delete is None))
        self.assertEqual(self.reloaded, [])  # that tab's rows are its own

    def test_the_cancel_button_still_stops_it(self):
        dlg = self.start(count=20)
        spin_until(lambda: self.done)
        dlg._on_refresh_clicked()  # the Refresh button reads Cancel meanwhile
        self.assertTrue(spin_until(lambda: dlg._delete is None))
        self.assertLess(len(self.done), 20)
        self.assertTrue(any("Cancelled" in text for text in self.said))

    def test_a_second_batch_waits_for_the_first(self):
        dlg = self.start(count=3)
        dlg._delete_many([("x", lambda: None)], lambda: None, **WORDS)
        self.assertTrue(any("already running" in text for text in self.said))
        spin_until(lambda: dlg._delete is None)


class TestFormFeedback(unittest.TestCase):
    def test_a_read_only_text_is_copyable_not_greyed(self):
        form = ResourceFormDialog(
            title="t",
            fields=[{"key": "url", "label": "URL", "type": "text", "read_only": True}],
            values={"url": "http://x"},
        )
        widget = form.get_widget("url")
        self.assertTrue(widget.isReadOnly())
        self.assertTrue(widget.isEnabled())

    def test_a_missing_field_is_named_in_words(self):
        form = ResourceFormDialog(
            title="t",
            fields=[{"key": "name", "label": "Name", "type": "text", "required": True}],
        )
        form._on_accept()
        self.assertFalse(form._validation_label.isHidden())
        self.assertEqual(form._validation_label.text(), "'Name' is required.")

    def test_an_empty_combo_says_there_is_nothing_to_pick(self):
        form = ResourceFormDialog(
            title="t",
            fields=[
                {
                    "key": "table",
                    "label": "Table",
                    "type": "combo",
                    "options": [],
                    "required": True,
                }
            ],
        )
        form._on_accept()
        self.assertEqual(
            form._validation_label.text(), "'Table' has nothing to choose from."
        )


class FakeSettings:
    def __init__(self):
        self.debug_mode = False
        self.version = ""
        self.geoserver_verify_tls = True
        self.geoserver_url = "http://old.example.org/geoserver"
        self.geoserver_auth_cfg_id = "authcfg1"
        self.removed = 0

    def save_credentials(self, username, password):
        return "authcfg1"

    def remove_credentials(self):
        self.removed += 1


class FakeManager:
    def __init__(self, settings):
        self.settings = settings

    def get_plg_settings(self):
        return self.settings

    def save_from_object(self, settings):
        pass

    def get_profiles(self):
        return []

    def save_profiles(self, profiles):
        pass

    def active_profile_name(self):
        return ""

    def set_value_from_key(self, key, value):
        return True


class TestSettingsExtras(unittest.TestCase):
    def setUp(self):
        self.page = ConfigOptionsPage(None)
        self.settings = FakeSettings()
        self.page.plg_settings = FakeManager(self.settings)
        self.pushed = []
        self.page.log = (
            lambda message, log_level=None, push=False, **kw: self.pushed.append(
                message
            )
        )

    def test_blank_fields_forget_the_stored_credentials(self):
        self.page.txt_gs_url.setText("https://gs.example.org/geoserver")
        self.page.txt_gs_username.setText("")
        self.page.txt_gs_password.setText("")
        self.page.apply()
        self.assertEqual(self.settings.removed, 1)
        self.assertEqual(self.settings.geoserver_auth_cfg_id, "")

    def test_a_password_in_the_url_is_refused(self):
        self.page.txt_gs_url.setText("https://admin:secret@gs.example.org/geoserver")
        self.page.txt_gs_username.setText("admin")
        self.page.txt_gs_password.setText("secret")
        self.page.apply()
        self.assertEqual(
            self.settings.geoserver_url, "http://old.example.org/geoserver"
        )
        self.assertTrue(any("out of the URL" in m for m in self.pushed), self.pushed)
        with patch("geoserver_manager.gui.dlg_settings.probe") as probe:
            self.page.test_connection()
        probe.assert_not_called()
        self.assertIn("out of the URL", self.page.lbl_test_result.text())


class TestTileCacheXml(unittest.TestCase):
    def test_names_are_escaped_and_odd_numbers_tolerated(self):
        self.assertIn(
            "<name>a&amp;b</name>",
            tab_gwc._NEW_LAYER_XML.format(name=tab_gwc.escape("a&b")),
        )
        self.assertEqual(tab_gwc._int_or_zero("4"), 4)
        self.assertEqual(tab_gwc._int_or_zero("four"), 0)
        self.assertEqual(tab_gwc._int_or_zero(None), 0)


class TestYesNo(unittest.TestCase):
    def test_a_boolean_cell_reads_as_words(self):
        dlg = SyncDialog()
        self.assertEqual(dlg._yes_no(True), "Yes")
        self.assertEqual(dlg._yes_no("true"), "Yes")
        self.assertEqual(dlg._yes_no(False), "No")
        self.assertEqual(dlg._yes_no("False"), "No")
        self.assertEqual(dlg._yes_no(None), "No")


class TestNavTooltips(unittest.TestCase):
    def test_every_tab_explains_itself_on_hover(self):
        dlg = SyncDialog()
        labels = [label for label, _icon, _loader in dlg.TABS]
        self.assertEqual(set(dlg._tab_help()), set(labels))
        for row in range(dlg.navList.count()):
            item = dlg.navList.item(row)
            self.assertTrue(item.toolTip(), item.text())


if __name__ == "__main__":
    unittest.main()
