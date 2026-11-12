"""1.1.1: a click outside a text box saves it and ends the edit; every title has the pencil / check mark."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

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
