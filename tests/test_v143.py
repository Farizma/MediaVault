"""1.3.8: Fix Scraped Data asks every database whatever the folder's source (ThePornDB too), and takes a pasted
link to any of them."""
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

from PySide6.QtGui import QGuiApplication  # noqa: E402

import database as db  # noqa: E402
from tests.test_v133 import make_dashboard  # noqa: E402
from utils import anilist, scraper, sources, tpdb  # noqa: E402

KEYS = {"tmdb": "k", "omdb": "", "fanart": "", "tpdb": "t"}


def run(d, query):
    got = []
    d.matchResults.connect(lambda k, r: got.append(r))
    d.matchFailed.connect(lambda k, e: got.append(e))
    waiting = []
    d.matchWaiting.connect(lambda k, w: waiting.append(w))
    d.searchMatch("x", query, "")
    end = time.time() + 10
    while not (waiting and waiting[-1] == [] and len(waiting) > 1 or got and waiting and waiting[-1] == []) \
            and time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.02)
    for _ in range(10):
        QGuiApplication.processEvents()
    return got


class LinkTests(unittest.TestCase):
    def test_theporndb_links(self):
        self.assertEqual(scraper.parse_link("https://theporndb.net/scenes/studio-sunset-swim"),
                         {"source": "tpdb", "id": "scenes:studio-sunset-swim", "kind": "movie"})
        self.assertEqual(scraper.parse_link("https://theporndb.net/movies/a-film-2024?x=1")["id"], "movies:a-film-2024")
        self.assertIsNone(scraper.parse_link("https://theporndb.net/performers/jo"))
        self.assertEqual(scraper.parse_link("https://www.tvmaze.com/shows/82/x")["source"], "tvmaze")


class SearchAllTests(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def test_a_tmdb_folder_also_asks_theporndb(self):
        d = make_dashboard()
        tp = [{"id": "scenes:1", "source": "tpdb", "title": "Studio · Swim"}]
        tm = [{"id": "movie:2", "source": "tmdb", "title": "Swim"}]
        with mock.patch.object(scraper, "api_keys", return_value=KEYS), \
                mock.patch.object(tpdb, "search", return_value=tp) as ts, \
                mock.patch.object(scraper, "tmdb_search", return_value=tm), \
                mock.patch.object(anilist, "search", return_value=[]), \
                mock.patch.object(sources, "mal_search", return_value=[]), \
                mock.patch.object(sources, "kitsu_search", return_value=[]):
            got = run(d, "Swim")
        ts.assert_called_once_with("Swim", "t")
        self.assertEqual([r["source"] for r in got[-1]], ["tmdb", "tpdb"])      # the folder's own source first

    def test_without_a_token_theporndb_is_not_asked(self):
        d = make_dashboard()
        with mock.patch.object(scraper, "api_keys", return_value={**KEYS, "tpdb": ""}), \
                mock.patch.object(tpdb, "search") as ts, \
                mock.patch.object(scraper, "tmdb_search", return_value=[]), \
                mock.patch.object(anilist, "search", return_value=[{"id": "1", "source": "anilist", "title": "A"}]), \
                mock.patch.object(sources, "mal_search", return_value=[]), \
                mock.patch.object(sources, "kitsu_search", return_value=[]):
            run(d, "A")
        ts.assert_not_called()

    def test_a_pasted_theporndb_link(self):
        d = make_dashboard()
        hit = {"title": "Swim", "release_date": "2024-03-15", "synopsis": "s", "poster_url": "https://img/p.jpg"}
        with mock.patch.object(scraper, "api_keys", return_value=KEYS), \
                mock.patch.object(tpdb, "details", return_value=hit) as det:
            got = run(d, "https://theporndb.net/scenes/studio-sunset-swim")
        det.assert_called_once_with("scenes:studio-sunset-swim", "t")
        self.assertEqual(got[0], [{"id": "scenes:studio-sunset-swim", "source": "tpdb", "title": "Swim", "year": "2024",
                                   "overview": "s", "thumb": "https://img/p.jpg"}])

    def test_a_link_without_a_token(self):
        d = make_dashboard()
        with mock.patch.object(scraper, "api_keys", return_value={**KEYS, "tpdb": ""}):
            got = run(d, "https://theporndb.net/scenes/x")
        self.assertIn("ThePornDB token", got[0])


if __name__ == "__main__":
    unittest.main()
