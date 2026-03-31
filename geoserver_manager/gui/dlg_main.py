#! python3  # noqa: E265

"""
Main plugin dialog.
"""

# standard
import sys
from pathlib import Path

# PyQGIS
from qgis.PyQt import uic
from qgis.PyQt.QtWidgets import QDialog, QMessageBox

# project
from geoserver_manager.toolbelt.preferences import PlgOptionsManager

# ############################################################################
# ########## Classes ###############
# ##################################

class GeoServerMainDialog(QDialog):
    """Main dialog window for the plugin."""

    def __init__(self, parent=None, iface=None) -> None:
        """Constructor."""
        super().__init__(parent)
        self.iface = iface
        
        # Load the UI file.
        uic.loadUi(Path(__file__).parent / "dlg_main.ui", self)
        
        self.plg_settings = PlgOptionsManager()
        
        # Wire up buttons
        self.btn_test_connection.clicked.connect(self.test_connection)
        self.btn_edit_credentials.clicked.connect(self.edit_credentials)
        
        self.refresh_ui()

    def refresh_ui(self) -> None:
        """Refresh the UI with current settings."""
        settings = self.plg_settings.get_plg_settings()
        
        if settings.has_credentials():
            self.lbl_url_value.setText(settings.geoserver_url)
            self.lbl_status_value.setText("Ready to test")
            self.lbl_status_value.setStyleSheet("color: black;")
            self.btn_test_connection.setEnabled(True)
        else:
            self.lbl_url_value.setText("Not configured")
            self.lbl_status_value.setText("Missing credentials")
            self.lbl_status_value.setStyleSheet("color: red;")
            self.btn_test_connection.setEnabled(False)

    def edit_credentials(self) -> None:
        """Open the QGIS Options dialog to the plugin's settings tab."""
        if self.iface:
            # We must close this dialog first before showing settings since settings is modal
            self.hide()
            from geoserver_manager.__about__ import __title__
            self.iface.showOptionsDialog(currentPage="mOptionsPage{}".format(__title__))
            # Refresh UI after settings dialog closes, incase credentials changed.
            self.refresh_ui()
            self.show()

    def test_connection(self) -> None:
        """Test the connection to GeoServer using geoservercloud."""
        settings = self.plg_settings.get_plg_settings()

        if not settings.has_credentials():
            QMessageBox.warning(
                self,
                "Incomplete Credentials",
                "Please configure the GeoServer URL and authentication first.",
            )
            return

        self.lbl_status_value.setText("Connecting...")
        self.lbl_status_value.setStyleSheet("color: orange;")
        self.repaint()  # Force UI update before blocking call

        try:
            from geoservercloud import GeoServerCloud

            # Retrieve credentials from the encrypted auth store
            username, password = settings.get_credentials()
            if not username or not password:
                self.lbl_status_value.setText("Auth config incomplete")
                self.lbl_status_value.setStyleSheet("color: red;")
                QMessageBox.warning(
                    self,
                    "Authentication Error",
                    "Could not retrieve username/password from the "
                    "selected authentication configuration.\n\n"
                    "Please check your auth config in Settings.",
                )
                return

            gs = GeoServerCloud(
                url=settings.geoserver_url,
                user=username,
                password=password,
            )

            # get_workspaces returns (list_or_error_str, status_code)
            result, status_code = gs.get_workspaces()
            if isinstance(result, str):
                # Error string returned
                raise Exception(f"HTTP {status_code}: {result}")

            num_wksp = len(result) if result else 0
            self.lbl_status_value.setText(
                f"Connected ({num_wksp} workspaces)"
            )
            self.lbl_status_value.setStyleSheet("color: green;")

        except ImportError:
            self.lbl_status_value.setText("Missing: geoservercloud")
            self.lbl_status_value.setStyleSheet("color: red;")
            QMessageBox.critical(
                self,
                "Error",
                "geoservercloud library not installed. "
                "Please check plugin logs.",
            )
        except Exception as e:
            self.lbl_status_value.setText("Connection failed")
            self.lbl_status_value.setStyleSheet("color: red;")
            QMessageBox.warning(
                self,
                "Connection Failed",
                f"Failed to connect to GeoServer:\n\n{e}",
            )
