"""Controller support through XInput (built into Windows: Xbox controllers, and most others in their Xbox mode).

Every 16 ms, while Media Vault is the active app, the connected controllers are read. A button press becomes a press of
the key its action is bound to (utils/controls.py), sent to the window that has focus: so the grid, View More, the
dialogs and the player all answer the controller exactly as they answer the keyboard. The left stick moves like the
D-pad. A held direction repeats like a held key.

Asking XInput about an empty slot is slow, so only connected controllers are read each frame; the others are looked
for every two seconds. Not on Windows (or no XInput): nothing happens.
"""
import ctypes
import logging
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent

from utils import controls

log = logging.getLogger(__name__)

BITS = {"DPad Up": 0x0001, "DPad Down": 0x0002, "DPad Left": 0x0004, "DPad Right": 0x0008, "Start": 0x0010,
        "Back": 0x0020, "LS": 0x0040, "RS": 0x0080, "LB": 0x0100, "RB": 0x0200, "A": 0x1000, "B": 0x2000,
        "X": 0x4000, "Y": 0x8000}
TRIGGER = 40            # of 255: a trigger counts as pressed past this
STICK = 16000           # of 32767: the left stick counts as a direction past this
REPEAT_AFTER, REPEAT_EVERY = 0.38, 0.11      # seconds: a held direction repeats like a held key
REPEATS = {"DPad Up", "DPad Down", "DPad Left", "DPad Right"}


class _Pad(ctypes.Structure):
    _fields_ = [("wButtons", ctypes.c_ushort), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                ("sThumbRY", ctypes.c_short)]


class _State(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint), ("Gamepad", _Pad)]


def _xinput():
    for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            return getattr(ctypes, "windll").LoadLibrary(name)
        except (AttributeError, OSError):
            continue
    return None


def pressed(pad: _Pad) -> set:
    """The buttons held, by name; the left stick reads as the D-pad."""
    out = {n for n, bit in BITS.items() if pad.wButtons & bit}
    if pad.bLeftTrigger > TRIGGER:
        out.add("LT")
    if pad.bRightTrigger > TRIGGER:
        out.add("RT")
    if pad.sThumbLY > STICK:
        out.add("DPad Up")
    elif pad.sThumbLY < -STICK:
        out.add("DPad Down")
    if pad.sThumbLX < -STICK:
        out.add("DPad Left")
    elif pad.sThumbLX > STICK:
        out.add("DPad Right")
    return out


class Gamepad(QObject):
    connectedChanged = Signal()
    buttonPressed = Signal(str)          # every press, by name (Settings > Controls uses it to bind a button)

    def __init__(self, parent=None, lib=None):
        super().__init__(parent)
        self._lib = lib if lib is not None else _xinput()
        self._slots: list[int] = []      # connected controllers
        self._held: dict[int, set] = {}
        self._next: dict[tuple, float] = {}       # (slot, button) -> when it repeats
        self.capturing = False           # Settings is waiting for a button: presses are not turned into keys
        self._poll = QTimer(self)
        self._poll.setInterval(16)
        self._poll.timeout.connect(self.tick)
        self._scan = QTimer(self)
        self._scan.setInterval(2000)
        self._scan.timeout.connect(self.scan)
        if self._lib is None:
            return
        app = QGuiApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._app_state)
        self.scan()
        self._scan.start()
        self._app_state(app.applicationState() if app else Qt.ApplicationActive)

    @property
    def available(self) -> bool:
        return self._lib is not None

    @property
    def connected(self) -> int:
        return len(self._slots)

    def _app_state(self, state):
        active = state == Qt.ApplicationActive
        if active and self._slots:
            self._poll.start()
        else:
            self._poll.stop()
            self._held.clear()

    def _read(self, slot: int):
        st = _State()
        return st if self._lib.XInputGetState(slot, ctypes.byref(st)) == 0 else None

    def scan(self):
        """Which of the four slots have a controller (every 2 s: reading an empty slot is slow)."""
        if self._lib is None:
            return
        try:
            now = [i for i in range(4) if self._read(i) is not None]
        except Exception:
            log.warning("controller scan", exc_info=True)
            now = []
        if now != self._slots:
            self._slots = now
            self.connectedChanged.emit()
            app = QGuiApplication.instance()
            self._app_state(app.applicationState() if app else Qt.ApplicationActive)

    def tick(self):
        t = time.monotonic()
        for slot in list(self._slots):
            st = self._read(slot)
            if st is None:                   # unplugged
                self._slots.remove(slot)
                self._held.pop(slot, None)
                self.connectedChanged.emit()
                continue
            self.feed(slot, pressed(st.Gamepad), t)

    def feed(self, slot: int, now: set, t: float):
        """New presses fire once; a held direction repeats."""
        before = self._held.get(slot, set())
        for b in now - before:
            self._fire(b)
            self._next[(slot, b)] = t + REPEAT_AFTER
        for b in now & before & REPEATS:
            if t >= self._next.get((slot, b), t + 1):
                self._fire(b)
                self._next[(slot, b)] = t + REPEAT_EVERY
        self._held[slot] = now

    def _fire(self, button: str):
        self.buttonPressed.emit(button)
        if self.capturing:
            return
        action = controls.action_for_button(button)
        k = controls.key_for(action) if action else None
        if k:
            send_key(*k)


def send_key(key: int, mods: int):
    """A key press and release, to whatever has the keyboard in Media Vault's focused window."""
    win = QGuiApplication.focusWindow()
    if win is None:
        return
    m = Qt.KeyboardModifier(mods)
    if key == controls.K["Tab"] and mods & controls.SHIFT:
        key = controls.K["Backtab"]              # what the keyboard itself sends for Shift+Tab
    for kind in (QEvent.KeyPress, QEvent.KeyRelease):
        QGuiApplication.sendEvent(win, QKeyEvent(kind, key, m))
