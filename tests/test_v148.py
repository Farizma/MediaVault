"""1.4.3: big libraries (6,000+ videos) switch tabs without freezing: pictures are looked up as cards are drawn,
the data folder is made once, folder cards load their pictures as they scroll near."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402


class BigLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])

    def setUp(self):
        db.init_db()
        with db._tx() as c:
            c.execute("DELETE FROM media_items")
            c.execute("DELETE FROM scanned_directories")
        self.root = tempfile.mkdtemp()
        self.did = db.add_directory(self.root, "Clips", False)
        rows = []
        for i in range(3000):
            p = os.path.join(self.root, f"a{i // 50}", f"clip {i}.mp4")
            rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": self.did,
                         "title": f"clip {i}", "media_type": "clip", "duration": 60})
        db.add_items(rows)

    def test_pictures_only_for_cards_drawn(self):
        from ui.dashboard import LibraryModel
        m = LibraryModel()
        with mock.patch("ui.dashboard.LibraryModel._find_art", autospec=True,
                        return_value={"poster": "", "spine": "", "disc": "", "thumb": ""}) as find:
            t = time.perf_counter()
            m.reload(self.did, fresh=True)
            took = time.perf_counter() - t
            self.assertEqual(m.rowCount(), 3000)
            self.assertEqual(find.call_count, 0)                         # none looked up to build the tab
            self.assertEqual(m.data(m.index(5), m.POSTER), "")
            m.data(m.index(5), m.THUMB)
            self.assertEqual(find.call_count, 1)                         # one card, once
        self.assertLess(took, 2.0)

    def test_data_folder_made_once(self):
        with mock.patch.object(Path, "mkdir") as mk:
            db._made_dirs.clear()
            for _ in range(100):
                db.data_dir()
        self.assertEqual(mk.call_count, 1)

    def test_folder_cards_load_when_near(self):
        dash = (ROOT / "ui" / "Dashboard.qml").read_text(encoding="utf-8")
        card = (ROOT / "ui" / "FolderCard.qml").read_text(encoding="utf-8")
        self.assertIn("load: seen", dash)
        self.assertIn('source: root.load ? (root.info.picture || "") : ""', card)
        self.assertIn('|| ""     // a recycled card has no data for a moment', dash)


if __name__ == "__main__":
    unittest.main()


class CardCacheTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        from PIL import Image
        self.dir = Path(tempfile.mkdtemp()) / "アーティスト 100%"
        self.dir.mkdir()
        self.cover = self.dir / "cover.webp"
        Image.new("RGB", (1200, 1800), (200, 30, 60)).save(self.cover, "WEBP")
        self.wide = self.dir / "wide.webp"
        Image.new("RGB", (1440, 810), (20, 30, 160)).save(self.wide, "WEBP")

    def test_address_round_trip(self):
        from utils import cardcache
        u = cardcache.url(self.cover)
        self.assertTrue(u.startswith("image://card/"))
        self.assertNotIn("/", u[len("image://card/"):])                  # one segment, no escaping trouble
        self.assertEqual(cardcache.local_path(u), str(self.cover))
        from PySide6.QtCore import QUrl
        self.assertEqual(cardcache.local_path(QUrl.fromLocalFile(str(self.cover)).toString()), str(self.cover).replace(os.sep, "/"))

    def test_card_sized_copy_then_memory(self):
        from PySide6.QtCore import QSize
        from utils import cardcache
        cache = cardcache.Cache()
        path, mtime = cardcache.parse(cardcache.url(self.cover)[len("image://card/"):])
        img = cache.get(path, mtime, 600, 900)                            # 400 x 600 at 150 % scaling
        self.assertEqual((img.width(), img.height()), (600, 900))
        self.assertTrue(cache.has_copy(path, mtime, 600, 900))
        with mock.patch.object(cardcache, "decode") as dec:
            self.assertIs(cache.get(path, mtime, 600, 900), img)          # memory: no disk, no decode
            cache.clear()
            again = cache.get(path, mtime, 600, 900)                      # the small copy: no decode of the original
            dec.assert_not_called()
        self.assertEqual(again.size(), QSize(600, 900))
        wide = cache.get(str(self.wide), 0, 400, 600)                     # covers the card, shape kept
        self.assertEqual((wide.width(), wide.height()), (1067, 600))
        big = cache.get(path, mtime, 0, 0)                                # View More: the original, no copy
        self.assertEqual(big.width(), 1200)

    def test_memory_budget(self):
        from utils import cardcache
        cache = cardcache.Cache(budget=3 * 400 * 600 * 4)
        for i in range(6):
            cache.get(str(self.cover), i, 400, 600)
        self.assertLessEqual(cache._bytes, cache.budget)
        self.assertEqual(len(cache._ram), 3)

    def test_provider_and_warm(self):
        from PySide6.QtCore import QSize
        from utils import cardcache
        u = cardcache.url(self.cover)
        img = cardcache.CardProvider().requestImage(u[len("image://card/"):], QSize(), QSize(400, 600))
        self.assertEqual((img.width(), img.height()), (400, 600))
        bad = cardcache.CardProvider().requestImage("nonsense", QSize(), QSize(400, 600))
        self.assertEqual(bad.width(), 1)
        p, m = cardcache.parse(cardcache.url(self.wide)[len("image://card/"):])
        got = cardcache.warm([(p, m, 640, 360, True), (p, m, 960, 540, False)], workers=2)
        self.assertEqual(got["made"], 2)
        self.assertEqual(got["in_memory"], 1)
        self.assertEqual(cardcache.warm([(p, m, 640, 360, False)])["made"], 0)
