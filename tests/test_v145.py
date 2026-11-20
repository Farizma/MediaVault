"""1.3.9: folder pictures framed or fitted whole, Library Status on request, more part names, the video frame as
default Gallery art, and the player's 3D / VR format picker."""
import json
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
from PIL import Image  # noqa: E402
from player import player_engine, vr_detector  # noqa: E402
from ui import dashboard  # noqa: E402
from utils import health, scraper  # noqa: E402


class PartNameTests(unittest.TestCase):
    def test_short_forms(self):
        for title, want in (("Lucy P1", ("Lucy", 1)), ("Lucy p.2", ("Lucy", 2)), ("Mona E1", ("Mona", 1)),
                            ("Mona e.03", ("Mona", 3)), ("Mona ep1", ("Mona", 1)), ("Mona episode 4", ("Mona", 4)),
                            ("Lucy part 1", ("Lucy", 1)), ("Lucy - Pt 2", ("Lucy", 2))):
            self.assertEqual(db.part_name(title), want, title)
        for title in ("Show S01E02", "Trip 2", "Apartment 3", "Grape 2", "Movie 2019", "Episode 1"):
            self.assertIsNone(db.part_name(title), title)


class GalleryTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.root = Path(tempfile.mkdtemp())
        p = self.root / "clip.mp4"
        p.write_bytes(b"")
        self.item = {"uuid": db.file_id(p), "file_path": db.norm(p), "key": db.file_id(p), "media_type": "clip"}

    def test_the_video_frame_stands_in(self):
        self.assertEqual(dashboard.gallery_rows(self.item), [])
        self.assertIsNone(dashboard.banner_for(self.item))
        thumb = scraper.thumb_path(self.item)
        thumb.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 36)).save(thumb, "WEBP")
        rows = dashboard.gallery_rows(self.item)
        self.assertEqual((len(rows), rows[0]["auto"], rows[0]["name"]), (1, True, ""))
        self.assertEqual(dashboard.banner_for(self.item), thumb)
        shot = scraper.gallery_dir(self.item)
        shot.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 36)).save(shot / "c-1.webp", "WEBP")
        self.assertEqual([r["name"] for r in dashboard.gallery_rows(self.item)], ["c-1.webp"])   # real art wins
        self.assertEqual(dashboard.banner_for(self.item).name, "c-1.webp")


class HealthTests(unittest.TestCase):
    def test_lists_are_cut_short_with_totals(self):
        art = [{"key": str(i), "title": str(i)} for i in range(250)]
        with mock.patch.object(health, "missing_artwork", return_value=art), \
                mock.patch.object(health, "duplicates", return_value=[]), \
                mock.patch.object(health, "missing_episodes", return_value=[]), \
                mock.patch.object(health, "folders", return_value=[]):
            r = health.report(lambda x: "", {})
        self.assertEqual((len(r["artwork"]), r["artworkTotal"], r["duplicatesTotal"]), (health.SHOW_MAX, 250, 0))

    def test_checked_in_the_background_only_when_asked(self):
        from PySide6.QtGui import QGuiApplication
        from tests.test_v133 import make_dashboard
        db.init_db()
        d = make_dashboard()
        got = []
        d.healthReady.connect(got.append)
        with mock.patch.object(health, "report", return_value={"artwork": [], "artworkTotal": 0}) as rep:
            d.checkHealth()
            end = time.time() + 5
            while not got and time.time() < end:
                QGuiApplication.processEvents()
                time.sleep(0.02)
        rep.assert_called_once()
        self.assertEqual(got[0]["artworkTotal"], 0)
        qml = (ROOT / "ui" / "SettingsView.qml").read_text(encoding="utf-8")
        self.assertNotIn('if (sectionName === "Library Status") refreshHealth()', qml)     # not on opening the page


