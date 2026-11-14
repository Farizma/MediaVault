"""1.3.0: Settings > Library > Storage: clean up unused artwork, or delete all of it."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from utils import cleanup, scraper  # noqa: E402


def touch(p: Path, size=10):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return p


class CleanupTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db._tx() as c:
            c.execute("DELETE FROM media_items")
            c.execute("DELETE FROM scanned_directories")
            c.execute("DELETE FROM cast_members")
        self.root = Path(tempfile.mkdtemp())
        did = db.add_directory(str(self.root), "Clean", True)
        video = touch(self.root / "Heat (1995).mkv")
        show = touch(self.root / "Show" / "Show S01E01.mkv")
        db.add_items([{"uuid": db.file_id(str(video)), "file_path": db.norm(str(video)), "parent_directory_id": did,
                       "title": "Heat", "media_type": "movie", "collection_id": 5, "collection_name": "Heat Set"},
                      {"uuid": db.file_id(str(show)), "file_path": db.norm(str(show)), "parent_directory_id": did,
                       "title": "Show S01E01", "media_type": "show"}])
        db.set_cast(db.file_id(str(video)), [{"id": 7, "name": "Al Pacino", "role": "Hanna"}])
        a, sa = self.root / scraper.ASSET_DIR, self.root / "Show" / scraper.ASSET_DIR
        self.keep = [touch(a / "Heat (1995).webp"), touch(a / "Heat (1995).banner.webp"), touch(a / "Heat (1995).front.webp"),
                     touch(a / "Heat (1995).gallery" / "s-01.webp"), touch(sa / "_series.banner.webp"),
                     touch(a / "notes.txt")]                                                   # not ours: never touched
        self.gone = [touch(a / "Old Film.webp", 100), touch(a / "Old Film.gallery" / "s-01.webp", 50),
                     touch(a / "Old Film.gallery" / "c-1-00.webp", 50)]
        cache = db.data_dir() / "cache"
        self.keep += [touch(cache / "set-5.webp"), touch(cache / "people" / "7.webp")]
        self.gone += [touch(cache / "set-99.webp"), touch(cache / "people" / "8.webp"), touch(cache / "box" / "nobody-front-abc.png")]
        self.own = [self.root / scraper.ASSET_DIR / "Heat (1995).front.webp"]

    def test_unused_goes_and_nothing_else(self):
        n, freed = cleanup.run("unused")
        self.assertTrue(all(not p.exists() for p in self.gone))
        self.assertTrue(all(p.exists() for p in self.keep))
        self.assertEqual(freed, 100 + 50 + 50 + 10 + 10 + 10)
        self.assertFalse((self.root / scraper.ASSET_DIR / "Old Film.gallery").exists())        # empty folder removed
        self.assertTrue((self.root / "Heat (1995).mkv").exists())

    def test_all_keeps_yours_and_videos(self):
        cleanup.run("all", keep_own=True)
        self.assertTrue(all(p.exists() for p in self.own))
        self.assertFalse((self.root / scraper.ASSET_DIR / "Heat (1995).webp").exists())
        self.assertTrue((self.root / scraper.ASSET_DIR / "notes.txt").exists())
        self.assertTrue((self.root / "Heat (1995).mkv").exists() and (self.root / "Show" / "Show S01E01.mkv").exists())
        cleanup.run("all", keep_own=False)
        self.assertFalse(any(p.exists() for p in self.own))

    def test_a_video_name_with_a_dot_keeps_its_art(self):
        video = touch(self.root / "Movie.banner.mkv")
        with db._tx() as c:
            did = c.execute("SELECT id FROM scanned_directories").fetchone()[0]
        db.add_items([{"uuid": db.file_id(str(video)), "file_path": db.norm(str(video)), "parent_directory_id": did,
                       "title": "M", "media_type": "movie"}])
        cover = touch(self.root / scraper.ASSET_DIR / "Movie.banner.webp")      # its cover, not "Movie"'s banner
        cleanup.run("unused")
        self.assertTrue(cover.exists())

    def test_usage_and_offline_folders(self):
        u = cleanup.usage()
        self.assertEqual(u["unusedCount"], 6)
        self.assertEqual(u["yours"], 10 + 50)            # your front cover, and your Gallery image of the old film
        with db._tx() as c:
            c.execute("UPDATE scanned_directories SET folder_path=?", (str(self.root / "unplugged"),))
        self.assertFalse(any(scraper.ASSET_DIR in p.parts for p, _ in cleanup.plan("unused")))  # drive gone: skipped

    def test_settings_wired(self):
        qml = (ROOT / "ui" / "SettingsView.qml").read_text(encoding="utf-8")
        self.assertIn('Backend.cleanAssets("unused", true)', qml)
        self.assertIn('Backend.cleanAssets("all", keepOwn.checked)', qml)
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_v132", wf)


if __name__ == "__main__":
    unittest.main()


class OverlayClickTests(unittest.TestCase):
    def test_no_overlay_lets_a_right_click_through(self):
        """A right click on View More fell through to the poster underneath, which opened that poster instead."""
        import re
        ui = ROOT / "ui"
        for f in list(ui.glob("*.qml")):
            for m in re.finditer(r"MouseArea \{ anchors\.fill: parent(?:; hoverEnabled: true)?(?:; onWheel[^}]*)? \}", f.read_text(encoding="utf-8")):
                self.fail(f"{f.name}: a blocker without acceptedButtons: {m.group(0)}")
        dv = (ui / "DetailView.qml").read_text(encoding="utf-8")
        scrim = dv[dv.index("// dim + click-outside-to-close"):dv.index("id: sheet")]
        self.assertIn("acceptedButtons: Qt.AllButtons", scrim)
        self.assertIn("if (m.button === Qt.LeftButton) root.close()", scrim)
        self.assertIn("hoverEnabled: true", scrim)

    def test_right_click_stays_on_the_overlay(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQuick import QQuickView
        from PySide6.QtTest import QTest
        QGuiApplication.instance() or QGuiApplication([])
        qml = Path(tempfile.mkdtemp()) / "t.qml"
        qml.write_text("""
import QtQuick
Item { width: 300; height: 200; property int under: 0; property int closed: 0
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton; onClicked: parent.under++ }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons
        onClicked: (m) => { if (m.button === Qt.LeftButton) parent.closed++ } } }
""", encoding="utf-8")
        view = QQuickView()
        view.setSource(qml.as_uri())
        view.show()
        for button in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            QTest.mouseClick(view, button, Qt.KeyboardModifier.NoModifier, QPoint(100, 100))
        QTest.qWait(30)
        root = view.rootObject()
        self.assertEqual((root.property("under"), root.property("closed")), (0, 1))
