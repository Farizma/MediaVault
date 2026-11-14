"""1.3.0: Continue Watching, right-click menu and selection actions, episode guide, private tabs, favourites and
watchlist, undo, Fix Scraped Data for box sets, subtitle download."""
import json
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
from utils import applock, scraper  # noqa: E402


def make_dashboard():
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])
    from ui.dashboard import Dashboard, LibraryModel, TabsModel
    from ui.dvd_box import FrameProvider
    app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None, stop=lambda: None), presence=None, play=lambda *a: None)
    d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())
    d._needs_setup = False
    return d


class FeatureTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db._tx() as c:
            for t in ("media_items", "scanned_directories", "watch_history", "marks", "tags"):
                c.execute(f"DELETE FROM {t}")
        for k in ("hidden_private_dirs", "hidden_continue_dirs", "continue_watching", "lock_scope"):
            db.set_setting(k, "")
        applock.reset()
        self.root = tempfile.mkdtemp()
        self.pub = db.add_directory(os.path.join(self.root, "pub"), "Films", True)
        self.priv = db.add_directory(os.path.join(self.root, "priv"), "Private", True)
        for d in ("pub", "priv", os.path.join("pub", "Show")):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        rows = []
        for name, folder, did, kind in (("Alpha", "pub", self.pub, "movie"), ("Beta", "pub", self.pub, "movie"),
                                        ("Secret", "priv", self.priv, "movie"),
                                        ("Show S01E01", os.path.join("pub", "Show"), self.pub, "show"),
                                        ("Show S01E02", os.path.join("pub", "Show"), self.pub, "show")):
            p = os.path.join(self.root, folder, name + ".mkv")
            open(p, "w").close()
            rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did, "title": name,
                         "media_type": kind, "duration": 1000})
        db.add_items(rows)
        self.alpha, self.beta, self.secret, self.e1, self.e2 = (r["uuid"] for r in rows)
        self.show = "show:" + os.path.dirname(rows[3]["file_path"])
        self.d = make_dashboard()

    def keys(self):
        return [r["key"] for r in self.d.library._rows]

    def test_continue_watching_row_and_its_switches(self):
        db.save_progress(self.alpha, 400, False)
        db.save_progress(self.e1, 1000, True)                    # an episode finished: the series is "next up"
        self.d.reload()
        got = {r["key"]: r for r in self.d.continueWatching}
        self.assertEqual(set(got), {self.alpha, self.show})
        self.assertAlmostEqual(got[self.alpha]["progress"], 0.4)
        self.assertIn("left", got[self.alpha]["note"])
        db.set_hidden("continue_dirs", [-1])                     # off for the All tab only
        self.d.reload()
        self.assertEqual(self.d.continueWatching, [])
        self.d.selectTab(self.pub)
        self.assertEqual(len(self.d.continueWatching), 2)
        db.set_setting("continue_watching", "0")                 # off everywhere
        self.d.reload()
        self.assertEqual(self.d.continueWatching, [])

    def test_watched_marks_and_filters(self):
        self.d.reload()
        self.d.setWatched([self.show, self.alpha], True)
        self.assertTrue(db.get_media(self.e2)["is_completed"] and db.get_media(self.alpha)["is_completed"])
        self.d.setWatched([self.alpha], False)
        self.assertFalse(db.get_media(self.alpha)["is_completed"])
        self.d.setMark([self.beta, self.show], "favourite", True)
        row = next(r for r in self.d.library._rows if r["key"] == self.beta)
        self.assertTrue(row["fav"] and not row["watch"])
        self.d.setMarkFilter("favourite", "")
        self.assertEqual(sorted(self.keys()), sorted([self.beta, self.show]))
        self.d.setMarkFilter("", "")
        self.assertEqual(self.d.library.keysBetween(2, 0), self.keys()[:3])       # Shift-click, either direction

    def test_group_selection_into_a_box_set(self):
        self.d.reload()
        self.assertEqual(self.d.groupIntoSet([self.alpha], "Solo"), "")           # one film is not a set
        key = self.d.groupIntoSet([self.alpha, self.beta, self.show], "Greek")
        self.assertTrue(key.startswith("set:"))
        self.assertEqual(len(db.films_in_set(key[4:])), 2)                         # the series is left out

    def test_undo(self):
        offered = []
        self.d.undoOffered.connect(offered.append)
        db.add_tag(self.alpha, "keeper")
        self.d.removeTag(self.alpha, "keeper")
        self.assertNotIn("keeper", db.tags_for(self.alpha))
        self.d.undoLast()
        self.assertIn("keeper", db.tags_for(self.alpha))
        key = self.d.groupIntoSet([self.alpha, self.beta], "Pair")
        self.d.ungroupSet(key)
        self.assertEqual(db.films_in_set(key[4:]), [])
        self.d.undoLast()
        self.assertEqual(len(db.films_in_set(key[4:])), 2)
        from PIL import Image
        g = scraper.gallery_dir(db.get_media(self.alpha))
        g.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 9)).save(g / "c-1-00.webp")
        self.d.removeGalleryImage(self.alpha, "c-1-00.webp")
        self.assertFalse((g / "c-1-00.webp").exists())
        self.d.undoLast()
        self.assertTrue((g / "c-1-00.webp").exists())
        self.assertEqual(len(offered), 3)
        self.d.undoLast()                                                          # nothing left: harmless

    def test_private_tab_is_hidden_until_you_sign_in(self):
        self.d.toggleHidden("private_dirs", str(self.priv))                        # no sign-in yet: refused
        self.assertEqual(db.private_dirs(), set())
        applock.set_password("letmein")
        db.set_setting("lock_scope", "private")
        self.d.toggleHidden("private_dirs", str(self.priv))
        d = make_dashboard()
        self.assertFalse(d.locked)                                                 # the app itself opens
        d.reload()
        self.assertNotIn(self.secret, [r["key"] for r in d.library._rows])
        self.assertTrue(next(r for r in d.tabs._rows if r[0] == self.priv)[2])     # its tab carries the lock
        d.selectTab(self.priv)
        self.assertNotEqual(d._tab, self.priv)
        d.requestPrivate(self.priv)
        self.assertTrue(d.locked and d.lockReason == "private")
        d.cancelLock()
        self.assertFalse(d.locked)
        opened = []
        d.privateOpened.connect(opened.append)
        d.requestPrivate(self.priv)
        d._set_unlocked()
        self.assertEqual(opened, [self.priv])
        self.assertIn(self.secret, [r["key"] for r in d.library._rows])
        d.lockNow()                                                                # locks the private tabs again, not the app
        self.assertFalse(d.locked)
        self.assertNotIn(self.secret, [r["key"] for r in d.library._rows])
        applock.reset()

    def test_episode_guide_fills_names_and_keeps_yours(self):
        season = {"episodes": [{"episode_number": 1, "name": "Pilot", "overview": "It begins.", "still_path": "/a.jpg"},
                               {"episode_number": 2, "name": "<b>Two</b>", "overview": "", "still_path": None}]}
        with mock.patch.object(scraper, "_tmdb_json", return_value=season):
            guide = scraper.episode_guide("Show", 5, {1}, {"tmdb": "k"})
        self.assertEqual(guide[(1, 2)]["name"], "Two")
        db.set_episode(self.e2, title="Mine")
        from PIL import Image
        eps = db.episodes_in(self.show[5:])
        with mock.patch.object(scraper, "fetch_image", return_value=Image.new("RGB", (32, 18))):
            self.assertEqual(scraper.save_episode_guide(eps, guide), 2)
        r = self.d.detail(self.show)["episodes"]
        self.assertEqual([(e["season"], e["number"], e["name"]) for e in r], [(1, 1, "Pilot"), (1, 2, "Mine")])
        self.assertTrue(r[0]["still"] and not r[1]["still"])
        tvmaze = {"_embedded": {"episodes": [{"season": 1, "number": 1, "name": "From TVmaze", "summary": "<p>x</p>", "image": None}]}}
        with mock.patch.object(scraper, "_get_json", return_value=tvmaze):
            self.assertEqual(scraper.episode_guide("Show", None, {1}, {})[(1, 1)]["name"], "From TVmaze")   # no TMDB: TVmaze

    def test_fix_scraped_data_on_a_box_set(self):
        key = self.d.groupIntoSet([self.alpha, self.beta], "Pair")
        self.assertTrue(self.d.detail(key)["canMatch"])
        self.d._match_hits[key] = {"tmdb|collection:9": {"title": "The Pair Collection", "synopsis": "Two films.", "poster_url": None}}
        self.d._apply_parts(key, {"title": "tmdb|collection:9", "synopsis": "tmdb|collection:9", "genres": "tmdb|collection:9"}, "")
        r = self.d.detail(key)
        self.assertEqual((r["title"], r["synopsis"]), ("The Pair Collection", "Two films."))
        self.assertEqual(db.get_media(self.alpha)["title"], "Alpha")              # its films are untouched

    def test_fetch_missing_for_a_selection_only(self):
        import watcher
        seen = []
        with mock.patch.object(watcher, "_fetch_groups", side_effect=lambda d, groups, *a: seen.append(sorted(groups)) or 0), \
                mock.patch.object(scraper, "api_keys", return_value={"tmdb": "k", "omdb": "", "fanart": ""}):
            watcher.fetch_missing(db.get_directory(self.pub), only={self.beta})
        self.assertEqual(seen, [[self.beta]])


