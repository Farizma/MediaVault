"""1.0.7: the dashboard keeps its place when filters or Box sets change; release workflow on Node 24 actions."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ScrollTests(unittest.TestCase):
    def test_grid_keeps_its_place_across_a_rebuild(self):
        qml = (ROOT / "ui" / "Dashboard.qml").read_text(encoding="utf-8")
        self.assertIn("function onModelAboutToBeReset() { grid.keptY = grid.contentY - grid.originY }", qml)
        self.assertIn("contentY = originY + Math.min(keptY, Math.max(0, contentHeight - height))", qml)
        # tabs and Grid / Shelf still go to the top on purpose
        self.assertIn("Backend.selectTab(tabId); grid.keptY = -1;", qml)


class WorkflowTests(unittest.TestCase):
    def test_actions_on_node24(self):
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        for old in ("actions/checkout@v4", "actions/setup-python@v5", "actions/upload-artifact@v4"):
            self.assertNotIn(old, wf)
        for new in ("actions/checkout@v5", "actions/setup-python@v6", "actions/upload-artifact@v6"):
            self.assertIn(new, wf)
        self.assertIn("tests.test_v107", wf)


if __name__ == "__main__":
    unittest.main()


class PreviewTests(unittest.TestCase):
    def test_video_is_not_inside_the_hidden_poster_layer(self):
        qml = (ROOT / "ui" / "Dashboard.qml").read_text(encoding="utf-8")
        art = qml[qml.index("id: art"):qml.index("MultiEffect { source: art")]
        self.assertNotIn("VideoOutput", art)
        self.assertIn("VideoOutput { id: vo; anchors.fill: parent; fillMode: VideoOutput.PreserveAspectCrop }", qml)

    def test_plays_without_waiting_for_the_length_and_logs_failures(self):
        qml = (ROOT / "ui" / "Dashboard.qml").read_text(encoding="utf-8")
        player = qml[qml.index("id: standby"):qml.index("property var previewOwner")]
        self.assertNotIn("duration > 0) {", player)          # the old gate: no play() until a length was known
        self.assertIn("onDurationChanged: jumpIn()", player)
        self.assertIn('console.warn("hover preview: "', player)
        self.assertIn("if (!dash.hoverPreview) return", qml)


class OvaMigrationTests(unittest.TestCase):
    def test_series_become_box_sets_once(self):
        import os
        import sys
        import tempfile
        from unittest import mock
        sys.path.insert(0, str(ROOT))
        os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
        import database as db
        import watcher
        from utils import anilist
        db.init_db()
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "A", True, source="anilist")
        rows = []
        for n in (1, 2):
            p = os.path.join(root, "Show", f"e{n}.mkv")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()
            rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did,
                         "title": f"Show S01E{n:02d}", "media_type": "show", "anilist_id": 5})
        db.add_items(rows)
        hit = {"anilist_id": 5, "format": "OVA", "certification": "18+", "title": "Show", "studios": ["Studio A"],
               "poster_url": None}
        with mock.patch.object(anilist, "details", return_value=hit) as ask:
            self.assertEqual(watcher.convert_ova_series(db.get_directory(did)), 1)
            self.assertEqual(ask.call_count, 1)                                     # one question per series
            self.assertEqual(watcher.convert_ova_series(db.get_directory(did)), 0)  # nothing left to convert
        items = db.list_media(did)
        self.assertEqual({i["media_type"] for i in items}, {"movie"})
        self.assertIn("studio:Studio A", db.tags_for(items[0]["uuid"]))
        tmdb = db.add_directory(tempfile.mkdtemp(), "M", True)
        self.assertEqual(watcher.convert_ova_series(db.get_directory(tmdb)), 0)     # only AniList folders


class CarouselTests(unittest.TestCase):
    def test_turn_moves_boxes_instead_of_swapping_in_place(self):
        qml = (ROOT / "ui" / "DetailView.qml").read_text(encoding="utf-8")
        self.assertNotIn("turnOut", qml)                                   # the old spin-edge-on-and-swap
        self.assertIn("readonly property bool turning: carousel.running", qml)
        # the box in focus slides out to the side and back, the next one comes forward, a new one fades in behind
        self.assertIn("- root.turnDir * root.sideX * root.turnP * root.spread", qml)
        self.assertIn("incoming ? dir * root.sideX * (1 - p) * root.spread", qml)
        self.assertIn("id: newcomer", qml)
        # ends where the resting layout starts: landing yaw of the incoming box = the box's yaw after the swap
        self.assertIn("box.yaw = -20 * turnDir", qml)
        self.assertIn("(dir * 30 - 20 * dir) * p", qml)


class FrontArtTests(unittest.TestCase):
    def test_front_always_opens_the_crop_editor(self):
        import os
        import sys
        import tempfile
        import types
        from unittest import mock
        sys.path.insert(0, str(ROOT))
        os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PIL import Image
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        import ui.dashboard as dash
        from ui.dvd_box import FrameProvider
        wide = os.path.join(tempfile.mkdtemp(), "sleeve.png")
        Image.new("RGB", (800, 540), "red").save(wide)
        d = dash.Dashboard(types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None),
                           dash.LibraryModel(), dash.TabsModel(), FrameProvider())
        picked = []
        d.artPicked.connect(lambda k, face, url, path: picked.append(face))
        with mock.patch.object(dash, "pick_image", return_value=wide), mock.patch.object(dash.QTimer, "singleShot", side_effect=lambda ms, fn: fn()), \
                mock.patch.object(d, "_apply_wrap", wraps=d._apply_wrap) as wrap, mock.patch.object(d, "_art_items", return_value=[]):
            d.pickBoxArt("k", "front")                   # a wide picture picked as the Front: cropped, never split
            self.assertEqual(picked, ["front"])
            wrap.assert_not_called()
            d.pickBoxArt("k", "wrap")                    # the Whole cover button still splits it
            wrap.assert_called_once()
            self.assertEqual(picked, ["front"])          # split, so no crop editor this time


class LinkTests(unittest.TestCase):
    def setUp(self):
        import os
        import sys
        import tempfile
        sys.path.insert(0, str(ROOT))
        os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    def test_parse(self):
        from utils.scraper import parse_link
        self.assertEqual(parse_link("https://www.themoviedb.org/tv/90395-x/season/1/episode/1"), {"source": "tmdb", "id": "90395", "kind": "show"})
        self.assertEqual(parse_link("https://www.themoviedb.org/movie/335984-blade-runner-2049?language=en")["kind"], "movie")
        self.assertEqual(parse_link("https://anilist.co/anime/115138/name/"), {"source": "anilist", "id": "115138", "kind": None})
        self.assertEqual(parse_link("https://myanimelist.net/anime/41261/x")["source"], "mal")
        self.assertEqual(parse_link("https://www.imdb.com/title/tt0113277/")["id"], "tt0113277")
        for text in ("Blade Runner", "", "https://example.com/movie/1", "themoviedb.org/person/123"):
            self.assertIsNone(parse_link(text))

    def _dash(self):
        import types
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        import database as db
        import ui.dashboard as dash
        from ui.dvd_box import FrameProvider
        db.init_db()
        return dash, dash.Dashboard(types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None),
                                    dash.LibraryModel(), dash.TabsModel(), FrameProvider())

    def _wait(self, d):
        import time
        from PySide6.QtGui import QGuiApplication
        got = []
        d.matchResults.connect(lambda k, r: got.append(r))
        d.matchFailed.connect(lambda k, e: got.append(e))
        return got, lambda: [QGuiApplication.processEvents() or time.sleep(0.02) for _ in range(250) if not got]

    def test_a_tmdb_link_is_the_only_result(self):
        from unittest import mock
        dash, d = self._dash()
        got, wait = self._wait(d)
        hit = {"title": "Show", "release_date": "2019-01-01", "synopsis": "s", "poster_url": "https://image.tmdb.org/p.jpg"}
        with mock.patch.object(dash.scraper, "api_keys", return_value={"tmdb": "k", "omdb": "", "fanart": ""}), \
                mock.patch.object(dash.scraper, "tmdb_details", return_value=hit) as det, \
                mock.patch.object(d, "_is_anime", return_value=True):
            d.searchMatch("k", "https://www.themoviedb.org/tv/90395-x/season/1/episode/1", "")
            wait()
        det.assert_called_once_with("show", 90395, "k")
        self.assertEqual(got[0], [{"id": "tv:90395", "source": "tmdb", "title": "Show", "year": "2019", "overview": "s",
                                   "thumb": "https://image.tmdb.org/p.jpg"}])

    def test_a_mal_link_is_myanimelist_itself(self):
        # 1.3.0: MyAnimeList is a source of its own (through Jikan), no longer looked up on AniList
        from unittest import mock
        from utils import sources
        dash, d = self._dash()
        got, wait = self._wait(d)
        with mock.patch.object(sources, "mal_details", return_value={"title": "A", "release_date": None, "synopsis": None,
                                                                      "poster_url": None}) as mal:
            d.searchMatch("k", "https://myanimelist.net/anime/41261/x", "")
            wait()
        mal.assert_called_once_with(41261)
        self.assertEqual((got[0][0]["id"], got[0][0]["source"]), ("41261", "mal"))

    def test_episode_stills_follow_backdrops(self):
        from unittest import mock
        from utils import scraper
        r = {"id": 90395, "seasons": [{"season_number": 0}, {"season_number": 1}, {"season_number": 2}]}
        seasons = {"tv/90395/season/1": {"episodes": [{"still_path": "/a.jpg"}, {"still_path": None}, {"still_path": "/b.jpg"}]},
                   "tv/90395/season/2": {"episodes": [{"still_path": "/c.jpg"}]}}
        with mock.patch.object(scraper, "_tmdb_json", side_effect=lambda path, key, **q: seasons[path]):
            urls = scraper.episode_stills(r, "k")
        self.assertEqual(urls, [scraper.IMG + "original/a.jpg", scraper.IMG + "original/b.jpg", scraper.IMG + "original/c.jpg"])
        self.assertEqual(scraper.GALLERY_MAX_SERIES, 18)


class BannerTests(unittest.TestCase):
    def setUp(self):
        import os
        import sys
        import tempfile
        sys.path.insert(0, str(ROOT))
        os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

    def test_best_backdrop_is_textless_and_highest_rated(self):
        from utils import scraper
        images = {"backdrops": [{"file_path": "/en.jpg", "iso_639_1": "en", "vote_average": 9.9},
                                {"file_path": "/a.jpg", "iso_639_1": None, "vote_average": 5.2, "vote_count": 3},
                                {"file_path": "/b.jpg", "iso_639_1": None, "vote_average": 5.6, "vote_count": 1},
                                {"file_path": "/xx.jpg", "iso_639_1": "xx", "vote_average": 5.4}]}
        self.assertEqual(scraper._best_backdrop(images), scraper.IMG + "original/b.jpg")
        self.assertEqual(scraper._best_backdrop({"backdrops": [{"file_path": "/en.jpg", "iso_639_1": "en"}]}),
                         scraper.IMG + "original/en.jpg")             # only text versions: still better than none
        self.assertIsNone(scraper._best_backdrop({}))

    def test_anilist_set_finds_its_tmdb_backdrop_by_name(self):
        from unittest import mock
        from utils import scraper
        calls = []

        def tmdb(path, key, **q):
            calls.append((path, q.get("query")))
            if path == "search/tv":
                return {"results": [{"id": 90395}]} if q.get("query") == "Master Piece THE ANIMATION" else {"results": []}
            if path == "tv/90395/images":
                return {"backdrops": [{"file_path": "/best.jpg", "iso_639_1": None, "vote_average": 6}]}
            return {"results": []}
        with mock.patch.object(scraper, "_tmdb_json", side_effect=tmdb):
            url = scraper.tmdb_banner_for(["Master Piece", "Master Piece THE ANIMATION"], None, "k")
        self.assertEqual(url, scraper.IMG + "original/best.jpg")

    def test_banner_for_sets_and_series(self):
        import os
        import tempfile
        import database as db
        from utils import scraper
        from ui.dashboard import banner_for
        db.init_db()
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "B", True)
        paths = []
        for n in (1, 2):
            p = os.path.join(root, f"Film {n}.mkv")
            open(p, "w").close()
            paths.append(p)
        db.add_items([{"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did, "title": f"Film {i}",
                       "media_type": "movie", "collection_id": 7, "collection_name": "Set"} for i, p in enumerate(paths)])
        film = db.get_media(db.file_id(paths[0]))
        self.assertIsNone(banner_for({**film, "key": film["uuid"]}))
        g = scraper.gallery_dir(film)
        g.mkdir(parents=True, exist_ok=True)
        (g / "c-1.webp").write_bytes(b"x")
        (g / "s-01.webp").write_bytes(b"x")
        self.assertEqual(banner_for({**film, "key": film["uuid"]}).name, "s-01.webp")    # best scraped still before yours
        self.assertEqual(banner_for({"key": "set:7"}).name, "s-01.webp")                 # a set borrows a film's
        own = scraper.banner_path(scraper.collection_item(7))
        own.parent.mkdir(parents=True, exist_ok=True)
        own.write_bytes(b"x")
        self.assertEqual(banner_for({"key": "set:7"}), own)                              # its own banner wins
        show = {"media_type": "show", "file_path": os.path.join(root, "Show", "e1.mkv"), "uuid": "u"}
        self.assertEqual(scraper.banner_path(show).name, "_series.banner.webp")          # one per series

    def test_view_more_header(self):
        qml = (ROOT / "ui" / "DetailView.qml").read_text(encoding="utf-8")
        self.assertIn("readonly property bool hasBanner: (info.banner || ", qml)
        self.assertIn("Qt.rgba(bannerFade.c.r, bannerFade.c.g, bannerFade.c.b, 1.0)", qml)      # ends opaque: no edge
        self.assertIn("Item { visible: root.hasBanner; Layout.preferredHeight: pane.bannerH * 0.42", qml)


class GridAnimationTests(unittest.TestCase):
    def _model(self, keys):
        import os
        import sys
        import tempfile
        sys.path.insert(0, str(ROOT))
        os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import LibraryModel
        m = LibraryModel()
        m._rows = [{"key": k} for k in keys]
        log = []
        m.rowsRemoved.connect(lambda p, a, b: log.append(("remove", a, b)))
        m.rowsInserted.connect(lambda p, a, b: log.append(("insert", a, b)))
        m.modelReset.connect(lambda: log.append(("reset",)))
        return m, log

    def test_adding_a_filter_removes_cards(self):
        m, log = self._model(list("abcdefg"))
        self.assertTrue(m._step_to([{"key": k} for k in "acfg"]))
        self.assertEqual(log, [("remove", 3, 4), ("remove", 1, 1)])           # from the end, neighbours together
        self.assertEqual([r["key"] for r in m._rows], list("acfg"))

    def test_removing_a_filter_inserts_them_back_in_place(self):
        m, log = self._model(list("acfg"))
        self.assertTrue(m._step_to([{"key": k} for k in "abcdefg"]))
        self.assertEqual(log, [("insert", 1, 1), ("insert", 3, 4)])
        self.assertEqual([r["key"] for r in m._rows], list("abcdefg"))

    def test_a_new_order_or_tab_rebuilds(self):
        m, _ = self._model(list("abc"))
        self.assertFalse(m._step_to([{"key": k} for k in "cba"]))             # a different sort
        self.assertFalse(m._step_to([{"key": k} for k in "xyz"]))             # nothing in common
        qml = (ROOT / "ui" / "Dashboard.qml").read_text(encoding="utf-8")
        for t in ("remove: Transition", "removeDisplaced: Transition", "add: Transition", "addDisplaced: Transition"):
            self.assertIn(t, qml)
        src = (ROOT / "ui" / "dashboard.py").read_text(encoding="utf-8")
        self.assertIn("self.library.reload(None if tab_id < 0 else tab_id, fresh=True)", src)   # tabs always replay


class IntroTests(unittest.TestCase):
    def test_vault_waits_for_the_library(self):
        qml = (ROOT / "ui" / "VaultIntro.qml").read_text(encoding="utf-8")
        self.assertIn("if (!ready || minSpin.running || phase !== ", qml)
        self.assertIn("loops: Animation.Infinite", qml)                       # spins as long as loading takes
        main = (ROOT / "ui" / "Main.qml").read_text(encoding="utf-8")
        self.assertIn("ready: Backend.startupReady && screen.status === Loader.Ready", main)
        self.assertIn("scale: intro.zoom", main)
        self.assertIn("self.mark_ready()", (ROOT / "ui" / "dashboard.py").read_text(encoding="utf-8"))
        self.assertIn("self.dashboard.mark_ready()", (ROOT / "main.py").read_text(encoding="utf-8"))   # first run too
