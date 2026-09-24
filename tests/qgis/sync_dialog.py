#! python3  # noqa E265

"""
A dialog whose tab loads run inline, for tests that assert on the table.

`GeoServerMainDialog` loads every tab in a `QgsTask`, so `_load_x()` returns
before a single row exists. Tests that care about *what* is loaded use the
fetch seam directly (`_fetch_x_rows()` is a plain function returning
`(rows, failures)`); tests that drive a whole loader use this subclass, which
runs the fetch on the calling thread and renders it immediately. Tests that
care about the threading itself use the real dialog; see
`tests/qgis/test_dlg_main.py::TestBackgroundLoading`.
"""

from geoserver_manager.gui.dlg_main import GeoServerMainDialog
from geoserver_manager.toolbelt.rest import PartlySaved


class SyncDialog(GeoServerMainDialog):
    """Loads tabs, and uploads, synchronously, reporting failures the way the real one does."""

    def _launch_task(
        self,
        slot,
        failure_message,
        work,
        on_success,
        on_cancel,
        busy_text=None,
        quiet=False,
        on_done=None,
    ):
        # No task, so nothing to cancel and no progress to report: work() gets
        # None where the real dialog passes the running task. Both _run_in_task
        # and _run_upload come through here.
        try:
            result = work(None)
        except PartlySaved as e:  # as the real dialog: saved, then a step failed
            self.show_warning_message(str(e))
            self._reload_current_tab()
            if on_done is not None:
                on_done("done")
            return
        except Exception as e:
            detail = self._error_text(e)
            self.show_error_message(f"{failure_message}: {detail}")
            if on_done is not None:
                on_done("failed")
            return
        on_success(result)
        if on_done is not None:
            on_done("done")
