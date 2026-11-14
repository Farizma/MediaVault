"""1.3.1: tag suggestions come from every tag in the library; Gallery tiles show each image's resolution."""
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
