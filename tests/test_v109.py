"""1.0.9: Gallery import from links (TMDB episode images), box set synopsis, episode names, grid that settles."""
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from utils import scraper  # noqa: E402

EP = "https://www.themoviedb.org/tv/104602/season/1/episode/1/images/backdrops"


def fake_tmdb(path, key, **q):
    return {
        "tv/104602/season/1/episode/1": {"name": "<b>Pilot</b>", "overview": "It begins.", "still_path": "/only.jpg"},
        "tv/104602/season/1/episode/1/images": {"stills": [{"file_path": "/low.jpg", "vote_average": 1},
                                                           {"file_path": "/high.jpg", "vote_average": 6}, {"file_path": None}]},
        "tv/104602/season/2": {"episodes": [{"still_path": "/e1.jpg"}, {"still_path": None}, {"still_path": "/e3.jpg"}]},
        "tv/104602/images": {"backdrops": [{"file_path": "/b.jpg", "vote_average": 5}], "posters": [{"file_path": "/p.jpg"}]},
        "movie/5/images": {"backdrops": [{"file_path": "/m.jpg"}]},
    }[path]


class GalleryLinkTests(unittest.TestCase):
    def test_episode_images_and_its_name(self):
        with mock.patch.object(scraper, "_tmdb_json", side_effect=fake_tmdb):
            got = scraper.gallery_link(EP, "k")
        self.assertEqual(got["urls"], [f"{scraper.IMG}original/high.jpg", f"{scraper.IMG}original/low.jpg"])
        self.assertEqual(got["episode"], {"name": "Pilot", "overview": "It begins."})     # markup stripped

    def test_season_series_film_and_posters(self):
        with mock.patch.object(scraper, "_tmdb_json", side_effect=fake_tmdb):
            self.assertEqual(len(scraper.gallery_link("https://www.themoviedb.org/tv/104602-name/season/2", "k")["urls"]), 2)
            self.assertEqual(scraper.gallery_link("https://www.themoviedb.org/tv/104602", "k")["urls"], [f"{scraper.IMG}original/b.jpg"])
            self.assertEqual(scraper.gallery_link("https://www.themoviedb.org/tv/104602/images/posters", "k")["urls"],
                             [f"{scraper.IMG}original/p.jpg"])
            self.assertEqual(scraper.gallery_link("https://www.themoviedb.org/movie/5-x", "k")["urls"], [f"{scraper.IMG}original/m.jpg"])

    def test_direct_image_mal_and_rejects(self):
        self.assertEqual(scraper.gallery_link("https://example.com/a/b.webp?x=1", "")["urls"], ["https://example.com/a/b.webp?x=1"])
        from utils import anilist
        with mock.patch.object(anilist, "mal_pictures", return_value=("https://cdn.myanimelist.net/1.jpg",)) as mp:
            self.assertEqual(scraper.gallery_link("https://myanimelist.net/anime/123/x", "")["urls"], ["https://cdn.myanimelist.net/1.jpg"])
            self.assertEqual(mp.call_args.args[0], 123)
        for bad in ("http://example.com/a.jpg", "hello", "file:///C:/x.png"):
            with self.assertRaises(scraper.ScrapeError):
                scraper.gallery_link(bad, "k")
        with self.assertRaises(scraper.ScrapeError):            # TMDB without a key
            scraper.gallery_link(EP, "")


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        cls.qapp = QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        db.init_db()
        cls.root = tempfile.mkdtemp()
        did = db.add_directory(cls.root, "V109", True)
        rows = []
        for name in ("OVA #1", "OVA #2"):
            p = os.path.join(cls.root, f"{name}.mkv")
            open(p, "w").close()
            rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did, "title": name,
                         "media_type": "movie", "duration": 900, "synopsis": "Series synopsis",
                         "collection_id": 9109, "collection_name": "OVA"})
        db.add_items(rows)
        cls.a, cls.b = rows[0]["uuid"], rows[1]["uuid"]
        app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None)
        cls.d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())

    def test_box_set_synopsis_is_its_own(self):
        self.assertEqual(self.d.detail("set:9109")["synopsis"], "")
        self.d.setSynopsis("set:9109", "Two sisters, two episodes.")
        self.assertEqual(self.d.detail("set:9109")["synopsis"], "Two sisters, two episodes.")
        self.assertEqual(db.get_media(self.a)["synopsis"], "Series synopsis")      # the films keep theirs

    def test_episode_name_and_synopsis(self):
        r = self.d.detail(self.a)
        self.assertTrue(r["inSet"])
        self.d.setEpisodeTitle(self.b, "  The Pool  ")
        self.d.setEpisodeSynopsis(self.b, "At the pool.")
        r = self.d.detail(self.b)
        self.assertEqual((r["episodeTitle"], r["episodeSynopsis"]), ("The Pool", "At the pool."))
        db.set_episode(self.b, title="Scraped", synopsis="Scraped too", only_empty=True)     # yours is kept
        self.assertEqual(self.d.detail(self.b)["episodeTitle"], "The Pool")
        self.assertIn("OVA #2 \u2014 The Pool", [e["title"] for e in self.d.detail("set:9109")["episodes"]])

    def test_import_saves_as_yours_and_fills_the_episode(self):
        from PIL import Image
        img = Image.new("RGB", (64, 36), "red")
        got = {"urls": ["https://x/1.jpg", "https://x/2.jpg"], "episode": {"name": "Ep One", "overview": "Things."}}
        item = db.get_media(self.a)
        gdir = scraper.gallery_dir(item)
        gdir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 36)).save(gdir / "s-01.webp")
        done = []
        with mock.patch.object(scraper, "gallery_link", return_value=got), mock.patch.object(scraper, "fetch_image", return_value=img), \
                mock.patch("threading.Thread", side_effect=lambda target, daemon: types.SimpleNamespace(start=target)):
            self.d.boxArtChanged.connect(done.append)
            self.d.importGalleryImages(self.a, EP, True)
        names = sorted(p.name for p in gdir.iterdir())
        self.assertEqual(len(names), 2)
        self.assertTrue(all(n.startswith("c-") for n in names))       # the scraped one went; these stay through a re-scrape
        self.assertEqual(db.get_media(self.a)["episode_title"], "Ep One")
        self.assertEqual(done, [self.a])


