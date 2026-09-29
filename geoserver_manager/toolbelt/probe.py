#! python3  # noqa: E265

"""
One bounded request that says whether a GeoServer REST API answers here.

Used by the main dialog before its first table, and by the Settings page's
*Test connection* button, with the fields as typed, saved or not.

TODO(#50): one of the two requests in the plugin that do not go through the
library (the other streams the server log, see tab_server._log_tail).
`RestClient` hardcodes `timeout=TIMEOUT` (120 s) and takes no
timeout argument, and this is the request the user waits for, so it uses
`requests` directly with PROBE_TIMEOUT: a dead host must cost 10 s, not two
minutes.
"""

from urllib.parse import urljoin

import requests
from qgis.PyQt.QtCore import QCoreApplication
from requests.exceptions import SSLError

PROBE_TIMEOUT = 10
ENDPOINT = "/rest/workspaces.json"

translate = QCoreApplication.translate


def probe(url, auth, verify_tls):
    """Return None when GeoServer answered, else (status, message) to show.

    :param auth: (username, password), HTTP Basic, as the library sends it.
    """
    endpoint = f"{url.rstrip('/')}{ENDPOINT}"
    try:
        # Not followed: a 301 or 302 resends a write as a GET, or bodiless.
        response = requests.get(
            endpoint,
            auth=auth,
            timeout=PROBE_TIMEOUT,
            verify=verify_tls,
            allow_redirects=False,
        )
    except SSLError:
        # Before OSError (it is a ConnectionError): a private-CA or
        # self-signed certificate used to read as "is the server running?"
        return (
            translate("ConnectionProbe", "Certificate not trusted"),
            translate(
                "ConnectionProbe",
                "{url} presented a TLS certificate this machine does not trust. "
                "If it is your own private CA or a self-signed certificate, untick "
                '"Verify the server\'s TLS certificate" in Settings.',
            ).format(url=url),
        )
    except OSError:
        # ConnectionError / Timeout: refused, unreachable, wrong host, or a
        # host that swallows the SYN; that one gives up after PROBE_TIMEOUT.
        return (
            translate("ConnectionProbe", "Server unreachable"),
            translate(
                "ConnectionProbe",
                "Cannot reach GeoServer at {url}. Is the server running?",
            ).format(url=url),
        )
    except Exception as e:
        return (
            translate("ConnectionProbe", "Connection error"),
            translate("ConnectionProbe", "Connection failed: {}").format(e),
        )

    if 300 <= response.status_code < 400 and response.headers.get("Location"):
        target = urljoin(endpoint, response.headers["Location"])
        if target.endswith(ENDPOINT):
            # The same API at another address: the usual http:// to https://.
            return (
                translate("ConnectionProbe", "Redirected"),
                translate(
                    "ConnectionProbe",
                    "{url} redirects to {target}. Put that address in Settings: "
                    "a save sent through a redirect can arrive empty, or as a read.",
                ).format(url=url, target=target[: -len(ENDPOINT)]),
            )
        return (
            translate("ConnectionProbe", "Not a GeoServer REST endpoint"),
            translate(
                "ConnectionProbe",
                "{url} redirects to {target}, not to the GeoServer REST API (a "
                "login page?). Check the URL, or the proxy in front of it.",
            ).format(url=url, target=target),
        )
    if response.status_code in (401, 403):
        return (
            translate("ConnectionProbe", "Authentication failed"),
            translate(
                "ConnectionProbe",
                "Authentication failed. Check your username and password in Settings.",
            ),
        )
    if response.status_code >= 400:
        # The URL usually points at something that is not a GeoServer REST
        # endpoint at all.
        return (
            translate("ConnectionProbe", "HTTP error {}").format(response.status_code),
            translate(
                "ConnectionProbe",
                "GeoServer returned HTTP {code} for {url}. Check the URL in Settings.",
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
            translate("ConnectionProbe", "Not a GeoServer REST endpoint"),
            translate(
                "ConnectionProbe",
                "{url} answered, but not with the GeoServer REST API (a login "
                "page?). Check the URL, or the proxy in front of it.",
            ).format(url=url),
        )
    return None
