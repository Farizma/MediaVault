"""View More layout order, scraped score, play from start."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

import database as db  # noqa: E402
from utils import scraper  # noqa: E402


class LayoutOrderTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        db.set_setting("detail_order", "")

    def test_default_and_saved(self):
        ids = [k for k, _ in db.DETAIL_SECTIONS]
        self.assertEqual(db.detail_order(), ids)
        db.set_setting("detail_order", "cast,title,bogus")
        order = db.detail_order()
        self.assertEqual(order[0], "cast")
        self.assertLess(order.index("cast"), order.index("title"))
        self.assertEqual(order[order.index("cast") + 1], "tags")       # a section you never placed follows its default neighbour
        self.assertEqual(sorted(order), sorted(ids))        # nothing lost, nothing unknown


class ScoreTests(unittest.TestCase):
    def test_tmdb_score_needs_votes(self):
        self.assertEqual(scraper._score({"vote_average": 7.86, "vote_count": 1200}), 7.9)
        self.assertIsNone(scraper._score({"vote_average": 10, "vote_count": 1}))
        self.assertIsNone(scraper._score({}))

    def test_omdb_score(self):
        r = {"Response": "True", "Title": "Heat", "imdbRating": "8.3", "Poster": "N/A", "Plot": "N/A"}
        with mock.patch.object(scraper, "_get_json", return_value=r):
            self.assertEqual(scraper._omdb("movie", scraper.Parsed("heat", None, None, None), "K")["score"], 8.3)

    def test_score_column(self):
        db.init_db()
        p = os.path.join(tempfile.mkdtemp(), "x.mkv")
        uid = db.file_id(p)
        db.add_items([{"uuid": uid, "file_path": db.norm(p), "parent_directory_id": None, "title": "X", "media_type": "movie",
                       "score": 6.5}])
        self.assertEqual(db.get_media(uid)["score"], 6.5)
        db.set_score([uid], 7.0)
        self.assertEqual(db.get_media(uid)["score"], 7.0)


class PlayFromStartTests(unittest.TestCase):
    def test_resume_skipped_once(self):
        import main
        db.init_db()
        p = os.path.join(tempfile.mkdtemp(), "film.mkv")
        uid = db.file_id(p)
        db.add_items([{"uuid": uid, "file_path": db.norm(p), "parent_directory_id": None, "title": "Film", "media_type": "movie",
                       "duration": 6000}])
        db.save_progress(uid, 1200, False)
        app = types.SimpleNamespace(db=db, ready=True, main_window=None, engine=types.SimpleNamespace(play=lambda path: None, screen=None))
        app.resolve = types.MethodType(main.App.resolve, app)
        self.assertGreater(app.resolve(db.norm(p)).start, 1000)          # normal play resumes
        main.App.play(app, db.norm(p), True)
        self.assertEqual(app.resolve(db.norm(p)).start, 0)                # from start, once
        self.assertGreater(app.resolve(db.norm(p)).start, 1000)          # and back to resuming


if __name__ == "__main__":
    unittest.main()
