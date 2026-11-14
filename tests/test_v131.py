"""1.3.0: more sources (TVmaze, MyAnimeList, Kitsu, fanart.tv), disc art and "Upload file" in Fix Scraped Data."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from utils import scraper, sources  # noqa: E402

TVMAZE = {"id": 82, "name": "Game of Thrones", "premiered": "2011-04-17", "summary": "<p>Nine noble families.</p>",
          "genres": ["Drama", "Fantasy"], "rating": {"average": 8.9}, "image": {"original": "https://static.tvmaze.com/p.jpg"},
          "externals": {"thetvdb": 121361, "imdb": "tt0944947"},
          "_embedded": {"cast": [{"person": {"name": "Peter Dinklage", "image": {"medium": "https://x/pd.jpg"}}, "character": {"name": "Tyrion"}}],
                        "images": [{"type": "poster", "main": True, "resolutions": {"original": {"url": "https://static.tvmaze.com/main.jpg"}}},
                                   {"type": "background", "resolutions": {"original": {"url": "https://static.tvmaze.com/bg.jpg"}}},
                                   {"type": "background", "resolutions": {"original": {"url": "http://insecure/bg.jpg"}}}]}}
MAL = {"data": {"mal_id": 1, "title": "Cowboy Bebop", "title_english": "Cowboy Bebop", "title_japanese": "カウボーイビバップ",
                "synopsis": "Bounty hunters. [Written by MAL Rewrite]", "score": 8.75, "rating": "R - 17+ (violence & profanity)",
                "aired": {"from": "1998-04-03T00:00:00+00:00"}, "type": "TV", "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/l.jpg"}},
                "genres": [{"name": "Action"}], "themes": [{"name": "Space"}], "studios": [{"name": "Sunrise"}], "titles": []}}
KITSU = {"data": {"id": "1", "attributes": {"canonicalTitle": "Cowboy Bebop", "titles": {"en": "Cowboy Bebop", "ja_jp": "カウボーイビバップ"},
                                            "synopsis": "Space.", "averageRating": "82.5", "ageRating": "R", "startDate": "1998-04-03",
                                            "posterImage": {"original": "https://media.kitsu.app/p.jpg"},
                                            "coverImage": {"original": "https://media.kitsu.app/c.jpg"}, "subtype": "TV"}},
         "included": [{"type": "categories", "attributes": {"title": "Space"}}]}
FANART = {"name": "Heat", "movieposter": [{"url": "https://assets.fanart.tv/a.jpg", "likes": "2", "lang": "de"},
                                          {"url": "https://assets.fanart.tv/b.jpg", "likes": "1", "lang": "en"}],
          "moviebackground": [{"url": "https://assets.fanart.tv/bg.jpg", "likes": "5", "lang": ""}],
          "moviedisc": [{"url": "https://assets.fanart.tv/d.png", "likes": "3", "lang": "en"}]}


class SourceTests(unittest.TestCase):
    def test_tvmaze(self):
        with mock.patch.object(sources, "_get", return_value=TVMAZE):
            h = sources.tvmaze_details(82)
        self.assertEqual((h["title"], h["synopsis"], h["score"], h["tvdb_id"]), ("Game of Thrones", "Nine noble families.", 8.9, 121361))
        self.assertEqual(h["poster_url"], "https://static.tvmaze.com/main.jpg")
        self.assertEqual(h["gallery_urls"], ["https://static.tvmaze.com/bg.jpg"])          # HTTPS only
        self.assertEqual(h["cast"][0]["role"], "Tyrion")

    def test_mal_and_kitsu(self):
        with mock.patch.object(sources, "_get", return_value=MAL), \
                mock.patch("utils.anilist.mal_pictures", return_value=("https://cdn.myanimelist.net/g.jpg",)):
            h = sources.mal_details(1)
        self.assertEqual(h["synopsis"], "Bounty hunters.")
        self.assertEqual((h["certification"], h["score"], h["studios"]), ("R", 8.75, ["Sunrise"]))
        self.assertIn("Space", h["genres"])
        with mock.patch.object(sources, "_get", return_value=KITSU):
            k = sources.kitsu_details("1")
        self.assertEqual((k["score"], k["score_scale"], k["banner_url"]), (8.2, "percent", "https://media.kitsu.app/c.jpg"))
        from ui.dashboard import match_preview
        self.assertEqual(match_preview({**k, "kitsu_id": "1"})["score"], "82%")

    def test_fanart_prefers_english_and_has_disc(self):
        with mock.patch.object(sources, "_get", return_value=FANART):
            a = sources.fanart_details("movie", 949, "key")
        self.assertEqual(a["poster_url"], "https://assets.fanart.tv/b.jpg")     # English before more likes in German
        self.assertEqual(a["disc_url"], "https://assets.fanart.tv/d.png")
        self.assertIsNone(sources.fanart_details("movie", 949, ""))              # no key: not asked

    def test_links(self):
        self.assertEqual(scraper.parse_link("https://www.tvmaze.com/shows/82/game-of-thrones")["source"], "tvmaze")
        self.assertEqual(scraper.parse_link("https://kitsu.app/anime/cowboy-bebop"), {"source": "kitsu", "id": "cowboy-bebop", "kind": None})
        self.assertEqual(scraper.parse_link("https://myanimelist.net/anime/1/x")["source"], "mal")


class ApplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        cls.qapp = QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        db.init_db()
        cls.root = tempfile.mkdtemp()
        did = db.add_directory(cls.root, "Up", True)
        p = os.path.join(cls.root, "film.mkv")
        open(p, "w").close()
        cls.uid = db.file_id(p)
        db.add_items([{"uuid": cls.uid, "file_path": db.norm(p), "parent_directory_id": did, "title": "film", "media_type": "movie", "duration": 60}])
        app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None)
        cls.d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())

    def test_uploads_become_your_art_and_disc_from_fanart(self):
        from PIL import Image
        poster = os.path.join(self.root, "mine.png")
        Image.new("RGB", (300, 450), "red").save(poster)
        shot = os.path.join(self.root, "shot.jpg")
        Image.new("RGB", (640, 360), "blue").save(shot)
        self.d._match_hits[self.uid] = {"tmdb|movie:1": {"title": "Film", "tmdb_id": 1},
                                        "fanart|movie:1": {"disc_url": "https://assets.fanart.tv/d.png", "art_only": True}}
        choices = {"poster": "file:" + poster, "disc": "fanart|movie:1", "gallery": ["file:" + shot, "file:/etc/passwd"]}
        with mock.patch.object(scraper, "fetch_image", return_value=Image.new("RGB", (500, 500))):
            self.d._apply_parts(self.uid, choices, "tmdb|movie:1")
        item = db.get_media(self.uid)
        self.assertTrue(scraper.custom_front_path(item).exists())                # your file: your own front cover
        self.assertTrue(scraper.disc_path(item).exists())
        names = [p.name for p in scraper.gallery_dir(item).iterdir()]
        self.assertEqual(len(names), 1)                                            # not an image: ignored
        self.assertTrue(names[0].startswith("c-"))

    def test_only_real_images_are_taken(self):
        from ui.dashboard import _upload_path
        self.assertIsNone(_upload_path("file:/etc/passwd"))
        self.assertIsNone(_upload_path("https://x/y.jpg"))
        self.assertIsNone(_upload_path(None))

    def test_window_and_workflow(self):
        fm = (ROOT / "ui" / "FixMatch.qml").read_text(encoding="utf-8")
        self.assertIn('["disc", "Disc art", "disc"]', fm)
        self.assertIn("Backend.pickMatchFiles(root.key, fieldRow.f)", fm)
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_v131", wf)


if __name__ == "__main__":
    unittest.main()
