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


SCENE = {"id": "a1b2", "_id": 77, "title": "Sunset Swim", "date": "2024-03-15", "description": "<b>Two</b> friends.",
         "site": {"id": 12, "name": "Example Studio", "network": {"name": "Example Network"}},
         "performers": [{"name": "Jo", "image": "https://img/x.jpg", "parent": {"_id": 5, "name": "Jo Smith",
                                                                              "image": {"large": "https://img/jo.jpg"}}}],
         "tags": [{"name": "Outdoor"}, {"name": "Outdoor"}, {"name": "Pool"}],
         "poster": {"small": "https://img/p-s.jpg", "large": "https://img/p-l.jpg"},
         "background": {"medium": "https://img/b-m.jpg", "full": "https://img/b-f.jpg"},
         "hashes": [{"hash": "00000000000a0000", "type": "OSHASH"}]}


class TPDBTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.root = Path(tempfile.mkdtemp())

    def test_shape_like_tmdb(self):
        from utils import tpdb
        h = tpdb._shape(SCENE)
        self.assertEqual((h["tpdb_id"], h["title"], h["release_date"], h["synopsis"]),
                         ("scenes:a1b2", "Sunset Swim", "2024-03-15", "Two friends."))
        self.assertEqual(h["poster_url"], "https://img/p-l.jpg")                    # the largest size given
        self.assertEqual(h["banner_url"], "https://img/b-f.jpg")
        self.assertEqual(h["genres"], ["Outdoor", "Pool"])
        self.assertEqual(h["studios"], ["Example Studio", "Example Network"])
        self.assertEqual(h["cast"], [{"id": tpdb.PERSON_OFFSET + 5, "name": "Jo Smith", "role": "Jo",
                                      "photo_url": "https://img/jo.jpg"}])
        self.assertEqual((h["collection_id"], h["collection_name"], h["certification"]),
                         (tpdb.SET_OFFSET + 12, "Example Studio", "18+"))

    def test_oshash(self):
        from utils import tpdb
        p = self.root / "v.mp4"
        p.write_bytes(b"\x01" + b"\x00" * (200_000 - 1))
        self.assertEqual(tpdb.oshash(str(p)), f"{(200_000 + 1) & (2**64 - 1):016x}")
        (self.root / "tiny.mp4").write_bytes(b"x")
        self.assertIsNone(tpdb.oshash(str(self.root / "tiny.mp4")))

    def test_lookup_takes_a_fitting_result_only(self):
        from utils import tpdb
        p = self.root / "ExampleStudio.24.03.15.Sunset.Swim.1080p.mp4"
        p.write_bytes(b"")
        asked = []

        def get(path, key):
            asked.append(path)
            return {"data": [{**SCENE, "title": "Something Else Entirely"}, SCENE]} if path.startswith("/scenes") else {}
        with mock.patch.object(tpdb, "_get", get):
            self.assertEqual(tpdb.lookup(str(p), "k")["title"], "Sunset Swim")
            self.assertIn("parse=ExampleStudio.24.03.15.Sunset.Swim", asked[0])
            self.assertNotIn("1080p", asked[0])
        with mock.patch.object(tpdb, "_get", lambda path, key: {"data": [{**SCENE, "title": "Other Thing"}]}):
            self.assertIsNone(tpdb.lookup(str(p), "k"))                            # scenes, then movies: nothing fits
        with self.assertRaises(tpdb.TPDBError):
            tpdb.lookup(str(p), "")

    def test_adult_folder_scrape(self):
        from utils import tpdb
        with db._tx() as c:
            for t in ("media_items", "scanned_directories"):
                c.execute(f"DELETE FROM {t}")
        (self.root / "Example Studio - Sunset Swim.mp4").write_bytes(b"")
        (self.root / "Show S01E02.mp4").write_bytes(b"")
        d = db.get_directory(db.add_directory(str(self.root), "Adult", True, ["titles", "synopsis", "genres", "sets"], "tpdb"))
        self.assertEqual(d["source"], "tpdb")
        db.set_setting("tpdb_key", "k")
        with mock.patch.object(tpdb, "lookup", lambda p, k: tpdb._shape(SCENE) if "Sunset" in p else None), \
                mock.patch.object(watcher, "_headless", lambda: None):
            watcher.scan_directory(d)
        rows = {Path(r["file_path"]).name: r for r in db.list_media(d["id"])}
        swim = rows["Example Studio - Sunset Swim.mp4"]
        self.assertEqual((swim["title"], swim["tpdb_id"], swim["collection_name"]), ("Sunset Swim", "scenes:a1b2", "Example Studio"))
        self.assertIn("genre:Pool", db.tags_for(swim["uuid"]))
        self.assertIn("studio:Example Studio", db.tags_for(swim["uuid"]))
        self.assertEqual(rows["Show S01E02.mp4"]["media_type"], "movie")             # an adult folder has no series
        db.set_setting("tpdb_key", "")


if __name__ == "__main__":
    unittest.main()
