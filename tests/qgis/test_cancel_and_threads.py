#! python3  # noqa E265

"""
Cancel, close and threading edges from the review: each test failed on the
code before its fix. These drive the real dialog and real QgsTasks, since
SyncDialog replaces exactly the machinery under test.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_cancel_and_threads
"""

import time
from unittest.mock import patch

from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QApplication
from qgis.testing import start_app, unittest

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
                "layer",
                [("a", refused), ("b", cancel_the_rest), ("c", lambda: None)],
                lambda: None,
                lambda n: f"{n} layers",
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
                "layer",
                [("a", lambda: None)],
                lambda: reloaded.append(1),
                lambda n: f"{n} layers",
            )
        self.assertEqual(reloaded, [])


if __name__ == "__main__":
    unittest.main()
