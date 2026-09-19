#! python3  # noqa E265

"""What a banner shows of a response body, and a rewindable upload body."""

import io
import unittest

from geoserver_manager.toolbelt.rest import ProgressReader, summarise_body


class TestSummariseBody(unittest.TestCase):
    def test_geoservers_own_reason_survives_first_line_only(self):
        body = "Unable to delete layer referenced by layer group 'x'\nmore\nlines"
        self.assertEqual(
            summarise_body(body), "Unable to delete layer referenced by layer group 'x'"
        )

    def test_a_long_line_is_cut(self):
        self.assertEqual(len(summarise_body("x" * 1000)), 300)

    def test_a_tomcat_error_page_becomes_its_title(self):
        page = "<!doctype html><html><head><title>HTTP Status 500 – Internal Server Error</title></head><body><h1>NullPointerException</h1><pre>at org.geoserver…</pre></body></html>"
        self.assertEqual(
            summarise_body(page), "HTTP Status 500 – Internal Server Error"
        )

    def test_an_ogc_exception_report_keeps_its_words(self):
        xml = '<?xml version="1.0"?>\n<ServiceExceptionReport><ServiceException code="LayerNotDefined">Could not find layer x</ServiceException></ServiceExceptionReport>'
        self.assertIn("Could not find layer x", summarise_body(xml))
        self.assertNotIn("<", summarise_body(xml))

    def test_empty_is_empty(self):
        self.assertEqual(summarise_body(""), "")
        self.assertEqual(summarise_body(None), "")


class TestProgressReaderRewind(unittest.TestCase):
    def test_a_redirect_can_resend_the_body_from_the_start(self):
        progress = []
        body = ProgressReader(
            io.BytesIO(b"0123456789"), 10, on_progress=progress.append
        )
        self.assertEqual(body.read(4) + body.read(), b"0123456789")
        self.assertEqual(body.tell(), 10)
        body.seek(0)
        self.assertEqual(body.tell(), 0)
        self.assertEqual(body.read(), b"0123456789")
        self.assertEqual(progress, [40, 100, 100])  # reported again after the rewind

    def test_only_a_rewind_is_supported(self):
        body = ProgressReader(io.BytesIO(b"abc"), 3)
        with self.assertRaises(OSError):
            body.seek(1)


if __name__ == "__main__":
    unittest.main()
