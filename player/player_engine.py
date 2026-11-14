"""Theater playback for Qt.

Layout of a playback session:
  * a frameless FULLSCREEN native window (BlackWindow) that mpv / VLC render into via `wid`
  * a transparent always-on-top QML window (player/Hud.qml) drawn over it: the glass HUD
  * a click-through black window on every other monitor

mpv / VLC receive no input. All keys and mouse go to the QML HUD, which calls the slots below.
Everything runs on the GUI thread (one 150 ms QTimer): no player threads, nothing blocks.

Keys (handled in Hud.qml): Space pause, Left/Right seek 10 s, Up/Down volume 5 % (also the scroll wheel), N night mode, U upscaling level,
Tab skip intro, Enter next episode, C box art, Shift+C fanart, I mark intro, V VR view, Esc back.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import (Property, QEasingCurve, QObject, QRect, QSize, QTimer, QVariantAnimation, Qt, Signal, Slot)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QRasterWindow

from utils import hw_accelerator as hw, scraper
from . import vr_detector

log = logging.getLogger(__name__)
COUNTDOWN = 15  # seconds before the end of an episode
_INTRO_CHAPTER = re.compile(r"^\W*(intro|opening|op|recap|previously)\b", re.I)
_CREDITS_CHAPTER = re.compile(r"^\W*(end\s*credits|credits|ending|outro|ed)\b", re.I)
SPEEDS = (0.5, 3.0)


@dataclass
class Session:
    path: str
    title: str = ""
    uuid: str | None = None          # None: file is not in the library (opened from Explorer)
    start: float = 0.0
    next_path: str | None = None
    next_title: str = ""
    intro: tuple[float, float] | None = None
    credits: float | None = None     # the credits start this many seconds before the end
    credits_key: str = ""            # where a credits mark is stored: the series folder, or the file
    poster: Path | None = None
    fanart: Path | None = None


# ------------------------------------------------------------------ windows and Windows APIs

class BlackWindow(QRasterWindow):
    """A black native window: the video surface (mpv / VLC draw into it), or a blackout on another monitor.
    The video window reports its moves and resizes (so the HUD follows it), its close button (stop), and hands
    keyboard focus to the HUD, which owns all input."""
    on_geometry = None
    on_close = None
    on_focus = None

    def paintEvent(self, _event):
        # QWindow has no rect(): fill by width and height. Any error must still end the painter, or Qt's backing
        # store stays mid-paint and the window freezes (the stuck black picture-in-picture box) or the app crashes.
        painter = QPainter(self)
        try:
            painter.fillRect(0, 0, self.width(), self.height(), QColor(0, 0, 0))
        finally:
            painter.end()

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.on_geometry:
            self.on_geometry()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.on_geometry:
            self.on_geometry()

    def closeEvent(self, e):
        if self.on_close:
            self.on_close()
        super().closeEvent(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        if self.on_focus:
            self.on_focus()


def _black_window(screen, passive: bool) -> BlackWindow:
    w = BlackWindow()
    flags = Qt.FramelessWindowHint
    if passive:  # blackout: on top, no focus, mouse falls through
        flags |= Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
    w.setFlags(flags)
    w.setScreen(screen)
    w.setGeometry(screen.geometry())
    return w


_ES_CONTINUOUS, _ES_SYSTEM, _ES_DISPLAY = 0x80000000, 0x1, 0x2


def keep_awake(on: bool) -> None:
    """SetThreadExecutionState. Always called from the GUI thread, which owns the flag."""
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(
            ctypes.c_uint(_ES_CONTINUOUS | ((_ES_SYSTEM | _ES_DISPLAY) if on else 0)))


# ------------------------------------------------------------------ playback cores (non-blocking)
# Both expose: load, ready, state, pos, dur, playing, set_paused, seek, tracks, set_sub, set_audio,
# chapters, frame, set_night, set_level, set_vf, set_shrink, close.   state(): playing | eof | closed

class MpvCore:
    name = "mpv"

    def __init__(self, wid: int, level: int, rtx: bool, night: bool, hdr: dict | None = None):
        import mpv
        self.rtx = rtx
        opts = hw.mpv_options(level, rtx, hdr_display=bool(hdr and hdr.get("mode") == "display"))
        self._vf = opts.pop("vf", None)
        self.d3d = bool(self._vf)  # level 3 needs the d3d11 surface chosen at start
        self.level = 3 if self.d3d else (2 if opts["scale"] == "spline36" else 1)
        self.p = mpv.MPV(wid=str(wid), input_default_bindings=False, input_vo_keyboard=False, osc=False,
                         osd_level=0, keep_open="yes", cursor_autohide="no", **opts)
        self._seek_to = None
        self.next_vo = opts["vo"] == "gpu-next"
        if night:
            self.set_night(True)
        if hdr:
            self.set_hdr(hdr)

    def load(self, path, start, vf):
        self.p.vf = vf or (self._vf if self.level == 3 else "")  # d3d11vpp cannot sit behind software filters
        self.p.play(str(path))
        self._seek_to = start or None

    def ready(self):  # resume seek: applied once the file reports a duration
        if self._seek_to is not None and self.dur() > 0:
            self.p.command("seek", self._seek_to, "absolute")
            self._seek_to = None

    def state(self):
        try:
            return "eof" if self.p.eof_reached else "playing"
        except Exception:  # ShutdownError when mpv went away
            return "closed"

    def pos(self):
        try:
            return float(self.p.time_pos or 0)
        except Exception:
            return 0.0

    def dur(self):
        try:
            return float(self.p.duration or 0)
        except Exception:
            return 0.0

    def playing(self):
        try:
            return not self.p.pause
        except Exception:
            return False

    def set_paused(self, paused):
        self.p.pause = bool(paused)

    def seek(self, t, relative=False):
        self.p.command("seek", t, "relative" if relative else "absolute")

    def tracks(self, kind):
        found = [t for t in (self.p.track_list or []) if t.get("type") == kind]
        out = [{"id": t["id"], "title": t.get("title") or t.get("lang") or f"Track {t['id']}",
                "on": bool(t.get("selected"))} for t in found]
        if kind == "sub":
            out.insert(0, {"id": 0, "title": "Off", "on": not any(t["on"] for t in out)})
        return out

    def set_sub(self, track_id):
        self.p.sid = track_id if track_id else "no"

    def add_sub(self, path: str):
        self.p.command("sub-add", path, "select")

    def set_audio(self, track_id):
        self.p.aid = track_id

    def set_video(self, track_id):
        self.p.vid = track_id

    def set_volume(self, v):
        self.p.volume = v

    def set_speed(self, x):
        self.p.speed = x

    def set_sub_style(self, scale, pos, box):
        self.p.sub_scale = scale
        self.p.sub_pos = int(pos)
        self.p.sub_border_style = "opaque-box" if box else "outline-and-shadow"
        self.p.sub_back_color = "#B3000000"

    def set_sub_delay(self, seconds):
        self.p.sub_delay = seconds

    def set_audio_delay(self, seconds):
        self.p.audio_delay = seconds

    def hdr_kind(self):
        """HDR10 (PQ) or HLG for the playing video, "" for SDR. Dolby Vision files report PQ and show as HDR10."""
        try:
            params = self.p.video_params or {}
        except Exception:
            return ""
        if not params:
            return None   # not decoded yet: ask again on the next tick
        return {"pq": "HDR10", "hlg": "HLG"}.get(params.get("gamma", ""), "")

    def set_hdr(self, hdr: dict):
        """tonemap: fit HDR into an SDR screen (per-scene peak detection, chosen brightness).
        display: send HDR to an HDR screen untouched (needs gpu-next, chosen when the player starts)."""
        display = hdr.get("mode") == "display"
        if display and not self.next_vo:
            return "HDR screen mode starts with the next video"
        p = self.p
        p.target_colorspace_hint = "yes" if display else "no"
        p.tone_mapping = "auto" if self.next_vo else "bt.2390"
        p.hdr_compute_peak = "yes" if hdr.get("scene", True) else "no"
        peak = int(hdr.get("peak") or 0)
        p.target_peak = str(peak) if peak and not display else "auto"
        return ""

    def chapters(self):
        return list(self.p.chapter_list or [])

    def frame(self):
        return self.p.screenshot_raw()

    def set_night(self, on):
        self.p.af = hw.MPV_NIGHT_FILTER if on else ""

    def set_level(self, n):
        if n == 3 and not self.d3d:
            return "AI Ultra needs an RTX GPU and level 3 chosen in Settings before playback starts"
        o = hw.mpv_options(n, self.rtx)
        self.p.scale, self.p.cscale = o["scale"], o["cscale"]
        self.p.glsl_shaders = o.get("glsl_shaders", "")
        self.level = n
        return f"Upscaling: {hw.LEVEL_NAMES[n]}"

    def set_vf(self, vf):
        self.p.vf = vf or ""

    def set_shrink(self, s):
        """0 = full window, 1 = small picture in the bottom-right corner (zoom is log2)."""
        p = self.p
        p.video_zoom = -1.9 * s
        p.video_align_x = s
        p.video_align_y = s
        p.video_margin_ratio_right = 0.02 * s
        p.video_margin_ratio_bottom = 0.03 * s

    def close(self):
        try:
            self.p.terminate()
        except Exception:
            log.debug("mpv terminate failed", exc_info=True)


class VlcCore:
    """Low-power core. Night mode re-opens the file at the same position (libvlc cannot toggle
    filters live). Upscaling levels and the shrinking corner picture are MPV-only."""
    name = "vlc"
    level = 1
    d3d = False

    def __init__(self, hwnd: int, night: bool):
        import vlc
        self.vlc, self._night, self._path = vlc, night, None
        self.inst = vlc.Instance(*hw.vlc_args(night))
        self.mp = self.inst.media_player_new()
        self.mp.set_hwnd(hwnd)
        self.mp.video_set_mouse_input(False)
        self.mp.video_set_key_input(False)
        self._seek_to = None
        self._volume = None

    def load(self, path, start, vf=None):
        self._path = str(path)
        media = self.inst.media_new(self._path)
        if self._night:
            media.add_option(":audio-filter=compressor")
        self.mp.set_media(media)
        self.mp.play()
        self._seek_to = start or None

    def ready(self):
        if self._volume is not None and self.mp.get_state() == self.vlc.State.Playing:
            self.mp.audio_set_volume(self._volume)
            self._volume = None
        if self._seek_to is not None and self.dur() > 0 and self.mp.get_state() == self.vlc.State.Playing:
            self.mp.set_time(int(self._seek_to * 1000))
            self._seek_to = None

    def state(self):
        s, S = self.mp.get_state(), self.vlc.State
        if s == S.Ended:
            return "eof"
        return "closed" if s in (S.Stopped, S.Error) else "playing"

    def pos(self):
        return max(self.mp.get_time(), 0) / 1000

    def dur(self):
        return max(self.mp.get_length(), 0) / 1000

    def playing(self):
        return bool(self.mp.is_playing())

    def set_paused(self, paused):
        self.mp.set_pause(1 if paused else 0)

    def seek(self, t, relative=False):
        self.mp.set_time(int((self.pos() + t if relative else t) * 1000))

    def _described(self, items, current, off_label=None):
        out = [{"id": i, "title": (n.decode("utf-8", "ignore") if isinstance(n, bytes) else str(n)), "on": i == current}
               for i, n in (items or []) if i != -1]
        if off_label:
            out.insert(0, {"id": 0, "title": off_label, "on": current in (-1, 0)})
        return out

    def tracks(self, kind):
        if kind == "sub":
            return self._described(self.mp.video_get_spu_description(), self.mp.video_get_spu(), "Off")
        if kind == "video":
            return self._described(self.mp.video_get_track_description(), self.mp.video_get_track())
        return self._described(self.mp.audio_get_track_description(), self.mp.audio_get_track())

    def set_sub(self, track_id):
        self.mp.video_set_spu(track_id if track_id else -1)

    def add_sub(self, path: str):
        import vlc
        self.mp.add_slave(vlc.MediaSlaveType.subtitle, Path(path).as_uri(), True)

    def set_audio(self, track_id):
        self.mp.audio_set_track(track_id)

    def set_video(self, track_id):
        self.mp.video_set_track(track_id)

    def set_speed(self, x):
        self.mp.set_rate(x)

    def set_sub_style(self, scale, pos, box):
        pass  # libvlc fixes subtitle styling when the player is created; timing still works

    def set_sub_delay(self, seconds):
        self.mp.video_set_spu_delay(int(seconds * 1_000_000))

    def set_audio_delay(self, seconds):
        self.mp.audio_set_delay(int(seconds * 1_000_000))

    def hdr_kind(self) -> str:
        return ""   # libvlc does not report the transfer function; it tone-maps on its own

    def set_hdr(self, hdr: dict):
        return "HDR options need the MPV core"

    def set_volume(self, v):
        self._volume = int(v)
        self.mp.audio_set_volume(self._volume)  # ignored until audio starts; ready() applies it again

    def chapters(self):
        return []

    def frame(self):
        from PIL import Image
        fd, name = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            self.mp.video_take_snapshot(0, name, 0, 0)
            time.sleep(0.3)
            with Image.open(name) as im:
                return im.copy()
        finally:
            os.unlink(name)

    def set_night(self, on):
        self._night = on
        if self._path:
            self.load(self._path, self.pos(), None)

    def set_level(self, n):
        return "Upscaling levels need the MPV core (dedicated GPU)"

    def set_vf(self, vf):
        pass

    def set_shrink(self, s):
        pass

    def close(self):
        for fn in (self.mp.stop, self.mp.release, self.inst.release):
            try:
                fn()
            except Exception:
                log.debug("vlc close step failed", exc_info=True)


# ------------------------------------------------------------------ engine

class PlayerEngine(QObject):
    """Exposed to QML as `Player`. `state` is one map the HUD binds to (refreshed every tick)."""
    stateChanged = Signal()
    closed = Signal()
    error = Signal(str)
    artChanged = Signal(str)
    pipChanged = Signal(bool)

    def __init__(self, resolve: Callable[[str], Session], frames, parent=None):
        """frames: ui.dvd_box.FrameProvider; resolve(path) -> Session comes from the app."""
        super().__init__(parent)
        self.resolve, self.frames = resolve, frames
        self.on_progress = None     # (session, pos, dur, completed, watched_seconds)
        self.on_mark_intro = None   # (session, start, end)
        self.on_mark_credits = None  # (session, seconds_before_end)
        self.on_setting = None      # (key, value): the app saves player preferences
        self.speed = 1.0
        self.sub = {"scale": 1.0, "pos": 100, "box": False}   # restored from settings by the app
        self.sub_delay = 0.0        # per file
        self.blackout = True        # black out the other monitors while playing (HUD button, remembered)
        self.fullscreen = False     # the theater opens as a window; F / double-click / HUD button go full screen
        self.player_geo = None      # QRect of the theater window last time (remembered by the app)
        self.hud = None             # the HUD's QQuickWindow, set by the app once QML is loaded
        self.audio_delay = 0.0      # lip sync: kept from file to file (it belongs to the speakers / headphones)
        self.hdr = {"mode": "tonemap", "peak": 0, "scene": True}   # restored from settings by the app
        self.auto_credits = True    # series: the next-episode countdown starts where the credits start
        self.pip = False
        self._full_geo = None
        self.hw = hw.detect()
        self.level, self.night = self.hw.level, False
        self.volume = 100           # 0..100, kept from file to file for this run
        self.core_pref = "auto"     # Settings: "auto" (what detect() recommends), "mpv" or "vlc"
        self.screen = None
        self.session: Session | None = None
        self.core = None
        self.win = None
        self.blackouts: list = []
        self._state = {"active": False}
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._tick)
        self._shrink = QVariantAnimation(self)
        self._shrink.setDuration(350)
        self._shrink.setEasingCurve(QEasingCurve.OutCubic)
        self._shrink.valueChanged.connect(self._on_shrink)
        self._reset_file_state()
        self._toast = (0, "")
        self._vr = None
        self._vr_view = "left"
        self._snap = None
        self._snap_kind = ""
        self._snap_id = 0
        self._snap_was_playing = False
        self._screen_geo = None
        self._tracks = ([], [], [])
        self._tracks_at = 0.0

    @Property("QVariantMap", notify=stateChanged)
    def state(self):
        return self._state

    @property
    def running(self) -> bool:
        return self.core is not None

    def _reset_file_state(self):
        self._go_next = False
        self._mark_start = None
        self._chapters_checked = False
        self._loaded_at = time.monotonic()
        self._last_tick = 0.0
        self._last_save = time.monotonic()
        self._acc = 0.0
        self._pos = self._dur = 0.0
        self._shrink_to = 0.0
        self._shrunk = 0.0
        self._credits_at = None
        self._in_credits = False
        self._hdr_seen = None

    # -- start / stop
    @Slot(str)
    def play(self, path: str):
        if self.core:  # a second file was opened while playing: switch inside the same window
            self._save()
            self._open(path)
        else:
            self._start(path)

    def _window_geometry(self, screen):
        """Where the theater window opens: where it was last time if that is still on a screen, else centred over
        most of the screen Media Vault is on."""
        g = self.player_geo
        if g and g.width() >= 480 and any(sc.availableGeometry().intersects(g) for sc in QGuiApplication.screens()):
            return g
        a = screen.availableGeometry()
        w, h = int(a.width() * 0.8), int(a.height() * 0.8)
        return QRect(a.x() + (a.width() - w) // 2, a.y() + (a.height() - h) // 2, w, h)

    def _start(self, path):
        screen = self.screen or QGuiApplication.primaryScreen()
        self.win = BlackWindow()
        self.win.setTitle("Media Vault")
        self.win.setScreen(screen)
        self.win.setMinimumSize(QSize(480, 270))
        self.win.setGeometry(self._window_geometry(screen))
        self.win.on_geometry = self._sync_geometry
        self.win.on_close = lambda: QTimer.singleShot(0, self.stop)     # the window's own close button
        self.win.on_focus = self._focus_hud
        self.fullscreen = False
        self.win.show()                       # a window first; F, a double-click or the HUD button go full screen
        wid = int(self.win.winId())
        if self.hud is not None:
            self.hud.setTransientParent(self.win)   # owned by the video window: always above it, never behind
        self.blackouts = []
        for other in QGuiApplication.screens():
            if other is not screen:
                b = _black_window(other, passive=True)
                if self.blackout:
                    b.show()
                self.blackouts.append(b)
        try:
            self.core = self._make_core(wid)
        except Exception as e:
            self._teardown()
            self.error.emit(str(e))
            return
        self._screen_geo = self.win.geometry()
        if not self._open(path):
            self.stop()
            return
        self._timer.start()
        self._raise_hud()

    def _make_core(self, wid):
        first = hw.resolve(self.core_pref, self.hw.backend)
        other = "vlc" if first == "mpv" else "mpv"
        errors = []
        for name in (first, other):  # the other core is the fallback if the first will not start
            try:
                if name == "mpv":
                    return MpvCore(wid, self.level, self.hw.rtx, self.night, self.hdr)
                return VlcCore(wid, self.night)
            except Exception as e:  # missing DLL, bad option
                errors.append(f"{name}: {e}")
                log.warning("%s core unavailable", name, exc_info=True)
        raise RuntimeError("Neither libmpv nor libvlc could be loaded. " + "; ".join(errors))

    def _open(self, path) -> bool:
        s = self.resolve(path)
        if s is None:
            return False
        self._shrink.stop()
        self.core.set_shrink(0)
        self._reset_file_state()
        self.session = s
        self._vr = vr_detector.detect(s.path)
        self._vr_view = "left"
        vf = vr_detector.mpv_filter(self._vr) if self.core.name == "mpv" else None
        self.core.load(s.path, s.start, vf)
        self._apply_volume()
        self.sub_delay = 0.0
        self._credits_at = None
        for apply in (lambda: self.core.set_speed(self.speed), lambda: self.core.set_sub_delay(0.0),
                      lambda: self.core.set_audio_delay(self.audio_delay),
                      lambda: self.core.set_sub_style(self.sub["scale"], self.sub["pos"], self.sub["box"])):
            try:
                apply()
            except Exception:
                log.debug("player option not applied", exc_info=True)
        return True

    def _apply_volume(self):
        try:
            self.core.set_volume(self.volume)
        except Exception:  # VLC refuses volume until its audio output exists; the next change retries
            log.debug("volume not applied yet", exc_info=True)

    @Slot()
    def stop(self):
        if not self.core and not self.win:
            return
        if self.player_geo and self.on_setting:
            g = self.player_geo
            self.on_setting("player_geometry", f"{g.x()},{g.y()},{g.width()},{g.height()}")
        self._timer.stop()
        self._save(final=True)
        self._teardown()
        self.session = None
        self.pip = False
        self._state = {"active": False}
        self.stateChanged.emit()
        self.closed.emit()

    def _teardown(self):
        keep_awake(False)
        if self.core:
            self.core.close()
            self.core = None
        if self.win:
            self.win.on_close = self.win.on_geometry = self.win.on_focus = None
        if self.hud is not None:
            self.hud.setTransientParent(None)
        for w in [self.win, *self.blackouts]:
            if w:
                w.close()
        self.win, self.blackouts = None, []
        self.fullscreen = False

    # -- tick
    def _tick(self):
        c, s = self.core, self.session
        if not c or not s:
            return
        state = c.state()
        if state == "closed":
            return self.stop()
        c.ready()
        pos, dur, playing = c.pos(), c.dur(), c.playing()
        self._pos, self._dur = pos, dur
        now = time.monotonic()
        if playing and self._last_tick:
            self._acc += min(now - self._last_tick, 1.0)  # time really spent playing
        self._last_tick = now
        keep_awake(playing)
        if dur == 0 and now - self._loaded_at > 20:
            self.error.emit(f"Could not play {os.path.basename(s.path)}")
            return self.stop()
        if dur and not self._chapters_checked:
            self._intro_from_chapters()
        left = dur - pos
        # credits: once they start, a series counts down into the next episode right away
        credits_start = dur - s.credits if (s.credits and dur > s.credits) else None
        in_credits = credits_start is not None and pos >= credits_start
        if in_credits and self._credits_at is None:
            self._credits_at = now
        elif credits_start is not None and pos < credits_start - 2:
            self._credits_at = None          # seeked back out of the credits
        credit_count = None
        if s.next_path and self.auto_credits and self._credits_at is not None:
            credit_count = COUNTDOWN - (now - self._credits_at)
            if credit_count <= 0:
                self._go_next = True
        end_count = left if (dur > 2 * COUNTDOWN and 0 < left <= COUNTDOWN) else None
        counting = bool(s.next_path and (credit_count is not None or end_count is not None))
        remaining = min(x for x in (credit_count, end_count) if x is not None) if counting else 0
        self._in_credits = in_credits
        self._animate_shrink(1.0 if counting else 0.0)
        if state == "eof" or (self._go_next and s.next_path):
            self._save(done=state == "eof")
            if not s.next_path or not self._open(s.next_path):
                return self.stop()
            return
        self._go_next = False
        if now - self._last_save >= 5:
            self._save()
        self._publish(pos, dur, playing, int(max(0, remaining)) + 1 if counting else 0)

    def _animate_shrink(self, target):
        if target != self._shrink_to:
            self._shrink_to = target
            self._shrink.stop()
            self._shrink.setStartValue(float(self._shrunk))
            self._shrink.setEndValue(float(target))
            self._shrink.start()

    def _on_shrink(self, value):
        self._shrunk = float(value)
        if self.core:
            self.core.set_shrink(self._shrunk)

    def _intro_from_chapters(self):
        """Auto skip: a chapter called Intro / Opening / Recap becomes this folder's skip bookmark, and one
        called Credits / Ending / Outro (in the second half) marks where the credits start."""
        self._chapters_checked = True
        s = self.session
        chapters = self.core.chapters()
        if not s.credits:
            for ch in chapters:
                start = float(ch.get("time") or 0)
                if _CREDITS_CHAPTER.match(ch.get("title") or "") and self._dur * 0.5 < start < self._dur - 5:
                    s.credits = self._dur - start
                    if self.on_mark_credits:
                        self.on_mark_credits(s, s.credits)
                    break
        if s.intro:
            return
        for i, ch in enumerate(chapters[:-1]):
            start, end = float(ch.get("time") or 0), float(chapters[i + 1].get("time") or 0)
            if _INTRO_CHAPTER.match(ch.get("title") or "") and 10 <= end - start <= 300:
                s.intro = (start, end)
                if self.on_mark_intro:
                    self.on_mark_intro(s, start, end)
                return

    def _save(self, done=False, final=False):
        s = self.session
        if s and self.on_progress:
            try:
                credits = s.credits and self._dur > s.credits and self._pos >= self._dur - s.credits
                completed = done or bool(credits) or (self._dur > 0 and self._dur - self._pos <= COUNTDOWN)
                self.on_progress(s, self._pos, self._dur, completed, self._acc)
            except Exception:
                log.exception("saving progress failed")
        self._acc = 0.0
        self._last_save = time.monotonic()

    def _publish(self, pos, dur, playing, countdown):
        s, c, now = self.session, self.core, time.monotonic()
        if now - self._tracks_at > 2:
            try:
                self._tracks = (c.tracks("sub"), c.tracks("audio"), c.tracks("video"))
            except Exception:
                log.debug("track list failed", exc_info=True)
            self._tracks_at = now
        g = self._screen_geo
        intro = bool(s.intro and s.intro[0] <= pos < s.intro[1] - 1)
        self._state = {
            "active": True, "x": g.x(), "y": g.y(), "w": g.width(), "h": g.height(),
            "title": s.title, "position": pos, "duration": dur, "paused": not playing,
            "subs": self._tracks[0], "audio": self._tracks[1], "video": self._tracks[2],
            "night": self.night, "core": c.name, "level": c.level, "levelNames": hw.LEVEL_NAMES, "volume": self.volume,
            "speed": self.speed, "subScale": self.sub["scale"], "subPos": self.sub["pos"], "subBox": self.sub["box"],
            "subDelay": self.sub_delay, "subStyleOk": c.name == "mpv", "pip": self.pip,
            "audioDelay": self.audio_delay, "blackout": self.blackout, "screens": len(self.blackouts) + 1,
            "fullscreen": self.fullscreen, "hdr": self._hdr_kind(), "hdrMode": self.hdr["mode"],
            "hdrPeak": self.hdr["peak"], "hdrScene": self.hdr["scene"], "hdrOk": c.name == "mpv",
            "creditsActive": bool(self._in_credits and not s.next_path), "hasCredits": bool(s.credits),
            "introActive": intro, "autoplayLeft": countdown, "nextTitle": s.next_title,
            "shrink": self._shrunk, "vr": self._vr is not None and c.name == "mpv", "vrView": self._vr_view,
            "toastId": self._toast[0], "toast": self._toast[1],
            "snapshot": self._snap_kind, "snapId": self._snap_id,
        }
        self.stateChanged.emit()

    def _say(self, text):
        self._toast = (self._toast[0] + 1, text)

    # -- slots called by Hud.qml
    @Slot()
    def togglePause(self):
        if self.core:
            self.core.set_paused(self.core.playing())

    @Slot(float)
    def seekTo(self, seconds: float):
        if self.core:
            self.core.seek(max(0.0, seconds))

    @Slot(float)
    def seekBy(self, seconds: float):
        if self.core:
            self.core.seek(seconds, relative=True)

    _subReady = Signal(str, str)          # path, message: from the search thread back to the player's thread

    @Slot()
    def findSubtitles(self):
        """Search OpenSubtitles for the video that is playing, take the most downloaded match in your language and
        switch it on."""
        import threading

        import database as db
        from utils import scraper, subtitles
        s = self.session
        if not (self.core and s):
            return
        key = db.get_setting("opensubtitles_key", "") or ""
        if not key:
            self._say("Add a free OpenSubtitles API key in Settings \u203A Integrations & APIs")
            self.stateChanged.emit()
            return
        lang = (db.get_setting("subtitle_language", "en") or "en").strip().lower()
        item = db.get_media(s.uuid) if s.uuid else None
        show = bool(item) and item["media_type"] == "show"
        title = (db.series_title(item["title"]) if show else item["title"]) if item else scraper.clean_name(s.path).title
        se = scraper.season_episode(item["title"]) if show else None
        dest = Path(s.path).parent / scraper.ASSET_DIR / f"{Path(s.path).stem}.{lang}.srt"
        if not getattr(self, "_sub_wired", False):
            self._subReady.connect(self._sub_ready)
            self._sub_wired = True
        self._say("Looking for subtitles\u2026")
        self.stateChanged.emit()

        def work():
            try:
                found = subtitles.search(key, title, lang, item.get("tmdb_id") if item else None,
                                         se[0] if se else None, se[1] if se else None, show)
                if not found and item and item.get("tmdb_id"):       # not filed under the id: by name
                    found = subtitles.search(key, title, lang, None, se[0] if se else None, se[1] if se else None, show)
                if not found:
                    self._subReady.emit("", f"No {lang.upper()} subtitles found for this title")
                    return
                subtitles.download(key, found[0]["file_id"], dest)
                self._subReady.emit(str(dest), "Subtitles added" + (f": {found[0]['release'][:60]}" if found[0]["release"] else ""))
            except Exception as e:
                self._subReady.emit("", str(e) if isinstance(e, subtitles.SubtitleError) else "Could not get subtitles")
        threading.Thread(target=work, daemon=True, name="subtitles").start()

    def _sub_ready(self, path: str, message: str):
        if path and self.core and self.session and Path(path).stem.startswith(Path(self.session.path).stem):
            try:
                self.core.add_sub(path)
                self._tracks_at = 0
            except Exception:
                logging.getLogger(__name__).exception("adding subtitles")
                message = "The subtitles were downloaded but could not be switched on"
        self._say(message)
        self.stateChanged.emit()

    @Slot(int)
    def setSub(self, track_id: int):
        if self.core:
            self.core.set_sub(track_id)
            self._tracks_at = 0

    @Slot(int)
    def setAudio(self, track_id: int):
        if self.core:
            self.core.set_audio(track_id)
            self._tracks_at = 0

    @Slot(int)
    def setVideo(self, track_id: int):
        if self.core:
            self.core.set_video(track_id)
            self._tracks_at = 0

    @Slot(int)
    def setVolume(self, volume: int):
        """0..100. The HUD shows the new value itself at once; this only applies it."""
        self.volume = max(0, min(100, int(volume)))
        if self.core:
            self._apply_volume()

    @Slot()
    def toggleNight(self):
        if self.core:
            self.night = not self.night
            self.core.set_night(self.night)
            self._say("Reduce loud sounds: " + ("ON" if self.night else "OFF"))

    @Slot(int)
    def setLevel(self, level: int):
        if self.core:
            self._say(self.core.set_level(level))

    @Slot()
    def cycleVrView(self):
        if self.core and self._vr and self.core.name == "mpv":
            self._vr_view = vr_detector.VIEWS[(vr_detector.VIEWS.index(self._vr_view) + 1) % 2]
            self.core.set_vf(vr_detector.mpv_filter(self._vr, self._vr_view))
            self._say("VR view: " + ("both eyes side by side" if self._vr_view == "sbs" else "left eye, flat"))

    @Slot()
    def skipIntro(self):
        s = self.session
        if self.core and s and s.intro and s.intro[0] <= self._pos < s.intro[1]:
            self.core.seek(s.intro[1])

    @Slot()
    def nextNow(self):
        s = self.session
        if s and s.next_path and (0 < self._dur - self._pos <= COUNTDOWN or self._credits_at is not None):
            self._go_next = True

    @Slot()
    def markIntro(self):
        if not self.core:
            return
        if self._mark_start is None:
            self._mark_start = self._pos
            self._say("Intro start marked. Press I again where the intro ends.")
        elif self._pos > self._mark_start:
            self.session.intro = (self._mark_start, self._pos)
            if self.on_mark_intro:
                self.on_mark_intro(self.session, self._mark_start, self._pos)
            self._mark_start = None
            self._say("Intro saved for this folder")

    @Slot()
    def markCredits(self):
        """O: the credits start here. Saved for the whole series folder (or this film)."""
        s = self.session
        if not (self.core and s and self._dur > 0 and self._pos > self._dur * 0.3):
            self._say("Mark the credits where they start, near the end")
            return
        s.credits = self._dur - self._pos
        self._credits_at = time.monotonic()
        if self.on_mark_credits:
            self.on_mark_credits(s, s.credits)
        self._say("Credits marked" + (" for this series" if s.next_path else ""))

    @Slot()
    def finishNow(self):
        """Skip Credits on a film (no next episode): counts as watched and ends playback."""
        if self.session:
            self._save(done=True)
            self.stop()

    @Slot(float)
    def setSpeed(self, x: float):
        self.speed = round(max(SPEEDS[0], min(SPEEDS[1], float(x))), 2)
        if self.core:
            self.core.set_speed(self.speed)

    @Slot(float, int, bool)
    def setSubStyle(self, scale: float, pos: int, box: bool):
        self.sub = {"scale": round(max(0.5, min(2.5, float(scale))), 2), "pos": max(0, min(100, int(pos))), "box": bool(box)}
        if self.core:
            self.core.set_sub_style(self.sub["scale"], self.sub["pos"], self.sub["box"])
        if self.on_setting:
            self.on_setting("sub_style", f'{self.sub["scale"]},{self.sub["pos"]},{int(self.sub["box"])}')

    @Slot(float)
    def setSubDelay(self, seconds: float):
        self.sub_delay = round(max(-30.0, min(30.0, float(seconds))), 2)
        if self.core:
            self.core.set_sub_delay(self.sub_delay)

    @Slot()
    def toggleBlackout(self):
        """Black out every other monitor while playing, or leave them as they are. Remembered for next time."""
        self.blackout = not self.blackout
        if not self.pip:
            for b in self.blackouts:
                b.setVisible(self.blackout)
        self._say("Other screens blacked out" if self.blackout else "Other screens left on")
        if self.on_setting:
            self.on_setting("blackout", "1" if self.blackout else "0")

    @Slot(float)
    def setAudioDelay(self, seconds: float):
        self.audio_delay = round(max(-5.0, min(5.0, float(seconds))), 3)
        if self.core:
            self.core.set_audio_delay(self.audio_delay)
        if self.on_setting:
            self.on_setting("audio_delay", str(self.audio_delay))

    def _hdr_kind(self) -> str:
        if self._hdr_seen is None and self._dur > 0:
            self._hdr_seen = self.core.hdr_kind()
        return self._hdr_seen or ""

    @Slot(str, int, bool)
    def setHdr(self, mode: str, peak: int, scene: bool):
        self.hdr = {"mode": mode if mode in ("tonemap", "display") else "tonemap",
                    "peak": max(0, min(1000, int(peak))), "scene": bool(scene)}
        if self.core:
            note = self.core.set_hdr(self.hdr)
            if note:
                self._say(note)
        if self.on_setting:
            self.on_setting("hdr", f'{self.hdr["mode"]},{self.hdr["peak"]},{int(self.hdr["scene"])}')

    # -- the theater window: full screen, picture in picture, and the HUD laid over it
    def _focus_hud(self):
        if self.hud is not None:
            self.hud.requestActivate()

    def _raise_hud(self):
        """After the video window is shown again (new flags, full screen, PiP) it must not cover the HUD."""
        if self.hud is not None and self.win is not None:
            QTimer.singleShot(0, lambda: self.hud and self.hud.raise_())
            QTimer.singleShot(0, self._focus_hud)

    def _sync_geometry(self):
        """The video window moved or was resized: the HUD follows at once (not on the next tick)."""
        if not self.win:
            return
        g = self.win.geometry()
        if g == self._screen_geo:
            return
        self._screen_geo = g
        if not (self.pip or self.fullscreen) and self.win.isVisible():
            self.player_geo = QRect(g)
        if self._state.get("active"):
            self._state = {**self._state, "x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()}
            self.stateChanged.emit()

    @Slot()
    def toggleFullscreen(self):
        if not self.win or self.pip:
            return
        if self.fullscreen:
            self.win.showNormal()
            if self.player_geo:
                self.win.setGeometry(self.player_geo)
            self.fullscreen = False
        else:
            screen = self.win.screen() or QGuiApplication.primaryScreen()
            self.player_geo = self.win.geometry()
            self.win.showFullScreen()
            self.win.setGeometry(screen.geometry())
            self.fullscreen = True
        self._sync_geometry()
        self._state = {**self._state, "fullscreen": self.fullscreen}
        self.stateChanged.emit()
        self._raise_hud()

    @Slot()
    def togglePip(self):
        """Picture in picture: the video becomes a small always-on-top window in the corner, Media Vault
        minimises, and the HUD shows Back, Play / Pause, Skip and PiP (return). Again (or Esc) returns to the theater."""
        if not self.win:
            return
        screen = self.win.screen() or QGuiApplication.primaryScreen()
        if not self.pip:
            self._was_full = self.fullscreen
            if not self.fullscreen:
                self.player_geo = self.win.geometry()
            avail = screen.availableGeometry()
            w = max(360, int(avail.width() * 0.26))
            h = int(w * 9 / 16)
            self.pip = True
            self.fullscreen = False
            self.win.showNormal()
            self.win.setFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
            self.win.setGeometry(avail.right() - w - 24, avail.bottom() - h - 24, w, h)
            self.win.show()
            for b in self.blackouts:
                b.hide()
            self.pipChanged.emit(True)
        else:
            self.pip = False
            self.win.setFlags(Qt.Window)            # a normal window again: title bar, move, resize, close
            if getattr(self, "_was_full", False):
                self.win.showFullScreen()
                self.win.setGeometry(screen.geometry())
                self.fullscreen = True
            else:
                self.win.setGeometry(self._window_geometry(screen))
                self.win.showNormal()
            for b in self.blackouts:
                b.setVisible(self.blackout)
            self.pipChanged.emit(False)
        self._screen_geo = None
        self._sync_geometry()
        self._state = {**self._state, "pip": self.pip, "fullscreen": self.fullscreen}
        self.stateChanged.emit()
        self._raise_hud()

    @Slot(int, int)
    def movePip(self, dx: int, dy: int):
        """Drag the picture-in-picture window (kept on its screen); the HUD moves with it."""
        if not (self.pip and self.win):
            return
        avail = (self.win.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        g = self.win.geometry()
        x = max(avail.left(), min(avail.right() - g.width(), g.x() + dx))
        y = max(avail.top(), min(avail.bottom() - g.height(), g.y() + dy))
        self.win.setPosition(x, y)
        self._sync_geometry()

    # -- snapshot -> crop canvas -> box art / fanart
    @Slot(str)
    def captureFrame(self, kind: str):
        if not self.core or kind not in ("poster", "fanart"):
            return
        try:
            self._snap = self.core.frame()
        except Exception:
            log.exception("frame grab failed")
            self._say("Snapshot failed")
            return
        self._snap_was_playing = self.core.playing()
        self.core.set_paused(True)
        self.frames.set_pil("snap", self._snap)
        self._snap_kind, self._snap_id = kind, self._snap_id + 1

    @Slot(str, float, float, float, float)
    def saveSnapshot(self, kind: str, x: float, y: float, w: float, h: float):
        """x, y, w, h are fractions (0..1) of the captured frame."""
        s, img = self.session, self._snap
        if not (s and img):
            return
        try:
            W, H = img.size
            box = (int(max(0, x) * W), int(max(0, y) * H), int(min(1, x + w) * W), int(min(1, y + h) * H))
            crop = img.crop(box)
            if kind == "fanart":
                scraper.save_webp(crop, s.fanart, box=scraper.FANART_BOX)
            else:
                scraper.save_webp(crop, s.poster)
                s.poster.with_suffix(".front.webp").unlink(missing_ok=True)  # custom box art: the newest choice wins
            self._say("Fanart updated" if kind == "fanart" else "Box art updated")
            self.artChanged.emit(s.path)
        except Exception:
            log.exception("saving snapshot failed")
            self._say("Could not save the image")
        self.cancelSnapshot()

    @Slot()
    def cancelSnapshot(self):
        self._snap, self._snap_kind = None, ""
        self.frames.clear("snap")
        if self.core and getattr(self, "_snap_was_playing", False):
            self.core.set_paused(False)
