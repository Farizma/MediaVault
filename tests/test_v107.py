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
        art = qml[qml.index("id: art"):qml.index("Item { id: mask")]
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
