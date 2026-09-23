#! python3  # noqa: E265

# standard library
import logging
from typing import Optional

# PyQGIS
from qgis.core import Qgis, QgsMessageLog
from qgis.utils import iface

# project package
import geoserver_manager.toolbelt.preferences as plg_prefs_hdlr
from geoserver_manager.__about__ import __title__

# ############################################################################
# ########## Classes ###############
# ##################################


class PlgLogger(logging.Handler):
    """Python logging handler supercharged with QGIS useful methods."""

    @staticmethod
    def log(
        message: str,
        application: str = __title__,
        log_level: Qgis.MessageLevel = Qgis.MessageLevel.Info,
        push: bool = False,
        duration: Optional[int] = None,
    ):
        """Send a message to the QGIS log panel, and to the message bar with `push`.

        Without debug mode, only warnings, errors and pushed messages are kept.

        :param message: message to display
        :param application: the log panel's tab; the plugin's title by default
        :param log_level: any `Qgis.MessageLevel`, Info by default
        :param push: also show it in QGIS's message bar, above the map canvas
        :param duration: seconds on the message bar; by default
            `(log_level + 1) * 3`, and 0 means until the user closes it

        :Example:

        .. code-block:: python

            log(message="Plugin loaded", log_level=Qgis.MessageLevel.Info)
            log(
                message="Plugin failed to load",
                log_level=Qgis.MessageLevel.Critical,
                push=True,
            )
        """
        # if not debug mode and not push, let's ignore INFO, SUCCESS and TEST
        debug_mode = plg_prefs_hdlr.PlgOptionsManager.get_plg_settings().debug_mode
        if (
            not debug_mode
            and not push
            and (
                log_level < Qgis.MessageLevel.Warning
                or log_level > Qgis.MessageLevel.Critical
            )
        ):
            return

        # ensure message is a string
        if not isinstance(message, str):
            try:
                message = str(message)
            except Exception as err:
                err_msg = "Log message must be a string, not: {}. Trace: {}".format(
                    type(message), err
                )
                logging.error(err_msg)
                message = err_msg

        # send it to QGIS messages panel
        QgsMessageLog.logMessage(
            message=message, tag=application, notifyUser=push, level=log_level
        )

        # optionally, display message on QGIS Message bar (above the map canvas)
        if push and iface is not None:
            if duration is None:
                duration = (int(log_level) + 1) * 3
            iface.messageBar().pushMessage(
                title=application, text=message, level=log_level, duration=duration
            )