class FolderPictureTests(unittest.TestCase):
    def test_fit_whole_fills_around_and_fill_crops(self):
        src = Path(tempfile.mkdtemp()) / "wide.png"
        img = Image.new("RGB", (400, 200), (255, 0, 0))
        img.paste((0, 0, 255), (0, 0, 200, 200))                     # blue left half, red right half
        img.save(src)
        dest = src.with_name("out.webp")
        # fitted whole: the square reaches 100 px above and below the 400 x 200 picture
        dashboard.save_folder_picture(str(src), 0, -0.5, 1, 2, 0, dest)
        out = Image.open(dest).convert("RGB")
        self.assertEqual(out.size, (512, 512))
        top = out.getpixel((256, 20))
        self.assertLess(max(top), 200)                                # the blurred, darker copy, not the picture
        self.assertGreater(out.getpixel((40, 256))[2], 200)           # the picture itself, blue on the left
        # filled: the right half's square only (all red)
        dashboard.save_folder_picture(str(src), 0.5, 0, 0.5, 1, 0, dest)
        out = Image.open(dest).convert("RGB")
        self.assertGreater(out.getpixel((10, 10))[0], 200)
        with self.assertRaises(ValueError):
            dashboard.save_folder_picture(str(src), 0, 0, 0.001, 0.001, 0, dest)

    def test_cropper_can_fit_only_folder_pictures(self):
        qml = (ROOT / "ui" / "ArtCropper.qml").read_text(encoding="utf-8")
        self.assertIn('readonly property bool canFit: face === "folder"', qml)
        self.assertIn("Backend.saveFolderPicture(key, path", qml)


class VrFormatTests(unittest.TestCase):
    def test_codes(self):
        for code, _, info in vr_detector.FORMATS:
            self.assertEqual(vr_detector.code_of(info), code)
        self.assertEqual(vr_detector.code_of(vr_detector.detect("a 180 SBS.mp4")), "180_sbs")
        self.assertEqual(vr_detector.code_of(vr_detector.detect("a_FSBS_3D.mkv")), "3d_sbs")     # full size: nearest
        with self.assertRaises(KeyError):
            vr_detector.by_code("bogus")

    def test_picking_a_format_is_remembered_per_file(self):
        db.init_db()
        db.set_setting("vr_formats", "")
        calls = []
        core = types.SimpleNamespace(name="mpv", set_vr=lambda *a, **k: calls.append(a))
        eng = types.SimpleNamespace(core=core, session=types.SimpleNamespace(path="/v/clip.mp4"), _state={}, _vr=None,
                                    _vr_view="left", _vr_look=[0, 0, 100], stateChanged=types.SimpleNamespace(emit=lambda: None),
                                    _say=lambda t: calls.append(t))
        eng._apply_vr = lambda moved=False: player_engine.PlayerEngine._apply_vr(eng, moved)
        player_engine.PlayerEngine.setVrFormat(eng, "360_tb")
        self.assertEqual(eng._vr, vr_detector.VRInfo("360", "tb", False))
        self.assertEqual(eng._vr_view, "look")
        self.assertEqual(eng._state["vrFormat"], "360_tb")
        self.assertEqual(list(json.loads(db.get_setting("vr_formats")).values()), ["360_tb"])
        player_engine.PlayerEngine.setVrFormat(eng, "2d")              # what the name says: nothing to remember
        self.assertIsNone(eng._vr)
        self.assertEqual(json.loads(db.get_setting("vr_formats")), {})
        player_engine.PlayerEngine.setVrFormat(eng, "bogus")
        self.assertIsNone(eng._vr)


class FolderConfigTests(unittest.TestCase):
    def test_two_columns_that_scroll_on_their_own(self):
        qml = (ROOT / "ui" / "FolderConfig.qml").read_text(encoding="utf-8")
        self.assertIn("scrolls: false", qml)
        self.assertIn("id: leftFlick", qml)
        self.assertLess(qml.index("id: leftFlick"), qml.index('text: "SUBFOLDERS"'))
        self.assertEqual(qml.count("{"), qml.count("}"))


if __name__ == "__main__":
    unittest.main()
