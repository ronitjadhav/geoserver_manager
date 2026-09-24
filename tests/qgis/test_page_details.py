#! python3  # noqa E265

"""
Issue #58: a tab lists names first, then fetches the summary columns of the
page on screen only, not every row's before showing any.

Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_page_details
"""

from qgis.testing import start_app, unittest

from geoserver_manager.gui.scope import PENDING
from tests.qgis.sync_dialog import SyncDialog

start_app()


class TestPageDetails(unittest.TestCase):
    def setUp(self):
        self.dlg = SyncDialog()
        self.asked = []
        self.dlg._setup_table(["Name", "Workspace", "Type"])
        self.dlg._row_detail = lambda row: self.asked.append(row[0]) or (
            f"type of {row[0]}",
        )
        self.dlg._detail_columns = (2,)
        self.rows = [[f"store{n:02}", "topp", PENDING] for n in range(45)]

    def test_only_the_page_shown_is_fetched(self):
        # 10,000 GETs for 200 workspaces of 50 stores, before a single row.
        self.dlg._populate_rows(self.rows)
        self.assertEqual(len(self.asked), self.dlg._page_size)
        self.assertEqual(self.rows[0][2], "type of store00")
        self.assertEqual(self.rows[-1][2], PENDING)
        self.assertEqual(self.dlg.resultsTable.item(0, 2).text(), "type of store00")

    def test_the_next_page_fetches_its_own(self):
        self.dlg._populate_rows(self.rows)
        self.dlg._page_next()
        self.assertEqual(len(self.asked), 2 * self.dlg._page_size)
        self.dlg._page_prev()  # already there: nothing asked again
        self.assertEqual(len(self.asked), 2 * self.dlg._page_size)

    def test_sorting_on_a_detail_column_completes_every_row(self):
        self.dlg._populate_rows(self.rows)
        self.dlg._on_header_clicked(2)
        self.assertEqual(len(self.asked), 45)
        self.assertNotIn(PENDING, [row[2] for row in self.rows])

    def test_a_row_action_gets_the_rows_details_first(self):
        # The Layers tab's actions read the type and the store.
        self.dlg._populate_rows(self.rows)
        last = self.rows[-1]
        self.assertTrue(self.dlg._addressable([last]))
        self.assertEqual(last[2], "type of store44")

    def test_a_fill_for_a_table_that_is_gone_is_dropped(self):
        landed = []

        def launch(slot, message, work, on_success, on_cancel, **kwargs):
            landed.append((work, on_success))

        self.dlg._launch_task = launch
        self.dlg._populate_rows(self.rows)
        (work, on_success) = landed[0]
        results = work(None)
        self.dlg._setup_table(["Name", "Other"])  # the user moved on
        on_success(results)
        self.assertEqual(self.rows[0][2], PENDING)

    def test_a_row_that_cannot_be_read_gets_dashes_and_one_warning(self):
        warnings = []
        self.dlg.show_warning_message = warnings.append

        def detail(row):
            if row[0] == "store03":
                raise RuntimeError("HTTP 500: boom")
            return ("ok",)

        self.dlg._row_detail = detail
        self.dlg._populate_rows(self.rows)
        self.assertEqual(self.rows[3][2], "-")
        self.assertEqual(len(warnings), 1)
        self.assertIn("topp:store03", warnings[0])


if __name__ == "__main__":
    unittest.main()
