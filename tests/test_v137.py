"""1.3.3: keyboard and controller controls, remappable in Settings > Controls."""
import ctypes
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
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from utils import controls, gamepad  # noqa: E402

KEY = lambda name: int(getattr(Qt, f"Key_{name}").value)       # noqa: E731
SHIFT = int(Qt.ShiftModifier.value)


class BindingTests(unittest.TestCase):
    def setUp(self):
        db.init_db()
        controls.reset()

    def test_defaults(self):
        a = controls.action_for_key
        self.assertEqual((a(KEY("Space"), 0), a(KEY("Return"), 0), a(KEY("Enter"), 0)), ("viewMore", "play", "play"))
        self.assertEqual((a(KEY("Tab"), 0), a(KEY("Backtab"), SHIFT), a(KEY("Escape"), 0)), ("nextTab", "prevTab", "back"))
        self.assertEqual(a(KEY("Up"), 0), "up")
        self.assertEqual(a(KEY("Space"), int(Qt.ControlModifier.value)), "")        # Ctrl+Space is something else
        self.assertEqual(controls.action_for_button("A"), "viewMore")
        self.assertEqual(controls.action_for_button("RB"), "nextTab")
        self.assertEqual([r["key"] for r in controls.rows()][4:], ["Space", "Enter", "Tab", "Shift+Tab", "Esc"])

    def test_remap_swaps(self):
        controls.set_key("play", KEY("P"), 0)
        self.assertEqual(controls.action_for_key(KEY("P"), 0), "play")
        self.assertEqual(controls.action_for_key(KEY("Return"), 0), "")             # Enter is free now
        controls.set_key("play", KEY("Space"), 0)                                    # View More had Space: it takes P
        self.assertEqual(controls.action_for_key(KEY("Space"), 0), "play")
        self.assertEqual(controls.action_for_key(KEY("P"), 0), "viewMore")
        controls.set_pad("play", "A")
        self.assertEqual((controls.action_for_button("A"), controls.action_for_button("X")), ("play", "viewMore"))
        controls.set_pad("play", "Nonsense")
        self.assertEqual(controls.pads()["play"], "A")
        controls.reset()
        self.assertEqual(controls.action_for_key(KEY("Return"), 0), "play")

    def test_a_controller_types_the_bound_key(self):
        self.assertEqual(controls.key_for("prevTab"), [KEY("Tab"), SHIFT])
        controls.set_key("play", KEY("P"), 0)
        self.assertEqual(controls.key_for("play"), [KEY("P"), 0])


class FakeXInput:
    """XInputGetState for slot 0 only; `buttons`, triggers and stick set by the test."""

    def __init__(self):
        self.connected = {0}
        self.buttons, self.lt, self.lx, self.ly = 0, 0, 0, 0

    def XInputGetState(self, slot, ref):
        if slot not in self.connected:
            return 1167                                   # ERROR_DEVICE_NOT_CONNECTED
        st = ctypes.cast(ref, ctypes.POINTER(gamepad._State)).contents
        st.Gamepad.wButtons, st.Gamepad.bLeftTrigger = self.buttons, self.lt
        st.Gamepad.sThumbLX, st.Gamepad.sThumbLY = self.lx, self.ly
        return 0


class GamepadTests(unittest.TestCase):
    def setUp(self):
        QGuiApplication.instance() or QGuiApplication([])
        db.init_db()
        controls.reset()
        self.lib = FakeXInput()
        self.pad = gamepad.Gamepad(lib=self.lib)
        self.sent = []
        patcher = mock.patch.object(gamepad, "send_key", side_effect=lambda k, m: self.sent.append((k, m)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_found_and_read(self):
        self.assertTrue(self.pad.available)
        self.assertEqual(self.pad.connected, 1)

    def test_buttons_press_their_keys(self):
        self.pad.feed(0, {"A"}, 0.0)
        self.pad.feed(0, {"A"}, 1.0)                       # held: a button does not repeat
        self.pad.feed(0, set(), 1.1)
        self.pad.feed(0, {"LB"}, 1.2)
        self.assertEqual(self.sent, [(KEY("Space"), 0), (KEY("Tab"), SHIFT)])

    def test_a_held_direction_repeats(self):
        for t in (0.0, 0.2, 0.39, 0.45, 0.51):
            self.pad.feed(0, {"DPad Down"}, t)
        self.assertEqual(self.sent, [(KEY("Down"), 0)] * 3)

    def test_stick_and_triggers(self):
        state = gamepad._Pad()
        state.sThumbLY, state.sThumbLX, state.bLeftTrigger = 30000, -30000, 200
        self.assertEqual(gamepad.pressed(state), {"DPad Up", "DPad Left", "LT"})
        state.sThumbLY, state.sThumbLX, state.bLeftTrigger = 5000, 0, 10           # inside the dead zone
        self.assertEqual(gamepad.pressed(state), set())

    def test_tick_reads_the_controller(self):
        self.lib.buttons = gamepad.BITS["B"]
        self.pad.tick()
        self.assertEqual(self.sent, [(KEY("Escape"), 0)])
        self.lib.connected.clear()                         # unplugged
        self.pad.tick()
        self.assertEqual(self.pad.connected, 0)

    def test_settings_waits_for_a_button(self):
        seen = []
        self.pad.buttonPressed.connect(seen.append)
        self.pad.capturing = True
        self.pad.feed(0, {"Y"}, 0.0)
        self.assertEqual((seen, self.sent), (["Y"], []))

    def test_no_xinput_no_controller(self):
        with mock.patch.object(gamepad, "_xinput", return_value=None):
            pad = gamepad.Gamepad()
        self.assertFalse(pad.available)
        pad.scan()
        self.assertEqual(pad.connected, 0)


class WiringTests(unittest.TestCase):
    def test_screens_use_the_bindings(self):
        read = lambda *p: ROOT.joinpath(*p).read_text(encoding="utf-8")   # noqa: E731
        dash, detail, settings = read("ui", "Dashboard.qml"), read("ui", "DetailView.qml"), read("ui", "SettingsView.qml")
        self.assertIn("keyNavigationEnabled: false", dash)
        self.assertIn('a === "viewMore" && currentItem', dash)
        self.assertIn('stepTab(a === "nextTab" ? 1 : -1)', dash)
        self.assertIn("Backend.keyAction(e.key, e.modifiers)", detail)
        self.assertIn('["Controls", "#FF2D55", "controls"]', settings)
        for f in ("Sheet", "SettingsView", "FixMatch", "InsightsSheet", "PickerView", "FolderSheet", "ArtCropper", "ResumeAsk"):
            self.assertIn('Backend.keyAction(e.key, e.modifiers)', read("ui", f + ".qml"), f)   # a remapped Back closes it
        self.assertIn("tests.test_v137", read(".github", "workflows", "release.yml"))

    def test_backend(self):
        from tests.test_v133 import make_dashboard
        db.init_db()
        controls.reset()
        d = make_dashboard()
        self.assertEqual(d.keyAction(KEY("Return"), 0), "play")
        d.setKeyBinding("play", KEY("P"), 0)
        self.assertEqual(next(r for r in d.controlRows if r["id"] == "play")["key"], "P")
        d.resetControls()
        self.assertEqual(d.tabOrder()[0], {"id": -1, "name": "All", "locked": False})
        # off Windows there is no XInput; on Windows (the release build) there is, with no controller plugged in
        self.assertTrue("XInput" in d.padStatus or d.padStatus.startswith("No controller connected"), d.padStatus)


if __name__ == "__main__":
    unittest.main()
