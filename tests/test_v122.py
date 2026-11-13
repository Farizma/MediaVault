"""1.2.0 performance pass: no per-frame billboard redraw, one folder listing per refresh, parallel artwork."""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PerfTests(unittest.TestCase):
    def test_billboard_bar_is_outside_the_masked_picture(self):
        qml = (ROOT / "ui" / "Dashboard.qml").read_text(encoding="utf-8")
        masked = qml[qml.index("id: bbArt"):qml.index("Item { id: bbMask")]
        self.assertNotIn("billboard.progress", masked)
        self.assertIn("maskSource: posterMask", qml)
        self.assertEqual(qml.count("Item { id: posterMask"), 1)          # one mask for every card

    def test_folder_index_lists_each_folder_once(self):
        from ui.dashboard import FolderIndex
        d = Path(tempfile.mkdtemp())
        (d / "a.webp").write_bytes(b"x")
        files = FolderIndex()
        with mock.patch("os.scandir", wraps=os.scandir) as scan:
            self.assertTrue(files.has(d / "a.webp"))
            self.assertFalse(files.has(d / "b.webp"))
            self.assertIn("?v=", files.url(d / "a.webp"))
            self.assertFalse(files.has(d / "missing" / "x.webp"))       # a gone folder is just empty
            self.assertEqual(scan.call_count, 2)

    def test_unchanged_refresh_touches_nothing(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        import database as db
        db.init_db()
        from ui.dashboard import LibraryModel
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "Perf", True)
        p = os.path.join(root, "A.mkv")
        open(p, "w").close()
        db.add_items([{"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did, "title": "A",
                       "media_type": "movie", "duration": 60}])
        m = LibraryModel()
        m.reload(did)
        seen = []
        m.dataChanged.connect(lambda *a: seen.append("changed"))
        m.modelReset.connect(lambda: seen.append("reset"))
        m.reload(did)
        self.assertEqual(seen, [])

    def test_gallery_images_download_together(self):
        from PIL import Image
        from utils import scraper
        running, peak, lock = [0], [0], threading.Lock()

        def slow(url):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            time.sleep(0.05)
            with lock:
                running[0] -= 1
            return Image.new("RGB", (16, 9))
        item = {"media_type": "movie", "file_path": str(Path(tempfile.mkdtemp()) / "F.mkv"), "uuid": "u"}
        with mock.patch.object(scraper, "fetch_image", side_effect=slow):
            self.assertEqual(scraper.save_gallery(item, [f"https://x/{i}.jpg" for i in range(6)]), 6)
        self.assertGreater(peak[0], 1)
        self.assertEqual(sorted(p.name for p in scraper.gallery_dir(item).iterdir()),
                         [f"s-{i:02d}.webp" for i in range(1, 7)])             # same names and order as before

    def test_gpu_lines_reach_the_log_and_index_exists(self):
        self.assertIn('"qt.scenegraph.general", "qt.rhi.general"', (ROOT / "main.py").read_text(encoding="utf-8"))
        import database as db
        db.init_db()
        names = [r[0] for r in db.conn().execute("SELECT name FROM sqlite_master WHERE type='index'")]
        self.assertIn("idx_media_collection", names)
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_v122", wf)
        self.assertIn("tests.test_qt", wf)


if __name__ == "__main__":
    unittest.main()
