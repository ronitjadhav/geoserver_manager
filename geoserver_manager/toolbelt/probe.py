#! python3  # noqa: E265

"""
One bounded request that says whether a GeoServer REST API answers here.

Used by the main dialog before its first table, and by the Settings page's
*Test connection* button, with the fields as typed, saved or not.

TODO(#50): the one request in the plugin that does not go through the
library. `RestClient` hardcodes `timeout=TIMEOUT` (120 s) and takes no
timeout argument, and this is the request the user waits for, so it uses
`requests` directly with PROBE_TIMEOUT: a dead host must cost 10 s, not two
minutes.
"""

import requests
from qgis.PyQt.QtCore import QCoreApplication
from requests.exceptions import SSLError

PROBE_TIMEOUT = 10


def _tr(text):
    return QCoreApplication.translate("ConnectionProbe", text)


def probe(url, auth, verify_tls):
    """Return None when GeoServer answered, else (status, message) to show.

    :param auth: (username, password), HTTP Basic, as the library sends it.
    """
    try:
        response = requests.get(
            f"{url.rstrip('/')}/rest/workspaces.json",
            auth=auth,
            timeout=PROBE_TIMEOUT,
            verify=verify_tls,
        )
    except SSLError:
        # Before OSError (it is a ConnectionError): a private-CA or
        # self-signed certificate used to read as "is the server running?"
        return (
            _tr("Certificate not trusted"),
            _tr(
                "{url} presented a TLS certificate this machine does not trust. "
                "If it is your own private CA or a self-signed certificate, untick "
                '"Verify the server\'s TLS certificate" in Settings.'
            ).format(url=url),
        )
    except OSError:
        # ConnectionError / Timeout: refused, unreachable, wrong host, or a
        # host that swallows the SYN; that one gives up after PROBE_TIMEOUT.
        return (
            _tr("Server unreachable"),
            _tr("Cannot reach GeoServer at {url}. Is the server running?").format(
                url=url
            ),
        )
    except Exception as e:
        return (_tr("Connection error"), _tr("Connection failed: {}").format(e))

    if response.status_code in (401, 403):
        return (
            _tr("Authentication failed"),
            _tr("Authentication failed. Check your username and password in Settings."),
        )
    if response.status_code >= 400:
        # The URL usually points at something that is not a GeoServer REST
        # endpoint at all.
        return (
            _tr("HTTP error {}").format(response.status_code),
            _tr(
                "GeoServer returned HTTP {code} for {url}. Check the URL in Settings."
            ).format(code=response.status_code, url=url),
        )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or "workspaces" not in payload:
        # An SSO / reverse-proxy login page answers 200 with HTML. Without
        # this check it showed a green "Connected" and empty tables.
        return (
            _tr("Not a GeoServer REST endpoint"),
            _tr(
                "{url} answered, but not with the GeoServer REST API (a login "
                "page?). Check the URL, or the proxy in front of it."
            ).format(url=url),
        )
    return None
