"""1.2.0: Privacy lock: password, Windows Hello, security keys (YubiKey) and phone passkeys on launch."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from utils import applock  # noqa: E402


class LockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def setUp(self):
        applock.reset()
        applock._failures = 0

    def test_password_is_a_salted_hash_and_checked(self):
        with self.assertRaises(ValueError):
            applock.set_password("abc")
        applock.set_password("correct horse")
        stored = db.get_setting(applock.SETTING)
        self.assertNotIn("correct horse", stored)
        self.assertTrue(applock.enabled())
        with mock.patch("time.sleep") as nap:
            self.assertFalse(applock.check_password("wrong"))
            self.assertFalse(applock.check_password("wrong"))
            self.assertEqual([c.args[0] for c in nap.call_args_list], [0.4, 0.8])      # each guess waits longer
            self.assertTrue(applock.check_password("correct horse"))
        applock.clear_password()
        self.assertFalse(applock.enabled())

    def test_security_key_signs_in_and_a_copy_does_not(self):
        from fake_authenticator import FakeKey
        key = FakeKey(applock.ORIGIN, applock.RP_ID)
        entry = applock.add_key("key", client=key)
        self.assertEqual(entry["label"], "Security key")
        self.assertNotIn("data", applock.summary()["keys"][0])                 # the summary carries no key material
        self.assertTrue(applock.verify_key(client=key))
        self.assertTrue(applock.verify_key("key", client=key))
        self.assertFalse(applock.verify_key("hello", client=key))              # none of that kind saved
        forged = FakeKey(applock.ORIGIN, applock.RP_ID)
        forged.cred_id = key.cred_id                                           # same id, different private key
        self.assertFalse(applock.verify_key(client=forged))
        other_site = FakeKey("https://example.com", applock.RP_ID)
        other_site.priv, other_site.cred_id = key.priv, key.cred_id
        self.assertFalse(applock.verify_key(client=other_site))
        applock.remove_key(entry["id"])
        self.assertFalse(applock.enabled())

    def test_two_of_a_kind_are_numbered(self):
        from fake_authenticator import FakeKey
        applock.add_key("phone", client=FakeKey(applock.ORIGIN, applock.RP_ID))
        second = applock.add_key("phone", client=FakeKey(applock.ORIGIN, applock.RP_ID))
        self.assertEqual(second["label"], "Phone passkey 2")


class ScreenTests(unittest.TestCase):
    def test_nothing_shows_or_plays_while_locked(self):
        main = (ROOT / "ui" / "Main.qml").read_text(encoding="utf-8")
        self.assertIn("visible: !Backend.locked", main)
        self.assertIn("LockScreen { anchors.fill: parent; z: 2000 }", main)
        self.assertIn("&& !Backend.locked", main)                                # the vault opens after sign-in
        py = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("if self.ready and not self.dashboard.locked:", py)        # "Open with" waits for sign-in
        self.assertIn('arg == "--reset-lock"', py)

    def test_dashboard_unlocks_only_on_success(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        applock.reset()
        applock.set_password("letmein")
        app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None, stop=lambda: None), presence=None, play=lambda *a: None)
        d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())
        self.assertTrue(d.locked)
        results = []
        d.unlockResult.connect(lambda ok, msg: results.append(ok))
        run_now = mock.patch("threading.Thread", side_effect=lambda target, daemon, name: types.SimpleNamespace(start=target))
        with run_now, mock.patch("time.sleep"):
            d.unlockWithPassword("nope")
            self.assertTrue(d.locked)
            d.unlockWithPassword("letmein")
        QGuiApplication.processEvents()
        self.assertFalse(d.locked)
        self.assertEqual(results, [False, True])
        d.lockNow()
        self.assertTrue(d.locked)
        applock.reset()

    def test_in_workflow_and_build(self):
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_v120", wf)
        self.assertIn("fido2", (ROOT / "requirements.txt").read_text(encoding="utf-8"))
        self.assertIn('"--collect-submodules", "fido2"', (ROOT / "build_installer.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