class SubtitleTests(unittest.TestCase):
    def test_search_and_download(self):
        from utils import subtitles
        calls = []

        def fake_call(path, key, body=None):
            calls.append((path, body))
            if path.startswith("subtitles?"):
                return {"data": [{"attributes": {"release": "Heat.1995.1080p", "download_count": 9, "files": [{"file_id": 77}]}},
                                 {"attributes": {"files": []}}]}
            return {"link": "https://dl.opensubtitles.org/x.srt"}
        with mock.patch.object(subtitles, "_call", side_effect=fake_call):
            found = subtitles.search("k", "Show", "en", 5, 1, 2, show=True)
            self.assertEqual(found, [{"file_id": 77, "release": "Heat.1995.1080p", "downloads": 9}])
            self.assertIn("parent_tmdb_id=5", calls[0][0])
            self.assertIn("episode_number=2", calls[0][0])
            dest = Path(tempfile.mkdtemp()) / "a" / "x.en.srt"
            resp = mock.MagicMock()
            resp.__enter__.return_value.read.return_value = b"1\n00:00:01,000 --> 00:00:02,000\nHi\n"
            with mock.patch("urllib.request.urlopen", return_value=resp):
                subtitles.download("k", 77, dest)
            self.assertTrue(dest.read_bytes().startswith(b"1\n"))
            self.assertEqual(calls[-1], ("download", {"file_id": 77}))
        with mock.patch.object(subtitles, "_call", return_value={"link": "http://plain/x.srt"}):
            with self.assertRaises(subtitles.SubtitleError):
                subtitles.download("k", 1, Path(tempfile.mkdtemp()) / "x.srt")

    def test_wired(self):
        self.assertIn("Player.findSubtitles()", (ROOT / "player" / "Hud.qml").read_text(encoding="utf-8"))
        self.assertIn('"opensubtitles_key"', (ROOT / "database.py").read_text(encoding="utf-8"))      # encrypted like the other keys
        dash = (ROOT / "ui" / "Dashboard.qml").read_text(encoding="utf-8")
        for needle in ("id: cardMenu", "id: selBar", "Backend.continueWatching", "keyNavigationEnabled: true", "Backend.undoLast()"):
            self.assertIn(needle, dash)
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_v133", wf)
        json.dumps({})


if __name__ == "__main__":
    unittest.main()
