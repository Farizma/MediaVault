"""1.3.0: Recently Added, resume question, Surprise me, auto-lock, missing episodes, rename files to match,
your own box set order, watch streaks, Next episode button, library kept open during picture in picture."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from tests.test_v133 import make_dashboard  # noqa: E402
from utils import applock, rename, scraper  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db._tx() as c:
            for t in ("media_items", "scanned_directories", "watch_history", "watch_log", "marks", "tags", "episode_gaps",
                      "cast_members", "custom_notes", "credit_marks"):
                c.execute(f"DELETE FROM {t}")
        for k in ("hidden_private_dirs", "hidden_recent_dirs", "recently_added", "lock_scope", "resume_prompt", "set_order",
                  "auto_lock_minutes", "lock_on_minimize", "show_missing_episodes"):
            db.set_setting(k, "")
        applock.reset()
        self.root = tempfile.mkdtemp()
        self.dir = db.add_directory(self.root, "Films", True)
        os.makedirs(os.path.join(self.root, "Show"))
        self.ids = {}
        for name, folder, kind, year in (("alpha.1999.1080p", "", "movie", "1999-03-31"), ("beta", "", "movie", None),
                                         ("show.s01e01", "Show", "show", None), ("show.s01e03", "Show", "show", None)):
            p = os.path.join(self.root, folder, name + ".mkv")
            open(p, "w").close()
            title = {"alpha.1999.1080p": "Alpha: Reborn", "beta": "Beta"}.get(name, "Show S01E0" + name[-1])
            db.add_items([{"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": self.dir, "title": title,
                           "media_type": kind, "duration": 3000, "release_date": year}])
            self.ids[name] = db.file_id(p)
        self.alpha, self.beta = self.ids["alpha.1999.1080p"], self.ids["beta"]
        self.show = "show:" + os.path.join(db.norm(self.root), "Show")
        self.d = make_dashboard()


class RowTests(Base):
    def test_recently_added_and_its_switches(self):
        old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        with db._tx() as c:
            c.execute("UPDATE media_items SET added_at=? WHERE uuid=?", (old, self.beta))
        self.d.reload()
        got = {r["key"]: r["note"] for r in self.d.recentlyAdded}
        self.assertEqual(set(got), {self.alpha, self.show})          # 45 days old: no longer recent
        self.assertEqual(got[self.alpha], "Added today")
        db.set_hidden("recent_dirs", [-1])
        self.d.reload()
        self.assertEqual(self.d.recentlyAdded, [])
        self.d.selectTab(self.dir)
        self.assertEqual(len(self.d.recentlyAdded), 2)
        db.set_setting("recently_added", "0")
        self.d.reload()
        self.assertEqual(self.d.recentlyAdded, [])

    def test_resume_question_and_surprise(self):
        self.assertEqual(self.d.resumeLabel(self.alpha), "")
        db.save_progress(self.alpha, 2530, False)
        self.assertEqual(self.d.resumeLabel(self.alpha), "42:10")
        db.set_setting("resume_prompt", "0")
        self.assertEqual(self.d.resumeLabel(self.alpha), "")
        db.save_progress(self.alpha, 3000, True)
        self.d.reload()
        for _ in range(20):
            self.assertIn(self.d.surprise(), {self.beta, self.show})    # the finished film is not offered
        self.d.setSearch("no such title") if hasattr(self.d, "setSearch") else self.d.library._rows.clear()
        self.d.library._rows.clear()
        self.assertEqual(self.d.surprise(), "")


class LockTests(Base):
    def test_auto_lock(self):
        self.d.idle_check(9999)
        self.assertFalse(self.d.locked)                               # no sign-in set up: nothing to lock
        applock.set_password("letmein")
        d = make_dashboard()
        d._set_unlocked()
        d.idle_check(9999)
        self.assertFalse(d.locked)                                    # Never
        db.set_setting("auto_lock_minutes", "5")
        d.idle_check(299)
        self.assertFalse(d.locked)
        d.app.engine.session = object()
        d.idle_check(301)
        self.assertFalse(d.locked)                                    # a film is playing
        d.app.engine.session = None
        d.idle_check(301)
        self.assertTrue(d.locked)
        d._set_unlocked()
        d.windowMinimized()
        self.assertFalse(d.locked)
        db.set_setting("lock_on_minimize", "1")
        d.app.engine.pip = True
        d.windowMinimized()
        self.assertFalse(d.locked)                                    # picture in picture minimised it
        d.app.engine.pip = False
        d.windowMinimized()
        self.assertTrue(d.locked)
        d._set_unlocked()
        db.set_setting("lock_scope", "private")                       # nothing private is open: stay quiet
        toasts = []
        d.toast.connect(toasts.append)
        d._private_open = False
        d.idle_check(301)
        self.assertEqual(toasts, [])
        applock.reset()


class EpisodeTests(Base):
    def test_missing_episodes_are_listed_greyed(self):
        guide = {(1, n): {"name": f"Ep {n}", "overview": "", "still": None} for n in (1, 2, 3, 4)}
        guide[(2, 1)] = {"name": "Next season", "overview": "", "still": None}      # a season you have none of: not listed
        done = []
        self.d.boxArtChanged.connect(done.append)
        with mock.patch.object(scraper, "episode_guide", return_value=guide), mock.patch.object(scraper, "save_episode_guide", return_value=0), \
                mock.patch("threading.Thread", side_effect=lambda target, **k: mock.Mock(start=target)):
            self.d.fetchEpisodeGuide(self.show)
        self.assertEqual(done, [self.show])
        rows = self.d.detail(self.show)["episodes"]
        self.assertEqual([(r["number"], bool(r.get("missing"))) for r in rows], [(1, False), (2, True), (3, False), (4, True)])
        self.assertEqual(rows[1]["name"], "Ep 2")
        db.set_setting("show_missing_episodes", "0")
        self.assertEqual(len(self.d.detail(self.show)["episodes"]), 2)


class RenameTests(Base):
    def test_plan(self):
        items = db.list_media(self.dir)
        plan = {r["old"]: r for r in rename.plan(items)}
        self.assertEqual(plan["alpha.1999.1080p.mkv"]["new"], "Alpha - Reborn (1999).mkv")     # ":" is not allowed on Windows
        self.assertEqual(plan["show.s01e01.mkv"]["new"], "Show S01E01.mkv")
        self.assertEqual(plan["beta.mkv"]["new"], "Beta.mkv") if "beta.mkv" in plan else None
        open(os.path.join(self.root, "Alpha - Reborn (1999).mkv"), "w").close()
        again = {r["old"]: r for r in rename.plan(items)}
        self.assertTrue(again["alpha.1999.1080p.mkv"]["problem"])
        self.assertEqual(rename.clean("CON"), "_CON")
        self.assertEqual(rename.clean('What? <Yes>. '), "What Yes")

    def test_apply_keeps_everything_attached(self):
        db.add_tag(self.alpha, "keeper")
        db.set_note(self.alpha, "mine")
        db.save_progress(self.alpha, 500, False)
        db.set_mark([self.alpha], "favourite", True)
        db.set_credits(db.get_media(self.alpha)["file_path"], 120)
        assets = Path(self.root) / scraper.ASSET_DIR
        (assets / "alpha.1999.1080p.gallery").mkdir(parents=True)
        for n in ("alpha.1999.1080p.webp", "alpha.1999.1080p.front.webp", "alpha.1999.1080p 2.webp"):
            (assets / n).write_bytes(b"x")
        (Path(self.root) / "alpha.1999.1080p.en.srt").write_text("1")
        rows = self.d.renamePlan([self.alpha])
        done, errors = rename.apply(rows)
        self.assertEqual((done, errors), (1, []))
        new_path = os.path.join(db.norm(self.root), "Alpha - Reborn (1999).mkv")
        self.assertTrue(os.path.isfile(new_path))
        new = db.file_id(new_path)
        self.assertIsNone(db.get_media(self.alpha))
        item = db.get_media(new)
        self.assertEqual((item["file_path"], item["last_position"]), (new_path, 500))
        self.assertEqual((db.tags_for(new), db.get_note(new)), (["keeper"], "mine"))
        self.assertIn(new, db.marks()["favourite"])
        self.assertEqual(db.get_credits(new_path), 120)
        self.assertTrue((assets / "Alpha - Reborn (1999).webp").exists() and (assets / "Alpha - Reborn (1999).front.webp").exists())
        self.assertTrue((assets / "Alpha - Reborn (1999).gallery").is_dir())
        self.assertTrue((assets / "alpha.1999.1080p 2.webp").exists())                 # another title's art is left alone
        self.assertTrue((Path(self.root) / "Alpha - Reborn (1999).en.srt").exists())
        self.assertEqual(rename.plan([item]), [])                                        # nothing left to do

    def test_a_failed_rename_changes_nothing(self):
        rows = self.d.renamePlan([self.alpha])
        with mock.patch("os.rename", side_effect=PermissionError(13, "in use")):
            done, errors = rename.apply(rows)
        self.assertEqual(done, 0)
        self.assertEqual(len(errors), 1)
        self.assertEqual(db.get_media(self.alpha)["title"], "Alpha: Reborn")


class SetOrderTests(Base):
    def test_your_own_order(self):
        key = self.d.groupIntoSet([self.alpha, self.beta], "Pair")
        self.assertEqual([f["uuid"] for f in db.films_in_set(key[4:])], [self.alpha, self.beta])     # by release; no date last
        self.d.moveFilm(key, self.beta, 0)
        self.assertEqual([f["uuid"] for f in db.films_in_set(key[4:])], [self.beta, self.alpha])
        self.assertEqual([e["uuid"] for e in self.d.detail(key)["episodes"]], [self.beta, self.alpha])
        new = db.move_item(self.beta, os.path.join(self.root, "Beta 2.mkv"))                         # a rename keeps its place
        self.assertEqual([f["uuid"] for f in db.films_in_set(key[4:])], [new, self.alpha])
        self.d.resetFilmOrder(key)
        self.assertEqual([f["uuid"] for f in db.films_in_set(key[4:])], [self.alpha, new])


class InsightTests(Base):
    def test_streak_weeks_and_top_titles(self):
        today = datetime.now(timezone.utc).date()
        with db._tx() as c:
            for back, uid, secs in ((1, self.alpha, 3600), (2, self.alpha, 600), (3, self.ids["show.s01e01"], 1200),
                                    (3, self.ids["show.s01e03"], 1200), (10, self.beta, 300), (11, self.beta, 300), (12, self.beta, 300),
                                    (13, self.beta, 300)):
                c.execute("INSERT INTO watch_log (media_uuid, day, seconds) VALUES (?,?,?)", (uid, (today - timedelta(days=back)).isoformat(), secs))
        a = db.analytics()
        self.assertEqual((a["streak"], a["best_streak"]), (3, 4))       # today not watched yet still counts yesterday's run
        self.assertEqual(len(a["weeks"]), 12)
        self.assertEqual(sum(m for _, m in a["weeks"]), 130)
        self.assertEqual(a["top_titles"][0], ("Alpha: Reborn", 70))
        self.assertEqual(a["top_titles"][1], ("Show", 40))             # a series is one title
        self.d._refresh_insights()
        self.assertEqual(self.d.insights["streak"], 3)


class WiringTests(unittest.TestCase):
    def test_wired(self):
        read = lambda *p: ROOT.joinpath(*p).read_text(encoding="utf-8")   # noqa: E731
        hud, eng = read("player", "Hud.qml"), read("player", "player_engine.py")
        self.assertIn("Player.playNext()", hud)
        self.assertIn("def playNext(self):", eng)
        self.assertIn('get_setting("pip_keep_library", "0") != "1"', read("main.py"))
        self.assertIn("Backend.windowMinimized()", read("ui", "Main.qml"))
        dash = read("ui", "Dashboard.qml")
        for needle in ("Backend.recentlyAdded", "Backend.surprise()", "ResumeAsk {", "RenameSheet {", "function playCard(k)", 'dash.toggleRow("continue")', 'dash.toggleRow("recent")'):
            self.assertIn(needle, dash)
        self.assertIn("Backend.moveFilm(", read("ui", "DetailView.qml"))
        self.assertIn("tests.test_v134", read(".github", "workflows", "release.yml"))


if __name__ == "__main__":
    unittest.main()
