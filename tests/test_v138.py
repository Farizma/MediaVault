"""1.3.4: View disc in View More, and a Landscape layout (16:9 thumbnails) per tab."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from PIL import Image  # noqa: E402
from tests.test_v133 import make_dashboard  # noqa: E402
from utils import scraper  # noqa: E402


class LandscapeTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        with db._tx() as c:
            for t in ("media_items", "scanned_directories"):
                c.execute(f"DELETE FROM {t}")
        db.set_setting("hidden_landscape_dirs", "")
        self.root = Path(tempfile.mkdtemp())
        self.dir = db.add_directory(str(self.root), "Home videos", True)
        rows = []
        for name in ("beach", "party", "hike"):
            p = self.root / f"{name}.mkv"
            p.write_bytes(b"")
            rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": self.dir, "title": name,
                         "media_type": "movie", "duration": 600})
        db.add_items(rows)
        self.beach, self.party, self.hike = (db.get_media(r["uuid"]) for r in rows)
        self.d = make_dashboard()

    def thumbs(self):
        return {r["key"]: r["thumb"] for r in self.d.library._rows}

    def test_layout_is_per_tab(self):
        self.d.reload()
        self.assertFalse(self.d.landscape)
        self.assertTrue(all(t == "" for t in self.thumbs().values()))         # DVD tabs never look thumbnails up
        changed = []
        self.d.layoutChanged.connect(lambda: changed.append(1))
        with mock.patch.object(self.d, "_auto_thumbs"):
            self.d.setTabLandscape(self.dir, True)
            self.d.selectTab(self.dir)
        self.assertTrue(self.d.landscape)
        self.assertEqual(changed, [1])
        self.d.selectTab(-1)
        self.assertFalse(self.d.landscape)                                     # the All tab is its own choice
        self.assertTrue(next(d for d in self.d.directories() if d["id"] == self.dir)["landscape"])

    def test_wide_picture_order(self):
        Image.new("RGB", (32, 18)).save(scraper.thumb_path(self.beach).parent.mkdir(parents=True, exist_ok=True) or scraper.thumb_path(self.beach))
        Image.new("RGB", (32, 18)).save(scraper.banner_path(self.beach))
        Image.new("RGB", (32, 18)).save(scraper.banner_path(self.party))
        g = scraper.gallery_dir(self.hike)
        g.mkdir(parents=True)
        Image.new("RGB", (32, 18)).save(g / "s-01.webp")
        with mock.patch.object(self.d, "_auto_thumbs"):
            self.d.setTabLandscape(-1, True)
        t = self.thumbs()
        self.assertIn(".thumb.webp", t[self.beach["uuid"]])                   # the frame you picked beats the banner
        self.assertIn(".banner.webp", t[self.party["uuid"]])
        self.assertIn("s-01.webp", t[self.hike["uuid"]])

    def test_frames_from_the_video_once(self):
        player = mock.MagicMock()
        player.open.return_value = True
        player.frame_at.return_value = Image.new("RGB", (1920, 1080), "red")
        changed = []
        self.d.libraryChanged.connect(lambda: changed.append(1))
        with mock.patch("utils.media_probe.HeadlessPlayer", return_value=player), \
                mock.patch("threading.Thread", side_effect=lambda target, **k: mock.Mock(start=target)):
            db.set_hidden("landscape_dirs", [-1])
            self.d.reload()
            self.d._auto_thumbs()                                             # the same titles: not again
        self.assertEqual(player.frame_at.call_count, 3)
        self.assertEqual(player.frame_at.call_args[0][0], 120)                # a fifth of the way in
        self.assertTrue(scraper.thumb_path(self.hike).exists())
        self.assertEqual(Image.open(scraper.thumb_path(self.hike)).size[0] / Image.open(scraper.thumb_path(self.hike)).size[1], 16 / 9)
        self.assertTrue(changed)

    def test_picked_frame(self):
        frame = Image.new("RGB", (1920, 1080), "blue")
        self.d._thumbs = [frame]
        self.d.library.landscape = True
        self.d.useThumbnail(self.beach["uuid"], 0)
        self.assertTrue(scraper.thumb_path(self.beach).exists())
        self.assertFalse(scraper.custom_front_path(self.beach).exists())
        self.d._thumbs = [frame]
        self.d.library.landscape = False                                       # a DVD tab: the front cover, as before
        self.d.useThumbnail(self.party["uuid"], 0)
        self.assertTrue(scraper.custom_front_path(self.party).exists())
        self.assertFalse(scraper.thumb_path(self.party).exists())


class WiringTests(unittest.TestCase):
    def test_qml(self):
        read = lambda *p: ROOT.joinpath(*p).read_text(encoding="utf-8")   # noqa: E731
        detail, box, disc, dash = read("ui", "DetailView.qml"), read("ui", "DvdBox.qml"), read("ui", "Disc.qml"), read("ui", "Dashboard.qml")
        for needle in ("function viewDisc()", "function hideDisc()", 'label: root.discMode ? "Back to box" : "View disc"',
                       "discOut: root.discOut > 0", "dataSide: true"):
            self.assertIn(needle, detail)
        self.assertIn("!root.discOut", box)                                    # the box hides its own disc once it is out
        self.assertIn("createConicalGradient", disc)
        self.assertIn('model: ["Grid", "Shelf", "Landscape"]', dash)
        self.assertIn("readonly property bool shelfView: shelf && !landscape", dash)
        self.assertIn("tests.test_v138", read(".github", "workflows", "release.yml"))


if __name__ == "__main__":
    unittest.main()
