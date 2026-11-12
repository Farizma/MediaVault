"""1.1.1: a click outside a text box saves it and ends the edit; every title has the pencil / check mark."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QML = b"""
import QtQuick
import QtQuick.Controls
Item {
    width: 400; height: 300
    property int saved: 0
    Item {
        objectName: "home"; property bool focusHome: true
        anchors.fill: parent
        TextField { objectName: "field"; x: 10; y: 10; width: 200; height: 40
            onActiveFocusChanged: if (!activeFocus) parent.parent.saved++ }
        Popup { objectName: "pop"; x: 10; y: 200; width: 100; height: 60; visible: true; closePolicy: Popup.NoAutoClose }
    }
}
"""


class ClickAwayTests(unittest.TestCase):
    def test_click_outside_ends_the_edit(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQuick import QQuickView
        from PySide6.QtTest import QTest
        QGuiApplication.instance() or QGuiApplication([])
        from ui.clickaway import ClickAway
        qml = Path(tempfile.mkdtemp()) / "t.qml"
        qml.write_bytes(QML)
        view = QQuickView()
        view.setSource(qml.as_uri())
        view.show()
        f = ClickAway()
        view.installEventFilter(f)
        root = view.rootObject()
        field = [i for i in root.findChildren(type(root)) if i.objectName() == "field"][0]
        home = [i for i in root.findChildren(type(root)) if i.objectName() == "home"][0]

        def click(x, y):
            QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
            QTest.qWait(20)
        field.forceActiveFocus(); QTest.qWait(20)
        click(50, 25)                                   # in the box: still editing
        self.assertTrue(field.hasActiveFocus())
        click(60, 225)                                  # in a popup (a suggestion): still editing
        self.assertTrue(field.hasActiveFocus())
        click(300, 150)                                 # empty space: saved, focus home
        self.assertFalse(field.hasActiveFocus())
        self.assertEqual(root.property("saved"), 1)
        self.assertTrue(home.hasActiveFocus())


class PencilTests(unittest.TestCase):
    def test_every_title_has_the_pencil(self):
        qml = (ROOT / "ui" / "DetailView.qml").read_text(encoding="utf-8")
        pencil = qml[qml.index("id: pencil"):qml.index("id: pencil") + 200]
        self.assertNotIn("visible: root.d.isSet", pencil)
        self.assertIn("readonly property bool picker: !root.renaming", qml)
        self.assertIn("readonly property bool focusHome: true", qml)
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("engine.rootObjects()[0].installEventFilter(app.click_away)", main)

    def test_in_workflow(self):
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_v111", wf)


if __name__ == "__main__":
    unittest.main()


class ImageResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
        import database as db
        db.init_db()
        cls.db = db

    def tearDown(self):
        self.db.set_setting("image_quality", "medium")

    def test_each_resolution_keeps_its_size_and_never_enlarges(self):
        from PIL import Image
        from utils import scraper
        big = Image.new("RGB", (3000, 4500), "red")
        out = Path(tempfile.mkdtemp())
        for name, poster in (("low", (360, 540)), ("medium", (720, 1080)), ("high", (1200, 1800))):
            self.db.set_setting("image_quality", name)
            scraper.save_webp(big, out / f"{name}.webp")
            self.assertEqual(Image.open(out / f"{name}.webp").size, poster)
            scraper.save_webp(Image.new("RGB", (4000, 2250)), out / f"{name}-g.webp", box=scraper.GALLERY_BOX)
            self.assertEqual(Image.open(out / f"{name}-g.webp").size[0], scraper.IMAGE_QUALITY[name]["gallery"][0])
        scraper.save_webp(Image.new("RGB", (200, 300)), out / "small.webp")          # High, but never blown up
        self.assertEqual(Image.open(out / "small.webp").size, (200, 300))
        self.db.set_setting("image_quality", "nonsense")
        self.assertEqual(scraper.image_quality(), scraper.IMAGE_QUALITY["medium"])

    def test_tmdb_sizes_follow_the_setting(self):
        from utils import scraper
        self.db.set_setting("image_quality", "high")
        self.assertIn("/original/x.jpg", scraper._backdrops({"backdrops": [{"file_path": "/x.jpg"}]})[0])
        self.db.set_setting("image_quality", "low")
        self.assertIn("/w780/x.jpg", scraper._backdrops({"backdrops": [{"file_path": "/x.jpg"}]})[0])
        self.assertEqual(scraper._sized((576, 810)), (432, 608))                     # box art faces scale too

    def test_ui_and_redownload(self):
        dv = (ROOT / "ui" / "DvdBox.qml").read_text(encoding="utf-8")
        self.assertNotIn("sourceSize.width: 426", dv)
        sv = (ROOT / "ui" / "SettingsView.qml").read_text(encoding="utf-8")
        self.assertIn('Backend.setSetting("image_quality", modelData[0])', sv)
        self.assertIn("Backend.redownloadImages()", sv)
        w = (ROOT / "watcher.py").read_text(encoding="utf-8")
        self.assertIn("def fetch_missing(directory: dict, redo_images: bool = False)", w)
        d = (ROOT / "ui" / "dashboard.py").read_text(encoding="utf-8")
        self.assertIn('save_box_art(img.crop((left, 0, left + tw, h)), [item], "front")', d)   # a picked frame is yours


class SmoothnessTests(unittest.TestCase):
    def test_card_faces_are_drawn_once_per_text(self):
        os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        import database as db
        db.init_db()
        from ui import dvd_box
        item = {"uuid": "card-test", "title": "T", "synopsis": "One", "media_type": "movie",
                "file_path": str(Path(tempfile.mkdtemp()) / "T.mkv")}
        a = dvd_box.box_textures(item)["back"]
        folder = db.data_dir() / "cache" / "box"
        first = sorted(folder.glob("card-test-back*"))
        stamp = first[0].stat().st_mtime_ns
        self.assertEqual(dvd_box.box_textures(item)["back"], a)              # same text: not drawn again
        self.assertEqual(first[0].stat().st_mtime_ns, stamp)
        dvd_box.box_textures({**item, "synopsis": "Two"})
        now = sorted(folder.glob("card-test-back*"))
        self.assertEqual(len(now), 1)                                         # the old card went
        self.assertNotEqual(now, first)

    def test_gpu_preference_never_overrides_yours(self):
        from utils import gpu_pref
        store = {}

        class K:
            def __init__(self, name): self.name = name
            def __enter__(self): return self
            def __exit__(self, *a): return False
        fake = types.SimpleNamespace(
            HKEY_CURRENT_USER="HKCU", REG_SZ=1,
            CreateKey=lambda hive, sub: K(sub),
            QueryValueEx=lambda k, n: (store[(k.name, n)], 1) if (k.name, n) in store else (_ for _ in ()).throw(OSError()),
            SetValueEx=lambda k, n, r, t, v: store.__setitem__((k.name, n), v),
            DeleteValue=lambda k, n: store.pop((k.name, n)) if (k.name, n) in store else (_ for _ in ()).throw(OSError()))
        exe = r"D:\Program Files\Media Vault\MediaVault.exe"
        with mock.patch.dict(sys.modules, {"winreg": fake}), mock.patch.object(gpu_pref, "_exe", return_value=exe):
            self.assertEqual(gpu_pref.apply(True), "set")
            self.assertEqual(store[(gpu_pref.KEY, exe)], "GpuPreference=2;")
            self.assertEqual(gpu_pref.apply(False), "cleared")
            self.assertNotIn((gpu_pref.KEY, exe), store)
            store[(gpu_pref.KEY, exe)] = "GpuPreference=1;"                   # you chose power saving in Windows
            self.assertEqual(gpu_pref.apply(True), "yours")
            self.assertEqual(store[(gpu_pref.KEY, exe)], "GpuPreference=1;")
        self.assertEqual(gpu_pref.apply(True), "n/a")                         # not the installed app: nothing


class ProgramFilesBinTests(unittest.TestCase):
    def test_update_moves_to_your_own_bin_when_program_files_refuses(self):
        import utils
        app, data = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        (app / "bin" / "vlc").mkdir(parents=True)
        (app / "bin" / "libmpv-2.dll").write_bytes(b"old dll")
        (app / "bin" / "mpv.version").write_text("2026-01-01")
        (app / "bin" / "vlc" / "libvlc.dll").write_bytes(b"vlc")
        locked = str(app / "bin")
        real = utils._writable
        with mock.patch.object(utils, "app_dir", return_value=app), \
                mock.patch.object(utils, "_user_bin", return_value=data / "bin"), \
                mock.patch.object(utils, "_writable", side_effect=lambda f: not str(f).startswith(locked) and real(f)), \
                mock.patch.object(utils, "use_bin_dir"):
            self.assertEqual(utils.bin_dir(), app / "bin")                    # reads from the app's bin/ as before
            from utils import rollback
            rollback.snapshot("libmpv", "2026-01-01")                         # was: WinError 5 on bin\\.previous
            self.assertEqual(utils.bin_dir(), data / "bin")                    # from now on: your own copy
            self.assertEqual((data / "bin" / "libmpv-2.dll").read_bytes(), b"old dll")
            self.assertTrue((data / "bin" / "vlc" / "libvlc.dll").exists())
            self.assertTrue((data / "bin" / ".previous" / "libmpv" / "files" / "libmpv-2.dll").exists())
            self.assertEqual(utils.writable_bin(), data / "bin")
        self.assertFalse((app / "bin" / ".previous").exists())                # nothing written to Program Files


class ComponentPermissionTests(unittest.TestCase):
    def test_refused_in_app_bin_retries_in_your_own(self):
        from utils import components
        calls = []

        def fake_update(component, log):
            calls.append(component)
            if len(calls) == 1:
                raise PermissionError(5, "Access is denied", r"D:\Program Files\Media Vault\bin\.previous")
            return "ok"
        with mock.patch.object(components, "_update", side_effect=fake_update), \
                mock.patch("utils.writable_bin") as wb:
            self.assertEqual(components.update("shader", log=lambda *a: None), "ok")
            wb.assert_called_once_with(force=True)
        with mock.patch.object(components, "_update", side_effect=PermissionError("x")):
            with self.assertRaises(PermissionError):           # pip packages: not a bin/ problem
                components.update("pillow", log=lambda *a: None)

    def test_force_moves_to_your_own_bin(self):
        import utils
        app = Path(tempfile.mkdtemp())
        (app / "bin" / "shaders").mkdir(parents=True)
        (app / "bin" / "mpv-2.dll").write_bytes(b"dll")
        user = Path(tempfile.mkdtemp()) / "bin"
        with mock.patch.object(utils, "app_dir", return_value=app), mock.patch.object(utils, "_user_bin", return_value=user), \
                mock.patch.object(utils, "use_bin_dir"):
            self.assertEqual(utils.writable_bin(), app / "bin")           # writable: stays
            self.assertEqual(utils.writable_bin(force=True), user)        # refused later: your own copy
            self.assertTrue((user / "mpv-2.dll").exists())
            self.assertEqual(utils.bin_dir(), user)
            self.assertEqual(utils.writable_bin(force=True), user)        # already there: no second copy
