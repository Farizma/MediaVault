"""1.0.3: age ratings, original / romaji titles, tag rules, the Tag Manager slots."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from utils import anilist, autotag, scraper, tagrules  # noqa: E402


class RatingTests(unittest.TestCase):
    def test_film_prefers_theatrical_us(self):
        r = {"release_dates": {"results": [
            {"iso_3166_1": "GB", "release_dates": [{"type": 3, "certification": "15"}]},
            {"iso_3166_1": "US", "release_dates": [{"type": 4, "certification": "R"}, {"type": 3, "certification": "PG-13"},
                                                   {"type": 1, "certification": ""}]}]}}
        self.assertEqual(scraper.certification(r, "movie"), "PG-13")
        self.assertIsNone(scraper.certification({"release_dates": {"results": []}}, "movie"))

    def test_show(self):
        r = {"content_ratings": {"results": [{"iso_3166_1": "DE", "rating": "16"}, {"iso_3166_1": "US", "rating": " TV-MA "}]}}
        self.assertEqual(scraper.certification(r, "show"), "TV-MA")
        self.assertIsNone(scraper.certification({}, "show"))

    def test_original_only_when_different(self):
        self.assertEqual(scraper._original({"title": "Spirited Away", "original_title": "千と千尋の神隠し"}), "千と千尋の神隠し")
        self.assertIsNone(scraper._original({"title": "Heat", "original_title": "heat"}))

    def test_omdb_rated(self):
        base = {"Response": "True", "Title": "Heat", "Year": "1995"}
        p = types.SimpleNamespace(title="Heat", year="1995")
        for rated, want in (("R", "R"), ("N/A", None), ("Not Rated", None)):
            with unittest.mock.patch.object(scraper, "_get_json", return_value={**base, "Rated": rated}):
                self.assertEqual(scraper._omdb("movie", p, "k")["certification"], want)

    def test_anilist_titles_and_adult(self):
        m = {"id": 1, "format": "MOVIE", "title": {"english": "Spirited Away", "romaji": "Sen to Chihiro no Kamikakushi",
             "native": "千と千尋の神隠し"}, "isAdult": False, "genres": [], "startDate": {}}
        hit = anilist._shape(m)
        self.assertEqual((hit["romaji_title"], hit["original_title"], hit["certification"]),
                         ("Sen to Chihiro no Kamikakushi", "千と千尋の神隠し", None))
        self.assertEqual(anilist._shape({**m, "isAdult": True})["certification"], "18+")


class TitleTests(unittest.TestCase):
    CARD = {"key": "u1", "title": "Spirited Away", "media_type": "movie",
            "original_title": "千と千尋の神隠し", "romaji_title": "Sen to Chihiro no Kamikakushi"}

    def test_each_preference(self):
        from ui.dashboard import display_titles
        self.assertEqual(display_titles(self.CARD, "english"), ("Spirited Away", "千と千尋の神隠し"))
        self.assertEqual(display_titles(self.CARD, "romaji"), ("Sen to Chihiro no Kamikakushi", "千と千尋の神隠し"))
        self.assertEqual(display_titles(self.CARD, "original"), ("千と千尋の神隠し", "Spirited Away"))
        plain = {"key": "u2", "title": "Heat", "media_type": "movie"}
        for pref in ("english", "romaji", "original"):
            self.assertEqual(display_titles(plain, pref), ("Heat", ""))
        self.assertEqual(display_titles({**self.CARD, "key": "set:4"}, "original"), ("Spirited Away", ""))


def _row(root, did, name, sub="", **kw):
    folder = os.path.join(root, sub) if sub else root
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, f"{name}.mkv")
    open(p, "w").close()
    r = {"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did, "title": name, "media_type": "movie",
         "duration": 6000, "resolution": "3840x2160", "codec": "HEVC", "container": ".mkv", "audio_layout": "5.1"}
    r.update(kw)
    return r


class RuleTests(unittest.TestCase):
    ITEM = {"file_path": os.path.join("D:", os.sep, "Kids", "Up (2009).mkv"), "title": "Up", "media_type": "movie",
            "certification": "PG", "release_date": "2009-05-29", "duration": 5760, "score": 7.9, "parent_directory_id": 3,
            "resolution": "1920x1080", "codec": "H.264", "audio_layout": "5.1", "original_title": None, "romaji_title": None}
    INFO = {"genres": ["Animation", "Family"], "tags": ["Pixar", "auto:4K"]}

    def check(self, field, test, value, want):
        rule = tagrules.clean({"field": field, "test": test, "value": value, "tag": "T"})
        self.assertEqual(tagrules.matches(rule, self.ITEM, self.INFO), want, (field, test, value))

    def test_clean(self):
        self.assertIsNone(tagrules.clean({"field": "nope", "test": "is", "tag": "x"}))
        self.assertIsNone(tagrules.clean({"field": "file", "test": "is", "tag": " "}))
        self.assertIsNone(tagrules.clean({"field": "file", "test": "regex", "value": "(", "tag": "x"}))
        self.assertEqual(tagrules.clean({"field": "file", "test": "is", "tag": "auto:Kids", "folders": ["2", "x"]})["tag"], "Kids")

    def test_each_test(self):
        self.check("folder", "contains", "kids", True)
        self.check("file", "not_contains", "Cars", True)
        self.check("rating", "is", "pg", True)
        self.check("rating", "is_not", "PG", False)
        self.check("title", "starts", "U", True)
        self.check("file", "ends", ".mkv", True)
        self.check("file", "regex", r"\(\d{4}\)", True)
        self.check("year", "gt", "2005", True)
        self.check("minutes", "lt", "90", False)
        self.check("score", "is", "7.9", True)
        self.check("genre", "is", "family", True)
        self.check("tag", "contains", "4K", False)                   # computed tags are not "your tags"
        self.check("tag", "is", "pixar", True)

    def test_off_and_folder_scope(self):
        r = tagrules.clean({"field": "type", "test": "is", "value": "movie", "tag": "T", "on": False})
        self.assertFalse(tagrules.matches(r, self.ITEM, self.INFO))
        r = tagrules.clean({"field": "type", "test": "is", "value": "movie", "tag": "T", "folders": [9]})
        self.assertFalse(tagrules.matches(r, self.ITEM, self.INFO))

    def test_computed_tags(self):
        rules = [tagrules.clean({"field": "folder", "test": "contains", "value": "Kids", "tag": "Family night"}),
                 tagrules.clean({"field": "rating", "test": "is", "value": "PG", "tag": "rated pg"})]
        tags = tagrules.computed_tags(self.ITEM, self.INFO, os.path.join("D:", os.sep), rules, names=False)
        self.assertEqual(tags, ["Rated PG", "Family night"])        # duplicates by case dropped


class LibraryTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        cls.qapp = QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        db.init_db()
        cls.root = tempfile.mkdtemp()
        cls.did = db.add_directory(cls.root, "T", True)
        cls.rows = [_row(cls.root, cls.did, "Spirited Away", certification="PG", original_title="千と千尋の神隠し"),
                    _row(cls.root, cls.did, "Heat", certification="R"),
                    _row(cls.root, cls.did, "Up", "Kids", certification="PG")]
        db.add_items(cls.rows)
        app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None)
        cls.d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())

    def uid(self, i):
        return self.rows[i]["uuid"]

    def test_retag_keeps_your_tags(self):
        db.add_tag(self.uid(0), "Favourite")
        db.add_tag(self.uid(0), "auto:Stale")
        tagrules.save([{"field": "folder", "test": "contains", "value": "Kids", "tag": "Kids"}])
        tagrules.retag_all()
        self.assertIn("Favourite", db.tags_for(self.uid(0)))
        self.assertNotIn("auto:Stale", db.tags_for(self.uid(0)))
        self.assertIn("auto:Rated PG", db.tags_for(self.uid(0)))
        self.assertIn("auto:Kids", db.tags_for(self.uid(2)))
        self.assertNotIn("auto:Kids", db.tags_for(self.uid(1)))
        self.assertEqual(tagrules.preview({"field": "rating", "test": "is", "value": "PG", "tag": "x"}), 2)
        tagrules.save([])

    def test_rename_merges_and_delete(self):
        db.add_tag(self.uid(1), "Crime")
        db.add_tag(self.uid(1), "crime drama")
        db.add_tag(self.uid(2), "crime drama")
        db.rename_tag("crime drama", "Crime")
        self.assertEqual(db.tags_for(self.uid(1)).count("Crime"), 1)
        self.assertIn("Crime", db.tags_for(self.uid(2)))
        counts = {t["name"]: t["n"] for t in db.tag_counts()}
        self.assertEqual(counts["Crime"], 2)
        self.assertNotIn("crime drama", counts)
        db.delete_tag("Crime")
        self.assertNotIn("Crime", db.tags_for(self.uid(1)))

    def test_search_finds_the_original_title(self):
        keys = [t["key"] for t in self.d.taggingTitles("千と千尋", "")]
        self.assertEqual(keys, [self.uid(0)])

    def test_bulk_tag_and_summary(self):
        keys = [self.uid(0), self.uid(1)]
        self.d.bulkTag(keys, "Rewatch", True)
        self.assertEqual({t["key"] for t in self.d.taggingTitles("", "Rewatch")}, set(keys))
        row = next(t for t in self.d.tagSummary() if t["name"] == "Rewatch")
        self.assertEqual((row["kind"], row["count"]), ("user", 2))
        self.d.bulkTag(keys, "Rewatch", False)
        self.assertEqual(self.d.taggingTitles("", "Rewatch"), [])
        self.d.bulkTag(keys, "auto:Nope", True)                       # computed tags cannot be added by hand
        self.assertNotIn("auto:Nope", db.tags_for(self.uid(0)))

    def test_rules_slots(self):
        info = self.d.tagRules()
        self.assertTrue({"rules", "fields", "tests", "folders"} <= set(info))
        kept = self.d.saveTagRules([{"field": "rating", "test": "is", "value": "R", "tag": "Grown-ups"}, {"field": "bad"}])
        self.assertEqual(len(kept), 1)
        self.assertEqual(self.d.previewTagRule(kept[0]), 1)
        self.d.saveTagRules([])

    def test_set_scraped_fills_only_empty(self):
        db.set_scraped([self.uid(1)], certification="PG-13", original_title="Heat!")
        it = db.get_media(self.uid(1))
        self.assertEqual(it["certification"], "R")
        self.assertEqual(it["original_title"], "Heat!")


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()


class V104Tests(unittest.TestCase):
    """1.0.4: adult / OVA file names, AniList retry, Fix Scraped Data across every source, AniList scores."""

    def test_more_episode_names(self):
        for f, want in [("Ane wa Yanmama Junyuu-chuu Episode 1.mp4", 1), ("Ane wa Yanmama Junyuu-chuu - Episode 02 (Uncensored).mp4", 2),
                        ("Ane wa Yanmama Junyuu-chuu OVA 3.mkv", 3), ("Ane wa Yanmama Junyuu-chuu 04.mkv", 4)]:
            p = scraper.clean_name(f)
            self.assertEqual((p.title, p.episode), ("Ane wa Yanmama Junyuu-chuu", want), f)
        for f, title in [("Apollo 13 (1995).mkv", "Apollo 13"), ("Ocean's 11.mkv", "Ocean's 11")]:
            self.assertEqual((scraper.clean_name(f).title, scraper.clean_name(f).episode), (title, None), f)

    def test_anilist_retries_without_a_trailing_number(self):
        asked = []
        media = {"id": 115138, "isAdult": True, "format": "OVA", "title": {"romaji": "Ane wa Yanmama Junyuu-chuu"}, "startDate": {}}

        def fake(q, v, retries=2):
            asked.append(v["q"])
            return {"Media": media} if v["q"] == "Ane wa Yanmama Junyuu-chuu" else {}
        with unittest.mock.patch.object(anilist, "_post", side_effect=fake):
            hit = anilist.lookup("Ane wa Yanmama Junyuu-chuu 1")
        self.assertEqual((hit["title"], hit["certification"]), ("Ane wa Yanmama Junyuu-chuu", "18+"))
        self.assertEqual(asked, ["Ane wa Yanmama Junyuu-chuu 1", "Ane wa Yanmama Junyuu-chuu"])

    def test_omdb_search_and_details(self):
        found = {"Response": "True", "Search": [{"Title": "Heat", "Year": "1995", "imdbID": "tt0113277", "Poster": "N/A"}]}
        with unittest.mock.patch.object(scraper, "_get_json", return_value=found):
            self.assertEqual(scraper.omdb_search("movie", "heat", "", "k"),
                             [{"id": "tt0113277", "source": "omdb", "title": "Heat", "year": "1995", "overview": "", "thumb": ""}])
        one = {"Response": "True", "Title": "Heat", "Released": "15 Dec 1995", "imdbRating": "8.3", "Rated": "R", "Genre": "Crime, Drama",
               "imdbID": "tt0113277", "Plot": "A heist."}
        with unittest.mock.patch.object(scraper, "_get_json", return_value=one):
            d = scraper.omdb_details("tt0113277", "k")
        self.assertEqual((d["score"], d["certification"], d["genres"], d["tmdb_id"]), (8.3, "R", ["Crime", "Drama"], None))

    def test_search_every_source(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        db.init_db()
        app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None)
        d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())
        got, done = [], __import__("threading").Event()
        d.matchResults.connect(lambda k, r: (got.append(r), done.set()))
        d.matchFailed.connect(lambda k, e: (got.append(e), done.set()))
        with unittest.mock.patch.object(d, "_is_anime", return_value=True), \
                unittest.mock.patch.object(scraper, "api_keys", return_value={"tmdb": "k", "omdb": "", "fanart": ""}), \
                unittest.mock.patch.object(anilist, "search", return_value=[{"id": "1", "source": "anilist", "title": "A"}]), \
                unittest.mock.patch.object(scraper, "tmdb_search", side_effect=scraper.ScrapeError("TMDB down")):
            d.searchMatch("x", "a", "")
            import time
            end = time.time() + 10
            while not done.is_set() and time.time() < end:    # results arrive queued, on this thread
                QGuiApplication.processEvents()
                time.sleep(0.02)
        self.assertEqual(got, [[{"id": "1", "source": "anilist", "title": "A"}]])   # TMDB failing does not hide AniList
