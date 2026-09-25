#! python3  # noqa E265

"""
Cancel, close and threading edges from the review: each test failed on the
code before its fix. These drive the real dialog and real QgsTasks, since
SyncDialog replaces exactly the machinery under test.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_cancel_and_threads
"""

import threading
import time
from unittest.mock import patch

from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QApplication
from qgis.testing import start_app, unittest

from geoserver_manager.gui import dlg_main
from geoserver_manager.gui.dlg_main import GeoServerMainDialog
from tests.qgis.sync_dialog import SyncDialog

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


class TestConnection(unittest.TestCase):
    def test_cancelling_the_probe_says_not_connected(self):
        # It stayed on "Connecting…" with the old rows and no client.
        dlg = SyncDialog()
        captured = {}
        dlg._run_in_task = lambda message, work, on_success, **kw: captured.update(kw)
        dlg._build_client = lambda settings: object()
        dlg._populate_rows([["old", "ws"]])
        dlg.refresh_ui()
        captured["on_cancel"](None)
        self.assertEqual(dlg.lbl_status.text(), "Not connected")
        self.assertEqual(dlg._all_rows, [])

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
