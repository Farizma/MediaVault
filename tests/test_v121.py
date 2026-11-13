"""1.2.0: progress pills for scraping, artwork and downloads."""
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

from utils import progress  # noqa: E402


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        progress.subscribe(self.events.append)

    def tearDown(self):
        progress.unsubscribe(self.events.append)

    def test_task_reports_start_steps_and_end_throttled(self):
        with progress.task("Scraping", total=500) as t:
            for _ in range(500):
                t.step(detail="x")
        states = [e["state"] for e in self.events]
        self.assertEqual(states[0], "running")
        self.assertEqual(states[-1], "done")
        self.assertEqual(self.events[-1]["done"], 500)
        self.assertLess(len(self.events), 60)                  # a fast loop does not flood the interface

    def test_failure_is_shown_and_still_raised(self):
        with self.assertRaises(RuntimeError):
            with progress.task("Downloading x", total=10, unit="bytes"):
                raise RuntimeError("offline")
        self.assertEqual(self.events[-1]["state"], "failed")

    def test_phase_change_goes_out_at_once(self):
        with progress.task("Adding 3 files", total=3) as t:
            t.update(label="Looking up titles", total=0, done=0)
            self.assertEqual(self.events[-1]["label"], "Looking up titles")

    def test_scrape_many_counts_lookups(self):
        import asyncio
        from utils import scraper
        t = progress.Task("lookups")
        jobs = [("movie", scraper.Parsed("A", None, None, None)), ("movie", scraper.Parsed("A", None, None, None)),
                ("movie", scraper.Parsed("B", None, None, None))]
        with mock.patch.object(scraper, "_lookup", return_value=None):
            asyncio.run(scraper.scrape_many(jobs, {}, "tmdb", t))
        self.assertEqual((t.done, t.total), (2, 2))            # the same title is asked (and counted) once

    def test_dashboard_keeps_then_drops_finished_jobs(self):
        import types
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        import database as db
        db.init_db()
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None)
        d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())
        with progress.task("Fetching", total=2) as t:
            t.step()
        QCoreApplication.processEvents()
        self.assertEqual(d.jobs[0]["state"], "done")
        d._drop_job(d.jobs[0]["id"])
        self.assertEqual(d.jobs, [])

    def test_wired_in(self):
        w = (ROOT / "watcher.py").read_text(encoding="utf-8")
        for needle in ("progress.task(f\"Adding", "Downloading artwork", "Fetching missing details", "Box set banners"):
            self.assertIn(needle, w)
        self.assertIn("progress.task(label or f\"Downloading {dest.name}\"", (ROOT / "setup.py").read_text(encoding="utf-8"))
        self.assertIn("ProgressDock {", (ROOT / "ui" / "Dashboard.qml").read_text(encoding="utf-8"))
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_v121", wf)


if __name__ == "__main__":
    unittest.main()


class PolishLoopTests(unittest.TestCase):
    def test_title_width_does_not_depend_on_its_own_layout(self):
        qml = (ROOT / "ui" / "DetailView.qml").read_text(encoding="utf-8")
        self.assertNotIn("titleCol.width", qml)        # 1.1.1: re-laid out every frame, the dashboard lagged
        self.assertIn("Math.min(tm.advanceWidth + 6, col.width - (root.d.isSet === true ? 84 : 48))", qml)
