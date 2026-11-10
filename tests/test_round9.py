"""Box sets, fix match, Discord status, HDR options."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

import database as db  # noqa: E402
from utils import discord_presence as dp, hw_accelerator, scraper  # noqa: E402


def _film(root, did, name, cid=None, cname=None, date=""):
    p = os.path.join(root, f"{name}.mkv")
    return {"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did, "title": name,
            "media_type": "movie", "release_date": date, "duration": 100, "collection_id": cid, "collection_name": cname}


class BoxSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.root = tempfile.mkdtemp()
        cls.did = db.add_directory(cls.root, "Sets", True)
        db.add_items([_film(cls.root, cls.did, "Dune Part Two", 726871, "Dune Collection", "2024-03-01"),
                      _film(cls.root, cls.did, "Dune", 726871, "Dune Collection", "2021-10-22"),
                      _film(cls.root, cls.did, "Alien", 8091, "Alien Collection", "1979-05-25"),
                      _film(cls.root, cls.did, "Heat")])

    def test_two_films_make_a_set_one_stays_alone(self):
        cards = db.list_library(self.did)
        keys = {c["key"]: c for c in cards}
        self.assertIn("set:726871", keys)
        box = keys["set:726871"]
        self.assertEqual(box["title"], "Dune Collection")
        self.assertEqual(box["films"], 2)
        self.assertEqual(box["file_path"], db.norm(os.path.join(self.root, "Dune.mkv")))   # first by release, next up
        self.assertNotIn("set:8091", keys)         # a lone film of a collection is a normal card
        self.assertEqual(len(cards), 3)

    def test_grouping_can_be_turned_off(self):
        self.assertEqual(len(db.list_library(self.did, sets=False)), 4)

    def test_uuids_for_set_in_release_order(self):
        names = [os.path.basename(db.get_media(u)["file_path"]) for u in db.uuids_for("set:726871")]
        self.assertEqual(names, ["Dune.mkv", "Dune Part Two.mkv"])

    def test_set_match_rewrites_details_and_genres_only(self):
        uid = db.file_id(os.path.join(self.root, "Heat.mkv"))
        db.add_tag(uid, "favourites")
        db.add_tag(uid, "genre:Comedy")
        db.set_match([uid], "1995-12-15", "A crew of thieves.", 949, 999, "Heat Collection", ["Crime", "Thriller"])
        item = db.get_media(uid)
        self.assertEqual((item["release_date"], item["tmdb_id"], item["collection_id"]), ("1995-12-15", 949, 999))
        tags = db.tags_for(uid)
        self.assertIn("favourites", tags)
        self.assertNotIn("genre:Comedy", tags)
        self.assertIn("genre:Crime", tags)

    def test_collection_art_lives_in_cache(self):
        item = scraper.collection_item(726871, "Dune Collection")
        self.assertEqual(scraper.poster_path(item).name, "set-726871.webp")
        self.assertEqual(scraper.custom_front_path(item).parent, db.data_dir() / "cache")


class FixMatchTests(unittest.TestCase):
    def test_search_shapes_results(self):
        fake = {"results": [{"id": 335984, "title": "Blade Runner 2049", "release_date": "2017-10-04",
                             "overview": "K.", "poster_path": "/x.jpg"}, {"id": 78, "title": "Blade Runner"}]}
        with mock.patch.object(scraper, "_get_json", return_value=fake) as g:
            out = scraper.tmdb_search("movie", "blade runner", "2017", "KEY")
        self.assertIn("year=2017", g.call_args[0][0])
        self.assertEqual(out[0], {"tmdbId": 335984, "title": "Blade Runner 2049", "year": "2017", "overview": "K.",
                                  "thumb": "https://image.tmdb.org/t/p/w185/x.jpg"})
        self.assertEqual(out[1]["thumb"], "")

    def test_search_without_key_explains(self):
        with self.assertRaises(scraper.ScrapeError):
            scraper.tmdb_search("movie", "x", "", "")

    def test_details_reads_collection(self):
        fake = {"id": 438631, "title": "Dune", "release_date": "2021-09-15", "overview": "o", "poster_path": "/d.jpg",
                "genres": [{"name": "Science Fiction"}], "belongs_to_collection": {"id": 726871, "name": "Dune Collection",
                                                                                   "poster_path": "/c.jpg"}}
        with mock.patch.object(scraper, "_get_json", return_value=fake):
            d = scraper.tmdb_details("movie", 438631, "KEY")
        self.assertEqual((d["collection_id"], d["collection_name"]), (726871, "Dune Collection"))
        self.assertTrue(d["collection_poster_url"].endswith("/c.jpg"))
        self.assertEqual(d["genres"], ["Science Fiction"])


class DiscordTests(unittest.TestCase):
    info = {"title": "Blade Runner 2049", "kind": "movie", "year": "2017", "position": 600, "duration": 9800,
            "paused": False, "speed": 1.0}

    def test_levels(self):
        self.assertEqual(dp.activity(self.info, "minimal")["details"], "Watching a movie")
        t = dp.activity(self.info, "title")
        self.assertEqual(t["details"], "Blade Runner 2049 (2017)")
        self.assertNotIn("timestamps", t)
        f = dp.activity(self.info, "full", now=10_000)
        self.assertEqual(f["timestamps"], {"start": 9_400, "end": 9_400 + 9800})
        self.assertEqual(dp.activity({**self.info, "paused": True}, "full")["state"], "Paused")
        self.assertIsNone(dp.activity(None, "full"))

    def test_episode_and_private_clips(self):
        ep = dp.activity({**self.info, "kind": "show", "title": "Severance", "episode": "S01E02"}, "title")
        self.assertEqual((ep["details"], ep["state"]), ("Severance", "S01E02"))
        clip = dp.activity({**self.info, "kind": "clip", "title": "Lake 2019"}, "full")
        self.assertEqual(clip["details"], "Watching a video")
        self.assertNotIn("Lake", str(clip))

    def test_presence_sends_changes_only(self):
        sent = []

        class Fake:
            def __init__(self, app_id):
                self.app_id = app_id

            def send(self, op, payload):
                sent.append(payload["args"]["activity"])

            def recv(self):
                return 1, {}

            def close(self):
                pass

        settings = {"discord": "1", "discord_detail": "title", "discord_app_id": "123"}
        with mock.patch.object(dp, "MIN_GAP", 0.05):
            p = dp.Presence(lambda k, d=None: settings.get(k, d), connect=Fake)
            for _ in range(5):                       # the same state many times: one update
                p.update(self.info)
            time.sleep(0.3)
            p.update({**self.info, "paused": True})
            time.sleep(0.3)
            settings["discord"] = "0"
            p.configure()
            time.sleep(0.3)
        self.assertEqual(p.status, "Off")
        self.assertEqual([a and a.get("state") for a in sent], [None, "Paused", None])
        self.assertEqual(sent[0]["details"], "Blade Runner 2049 (2017)")

    def test_needs_app_id(self):
        p = dp.Presence(lambda k, d=None: {"discord": "1"}.get(k, d), connect=lambda _id: None)
        self.assertTrue(p.status.startswith("Needs"))


class HdrTests(unittest.TestCase):
    def test_hdr_screen_needs_gpu_next(self):
        self.assertEqual(hw_accelerator.mpv_options(1, False)["vo"], "gpu")
        self.assertEqual(hw_accelerator.mpv_options(1, False, hdr_display=True)["vo"], "gpu-next")
        self.assertEqual(hw_accelerator.mpv_options(3, True, hdr_display=True)["vf"], "d3d11vpp=scaling-mode=nvidia")


if __name__ == "__main__":
    unittest.main()
