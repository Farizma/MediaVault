"""1.0.5: updates install inside Media Vault (no wizard), Update all, the update badge, rollbacks."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from utils import components, rollback  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class SilentSetupTests(unittest.TestCase):
    def test_arguments(self):
        a = components.setup_arguments(Path(r"C:\Users\me\AppData\Local\Programs\Media Vault"), all_users=False)
        for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/RELAUNCH", '/DIR="C:\\Users\\me\\AppData\\Local\\Programs\\Media Vault"'):
            self.assertIn(flag, a)
        self.assertNotIn("/ALLUSERS", a)
        self.assertIn("/ALLUSERS", components.setup_arguments(Path(r"C:\Program Files\Media Vault"), all_users=True))

    def test_installer_relaunches_only_for_the_updater(self):
        iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("Check: RelaunchAfterUpdate", iss)
        self.assertIn("runasoriginaluser", iss)
        self.assertIn("Pos('/RELAUNCH'", iss)

    def test_previous_release_picks_the_newest_older_one(self):
        rel = lambda tag, asset=True, **kw: {"tag_name": tag, "html_url": tag, **kw,
                                             "assets": [{"name": f"MediaVault_{tag}_setup.exe", "browser_download_url": f"u/{tag}"}] if asset else []}
        listing = [rel("v9.0.0"), rel("v1.0.2"), rel("v1.0.3", asset=False), rel("v1.0.1"), rel("v1.0.0", draft=True)]
        with mock.patch.object(components, "_get_json", return_value=listing), mock.patch.object(components.version, "VERSION", "1.0.4"):
            self.assertEqual(components.previous_release()["version"], "1.0.2")


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.bin = Path(tempfile.mkdtemp())
        self.p = mock.patch.object(rollback, "_bin", return_value=self.bin)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def write(self, rel, text):
        f = self.bin / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")

    def test_snapshot_then_swap_and_undo(self):
        self.write("libmpv-2.dll", "old"); self.write("mpv.version", "build-1")
        rollback.snapshot("libmpv", "2026-01-01")
        self.write("libmpv-2.dll", "new"); self.write("mpv.version", "build-2")       # the update
        self.assertEqual(rollback.previous("libmpv"), "2026-01-01")
        rollback.request("libmpv", "2026-02-02")
        self.assertEqual(rollback.pending(), ["libmpv"])
        self.assertEqual(rollback.apply_pending(), ["libmpv"])
        self.assertEqual((self.bin / "libmpv-2.dll").read_text(), "old")
        self.assertEqual(rollback.previous("libmpv"), "2026-02-02")                  # rolling back again = undo
        self.assertEqual(rollback.pending(), [])
        rollback.request("libmpv", "2026-01-01")
        rollback.apply_pending()
        self.assertEqual((self.bin / "libmpv-2.dll").read_text(), "new")

    def test_folder_component(self):
        self.write("vlc/libvlc.dll", "3.0.20"); self.write("vlc/plugins/a.dll", "a")
        rollback.snapshot("libvlc", "3.0.20")
        self.write("vlc/libvlc.dll", "3.0.21")
        rollback.request("libvlc", "3.0.21")
        rollback.apply_pending()
        self.assertEqual((self.bin / "vlc/libvlc.dll").read_text(), "3.0.20")
        self.assertTrue((self.bin / "vlc/plugins/a.dll").exists())

    def test_nothing_kept_nothing_to_roll_back(self):
        self.assertEqual(rollback.previous("shader"), "")
        rollback.snapshot("shader", "1.1")             # no shader on this PC: nothing to keep
        self.assertEqual(rollback.previous("shader"), "")

    def test_component_rollback_asks_for_restart(self):
        self.write("libmpv-2.dll", "old")
        rollback.snapshot("libmpv", "2026-01-01")
        with mock.patch.object(components, "_installed", return_value="2026-02-02"):
            msg = components.rollback_component("libmpv")
        self.assertIn("Restart", msg)
        self.assertEqual(json.loads((self.bin / ".previous" / "pending.json").read_text()), {"libmpv": "2026-02-02"})

    def test_pip_rollback_for_source_installs(self):
        rollback.remember_pip("watchdog", "5.0.0")
        with mock.patch.object(components, "frozen", return_value=False), \
                mock.patch.object(components, "_installed", return_value="6.0.0"), \
                mock.patch("setup.pip_install") as pip:
            components.rollback_component("watchdog")
        pip.assert_called_once()
        self.assertEqual(pip.call_args[0][0], ["watchdog==5.0.0"])
        self.assertEqual(rollback.previous("watchdog"), "6.0.0")

    def test_update_keeps_the_old_version(self):
        self.write("shaders/FSRCNNX_x2_8-0-4-1.glsl", "v1")
        with mock.patch.object(components, "_installed", return_value="1.1"), mock.patch("setup.download_shader"):
            components.update("shader")
        self.assertEqual(rollback.previous("shader"), "1.1")


class BadgeTests(unittest.TestCase):
    def test_count_and_quit_on_main_thread(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        import database as db
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        db.init_db()
        app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None, quit=mock.Mock())
        d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())
        seen = []
        d.updateCountChanged.connect(lambda: seen.append(d.updateCount))
        d.componentsChecked.emit([{"status": "update", "kind": "app"}, {"status": "update", "kind": "runtime"},
                                  {"status": "update", "kind": "bundled"}, {"status": "ok", "kind": "python"}])
        self.assertEqual(d.updateCount, 2)                 # built-in packages update with the app: not counted
        d.componentsChecked.emit([])
        self.assertEqual(seen, [2, 0])
        import threading
        import time
        threading.Thread(target=d._quitForUpdate.emit).start()   # from a worker, as after the setup starts
        end = time.time() + 3
        while not app.quit.called and time.time() < end:
            QGuiApplication.processEvents()
            time.sleep(0.02)
        app.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
