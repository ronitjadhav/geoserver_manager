#! python3  # noqa E265

"""
A dialog whose tab loads run inline, for tests that assert on the table.

`GeoServerMainDialog` loads every tab in a `QgsTask`, so `_load_x()` returns
before a single row exists. Tests that care about *what* is loaded use the
fetch seam directly (`_fetch_x_rows()` is a plain function returning
`(rows, failures)`); tests that drive a whole loader use this subclass, which
runs the fetch on the calling thread and renders it immediately. Tests that
care about the threading itself use the real dialog — see
`tests/qgis/test_dlg_main.py::TestBackgroundLoading`.
"""

from geoserver_manager.gui.dlg_main import GeoServerMainDialog


class SyncDialog(GeoServerMainDialog):
    """Loads tabs synchronously, reporting failures the way the real one does."""

    def _run_in_task(self, failure_message, work, on_success):
        # No task, so nothing to cancel and no progress to report: work() gets
        # None where the real loader passes the running task.
        try:
            result = work(None)
        except Exception as e:
            detail = self._error_text(e)
            self.show_error_message(f"{failure_message}: {detail}")
            return
        on_success(result)
