"""Run: python -m unittest discover -s tests -v   (from the project root; no Windows needed)."""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_TMP = tempfile.mkdtemp()
os.environ["LOCALAPPDATA"] = _TMP  # keep the test database away from the real one

import database as db  # noqa: E402
from player import vr_detector  # noqa: E402
from utils import hw_accelerator, scraper  # noqa: E402


def _row(path, did, kind="movie", title="T"):
    return {"uuid": db.file_id(path), "file_path": db.norm(path), "parent_directory_id": did,
            "title": title, "media_type": kind, "duration": 100, "resolution": "1080p",
            "codec": "H.264", "container": ".mkv", "audio_layout": "Stereo"}


class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.did = db.add_directory(os.path.join(_TMP, "movies"), "Movies", True)

    def test_wal_and_foreign_keys(self):
        self.assertEqual(db.conn().execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(db.conn().execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_rescan_keeps_user_edits_but_refreshes_read_only_fields(self):
        p = os.path.join(_TMP, "movies", "a.mkv")
        db.add_items([_row(p, self.did, title="Original")])
        uid = db.file_id(p)
        db.update_media(uid, title="My Title")
        again = _row(p, self.did, title="Scraped")
        again["resolution"] = "4K"
        db.add_items([again])
        item = db.get_media(uid)
        self.assertEqual(item["title"], "My Title")
        self.assertEqual(item["resolution"], "4K")

    def test_read_only_fields_cannot_be_edited(self):
        with self.assertRaises(ValueError):
            db.update_media("x", resolution="8K")

    def test_id_is_stable_between_scans(self):
        self.assertEqual(db.file_id("/a/b.mkv"), db.file_id("/a/../a/b.mkv"))

    def test_next_episode_uses_natural_order(self):
        folder = os.path.join(_TMP, "shows", "S")
        names = ["S01E02.mkv", "S01E10.mkv", "S01E01.mkv"]
        db.add_items([_row(os.path.join(folder, n), self.did, "show", n) for n in names])
        first = db.file_id(os.path.join(folder, "S01E01.mkv"))
        second = db.next_episode(first)
        self.assertTrue(second["file_path"].endswith("S01E02.mkv"))
        third = db.next_episode(second["uuid"])
        self.assertTrue(third["file_path"].endswith("S01E10.mkv"))
        self.assertIsNone(db.next_episode(third["uuid"]))

    def test_remove_under_deletes_folder_and_cascades(self):
        folder = os.path.join(_TMP, "gone")
        p = os.path.join(folder, "x.mkv")
        db.add_items([_row(p, self.did)], [(db.file_id(p), "keep")])
        db.save_progress(db.file_id(p), 30, False)
        db.remove_under([folder])
        self.assertIsNone(db.get_media(db.file_id(p)))
        self.assertEqual(db.tags_for(db.file_id(p)), [])

    def test_analytics_excludes_tagged_items(self):
        p = os.path.join(_TMP, "movies", "home.mp4")
        db.add_items([_row(p, self.did, "clip")], [(db.file_id(p), "Personal")])
        db.log_watch(db.file_id(p), 600)
        with_all = db.analytics([])["total_minutes"]
        without = db.analytics(["Personal"])["total_minutes"]
        self.assertEqual(with_all - without, 10)

    def test_watch_time_is_time_played_not_furthest_point(self):
        p = os.path.join(_TMP, "movies", "seeker.mkv")
        db.add_items([_row(p, self.did)])
        uid = db.file_id(p)
        db.save_progress(uid, 5000, False)  # jumped to the end...
        before = db.analytics([])["total_minutes"]
        db.log_watch(uid, 120)              # ...but only watched 2 minutes
        self.assertEqual(db.analytics([])["total_minutes"] - before, 2)

    def test_top_genres_rated_first_then_by_watch_time(self):
        movies = []
        for name, genre, stars, secs in (("g1", "Drama", 5, 60), ("g2", "Comedy", 0, 6000), ("g3", "Horror", 3, 600)):
            p = os.path.join(_TMP, "movies", name + ".mkv")
            db.add_items([_row(p, self.did)], [(db.file_id(p), f"genre:{genre}")])
            if stars:
                db.set_rating(db.file_id(p), stars)
            db.log_watch(db.file_id(p), secs)
        names = [g[0] for g in db.analytics([])["genres"]]
        self.assertLess(names.index("Drama"), names.index("Horror"))   # 5 stars beats 3 stars
        self.assertLess(names.index("Horror"), names.index("Comedy"))  # unrated comes last despite most time

    def test_show_folder_becomes_one_card(self):
        folder = db.norm(os.path.join(_TMP, "shows", "Series A"))
        paths = [os.path.join(folder, f"Series A S01E0{i}.mkv") for i in (1, 2, 3)]
        db.add_items([_row(p, self.did, "show", f"Series A S01E0{i}") for i, p in enumerate(paths, 1)])
        db.save_progress(db.file_id(paths[1]), 40, False)
        cards = [c for c in db.list_library(self.did) if c["key"] == "show:" + folder]
        self.assertEqual(len(cards), 1)
        self.assertEqual((cards[0]["title"], cards[0]["episodes"]), ("Series A", 3))
        self.assertTrue(cards[0]["file_path"].endswith("S01E02.mkv"))   # plays the episode in progress
        self.assertEqual(len(db.uuids_for("show:" + folder)), 3)

    def test_series_rename_keeps_episode_numbers(self):
        folder = db.norm(os.path.join(_TMP, "shows", "Series B"))
        paths = [os.path.join(folder, f"b{i}.mkv") for i in (1, 2)]
        db.add_items([_row(p, self.did, "show", f"Old Name S01E0{i}") for i, p in enumerate(paths, 1)])
        db.rename_series(folder, "New Name")
        titles = sorted(e["title"] for e in db.episodes_in(folder))
        self.assertEqual(titles, ["New Name S01E01", "New Name S01E02"])

    def test_backup_roundtrip_restores_edits_and_ignores_unknown_files(self):
        p = os.path.join(_TMP, "movies", "restore.mkv")
        db.add_items([_row(p, self.did)])
        uid = db.file_id(p)
        db.update_media(uid, title="Kept Title")
        db.add_tag(uid, "favourite")
        db.set_note(uid, "my note")
        backup = db.export_user_data()
        backup["items"].append({"uuid": "not-in-library", "title": "ghost", "synopsis": None, "release_date": None})
        db.update_media(uid, title="Changed")
        db.remove_tag(uid, "favourite")
        db.set_note(uid, "")
        result = db.import_user_data(backup)
        self.assertEqual(db.get_media(uid)["title"], "Kept Title")
        self.assertIn("favourite", db.tags_for(uid))
        self.assertEqual(db.get_note(uid), "my note")
        self.assertIsNone(db.get_media("not-in-library"))
        self.assertGreater(result["items"], 0)

    def test_old_database_gets_frame_rate_column(self):
        import sqlite3
        old = sqlite3.connect(":memory:")
        old.row_factory = sqlite3.Row
        old.execute("CREATE TABLE media_items (uuid TEXT PRIMARY KEY, file_path TEXT UNIQUE NOT NULL, "
                    "parent_directory_id INTEGER, title TEXT NOT NULL, media_type TEXT, release_date TEXT, "
                    "synopsis TEXT, duration INTEGER, resolution TEXT, codec TEXT, container TEXT, audio_layout TEXT)")
        real, db._local.conn = db._local.conn, old
        try:
            db.init_db()
            cols = {r["name"] for r in old.execute("PRAGMA table_info(media_items)")}
        finally:
            db._local.conn = real
        self.assertIn("frame_rate", cols)

    def test_failed_scrape_registry(self):
        h = db.file_hash("/nope/file.mkv")
        self.assertFalse(db.is_failed(h))
        db.mark_failed([h])
        self.assertTrue(db.is_failed(h))


class CleanNameTests(unittest.TestCase):
    def test_movie(self):
        p = scraper.clean_name("The.Movie.Name.2019.1080p.BluRay.x264-GRP.mkv")
        self.assertEqual((p.title, p.year, p.episode), ("The Movie Name", "2019", None))

    def test_show(self):
        p = scraper.clean_name("Some Show S02E05 720p WEB-DL.mkv")
        self.assertEqual((p.title, p.season, p.episode), ("Some Show", 2, 5))

    def test_group_tags_and_parentheses(self):
        p = scraper.clean_name("[YTS] Big Film (2011) [1080p].mp4")
        self.assertEqual((p.title, p.year), ("Big Film", "2011"))

    def test_title_that_is_a_year(self):
        self.assertEqual(scraper.clean_name("1917.2019.1080p.mkv").title, "1917")

    def test_bare_episode_file_uses_folder_name(self):
        self.assertEqual(scraper.clean_name("S01E03.mkv", fallback="Show Folder").title, "Show Folder")


class VRTests(unittest.TestCase):
    def test_tags(self):
        self.assertEqual(vr_detector.detect("Film_3D_SBS.mkv"), vr_detector.VRInfo("flat", "sbs", False))
        self.assertEqual(vr_detector.detect("Clip_180_TB.mp4"), vr_detector.VRInfo("180", "tb", False))
        self.assertEqual(vr_detector.detect("Walk_360.mp4").projection, "360")
        self.assertIsNone(vr_detector.detect("Normal Movie 2020.mkv"))

    def test_filter(self):
        f = vr_detector.mpv_filter(vr_detector.detect("a_180_TB.mp4"))
        self.assertIn("stereo3d=in=abl:out=ml", f)
        self.assertIn("v360=input=hequirect", f)


class VRViewTests(unittest.TestCase):
    def test_side_by_side_view_passes_sbs_through_and_converts_top_bottom(self):
        sbs = vr_detector.detect("a_3D_SBS.mkv")
        tb = vr_detector.detect("a_180_TB.mp4")
        self.assertIsNone(vr_detector.mpv_filter(sbs, "sbs"))
        self.assertIn("in=abl:out=sbsl", vr_detector.mpv_filter(tb, "sbs"))
        self.assertIn("out=ml", vr_detector.mpv_filter(sbs, "left"))


class HardwareTests(unittest.TestCase):
    def test_backend_choice(self):
        self.assertEqual(hw_accelerator.detect(["NVIDIA GeForce RTX 4070"]).backend, "mpv")
        self.assertTrue(hw_accelerator.detect(["NVIDIA GeForce RTX 4070"]).rtx)
        self.assertEqual(hw_accelerator.detect(["AMD Radeon RX 6600"]).backend, "mpv")
        self.assertEqual(hw_accelerator.detect(["Intel(R) HD Graphics 620"]).backend, "vlc")
        self.assertEqual(hw_accelerator.detect([]).backend, "vlc")

    def test_level_three_needs_rtx(self):
        self.assertNotIn("vf", hw_accelerator.mpv_options(3, rtx=False))
        self.assertEqual(hw_accelerator.mpv_options(3, rtx=True)["gpu_api"], "d3d11")


class WatcherTests(unittest.TestCase):
    def test_burst_of_events_becomes_one_batch(self):
        from watcher import Watcher
        folder = Path(_TMP) / "burst"
        folder.mkdir()
        did = db.add_directory(str(folder), "Burst", False)
        calls = []
        done = threading.Event()
        w = Watcher(lambda ids: (calls.append(ids), done.set()), quiet=0.3)
        w.start()
        try:
            w.watch(db.get_directory(did))
            for i in range(30):  # 30 files in quick succession
                (folder / f"f{i}.mp4").write_bytes(b"x")
            self.assertTrue(done.wait(5))
            time.sleep(0.6)
            self.assertEqual(len(calls), 1)  # one write and one UI refresh, not thirty
            self.assertEqual(len(db.known_paths(did)), 30)
        finally:
            w.stop()


class NewFeatureTests(unittest.TestCase):
    def test_recommendation_picks_engine_and_level_from_specs(self):
        rec = hw_accelerator.recommend
        self.assertEqual(rec(["NVIDIA GeForce RTX 4070 Laptop GPU"], 32, 16)[:2], ("mpv", 3))
        self.assertEqual(rec(["AMD Radeon RX 6600"], 16, 8)[:2], ("mpv", 2))
        self.assertEqual(rec(["Intel(R) Iris(R) Xe Graphics"], 16, 8)[:2], ("mpv", 2))
        self.assertEqual(rec(["Intel(R) Iris(R) Xe Graphics"], 8, 4)[:2], ("mpv", 1))
        self.assertEqual(rec(["Intel(R) UHD Graphics 620"], 8, 4)[:2], ("vlc", 1))
        self.assertEqual(rec([], 4, 2)[:2], ("vlc", 1))
        self.assertEqual(hw_accelerator.resolve("auto", 3), 3)
        self.assertEqual(hw_accelerator.resolve("", "mpv"), "mpv")
        self.assertEqual(hw_accelerator.resolve("vlc", "mpv"), "vlc")

    def test_tab_rename_and_blank_goes_back_to_folder_name(self):
        db.init_db()
        did = db.add_directory(os.path.join(_TMP, "Anime Collection"), "Anime Collection", True)
        self.assertEqual(db.rename_directory(did, "  My   Anime "), "My Anime")
        self.assertEqual(db.get_directory(did)["tab_name"], "My Anime")
        self.assertEqual(db.rename_directory(did, "   "), "Anime Collection")

    def test_themes_switch_colours_and_pick_readable_text(self):
        import ui
        self.assertEqual(ui.apply_theme("no-such-theme"), "midnight")
        self.assertEqual(ui.THEME["black"], "#000000")
        ui.apply_theme("titanium")
        self.assertEqual(ui.THEME["green"], "#F59E0B")
        self.assertEqual(ui.THEME["onBlue"], "#000000")        # light highlight: dark text
        ui.apply_theme("midnight")
        self.assertEqual(ui.THEME["onBlue"], "#FFFFFF")
        ui.apply_theme("custom", "#ff2d95", "not-a-colour")          # bad value: that colour keeps its default
        self.assertEqual((ui.THEME["green"], ui.THEME["blue"]), ("#FF2D95", "#0A84FF"))
        self.assertEqual(ui.apply_theme("graphite"), "custom")        # old saved name still works
        ui.apply_theme("midnight")


if __name__ == "__main__":
    unittest.main()
