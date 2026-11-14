"""1.3.0: Fix Scraped Data window: search every source, pick several, choose each field from any of them."""
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

TMDB = {"title": "Heat", "release_date": "1995-12-15", "synopsis": "A crew of thieves.", "tmdb_id": 949, "anilist_id": None,
        "poster_url": "https://image.tmdb.org/p.jpg", "banner_url": "https://image.tmdb.org/b.jpg", "genres": ["Crime"],
        "score": 8.3, "certification": "R", "original_title": "Heat", "romaji_title": None, "alt_titles": None,
        "cast": [{"id": 1, "name": "Al Pacino", "role": "Hanna"}], "gallery_urls": ["https://image.tmdb.org/g1.jpg"],
        "collection_id": None, "collection_name": None}
ANI = {"title": "Heat (anime)", "release_date": "2001-01-01", "synopsis": "<i>Other</i> story.", "tmdb_id": None, "anilist_id": 77,
       "poster_url": "https://s4.anilist.co/p.jpg", "banner_url": None, "genres": ["Action"], "studios": ["Madhouse"],
       "score": 7.1, "certification": "", "cast": [], "gallery_urls": ["https://s4.anilist.co/g2.jpg"], "collection_id": None}


class FixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        cls.qapp = QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        db.init_db()
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "Fix", True)
        p = os.path.join(root, "heat.mkv")
        open(p, "w").close()
        cls.uid = db.file_id(p)
        db.add_items([{"uuid": cls.uid, "file_path": db.norm(p), "parent_directory_id": did, "title": "heat",
                       "media_type": "movie", "duration": 60, "synopsis": "mine"}])
        app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None)
        cls.d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())

    def test_preview_is_short_and_safe(self):
        from ui.dashboard import match_preview
        p = match_preview({**ANI, "gallery_urls": ["http://plain/x.jpg", "https://ok/y.jpg"]})
        self.assertEqual(p["synopsis"], "Other story.")                 # markup stripped
        self.assertEqual(p["gallery"], ["https://ok/y.jpg"])            # HTTPS only
        self.assertEqual(p["score"], "71%")                             # AniList as a percentage
        self.assertIn("Madhouse (studio)", p["genres"])
        self.assertEqual(match_preview(TMDB)["score"], "8.3 / 10")

    def test_each_field_from_the_result_you_chose(self):
        from utils import scraper
        self.d._match_hits[self.uid] = {"tmdb|movie:949": TMDB, "anilist|77": ANI}
        choices = {"title": "tmdb|movie:949", "year": "", "synopsis": "anilist|77", "genres": "anilist|77",
                   "score": "tmdb|movie:949", "poster": "", "gallery": ["tmdb|movie:949", "anilist|77"]}
        saved = []
        with mock.patch.object(scraper, "save_gallery", side_effect=lambda item, urls, replace=False: saved.append((urls, replace))), \
                mock.patch.object(scraper, "fetch_image") as fetch, mock.patch.object(scraper, "save_person_photos"):
            self.d._apply_parts(self.uid, choices, "tmdb|movie:949")
            fetch.assert_not_called()                                    # no poster chosen: nothing downloaded
        m = db.get_media(self.uid)
        self.assertEqual(m["title"], "Heat")
        self.assertIsNone(m["release_date"])                             # "keep yours"
        self.assertEqual(m["synopsis"], "<i>Other</i> story.")
        self.assertEqual((m["tmdb_id"], m["anilist_id"]), (949, None))  # linked to the TMDB result
        self.assertEqual(m["score"], 8.3)
        self.assertEqual(self.d.detail(self.uid)["scoreSource"], "")    # stars, not AniList %
        tags = db.tags_for(self.uid)
        self.assertIn("genre:Action", tags)
        self.assertIn("studio:Madhouse", tags)
        self.assertEqual(saved, [(["https://image.tmdb.org/g1.jpg", "https://s4.anilist.co/g2.jpg"], True)])   # both, merged

    def test_expired_results_say_so(self):
        failed = []
        self.d.matchFailed.connect(lambda k, why: failed.append(why))
        self.d._match_hits.pop("nothing", None)
        self.d._apply_parts("nothing", {"title": "x"}, "x")
        self.assertTrue(failed)

    def test_window_wired(self):
        dv = (ROOT / "ui" / "DetailView.qml").read_text(encoding="utf-8")
        self.assertIn("FixMatch { id: fixMatch; anchors.fill: parent }", dv)
        self.assertNotIn("id: matchMenu", dv)
        fm = (ROOT / "ui" / "FixMatch.qml").read_text(encoding="utf-8")
        self.assertIn("Backend.matchDetails(key", fm)
        self.assertIn("Backend.applyMatchParts(key, choices, primary)", fm)
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_v130", wf)


if __name__ == "__main__":
    unittest.main()
