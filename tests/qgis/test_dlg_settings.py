#! python3  # noqa E265

"""
Usage from the repo root folder:

.. code-block:: bash

    QT_QPA_PLATFORM=offscreen python -m unittest tests.qgis.test_dlg_settings
"""

from unittest.mock import patch

from qgis.core import Qgis
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.testing import start_app, unittest

from geoserver_manager.gui.dlg_settings import ConfigOptionsPage

start_app()


class TestPasswordInTheClear(unittest.TestCase):
    """The plugin authenticates with HTTP Basic, so the scheme matters."""

    def warns_about(self, url, username="admin", password="geoserver"):
        return ConfigOptionsPage._password_travels_in_clear(url, username, password)

    def test_plain_http_to_a_real_host_is_worth_saying(self):
        self.assertTrue(self.warns_about("http://gs.example.org/geoserver"))
        self.assertTrue(self.warns_about("http://192.168.1.10:8080/geoserver"))
        self.assertTrue(
            self.warns_about("http://10.0.0.5/geoserver")
        )  # a LAN is a path

    def test_https_is_not_worth_saying_anything_about(self):
        self.assertFalse(self.warns_about("https://gs.example.org/geoserver"))
        self.assertFalse(self.warns_about("HTTPS://gs.example.org/geoserver".lower()))

    def test_loopback_is_exempt_because_nothing_leaves_the_machine(self):
        # This repo's own docker-compose sandbox is exactly this.
        for url in (
            "http://localhost:8080/geoserver",
            "http://LOCALHOST:8080/geoserver",
            "http://127.0.0.1:8080/geoserver",
            "http://127.0.1.1/geoserver",
            "http://[::1]:8080/geoserver",
            "http://gs.localhost:8080/geoserver",
        ):
            self.assertFalse(self.warns_about(url), url)

    def test_nothing_is_said_when_there_is_no_password_to_leak(self):
        self.assertFalse(self.warns_about("http://gs.example.org", "", ""))
        # a username alone still authenticates, so it counts
        self.assertTrue(self.warns_about("http://gs.example.org", "admin", ""))
        self.assertTrue(self.warns_about("http://gs.example.org", "", "geoserver"))

    def test_junk_and_emptiness_do_not_raise(self):
        self.assertFalse(self.warns_about(""))
        self.assertFalse(self.warns_about(None))
        self.assertFalse(self.warns_about("gs.example.org"))  # no scheme yet
        self.assertFalse(self.warns_about("ftp://gs.example.org"))


class FakeSettings:
    """Stands in for PlgSettingsStructure so apply() writes nothing real."""

    def __init__(self):
        self.debug_mode = False
        self.version = ""
        self.geoserver_verify_tls = True
        self.geoserver_url = "http://old.example.org/geoserver"
        self.geoserver_auth_cfg_id = ""
        self.saved_credentials = []

    def save_credentials(self, username, password):
        self.saved_credentials.append((username, password))
        return "authcfg1"


class FakeSettingsManager:
    """Stands in for PlgOptionsManager: no QgsSettings, no auth database."""

    def __init__(self, settings):
        self.settings = settings
        self.saved = []

    def get_plg_settings(self):
        return self.settings

    def save_from_object(self, settings):
        self.saved.append(settings)

    # Profiles: none until the first save makes one (#47).
    profiles = ()
    values = None

    def get_profiles(self):
        return [dict(profile) for profile in self.profiles]

    def save_profiles(self, profiles):
        self.profiles = [dict(profile) for profile in profiles]

    def active_profile_name(self):
        return (self.values or {}).get("active_profile", "")

    def set_value_from_key(self, key, value):
        self.values = {**(self.values or {}), key: value}