class GridSettleTests(unittest.TestCase):
    def test_second_change_while_animating_rebuilds(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import LibraryModel
        m = LibraryModel()
        m._rows = [{"key": k} for k in "abcd"]
        m.view = {"sort": "title"}
        resets = []
        m.modelReset.connect(lambda: resets.append(1))
        with mock.patch.object(db, "list_library", return_value=[]), mock.patch.object(db, "search_index", return_value={}), \
                mock.patch.object(db, "list_directories", return_value=[]), \
                mock.patch.object(m, "_row", side_effect=lambda c, on: {"key": c["k"]}):
            with mock.patch("ui.dashboard.library_view", return_value=[{"k": "a", "parent_directory_id": 1}, {"k": "c", "parent_directory_id": 1}]):
                m.reload(1)
            self.assertEqual(resets, [])                      # stepped: animated
            with mock.patch("ui.dashboard.library_view", return_value=[{"k": "a", "parent_directory_id": 1}, {"k": "b", "parent_directory_id": 1}, {"k": "c", "parent_directory_id": 1}]):
                m.reload(1)
            self.assertEqual(resets, [1])                     # right after: rebuilt, nothing left half-way
            m._stepped_at = time.monotonic() - 5
            with mock.patch("ui.dashboard.library_view", return_value=[{"k": "a", "parent_directory_id": 1}]):
                m.reload(1)
            self.assertEqual(resets, [1])

    def test_grid_puts_stranded_cards_right(self):
        qml = (ROOT / "ui" / "Dashboard.qml").read_text(encoding="utf-8")
        self.assertIn("function settle()", qml)
        self.assertIn("function onRowsRemoved() { settle.restart() }", qml)
        self.assertIn("function enter() { scale = 1; appear = 1;", qml)


class DetailViewTests(unittest.TestCase):
    def test_box_fits_its_pane(self):
        qml = (ROOT / "ui" / "DetailView.qml").read_text(encoding="utf-8")
        self.assertIn("root.fitFaceW / faceWPerH + 24", qml)
        self.assertIn("stage.width / 2 - 12 - 0.62 * 0.6 * faceW", qml)
        self.assertNotIn("1.35", qml)

    def test_pencil_rename_and_gallery_menu(self):
        qml = (ROOT / "ui" / "DetailView.qml").read_text(encoding="utf-8")
        self.assertIn("onClicked: root.renaming ? root.commitTitle() : root.startRename()", qml)
        self.assertIn('label: "Add or Import images\\u2026"', qml)
        self.assertIn("Backend.importGalleryImages(root.infoKey, link.text.trim(), replaceScraped.checked)", qml)

    def test_in_workflow(self):
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_v109", wf)


class DesktopShortcutTests(unittest.TestCase):
    def test_update_runs_in_the_mode_it_was_installed_in(self):
        from utils import components
        self.assertIn("/CURRENTUSER", components.setup_arguments(Path("C:/MV"), all_users=False))
        self.assertNotIn("/CURRENTUSER", components.setup_arguments(Path("C:/MV"), all_users=True))
        entries = {}

        class Key:
            def __init__(self, loc): self.loc = loc
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def open_key(hive, sub, res, access):
            if (hive, bool(access & 0x0100)) not in entries:
                raise OSError("no key")
            return Key(entries[(hive, bool(access & 0x0100))])
        fake = types.SimpleNamespace(HKEY_LOCAL_MACHINE="HKLM", HKEY_CURRENT_USER="HKCU", KEY_READ=0x20019,
                                     KEY_WOW64_64KEY=0x0100, KEY_WOW64_32KEY=0x0200, OpenKey=open_key,
                                     QueryValueEx=lambda k, name: (k.loc, 1))
        with mock.patch.dict(sys.modules, {"winreg": fake}), mock.patch.object(components.sys, "platform", "win32"):
            folder = Path("D:/Apps/Media Vault")
            self.assertIsNone(components.installed_for_all_users(folder))
            entries[("HKCU", False)] = "D:\\Apps\\Media Vault\\"
            self.assertIs(components.installed_for_all_users(folder), False)
            entries[("HKLM", True)] = "D:\\Apps\\Media Vault\\"
            self.assertTrue(components.installed_for_all_users(folder))      # all users wins: that is the real copy
            entries[("HKLM", True)] = "C:\\Program Files\\Media Vault\\"
            self.assertIs(components.installed_for_all_users(folder), False)     # another folder's entry does not count

    def test_installer_never_makes_a_second_shortcut(self):
        iss = (ROOT / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("Tasks: desktopicon; Check: DesktopIconNeeded", iss)
        self.assertIn("DeleteFile(ExpandConstant('{userdesktop}\\Media Vault.lnk'))", iss)


if __name__ == "__main__":
    unittest.main()
