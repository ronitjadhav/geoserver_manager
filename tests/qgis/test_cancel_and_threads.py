#! python3  # noqa E265

"""
Cancel, close and threading edges from the review: each test failed on the
code before its fix. These drive the real dialog and real QgsTasks, since
SyncDialog replaces exactly the machinery under test.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_cancel_and_threads
"""

import shutil
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qgis.core import Qgis, QgsApplication
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QApplication
from qgis.testing import start_app, unittest

from geoserver_manager.gui import dlg_main
from geoserver_manager.gui.dlg_main import GeoServerMainDialog
from geoserver_manager.toolbelt import log_handler
from geoserver_manager.toolbelt.rest import UploadCancelled
from tests.qgis.sync_dialog import SyncDialog
from tests.qgis.test_i18n import Spy

start_app()


def settle(until, timeout=10.0):
    """Process events until until() is true, or fail after timeout seconds."""
    deadline = time.monotonic() + timeout
    while not until():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        QApplication.processEvents()
        time.sleep(0.01)


class TestTasks(unittest.TestCase):
    def setUp(self):
        self.dlg = GeoServerMainDialog()
        self.addCleanup(self.dlg.close)
        self.messages = []
        self.dlg.show_error_message = lambda t: self.messages.append(("error", t))
        self.dlg.show_warning_message = lambda t: self.messages.append(("warning", t))
        self.dlg.show_success_message = lambda t: self.messages.append(("success", t))

    def test_a_cancel_after_the_upload_completed_is_a_success(self):
        # Reported as cancelled, it said the data file was gone and stopped
        # a batch, although the server had stored everything.
        outcome = []

        def work(task):
            task.completed = True  # what _upload_file marks after its PUT
            task.cancel()  # the user pressed Cancel just too late

        self.dlg._launch_task(
            "_upload",
            "Failed",
            work,
            lambda result: outcome.append("success"),
            lambda task: outcome.append("cancelled"),
            on_done=outcome.append,
        )
        settle(lambda: self.dlg._upload is None and outcome)
        self.assertEqual(outcome, ["success", "done"])

    def test_a_cancelled_delete_batch_still_reports_its_failures(self):
        def refused():
            raise RuntimeError("HTTP 403: referenced by layer group 'x'")

        def cancel_the_rest():
            self.dlg._delete.cancel()

        with patch.object(self.dlg, "_confirm_delete", return_value=True):
            self.dlg._delete_many(
                [("a", refused), ("b", cancel_the_rest), ("c", lambda: None)],
                lambda: None,
                ask=dlg_main.GeoServerMainDialog._one_or_many(
                    "Delete '{}'?", lambda n: ""
                ),
                done=dlg_main.GeoServerMainDialog._one_or_many(
                    "'{}' deleted.", lambda n: ""
                ),
            )
        settle(lambda: self.dlg._delete is None and self.messages)
        kinds = [kind for kind, _text in self.messages]
        self.assertIn("error", kinds)
        self.assertIn("referenced by layer group", self.messages[-1][1])

    def test_a_failed_load_forgets_the_pending_banner(self):
        # Else a later, unrelated load showed "Resources loaded."
        self.dlg._announce_after_load = "Resources loaded."

        def boom(task):
            raise RuntimeError("HTTP 500")

        self.dlg._launch_task("_task", "Failed", boom, lambda r: None, lambda t: None)
        settle(lambda: self.dlg._task is None)
        self.assertIsNone(self.dlg._announce_after_load)

    def test_the_task_bar_never_shows_the_failure_message(self):
        added = []
        with patch.object(QgsApplication.taskManager(), "addTask", added.append):
            self.dlg._launch_task(
                "_side",
                "Failed to load styles",
                lambda t: None,
                lambda r: None,
                lambda t: None,
                quiet=True,
            )
        self.dlg._side = None
        self.assertNotIn("Failed", added[0].description())

    def test_an_upload_cancelled_before_it_started_removes_its_export(self):
        # run() never ran, so neither did the finally that removes the
        # folder: a full copy of the layer stayed in the temp directory.
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        source = folder / "roads.gpkg"
        source.write_bytes(b"data")
        added = []
        with patch.object(QgsApplication.taskManager(), "addTask", added.append):
            self.dlg._upload_file(
                "Failed",
                None,
                "path",
                source,
                {},
                {},
                print,
                lambda task: None,
                folder=folder,
            )
        task = added[0]
        task.cancel()  # QGIS's task bar, before the thread pool started it
        task.finished(False)  # what the task manager then calls
        self.assertIsNone(self.dlg._upload)
        self.assertFalse(folder.exists())