class TestApplyWarnsAndStillSaves(unittest.TestCase):
    """The real apply(), driven against stubs: it must warn *and* save."""

    def setUp(self):
        self.page = ConfigOptionsPage(None)
        self.settings = FakeSettings()
        self.manager = FakeSettingsManager(self.settings)
        self.page.plg_settings = self.manager
        self.page.load_settings()  # the profiles of the fake, not of this machine
        self.pushed = []
        self.page.log = lambda message, log_level=None, push=False, **kw: (
            self.pushed.append((message, log_level, push))
        )

    def fill(self, url, username="admin", password="geoserver"):
        self.page.txt_gs_url.setText(url)
        self.page.txt_gs_username.setText(username)
        self.page.txt_gs_password.setText(password)

    def warnings(self):
        return [
            message
            for message, level, push in self.pushed
            if level == Qgis.MessageLevel.Warning and push
        ]

    def test_a_remote_http_server_is_warned_about_and_saved_anyway(self):
        self.fill("http://gs.example.org/geoserver")
        self.page.apply()

        warnings = self.warnings()
        self.assertEqual(len(warnings), 1, self.pushed)
        self.assertIn("plain HTTP", warnings[0])
        self.assertIn("https://", warnings[0])
        # refusing would be wrong: the settings still land
        self.assertEqual(self.settings.geoserver_url, "http://gs.example.org/geoserver")
        self.assertEqual(self.settings.saved_credentials, [("admin", "geoserver")])
        self.assertEqual(self.settings.geoserver_auth_cfg_id, "authcfg1")
        self.assertEqual(len(self.manager.saved), 1)

    def test_the_local_sandbox_saves_without_a_word(self):
        self.fill("http://localhost:8080/geoserver")
        self.page.apply()
        self.assertEqual(self.warnings(), [])
        self.assertEqual(self.settings.geoserver_url, "http://localhost:8080/geoserver")

    def test_https_saves_without_a_word(self):
        self.fill("https://gs.example.org/geoserver")
        self.page.apply()
        self.assertEqual(self.warnings(), [])

    def test_no_credentials_yet_means_nothing_to_warn_about(self):
        self.fill("http://gs.example.org/geoserver", "", "")
        self.page.apply()
        self.assertEqual(self.warnings(), [])
        self.assertEqual(self.settings.saved_credentials, [])

    def test_a_url_without_a_scheme_is_still_refused_as_before(self):
        self.fill("gs.example.org")
        self.page.apply()
        # the pre-existing guard: the URL is not saved, and it says so
        self.assertEqual(
            self.settings.geoserver_url, "http://old.example.org/geoserver"
        )
        self.assertTrue(
            any("must start with http" in message for message, _l, _p in self.pushed)
        )


if __name__ == "__main__":
    unittest.main()


