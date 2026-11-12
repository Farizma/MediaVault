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
