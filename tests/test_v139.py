"""1.3.5: leave subfolders of a library folder out (Configure > Subfolders)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
import watcher  # noqa: E402
from tests.test_v133 import make_dashboard  # noqa: E402
from ui import dashboard  # noqa: E402


class SubfolderTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db._tx() as c:
            for t in ("media_items", "scanned_directories"):
                c.execute(f"DELETE FROM {t}")
        db.set_setting("excluded_subfolders", "")
        self.root = Path(tempfile.mkdtemp())
        for rel in ("a.mkv", "Extras/x.mkv", "Extras/Trailers/t.mkv", "Season 1/e1.mkv", "Season 1/e2.mkv", "Season 1/notes.txt"):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"")
        self.dir = db.add_directory(str(self.root), "Shows", False)
        self.d = db.get_directory(self.dir)

    def scan(self):
        with mock.patch.object(watcher, "_index", lambda d, new, t: db.add_items(
                [{"uuid": db.file_id(p), "file_path": p, "parent_directory_id": d["id"], "title": Path(p).stem,
                  "media_type": "movie"} for p in new])):
            watcher.scan_directory(self.d)

    def titles(self):
        return sorted(r["title"] for r in db.list_media(self.dir))

    def test_left_out_subfolder_is_hidden_kept_and_back(self):
        self.scan()
        self.assertEqual(self.titles(), ["a", "e1", "e2", "t", "x"])
        db.set_excluded_subfolders(self.dir, ["Extras"])
        self.assertEqual(self.titles(), ["a", "e1", "e2"])                       # Extras and Extras/Trailers
        self.scan()                                                             # a rescan does not prune them
        self.assertEqual(len(db.list_media(self.dir, everything=True)), 5)
        db.set_excluded_subfolders(self.dir, [])
        self.assertEqual(self.titles(), ["a", "e1", "e2", "t", "x"])

    def test_scan_skips_a_left_out_subfolder(self):
        db.set_excluded_subfolders(self.dir, ["Season 1"])
        self.scan()
        self.assertEqual(self.titles(), ["a", "t", "x"])
        self.assertEqual(len(db.list_media(self.dir, everything=True)), 3)      # never added
        self.assertTrue(db.is_excluded(self.dir, str(self.root / "Season 1" / "e3.mkv")))
        self.assertFalse(db.is_excluded(self.dir, str(self.root / "Season 10" / "e.mkv")))  # a prefix is not a folder

    def test_inner_choice_folds_into_outer(self):
        db.set_excluded_subfolders(self.dir, ["Extras/Trailers", "Extras", "../escape", str(self.root)])
        self.assertEqual(db.excluded_subfolders(self.dir), ["Extras"])

    def test_rows_are_a_tree_with_counts(self):
        rows = dashboard.subfolder_rows(str(self.root), ["Extras"])
        self.assertEqual([(r["name"], r["depth"], r["videos"], r["excluded"], r["inherited"]) for r in rows],
                         [("Extras", 0, 2, True, False), ("Trailers", 1, 1, False, True), ("Season 1", 0, 2, False, False)])

    def test_backend_tick_and_untick(self):
        self.scan()
        d = make_dashboard()
        d.setSubfolderIncluded(self.dir, "Season 1", False)
        self.assertEqual(db.excluded_subfolders(self.dir), ["Season 1"])
        self.assertEqual(next(x for x in d.directories() if x["id"] == self.dir)["leftOut"], 1)
        d.setSubfolderIncluded(self.dir, "Season 1", True)
        self.assertEqual(db.excluded_subfolders(self.dir), [])
        d.setSubfolderIncluded(self.dir, "../x", False)                        # outside the folder: ignored
        self.assertEqual(db.excluded_subfolders(self.dir), [])


if __name__ == "__main__":
    unittest.main()
