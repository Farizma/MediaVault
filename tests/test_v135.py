"""1.3.1: tag suggestions from every tag in the library; Gallery resolution; drop images on the Gallery; search spinner."""
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
from tests.test_v133 import make_dashboard  # noqa: E402


class TagSuggestionTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db._tx() as c:
            for t in ("media_items", "scanned_directories", "tags"):
                c.execute(f"DELETE FROM {t}")
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "Films", True)
        rows = []
        for i in range(3):
            p = os.path.join(root, f"f{i}.mkv")
            rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did, "title": f"F{i}", "media_type": "movie"})
        tags = [(rows[0]["uuid"], "genre:Drama"), (rows[1]["uuid"], "genre:Drama"), (rows[2]["uuid"], "genre:Horror"),
                (rows[0]["uuid"], "studio:Ghibli"), (rows[0]["uuid"], "auto:Rated PG"), (rows[1]["uuid"], "rating:4"),
                (rows[2]["uuid"], "Rewatch"), (rows[1]["uuid"], "Rated PG")]          # yours and an automatic one, same name
        db.add_items(rows, tags)
        self.d = make_dashboard()

    def test_every_tag_is_suggested(self):
        got = self.d.tagNames()
        self.assertEqual([(t["name"], t["label"], t["kind"]) for t in got], [
            ("Rated PG", "Rated PG", ""), ("Rewatch", "Rewatch", ""),          # yours first
            ("genre:Drama", "Drama", "Genre"), ("genre:Horror", "Horror", "Genre"),   # then genres, most used first
            ("studio:Ghibli", "Ghibli", "Studio")])                             # the automatic "Rated PG" is the same tag as yours: once
        self.assertNotIn("rating:4", [t["name"] for t in got])

    def test_a_genre_suggestion_can_be_added_in_bulk(self):
        self.d.reload()
        uid = self.d.library._rows[0]["key"]
        self.d.bulkTag([uid], "studio:Ghibli", True)
        self.assertIn("studio:Ghibli", db.tags_for(uid))
        self.d.bulkTag([uid], "auto:Sneaky", True)
        self.assertNotIn("auto:Sneaky", db.tags_for(uid))

    def test_tag_field_matches_labels(self):
        qml = (ROOT / "ui" / "TagField.qml").read_text(encoding="utf-8")
        self.assertIn("t.label.toLowerCase()", qml)
        self.assertIn("take(modelData.name)", qml)


class GalleryDropTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db._tx() as c:
            for t in ("media_items", "scanned_directories"):
                c.execute(f"DELETE FROM {t}")
        self.root = tempfile.mkdtemp()
        did = db.add_directory(self.root, "Films", True)
        p = os.path.join(self.root, "film.mkv")
        open(p, "w").close()
        self.uid = db.file_id(p)
        db.add_items([{"uuid": self.uid, "file_path": db.norm(p), "parent_directory_id": did, "title": "Film", "media_type": "movie"}])
        self.d = make_dashboard()

    def test_dropped_files_and_links(self):
        from unittest import mock
        from PIL import Image
        from PySide6.QtCore import QUrl
        from utils import scraper
        img = os.path.join(self.root, "still.PNG")
        Image.new("RGB", (2400, 1000)).save(img, "PNG")
        notes = os.path.join(self.root, "notes.txt")
        open(notes, "w").close()
        linked = []
        with mock.patch("threading.Thread", side_effect=lambda target, **k: mock.Mock(start=target)), \
                mock.patch.object(self.d, "importGalleryImages", side_effect=lambda k, l, r: linked.append((l, r))):
            self.d.dropGalleryImages(self.uid, [QUrl.fromLocalFile(img).toString(), QUrl.fromLocalFile(notes).toString(),
                                                "https://image.tmdb.org/t/p/original/x.jpg"])
        saved = [p.name for p in scraper.gallery_images(db.get_media(self.uid))]
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].startswith("c-"))                        # your own: a later scrape keeps it
        self.assertEqual(linked, [("https://image.tmdb.org/t/p/original/x.jpg", False)])   # a web picture: imported, scraped ones stay
        toasts = []
        self.d.toast.connect(toasts.append)
        self.d.dropGalleryImages(self.uid, [QUrl.fromLocalFile(notes).toString()])
        self.assertEqual(toasts, ["Only image files can go in the Gallery"])

    def test_search_reports_sites_still_answering(self):
        from unittest import mock
        from utils import anilist, scraper, sources
        import threading
        waits, real = [], threading.Thread
        self.d.matchWaiting.connect(lambda k, sites: waits.append(list(sites)))
        inline = lambda *a, target=None, name="", **k: mock.Mock(start=target) if name == "match-search" else real(*a, target=target, name=name, **k)  # noqa: E731
        with mock.patch("threading.Thread", side_effect=inline), \
                mock.patch.object(scraper, "api_keys", return_value={"tmdb": "", "omdb": "", "fanart": ""}), \
                mock.patch.object(anilist, "search", return_value=[]), mock.patch.object(sources, "mal_search", return_value=[]), \
                mock.patch.object(sources, "kitsu_search", side_effect=RuntimeError("down")):
            self.d.searchMatch(self.uid, "Film", "")
        self.assertEqual(sorted(waits[0]), ["AniList", "Kitsu", "MyAnimeList"])
        self.assertEqual(waits[-1], [])                                   # the spinner always stops
        self.assertEqual([len(w) for w in waits[:-1]], [3, 2, 1, 0])


class GallerySizeTests(unittest.TestCase):
    def test_size_label(self):
        from PIL import Image
        from ui.dashboard import image_size
        p = Path(tempfile.mkdtemp()) / "s-01.webp"
        Image.new("RGB", (1920, 1080)).save(p)
        self.assertEqual(image_size(p), "1920 × 1080")
        self.assertEqual(image_size(p.with_name("gone.webp")), "")
        self.assertIn("modelData.size", (ROOT / "ui" / "DetailView.qml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
