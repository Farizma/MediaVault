"""1.0.2: AniList, auto tags, tab order, hiding from All, Gallery, crop editor, Custom theme colours."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from utils import anilist, autotag, scraper  # noqa: E402


class AniListTests(unittest.TestCase):
    MEDIA = {"id": 21, "format": "TV", "seasonYear": 1999, "title": {"english": None, "romaji": "One Piece", "native": "x"},
             "startDate": {"year": 1999, "month": 10, "day": 20},
             "description": "Gold Roger was known as the <i>Pirate King</i>.<br><br>He was executed. (Source: Crunchyroll)",
             "coverImage": {"extraLarge": "https://img/x.jpg"}, "bannerImage": "https://img/b.jpg",
             "genres": ["Action", "Adventure"], "averageScore": 88,
             "characters": {"edges": [{"role": "MAIN", "node": {"name": {"full": "Monkey D. Luffy"}},
                                       "voiceActors": [{"id": 95, "name": {"full": "Mayumi Tanaka"}, "image": {"large": "https://img/v.jpg"}}]},
                                      {"role": "MAIN", "node": {"name": {"full": "Nobody"}}, "voiceActors": []}]}}

    def test_shape_matches_a_tmdb_hit(self):
        hit = anilist._shape(self.MEDIA)
        self.assertEqual(hit["title"], "One Piece")                      # romaji when there is no English title
        self.assertEqual(hit["release_date"], "1999-10-20")
        self.assertEqual(hit["synopsis"], "Gold Roger was known as the Pirate King.\n\nHe was executed.")
        self.assertEqual(hit["score"], 8.8)
        self.assertEqual(hit["cast"], [{"id": anilist.PERSON_OFFSET + 95, "name": "Mayumi Tanaka", "role": "Monkey D. Luffy",
                                        "photo_url": "https://img/v.jpg"}])
        self.assertEqual(hit["gallery_urls"], ["https://img/b.jpg"])
        for k in ("poster_url", "genres", "collection_id", "disc_url"):
            self.assertIn(k, hit)

    def test_lookup_retries_without_year(self):
        calls = []

        def fake(q, v, retries=2):
            calls.append(v)
            return {} if "y" in v else {"Media": self.MEDIA}
        with mock.patch.object(anilist, "_post", side_effect=fake):
            self.assertEqual(anilist.lookup("one piece", "2001")["title"], "One Piece")
        self.assertEqual(len(calls), 2)


class AutoTagTests(unittest.TestCase):
    def test_folders_and_name(self):
        root = os.path.join("D:", os.sep, "Media")
        tags = autotag.tags_for(os.path.join(root, "Sci-Fi", "Blade Runner 2049 (2017)", "Blade.Runner.2049.2017.2160p.UHD.BluRay.REMUX.HDR.HEVC.Atmos.mkv"), root)
        self.assertEqual(tags[0], "Sci-Fi")                     # the title's own folder is not a tag
        for t in ("4K", "HDR", "Remux", "HEVC", "Atmos", "2010s"):
            self.assertIn(t, tags)
        self.assertNotIn("Blu-ray", tags)                       # one source per file: Remux wins

    def test_series_and_anime(self):
        root = os.path.join("D:", os.sep, "Anime")
        tags = autotag.tags_for(os.path.join(root, "Frieren", "Season 1", "[SubsPlease] Sousou no Frieren - 07 (1080p).mkv"), root, show=True)
        self.assertNotIn("Frieren", tags)
        self.assertNotIn("Season 1", tags)
        self.assertIn("1080p", tags)
        self.assertIn("Release: SubsPlease", tags)


class LibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_tab_order_and_source(self):
        a = db.add_directory(tempfile.mkdtemp(), "A", True)
        b = db.add_directory(tempfile.mkdtemp(), "B", True, source="anilist")
        self.assertEqual(db.get_directory(b)["source"], "anilist")
        db.set_directory_order([b, a])
        order = [d["id"] for d in db.list_directories() if d["id"] in (a, b)]
        self.assertEqual(order, [b, a])

    def test_hidden_from_all(self):
        cards = [{"uuid": "1", "parent_directory_id": 1}, {"uuid": "2", "parent_directory_id": 2}, {"uuid": "3", "parent_directory_id": 1}]
        index = {"3": {"tags": ["kids"], "genres": []}}
        db.set_hidden("all_dirs", [2])
        db.set_hidden("all_tags", ["kids"])
        self.assertEqual([c["uuid"] for c in db.visible_in_all(cards, index)], ["1"])
        db.set_hidden("all_dirs", [])
        db.set_hidden("all_tags", [])
        self.assertEqual(len(db.visible_in_all(cards, index)), 3)


class GalleryAndCropTests(unittest.TestCase):
    def test_gallery_keeps_your_images_first(self):
        from PIL import Image
        root = tempfile.mkdtemp()
        item = {"uuid": "u", "media_type": "movie", "file_path": os.path.join(root, "Heat.mkv")}
        with mock.patch.object(scraper, "fetch_image", return_value=Image.new("RGB", (1920, 1080), "blue")):
            self.assertEqual(scraper.save_gallery(item, ["https://a", "https://b"]), 2)
        d = scraper.gallery_dir(item)
        Image.new("RGB", (800, 450)).save(d / "c-01.webp")
        names = [p.name for p in scraper.gallery_images(item)]
        self.assertEqual(names[0], "c-01.webp")
        self.assertEqual(len(names), 3)

    def test_crop_saves_the_chosen_part(self):
        from PIL import Image
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        from ui import dashboard
        root = tempfile.mkdtemp()
        src = os.path.join(root, "art.png")
        img = Image.new("RGB", (400, 400), "white")
        img.paste(Image.new("RGB", (200, 400), "red"), (0, 0))
        img.save(src)
        item = {"uuid": "u", "media_type": "movie", "file_path": os.path.join(root, "Heat.mkv"), "title": "Heat"}
        d = dashboard.Dashboard.__new__(dashboard.Dashboard)
        d._art_items = lambda key: [item]
        d.toast = mock.MagicMock()
        d.boxArtChanged = mock.MagicMock()
        dashboard.Dashboard.saveCroppedArt(d, "u", "front", src, 0.0, 0.0, 0.5, 1.0, 0)   # the red half only
        out = Image.open(scraper.custom_front_path(item)).convert("RGB")
        r, g, b = out.getpixel((out.width // 2, out.height // 2))
        self.assertGreater(r, 200)
        self.assertLess(g, 60)


class CustomThemeTests(unittest.TestCase):
    def test_every_colour_applies(self):
        import ui
        custom = ui.custom_defaults()
        custom.update(custom_page="#101010", custom_text="#EEEEEE", custom_red="#FF0000", custom_accent="#00FF00")
        ui.apply_theme("custom", custom=custom)
        self.assertEqual(ui.THEME["black"].upper(), "#101010")
        self.assertEqual(ui.THEME["green"].upper(), "#00FF00")
        self.assertEqual(ui.THEME["text"].upper(), "#EEEEEE")
        self.assertEqual(ui.THEME["red"].upper(), "#FF0000")
        ui.apply_theme("midnight")


if __name__ == "__main__":
    unittest.main()
