"""Needs PySide6 (skipped without it). Compiles every QML file with Qt's own compiler and exercises the
Python models. Run on your machine:  python -m unittest tests.test_qt  (uses the offscreen platform)."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp()
os.environ["LOCALAPPDATA"] = _TMP
HAVE_QT = importlib.util.find_spec("PySide6") is not None


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_every_qml_file_compiles(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlComponent, QQmlEngine
        from PySide6.QtQuickControls2 import QQuickStyle
        QQuickStyle.setStyle("Basic")
        engine = QQmlEngine()
        for f in sorted((ROOT / "ui").glob("*.qml")) + [ROOT / "player" / "Hud.qml"]:
            comp = QQmlComponent(engine, QUrl.fromLocalFile(str(f)))
            errors = [e.toString() for e in comp.errors()]
            self.assertNotEqual(comp.status(), QQmlComponent.Error, f"{f.name}:\n" + "\n".join(errors))

    def test_library_model_roles_and_inplace_refresh(self):
        import database as db
        from ui.dashboard import LibraryModel
        db.init_db()
        did = db.add_directory(os.path.join(_TMP, "m"), "M", True)
        p = os.path.join(_TMP, "m", "Film.mkv")
        db.add_items([{"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did, "title": "Film",
                       "media_type": "movie", "duration": 7200, "resolution": "1080p"}])
        model = LibraryModel()
        model.reload(None)
        self.assertEqual(model.rowCount(), 1)
        names = {bytes(v).decode() for v in model.roleNames().values()}
        self.assertTrue({"key", "title", "poster", "progress", "videoUrl"} <= names)
        self.assertEqual(model.data(model.index(0), LibraryModel.TITLE), "Film")
        seen = []
        model.modelReset.connect(lambda: seen.append("reset"))
        db.save_progress(db.file_id(p), 600, False)
        model.reload(None)
        self.assertEqual(seen, [])  # same cards: refreshed in place, scroll position kept

    def test_billboard_deck_is_random_stable_and_prefers_unwatched(self):
        from ui.dashboard import billboard_deck

        def card(i, done=False):
            return {"key": f"k{i}", "uuid": f"u{i}", "title": f"T{i}", "media_type": "movie", "is_completed": done,
                    "file_path": os.path.join(_TMP, "none", f"{i}.mkv"), "episodes": 0, "duration": 600,
                    "release_date": "2020", "resolution": "", "codec": "", "audio_layout": "", "synopsis": None}
        cards = [card(i) for i in range(20)] + [card(i, done=True) for i in range(20, 25)]
        deck = billboard_deck(cards, [], size=8)
        keys = [i["key"] for i in deck["items"]]
        self.assertEqual(len(keys), 8)
        self.assertEqual(len(set(keys)), 8)
        self.assertTrue(all(int(k[1:]) < 20 for k in keys))                 # finished titles stay out
        self.assertEqual([i["key"] for i in billboard_deck(cards, keys)["items"]], keys)  # refresh keeps the deck
        few = billboard_deck([card(1), card(2, done=True)], [], size=8)
        self.assertEqual([i["key"] for i in few["items"]], ["k1", "k2"])    # unwatched first, watched fills
        self.assertFalse(billboard_deck([], [])["visible"])

    def test_custom_box_art_wins_and_reset_restores_scraped(self):
        from PIL import Image
        from ui import dvd_box
        from ui.dashboard import save_box_art
        from utils import scraper
        item = {"uuid": "box1", "title": "Boxed", "media_type": "movie", "synopsis": "",
                "file_path": os.path.join(_TMP, "art", "Boxed.mkv")}
        scraper.save_webp(Image.new("RGB", (360, 540), "red"), scraper.poster_path(item))       # the scraped poster
        save_box_art(Image.new("RGB", (1000, 500), "blue"), [item, None], "front")               # wide image, cropped
        self.assertEqual(scraper.cover_path(item), scraper.custom_front_path(item))
        with Image.open(scraper.cover_path(item)) as im:
            self.assertAlmostEqual(im.width / im.height, 2 / 3, places=2)
        save_box_art(Image.new("RGB", (400, 600), "green"), [item], "back")
        tex = dvd_box.box_textures(item)
        self.assertTrue(tex["customFront"] and tex["customBack"])
        self.assertIn(".back.webp", tex["back"])
        scraper.custom_front_path(item).unlink()                                                  # what Reset does
        self.assertEqual(scraper.cover_path(item), scraper.poster_path(item))

    def test_volume_is_clamped_and_kept_between_files(self):
        from player.player_engine import PlayerEngine
        e = PlayerEngine(lambda p: None, None)
        e.setVolume(140)
        self.assertEqual(e.volume, 100)
        e.setVolume(-5)
        self.assertEqual(e.volume, 0)

    def test_frame_provider_round_trip(self):
        from PIL import Image
        from ui.dvd_box import FrameProvider
        fp = FrameProvider()
        fp.set_pil("snap", Image.new("RGB", (64, 36), (255, 0, 0)))
        img = fp.requestImage("snap?3", None, None)
        self.assertEqual((img.width(), img.height()), (64, 36))
        fp.clear("snap")
        self.assertEqual(fp.requestImage("snap", None, None).width(), 1)


if __name__ == "__main__":
    unittest.main()
