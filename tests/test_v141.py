"""1.3.6: the HUD survives Windows destroying its window; VR videos open in a look-around view."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from player import player_engine, vr_detector  # noqa: E402
from player.vr_detector import VRInfo  # noqa: E402


class DetectTests(unittest.TestCase):
    def test_names_seen_in_the_wild(self):
        d = vr_detector.detect
        self.assertEqual(d("OpalChristmasReverseCowgirl 60FPS6K 180 SBS.mp4"), VRInfo("180", "sbs", False))
        self.assertEqual(d("Twilight scene VR 2.mp4"), VRInfo("180", "sbs", False))          # plain "VR"
        self.assertEqual(d("clip_VR180_LR.mp4"), VRInfo("180", "sbs", False))
        self.assertEqual(d("walk_360.mp4"), VRInfo("360", "mono", False))
        self.assertEqual(d("walk_360_TB.mp4"), VRInfo("360", "tb", False))
        self.assertEqual(d("scene_MKX200.mp4"), VRInfo("fisheye", "sbs", False, 200))
        self.assertEqual(d("scene_FISHEYE190_LR.mp4"), VRInfo("fisheye", "sbs", False, 190))
        self.assertEqual(d("scene RF52.mp4").lens, 190)
        self.assertEqual(d("film 3DV.mkv"), VRInfo("flat", "tb", False))
        self.assertIsNone(d("Coward3D - My Tomboy.mp4"))                  # a word ending in 3D is not a tag
        self.assertIsNone(d("VRChat stream.mp4"))
        self.assertIsNone(d("Movie 2020 1080p.mkv"))

    def test_views_and_labels(self):
        self.assertEqual(vr_detector.views(VRInfo("180", "sbs", False)), ("look", "sbs"))
        self.assertEqual(vr_detector.views(VRInfo("360", "mono", False)), ("look",))
        self.assertEqual(vr_detector.views(VRInfo("flat", "sbs", False)), ("left", "sbs"))
        self.assertEqual(vr_detector.views(None), ())
        self.assertEqual(vr_detector.label(VRInfo("fisheye", "sbs", False, 200)), "VR fisheye 200°")

    def test_look_limits(self):
        c = vr_detector.clamp_look
        self.assertEqual(c(200, 0, 100, VRInfo("360", "mono", False)), (-160.0, 0.0, 100.0))   # 360 wraps
        y, p, f = c(200, 120, 300, VRInfo("180", "sbs", False))
        self.assertEqual((p, f), (85.0, 140.0))
        self.assertLess(y, 90)                                                                    # 180 stops at its edge
        self.assertEqual(c(0, 0, 10, None)[2], 40.0)

    def test_filters(self):
        f = vr_detector.mpv_filter(VRInfo("180", "sbs", False), "look", 15, -5, 90)
        self.assertTrue(f.startswith("@vr:lavfi=["))                                              # turnable by vf-command
        self.assertIn("v360=input=hequirect:output=flat:w=1920:h=1080:yaw=15:pitch=-5:h_fov=90", f)
        self.assertNotIn("scale=iw*2", f)                       # one eye goes straight into v360, no stretch first
        fish = vr_detector.mpv_filter(VRInfo("fisheye", "sbs", False, 200), "look")
        self.assertIn("input=fisheye:ih_fov=200:iv_fov=200", fish)
        flat = vr_detector.mpv_filter(VRInfo("flat", "sbs", False), "left")
        self.assertTrue(flat.startswith("lavfi=[") and "scale=iw*2:ih" in flat)
        self.assertAlmostEqual(vr_detector.v_fov(90), 58.72, places=1)
        self.assertEqual(vr_detector.shader_opts(VRInfo("360", "tb", False), 10, 5, 80),
                         "proj=1,stereo=2,lens=180.0,yaw=10.0,pitch=5.0,fov=80.0")

    def test_shader_file(self):
        src = Path(vr_detector.SHADER).read_text()
        for param in ("proj", "stereo", "lens", "yaw", "pitch", "fov"):
            self.assertIn(f"//!PARAM {param}\n", src)
        self.assertNotIn("layout", src.split("vec4 hook()")[1])                  # a reserved word in GLSL
        self.assertIn("//!HOOK MAIN", src)


class FakeMpv(dict):
    def __init__(self):
        super().__init__()
        self.vf, self.glsl_shaders, self.commands = "", "", []

    def command(self, *a):
        self.commands.append(a)


class CoreTests(unittest.TestCase):
    def core(self, next_vo=True):
        c = object.__new__(player_engine.MpvCore)
        c.p, c.next_vo, c._vr_shader, c.level, c.rtx, c._vf = FakeMpv(), next_vo, False, 1, False, None
        return c

    def test_gpu_look_then_move_then_leave(self):
        c, info = self.core(), VRInfo("180", "sbs", False)
        c.set_vr(info, "look", 0, 0, 100)
        self.assertIn(vr_detector.SHADER, c.p.glsl_shaders)
        self.assertEqual(c.p["video-aspect-override"], "16:9")
        c.set_vr(info, "look", 20, 0, 100, moved=True)
        self.assertIn("yaw=20.0", c.p["glsl-shader-opts"])
        c.set_vr(info, "sbs", 0, 0, 100)
        self.assertNotIn(vr_detector.SHADER, c.p.glsl_shaders)
        self.assertEqual(c.p["video-aspect-override"], "no")

    def test_software_look_turns_with_vf_command(self):
        c, info = self.core(next_vo=False), VRInfo("360", "mono", False)
        c.set_vr(info, "look", 0, 0, 100)
        self.assertTrue(c.p.vf.startswith("@vr:"))
        c.set_vr(info, "look", 30, 0, 100, moved=True)
        self.assertIn(("vf-command", "vr", "yaw", "30"), c.p.commands)


class HudTests(unittest.TestCase):
    def test_a_lost_hud_window_is_made_again(self):
        calls = []
        hud = types.SimpleNamespace(isVisible=lambda: True, winId=lambda: 0, destroy=lambda: calls.append("destroy"),
                                    setTransientParent=lambda w: calls.append("owner"), setVisible=lambda v: calls.append(v))
        eng = types.SimpleNamespace(hud=hud, win=object(), _state={"active": True}, _hud_rebuilds=0,
                                    _raise_hud=lambda: calls.append("raise"))
        player_engine.PlayerEngine._hud_alive(eng)
        self.assertEqual(calls, ["destroy", "owner", True, "raise"])
        for _ in range(5):
            player_engine.PlayerEngine._hud_alive(eng)
        self.assertEqual(calls.count("destroy"), 3)                               # gives up after a few tries
        eng._state = {"active": False}
        eng._hud_rebuilds = 0
        player_engine.PlayerEngine._hud_alive(eng)
        self.assertEqual(calls.count("destroy"), 3)


if __name__ == "__main__":
    unittest.main()
