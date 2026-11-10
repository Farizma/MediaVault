"""Scrape options per folder, cast and actor photos, box sets you edit, fetch missing."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

import database as db  # noqa: E402
import watcher  # noqa: E402
from utils import scraper  # noqa: E402
from PIL import Image  # noqa: E402


def _row(root, did, name, kind="movie", **kw):
    p = os.path.join(root, f"{name}.mkv")
    r = {"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did, "title": name, "media_type": kind,
         "duration": 100}
    r.update(kw)
    return r


class ScrapeOptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_defaults_and_choices(self):
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "A", True)
        everything = {k for k, _ in db.SCRAPE_PARTS}
        self.assertEqual(db.scrape_opts(db.get_directory(did)), everything)
        db.set_scrape_opts(did, ["poster", "cast", "bogus"])
        self.assertEqual(db.scrape_opts(db.get_directory(did)), {"poster", "cast"})
        db.set_scrape_opts(did, [])
        self.assertEqual(db.scrape_opts(db.get_directory(did)), set())
        db.set_scrape(did, False)
        self.assertEqual(db.scrape_opts(db.get_directory(did)), set())
        did2 = db.add_directory(tempfile.mkdtemp(), "B", True, ["synopsis"])
        self.assertEqual(db.scrape_opts(db.get_directory(did2)), {"synopsis"})

    def test_scrape_respects_choices(self):
        root = tempfile.mkdtemp()
        row = _row(root, 1, "Heat", release_date="1995")
        hit = {"title": "Heat", "release_date": "1995-12-15", "synopsis": "Thieves.", "genres": ["Crime"],
               "poster_url": "http://p", "tmdb_id": 949, "collection_id": 5, "collection_name": "X",
               "collection_poster_url": None, "disc_url": None,
               "cast": [{"id": 1, "name": "Al Pacino", "role": "Hanna", "photo_url": "http://a"}]}
        tags = []

        async def fake_many(jobs, keys, source="tmdb"):
            return [hit]
        with mock.patch.object(scraper, "api_keys", return_value={"tmdb": "K", "omdb": "", "fanart": ""}), \
                mock.patch.object(scraper, "scrape_many", fake_many), \
                mock.patch.object(scraper, "fetch_image", return_value=Image.new("RGB", (300, 450))) as fetch:
            watcher._scrape_into([(row, scraper.Parsed("heat", "1995", None, None))], tags, {"synopsis", "cast"})
        self.assertEqual(row["synopsis"], "Thieves.")
        self.assertNotIn("collection_id", row)            # box sets not chosen
        self.assertEqual(tags, [])                        # genres not chosen
        fetch.assert_not_called()                         # no poster, no photos
        self.assertEqual(db.get_cast(row["uuid"])[0]["name"], "Al Pacino")


class CastTests(unittest.TestCase):
    def test_film_and_series_credits(self):
        film = scraper._cast([{"id": 3, "name": "Ryan Gosling", "character": "K", "profile_path": "/g.jpg"},
                              {"id": 4, "name": "", "character": "x"}])
        self.assertEqual(film, [{"id": 3, "name": "Ryan Gosling", "role": "K", "photo_url": "https://image.tmdb.org/t/p/w185/g.jpg"}])
        show = scraper._cast([{"id": 5, "name": "Adam Scott", "profile_path": None,
                               "roles": [{"character": "Mark S.", "episode_count": 19}, {"character": "Mark", "episode_count": 2}]}])
        self.assertEqual((show[0]["role"], show[0]["photo_url"]), ("Mark S.", None))

    def test_series_share_one_cast(self):
        ep = {"uuid": "u", "media_type": "show", "file_path": os.path.join("/tv", "Severance", "S01E01.mkv")}
        self.assertEqual(db.cast_owner(ep), "show:" + os.path.join("/tv", "Severance"))
        db.init_db()
        db.set_cast("o", [{"id": 1, "name": "A", "role": "r"}, {"id": 2, "name": "B"}])
        db.set_cast("o", [{"id": 2, "name": "B", "role": "s"}])
        self.assertEqual([c["name"] for c in db.get_cast("o")], ["B"])

    def test_round_photo_has_transparent_corners(self):
        dest = Path(tempfile.mkdtemp()) / "p.webp"
        scraper.save_round(Image.new("RGB", (185, 278), "red"), dest)
        im = Image.open(dest)
        self.assertEqual(im.size, (160, 160))
        self.assertEqual(im.getpixel((0, 0))[3], 0)
        self.assertEqual(im.getpixel((80, 80))[3], 255)


class EditableSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.root = tempfile.mkdtemp()
        cls.did = db.add_directory(cls.root, "Mine", True)
        db.add_items([_row(cls.root, cls.did, "Before Sunrise"), _row(cls.root, cls.did, "Before Sunset"),
                      _row(cls.root, cls.did, "Heat")])

    def _uid(self, name):
        return db.file_id(os.path.join(self.root, f"{name}.mkv"))

    def test_make_add_remove(self):
        cid = db.new_set_id()
        self.assertLess(cid, 0)
        db.add_to_set([self._uid("Before Sunrise")], cid, "Before Trilogy")
        keys = [c["key"] for c in db.list_library(self.did)]
        self.assertIn(f"set:{cid}", keys)                 # your own set shows even with one film
        db.add_to_set([self._uid("Before Sunset")], cid, "Before Trilogy")
        box = next(c for c in db.list_library(self.did) if c["key"] == f"set:{cid}")
        self.assertEqual(box["films"], 2)
        self.assertIn({"id": cid, "name": "Before Trilogy", "films": 2}, db.box_sets())
        db.remove_from_set(db.uuids_for(f"set:{cid}"))
        self.assertNotIn(f"set:{cid}", [c["key"] for c in db.list_library(self.did)])
        self.assertLess(db.new_set_id(), 0)


class FetchMissingTests(unittest.TestCase):
    def test_fills_gaps_without_touching_titles(self):
        db.init_db()
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "FM", True, ["cast", "synopsis", "genres"])
        row = _row(root, did, "My Own Title", tmdb_id=949)
        db.add_items([row])
        details = {"tmdb_id": 949, "title": "Heat", "release_date": "1995", "synopsis": "Thieves.", "poster_url": None,
                   "genres": ["Crime"], "collection_id": None, "collection_name": None, "collection_poster_url": None,
                   "cast": [{"id": 1, "name": "Al Pacino", "role": "Hanna", "photo_url": None}]}
        with mock.patch.object(scraper, "api_keys", return_value={"tmdb": "K", "omdb": "", "fanart": ""}), \
                mock.patch.object(scraper, "tmdb_details", return_value=details) as det:
            self.assertEqual(watcher.fetch_missing(db.get_directory(did)), 1)
            self.assertEqual(watcher.fetch_missing(db.get_directory(did)), 0)   # nothing left to fetch
        self.assertEqual(det.call_count, 1)
        item = db.get_media(row["uuid"])
        self.assertEqual((item["title"], item["synopsis"]), ("My Own Title", "Thieves."))
        self.assertIn("genre:Crime", db.tags_for(row["uuid"]))
        self.assertEqual(db.get_cast(row["uuid"])[0]["role"], "Hanna")


if __name__ == "__main__":
    unittest.main()