class CancelledBox:
    """The waiting box, its Cancel pressed as soon as it shows."""

    def __init__(self, *args):
        pass

    def wasCanceled(self):  # noqa: N802
        return True

    def __getattr__(self, name):  # setWindowTitle, show, close...
        return lambda *args: None


class TestLifecycle(unittest.TestCase):
    """Review of 2026-09-24: each test failed on the code before its fix."""

    def setUp(self):
        self.dlg = GeoServerMainDialog()
        self.addCleanup(self.dlg.close)
        self.messages = []
        self.dlg.show_error_message = lambda t: self.messages.append(("error", t))
        self.dlg.show_warning_message = lambda t: self.messages.append(("warning", t))
        self.dlg.show_success_message = lambda t: self.messages.append(("success", t))
        self.release = threading.Event()
        self.addCleanup(self.release.set)

    def wait_box_cancels(self):
        for name, value in (
            ("QProgressDialog", CancelledBox),
            ("_WAIT_BEFORE_BOX", 0.01),
        ):
            patcher = patch.object(dlg_main, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_dialog_shown_again_after_close_takes_its_results(self):
        # The layer tree's Publish shows the dialog without reconnecting:
        # _closing stayed set from the last Close, and the table, the
        # upload's title and style and a batch's next layer were dropped.
        self.dlg.show()
        self.dlg.close()
        self.dlg.show()
        landed = []
        self.dlg._launch_task(
            "_task", "Failed", lambda t: "rows", landed.append, lambda t: None
        )
        settle(lambda: self.dlg._task is None)
        self.assertEqual(landed, ["rows"])

    def test_an_abandoned_save_holds_off_a_refresh_until_it_ends(self):
        # Its remaining requests read self.gs: a profile switch meanwhile
        # sent the rest of the save to the other server.
        self.wait_box_cancels()
        started = threading.Event()
        with self.assertRaises(dlg_main.Abandoned):
            self.dlg._wait_for_save(lambda: started.set() or self.release.wait(5))
        settle(started.is_set)
        self.assertTrue(self.dlg._refuse_while_writing())
        self.assertEqual(self.messages[-1][0], "warning")
        self.release.set()
        settle(lambda: not any(thread.write for thread in dlg_main._RUNNING))
        self.assertFalse(self.dlg._refuse_while_writing())

    def test_cancel_lets_go_of_a_hung_load_at_once(self):
        # cancel() only sets a flag: the button stayed on Cancel until the
        # request returned, up to two minutes.
        started = threading.Event()
        self.dlg._run_in_task(
            "Failed", lambda t: started.set() or self.release.wait(5), print
        )
        task = self.dlg._task
        settle(started.is_set)  # the request is on its way, and hangs
        self.dlg._on_refresh_clicked()  # Cancel
        self.assertIsNone(self.dlg._task)
        self.assertEqual(self.dlg.btn_refresh.text(), "Refresh")
        self.assertEqual(self.messages, [("warning", "Loading cancelled.")])
        self.release.set()
        settle(
            lambda: task.status()
            in (task.TaskStatus.Complete, task.TaskStatus.Terminated)
        )
        QApplication.processEvents()
        self.assertEqual(len(self.messages), 1)  # the late finish stays quiet

    def test_a_load_cancelled_from_the_task_bar_says_so(self):
        # The empty table read "Nothing here yet", as if the server had nothing.
        self.dlg._run_in_task("Failed", lambda t: self.release.wait(5), print)
        self.dlg._task.cancel()  # QGIS's task bar
        self.release.set()
        settle(lambda: self.dlg._task is None)
        self.assertIn(("warning", "Loading cancelled."), self.messages)
        self.assertIn("cancelled", self.dlg.lbl_page_info.text())

    def test_a_cancelled_save_says_it_may_still_land_and_reloads(self):
        # It ran on in its thread and changed the server without a word.
        self.wait_box_cancels()
        reloads = []
        self.dlg._reload_current_tab = lambda: reloads.append(True)
        saved = self.dlg._run_action(
            lambda: self.dlg._wait_for_save(lambda: self.release.wait(5)), "Failed"
        )
        self.assertFalse(saved)
        self.assertIn("may still apply the change", self.messages[-1][1])
        self.release.set()
        settle(lambda: reloads)

    def test_cancel_stops_the_requests_behind_a_sort(self):
        # The abandoned fan-out went on GETting every remaining row.
        self.wait_box_cancels()
        asked = []

        def detail(row):
            asked.append(row[0])
            self.release.wait(0.2)
            return ("x",)

        self.dlg.gs = object()
        self.dlg._row_detail, self.dlg._detail_columns = detail, (1,)
        rows = [[f"r{n}", dlg_main.PENDING] for n in range(100)]
        self.assertFalse(self.dlg._complete_rows(rows))
        time.sleep(1)
        self.assertLess(len(asked), 40)

    def late_cancel_box(self):
        """The waiting box, Cancel pressed in the event pass where the work lands."""
        release, before = self.release, set(dlg_main._RUNNING)

        class LateCancel(CancelledBox):
            def wasCanceled(self):  # noqa: N802
                release.set()
                for thread in dlg_main._RUNNING - before:
                    thread.wait(5000)
                return True

        for name, value in (
            ("QProgressDialog", LateCancel),
            ("_WAIT_BEFORE_BOX", 0.01),
        ):
            patcher = patch.object(dlg_main, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_read_that_lands_as_cancel_is_pressed_is_kept(self):
        # Its value was dropped for an Abandoned.
        self.late_cancel_box()
        value = self.dlg._wait_for(lambda: self.release.wait(5) and "landed")
        self.assertEqual(value, "landed")

    def test_a_save_that_lands_as_cancel_is_pressed_is_a_success(self):
        # "It may still apply the change" was said of a save already done,
        # and the reload, connected after its thread ended, never came.
        self.late_cancel_box()
        value = self.dlg._wait_for_save(lambda: self.release.wait(5) and "saved")
        self.assertEqual(value, "saved")

    def test_a_save_ending_while_its_cancel_is_handled_still_reloads(self):
        # The reload was connected to a finished() already emitted: never ran.
        self.wait_box_cancels()
        reloads = []
        self.dlg._reload_current_tab = lambda: reloads.append(True)
        release, before = self.release, set(dlg_main._RUNNING)

        class EndsTheSave:
            def set(inner):
                release.set()
                for thread in dlg_main._RUNNING - before:
                    thread.wait(5000)

        with self.assertRaises(dlg_main.Abandoned):
            self.dlg._wait_for(
                lambda: self.release.wait(5), write=True, stop=EndsTheSave()
            )
        settle(lambda: reloads, timeout=3)

    def test_a_fast_save_does_not_hold_off_a_refresh(self):
        # Its thread left _RUNNING only once the event loop turned, so every
        # later refresh_ui() in a headless run was refused as "still running".
        self.dlg._wait_for_save(lambda: None)
        self.assertFalse(self.dlg._refuse_while_writing())

    def test_a_delete_batch_ending_after_close_logs_its_failures(self):
        # Only its banner logged them, and a closed dialog shows none.
        logged = []
        self.dlg.log = lambda message, **kwargs: logged.append(message)

        def refused():
            self.release.wait(5)
            raise RuntimeError("HTTP 403: referenced by layer group 'x'")

        with patch.object(self.dlg, "_confirm_delete", return_value=True):
            self.dlg._delete_many(
                [("a", refused)],
                lambda: None,
                ask=dlg_main.GeoServerMainDialog._one_or_many(
                    "Delete '{}'?", lambda n: ""
                ),
                done=dlg_main.GeoServerMainDialog._one_or_many(
                    "'{}' deleted.", lambda n: ""
                ),
            )
        self.dlg.show()
        self.dlg.close()
        self.release.set()
        settle(lambda: self.dlg._delete is None)
        self.assertTrue(any("referenced by layer group" in m for m in logged), logged)

    def test_an_upload_cancelled_after_close_says_what_a_replace_leaves(self):
        # The log read "Failed to publish 'roads': ", and nothing said the
        # store may have lost its data file.
        logged = []
        self.dlg.log = lambda message, **kwargs: logged.append(message)

        def work(task):
            self.release.wait(5)
            if task.isCanceled():
                raise UploadCancelled()

        self.dlg._launch_task(
            "_upload", "Failed to publish 'roads'", work, print, print
        )
        self.dlg.show()
        self.dlg.close()
        self.dlg._upload.cancel()  # QGIS's task bar
        self.release.set()
        settle(lambda: self.dlg._upload is None)
        self.assertTrue(
            any("'roads'" in m and "data file" in m for m in logged), logged
        )

    def test_a_load_dropped_by_close_is_reloaded_when_shown_again(self):
        # Shown again without a refresh (the layer tree's Publish), it said
        # Cancel and "Loading…" over an empty table while nothing ran.
        self.dlg.show()
        self.dlg._run_in_task("Failed", lambda t: self.release.wait(5), print)
        self.dlg.close()
        self.release.set()
        settle(lambda: self.dlg._task is None)
        self.assertEqual(self.dlg.btn_refresh.text(), "Refresh")
        self.assertNotIn("Loading", self.dlg.lbl_page_info.text())
        reloads = []
        self.dlg._reload_current_tab = lambda: reloads.append(True)
        self.dlg.show()
        self.assertEqual(reloads, [True])
        self.dlg.close()
        self.dlg.show()
        self.assertEqual(reloads, [True])  # once, for the load it dropped

    def test_a_load_still_running_when_shown_again_is_reloaded(self):
        # Its request was in flight at Close and returned after the show: the
        # late finish stayed quiet, and the empty table said "Nothing here yet".
        started, landed = threading.Event(), []
        self.dlg.show()
        self.dlg._run_in_task(
            "Failed", lambda t: started.set() or self.release.wait(5), print
        )
        dropped = self.dlg._task
        settle(started.is_set)
        self.dlg.close()
        self.dlg._reload_current_tab = lambda: self.dlg._run_in_task(
            "Failed", lambda t: "rows", landed.append
        )
        self.dlg.show()
        self.release.set()
        settle(
            lambda: self.dlg._task is None
            and dropped.status()
            in (dropped.TaskStatus.Complete, dropped.TaskStatus.Terminated)
        )
        QApplication.processEvents()
        self.assertEqual(landed, ["rows"])
        self.assertEqual(self.messages, [])  # the dropped load stays quiet
        self.assertEqual(self.dlg.btn_refresh.text(), "Refresh")

    def test_a_truncate_runs_off_the_gui_thread(self):
        # Nine writes ran on the GUI thread: a slow server froze QGIS.
        waited = []
        self.dlg._wait_for_save = lambda action: waited.append(action)
        with patch.object(self.dlg, "_confirm_delete", return_value=True):
            self.dlg._truncate_gwc_layer(["topp:states", "topp"])
        self.assertEqual(len(waited), 1)


class TestSignInPage(unittest.TestCase):
    """An expired SSO session answers 200 with a sign-in page (review)."""

    def test_a_json_read_of_it_says_what_it_is(self):
        import json

        try:
            json.loads("<html><title>Sign in</title></html>")
        except ValueError as error:
            text = GeoServerMainDialog._error_text(error)
        self.assertIn("sign-in page", text)

    def test_a_list_read_of_it_shows_its_title_not_its_markup(self):
        page = "<html><head><title>Sign in</title></head><body>" + "x" * 500
        dlg = SyncDialog()
        with self.assertRaises(RuntimeError) as caught:
            dlg._fetch_list(lambda: (page, 200))
        self.assertIn("Sign in", str(caught.exception))
        self.assertNotIn("<html>", str(caught.exception))

    def test_a_list_read_of_it_is_reported_in_the_users_language(self):
        # The banner carried English prose whatever the locale.
        spy = Spy(["GeoServerMainDialog"])
        QCoreApplication.installTranslator(spy)
        self.addCleanup(QCoreApplication.removeTranslator, spy)
        with self.assertRaises(RuntimeError) as caught:
            SyncDialog()._fetch_list(lambda: ("<html>Sign in</html>", 200))
        self.assertTrue(
            str(caught.exception).startswith(
                "[GeoServerMainDialog] Unexpected response"
            ),
            str(caught.exception),
        )

    def test_a_form_check_that_meets_it_says_what_it_is(self):
        # "Expecting value: line 1 column 1 (char 0)" under the form.
        import json

        def check(values):
            return json.loads("<html><title>Sign in</title></html>")

        with self.assertRaises(ValueError) as caught:
            SyncDialog()._form_check(check)({})
        self.assertIn("sign-in page", str(caught.exception))

    def test_a_form_checks_own_refusal_keeps_its_words(self):
        def check(values):
            raise ValueError("Workspace 'topp' already exists.")

        with self.assertRaises(ValueError) as caught:
            SyncDialog()._form_check(check)({})
        self.assertEqual(str(caught.exception), "Workspace 'topp' already exists.")


class TestConnection(unittest.TestCase):
    def test_cancelling_the_probe_says_not_connected(self):
        # It stayed on "Connecting…" with the old rows and no client: the
        # Cancel button let go of the probe, so its on_cancel never ran.
        dlg = GeoServerMainDialog()
        self.addCleanup(dlg.close)
        dlg.show_warning_message = lambda text: None
        release = threading.Event()
        self.addCleanup(release.set)
        dlg._build_client = lambda settings: object()

        def hung_probe(gs, url):
            release.wait(5)  # a host that swallows the request

        dlg._probe = hung_probe
        dlg._populate_rows([["old", "ws"]])
        dlg.refresh_ui()
        task = dlg._task
        dlg._on_refresh_clicked()  # Cancel, while the probe hangs
        self.assertEqual(dlg.lbl_status.text(), "Not connected")
        self.assertEqual(dlg._all_rows, [])
        self.assertEqual(dlg.btn_refresh.text(), "Refresh")
        release.set()
        settle(
            lambda: task.status()
            in (task.TaskStatus.Complete, task.TaskStatus.Terminated)
        )
        QApplication.processEvents()
        self.assertEqual(dlg.lbl_status.text(), "Not connected")

    def test_a_superseded_probe_leaves_the_newer_refresh_alone(self):
        # Its cancel set "Not connected" over the new probe's "Connecting…".
        dlg = SyncDialog()
        captured = []
        dlg._run_in_task = lambda message, work, on_success, **kw: captured.append(
            kw["on_cancel"]
        )
        dlg._build_client = lambda settings: object()
        dlg.refresh_ui()
        dlg.refresh_ui()
        captured[0](SimpleNamespace(superseded=True))
        self.assertEqual(dlg.lbl_status.text(), "Connecting…")

    def test_a_failed_connection_check_is_logged_as_an_error(self):
        # The level went positionally into the logger's application slot,
        # and a message at the default level was dropped.
        dlg = SyncDialog()
        dlg.show_error_message = lambda text: None
        dlg._build_client = lambda settings: object()
        dlg._probe = lambda gs, url: ("Server unreachable", "Is it running?")
        with patch.object(log_handler, "QgsMessageLog") as message_log:
            dlg.refresh_ui()
        levels = [
            call.kwargs["level"]
            for call in message_log.logMessage.call_args_list
            if "Connection check failed" in call.kwargs["message"]
        ]
        self.assertEqual(levels, [Qgis.MessageLevel.Critical])

    def test_a_delete_ending_during_a_refresh_does_not_reload(self):
        # Its load would cancel the probe: "Connecting…" for good.
        dlg = SyncDialog()
        dlg.show_success_message = lambda text: None
        dlg.gs = None  # a Refresh is probing
        reloaded = []
        with patch.object(dlg, "_confirm_delete", return_value=True):
            dlg._delete_many(
                [("a", lambda: None)],
                lambda: reloaded.append(1),
                ask=dlg_main.GeoServerMainDialog._one_or_many(
                    "Delete '{}'?", lambda n: ""
                ),
                done=dlg_main.GeoServerMainDialog._one_or_many(
                    "'{}' deleted.", lambda n: ""
                ),
            )
        self.assertEqual(reloaded, [])


if __name__ == "__main__":
    unittest.main()
