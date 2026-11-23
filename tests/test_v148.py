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