class TestProfiles(unittest.TestCase):
    """Several saved connections on the settings page (#47)."""

    def setUp(self):
        from geoserver_manager.toolbelt.preferences import PlgSettingsStructure

        # QgsAuthManager, in memory: auth config id -> (user, password).
        self.store = {"idA": ("ua", "pa")}

        def get_credentials(inner):
            return self.store.get(inner.geoserver_auth_cfg_id, ("", ""))

        def save_credentials(inner, username, password):
            auth_id = inner.geoserver_auth_cfg_id or f"id{len(self.store)}"
            self.store[auth_id] = (username, password)
            return auth_id

        def remove_credentials(inner):
            self.store.pop(inner.geoserver_auth_cfg_id, None)
            inner.geoserver_auth_cfg_id = ""

        for name, fn in (
            ("get_credentials", get_credentials),
            ("save_credentials", save_credentials),
            ("remove_credentials", remove_credentials),
        ):
            patcher = patch.object(PlgSettingsStructure, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.settings = PlgSettingsStructure(
            geoserver_url="https://a.example.org/geoserver", geoserver_auth_cfg_id="idA"
        )
        self.manager = FakeSettingsManager(self.settings)
        self.manager.profiles = [
            {
                "name": "A",
                "url": "https://a.example.org/geoserver",
                "auth_cfg_id": "idA",
                "verify_tls": True,
            }
        ]
        self.manager.values = {"active_profile": "A"}
        self.page = ConfigOptionsPage(None)
        self.page.plg_settings = self.manager
        self.page.log = lambda *args, **kwargs: None
        self.page.load_settings()

    def add(self, name):
        with patch(
            "geoserver_manager.gui.dlg_settings.QInputDialog.getText",
            return_value=(name, True),
        ):
            self.page._add_profile()

    def test_the_active_profile_is_shown_with_its_credentials(self):
        self.assertEqual(self.page.cmb_profile.currentText(), "A")
        self.assertEqual(self.page.txt_gs_url.text(), "https://a.example.org/geoserver")
        self.assertEqual(self.page.txt_gs_username.text(), "ua")

    def test_two_profiles_round_trip_and_edits_survive_a_switch(self):
        self.add("B")
        self.assertEqual(self.page.txt_gs_url.text(), "")  # a new profile starts empty
        self.page.txt_gs_url.setText("https://b.example.org/geoserver")
        self.page.txt_gs_username.setText("ub")
        self.page.txt_gs_password.setText("pb")
        self.page.cmb_profile.setCurrentText("A")  # B's edits are kept, not saved
        self.page.txt_gs_url.setText("https://a2.example.org/geoserver")
        self.page.apply()

        a, b = self.manager.profiles
        self.assertEqual(a["url"], "https://a2.example.org/geoserver")
        self.assertEqual(b["url"], "https://b.example.org/geoserver")
        self.assertNotEqual(b["auth_cfg_id"], "idA")  # its own credentials
        self.assertEqual(self.store[b["auth_cfg_id"]], ("ub", "pb"))
        self.assertEqual(self.store["idA"], ("ua", "pa"))
        # The shown profile is the one the dialog connects to now.
        self.assertEqual(self.manager.values["active_profile"], "A")
        self.assertEqual(
            self.settings.geoserver_url, "https://a2.example.org/geoserver"
        )

    def test_saving_another_profile_makes_it_active_with_its_own_auth(self):
        self.add("B")
        self.page.txt_gs_url.setText("https://b.example.org/geoserver")
        self.page.txt_gs_username.setText("ub")
        self.page.txt_gs_password.setText("pb")
        self.page.apply()
        self.assertEqual(self.manager.values["active_profile"], "B")
        self.assertEqual(self.settings.geoserver_url, "https://b.example.org/geoserver")
        self.assertNotEqual(self.settings.geoserver_auth_cfg_id, "idA")
        self.assertEqual(self.store["idA"], ("ua", "pa"))  # A was not overwritten

    def test_a_duplicate_name_is_refused(self):
        said = []
        with patch(
            "geoserver_manager.gui.dlg_settings.QMessageBox.warning",
            lambda parent, title, text: said.append(text),
        ):
            self.add("A")
        self.assertEqual(len(self.page._profiles), 1)
        self.assertIn("already exists", said[0])

    def test_removing_the_last_profile_leaves_not_configured(self):
        self.page._remove_profile()
        self.assertFalse(self.page.cmb_profile.isEnabled())
        self.assertIn("Saving creates one", self.page.cmb_profile.currentText())
        self.assertEqual(self.store["idA"], ("ua", "pa"))  # nothing gone before Save
        self.page.apply()
        self.assertEqual(self.manager.profiles, [])
        self.assertEqual(self.manager.values["active_profile"], "")
        self.assertEqual(self.settings.geoserver_url, "")
        self.assertNotIn("idA", self.store)

    def test_naming_a_first_connection_keeps_what_was_typed(self):
        self.manager.profiles = []
        self.manager.values = {}
        self.page.load_settings()
        self.page.txt_gs_url.setText("https://first.example.org/geoserver")
        self.page.txt_gs_username.setText("u1")
        self.page.txt_gs_password.setText("p1")
        self.add("first")
        self.assertEqual(
            self.page.txt_gs_url.text(), "https://first.example.org/geoserver"
        )
        self.assertEqual(self.page.txt_gs_password.text(), "p1")
        self.page.apply()
        (first,) = self.manager.profiles
        self.assertEqual(first["name"], "first")
        self.assertEqual(self.store[first["auth_cfg_id"]], ("u1", "p1"))

    def test_removing_another_profile_keeps_the_active_one(self):
        self.manager.profiles = [
            {
                "name": n,
                "url": f"https://{n}.example.org/geoserver",
                "auth_cfg_id": f"id{n}",
                "verify_tls": True,
            }
            for n in ("A", "B", "C")
        ]
        self.manager.values = {"active_profile": "C"}
        self.page.load_settings()
        self.page.cmb_profile.setCurrentText("B")
        self.page._remove_profile()
        self.assertEqual(self.page.cmb_profile.currentText(), "C")
        self.page.apply()
        self.assertEqual(self.manager.values["active_profile"], "C")

    def test_reset_asks_first_and_no_keeps_everything(self):
        with patch(
            "geoserver_manager.gui.dlg_settings.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No,
        ) as asked:
            self.page.on_reset_settings()
        asked.assert_called_once()
        self.assertIn("idA", self.store)
        self.assertEqual(len(self.manager.profiles), 1)

    def test_the_page_says_which_profile_is_active_and_what_save_does(self):
        self.assertIn("active profile", self.page.lbl_profile_note.text())
        self.add("B")
        note = self.page.lbl_profile_note.text()
        self.assertIn("Active: A", note)
        self.assertIn("'B'", note)

    def test_cancel_keeps_a_removed_profile(self):
        self.page._remove_profile()
        self.page.load_settings()  # what reopening the page does after Cancel
        self.assertEqual(self.page.cmb_profile.currentText(), "A")
        self.assertIn("idA", self.store)


class TestTestConnection(unittest.TestCase):
    """The button probes what is typed, saved or not, and says what it found."""

    def setUp(self):
        self.page = ConfigOptionsPage(None)
        self.page.plg_settings = FakeSettingsManager(FakeSettings())
        self.page.txt_gs_url.setText("http://gs.example.org/geoserver")
        self.page.txt_gs_username.setText("admin")
        self.page.txt_gs_password.setText("typed-not-saved")
        self.page.opt_verify_tls.setChecked(False)
        self.calls = []

    def probe(self, result):
        def fake(url, auth, verify_tls):
            self.calls.append((url, auth, verify_tls))
            return result

        return patch("geoserver_manager.gui.dlg_settings.probe", fake)

    def test_it_probes_the_fields_as_typed(self):
        with self.probe(None):
            self.page.btn_test_connection.click()
        self.assertEqual(
            self.calls,
            [("http://gs.example.org/geoserver", ("admin", "typed-not-saved"), False)],
        )
        self.assertIn("Connected", self.page.lbl_test_result.text())

    def test_a_problem_shows_its_message(self):
        problem = ("Server unreachable", "Cannot reach GeoServer, is it running?")
        with self.probe(problem):
            self.page.btn_test_connection.click()
        self.assertIn("is it running", self.page.lbl_test_result.text())

    def test_a_url_without_a_scheme_is_not_even_tried(self):
        self.page.txt_gs_url.setText("gs.example.org/geoserver")
        with self.probe(None):
            self.page.btn_test_connection.click()
        self.assertEqual(self.calls, [])
        self.assertIn("http://", self.page.lbl_test_result.text())

    def test_editing_a_field_retires_the_result(self):
        with self.probe(None):
            self.page.btn_test_connection.click()
        self.assertTrue(self.page.lbl_test_result.text())
        self.page.txt_gs_password.setText("other")
        self.assertEqual(self.page.lbl_test_result.text(), "")

    def test_testing_saves_nothing(self):
        with self.probe(None):
            self.page.btn_test_connection.click()
        self.assertEqual(self.page.plg_settings.saved, [])
        self.assertEqual(self.page.plg_settings.settings.saved_credentials, [])
