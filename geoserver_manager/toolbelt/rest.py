#! python3  # noqa: E265

"""
What the dialog needs from the REST client that geoservercloud does not offer:
a raw call that raises with GeoServer's own explanation, and a request body
that reports its progress and stops when asked.

No QGIS import: the unit suite runs this on a plain Python.
"""

import html
import re


def summarise_body(text, limit=300):
    """One line of a response body, for a banner and a log line.

    GeoServer puts the reason in the body ("Unable to delete layer referenced
    by layer group …"), so the first line is kept, cut at `limit`. A Tomcat
    error page or a proxy's login page is markup that explains nothing: an
    HTML or XML body is reduced to its <title> when it has one, else to its
    text.
    """
    text = (text or "").strip()
    if not text:
        return ""
    if text.startswith("<"):
        # Tomcat's page carries GeoServer's reason as its "Message" line
        # ("Invalid style: … (line 1, column 18)"); the title only says 400.
        message = re.search(r"<b>Message</b>(.*?)</p>", text, re.I | re.S)
        if message and message.group(1).strip():
            text = " ".join(html.unescape(message.group(1)).split())
            return text[:limit]
        title = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
        text = title.group(1) if title else re.sub(r"<[^>]+>", " ", text)
        text = " ".join(text.split())
    return text.splitlines()[0][:limit] if text else ""


def raw_rest(client, method, path, **kwargs):
    """Call the library's REST client directly, for what it has no method for.

    Raises RuntimeError carrying GeoServer's response body on any HTTP error,
    so the message the user sees has the same shape as `_check`'s. Every
    caller is a library gap: list it in issue #50 and mark it TODO(#50).
    Module-level so a worker thread can hold the client it was given instead
    of reading `dialog.gs`, which a Refresh clears mid-flight.
    """
    response = getattr(client, method)(path, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(
            f"HTTP {response.status_code}: {summarise_body(response.text)}"
        )
    return response


class UploadCancelled(Exception):
    """Raised inside ProgressReader.read() when the caller asked to stop.

    `requests` lets it out of put() unchanged and urllib3 closes the socket on
    the way, so the transfer stops there instead of running to the end.
    """


class ProgressReader:
    """A file-like body for a streaming PUT that reports and can be stopped.

    `requests` streams anything with read(); __len__ is what gives the request
    its Content-Length. Each read() reports the whole percent sent so far
    through on_progress (QgsTask.setProgress is thread-safe, so the task's
    own method fits), and raises UploadCancelled when is_cancelled() says so.
    """

    def __init__(self, handle, total, on_progress=None, is_cancelled=None):
        self._handle = handle
        self._total = total
        self._on_progress = on_progress
        self._is_cancelled = is_cancelled
        self.sent = 0
        self._reported = None

    def __len__(self):
        return self._total

    def tell(self):
        return self.sent

    def seek(self, offset, whence=0):
        """Rewind, which is all `requests` needs: a redirect (an http:// URL the
        server sends to https://) makes it resend the body from the start."""
        if offset != 0 or whence != 0:
            raise OSError("an upload body can only be rewound to its start")
        self._handle.seek(0)
        self.sent = 0
        self._reported = None

    def read(self, size=-1):
        if self._is_cancelled is not None and self._is_cancelled():
            raise UploadCancelled()
        chunk = self._handle.read(size)
        self.sent += len(chunk)
        if self._on_progress is not None:
            percent = int(100 * self.sent / self._total) if self._total else 100
            if percent != self._reported:
                self._reported = percent
                self._on_progress(percent)
        return chunk
