"""Read-only media facts and raw frames, from a windowless libmpv (vo=null).

Not in the spec's file tree: probe and thumbnail grabber share one headless
player, so they live here instead of being written twice.
"""
import logging
import time
from pathlib import Path

import utils  # noqa: F401  (puts bin/ on PATH before libmpv is loaded)

log = logging.getLogger(__name__)

_CODECS = {"h264": "H.264", "hevc": "HEVC", "av1": "AV1", "vp9": "VP9", "mpeg4": "MPEG-4",
           "mpeg2video": "MPEG-2", "vc1": "VC-1", "wmv3": "WMV"}
FRACTIONS = (0.10, 0.30, 0.50, 0.70)  # avoids dark intro and credits


def resolution_label(w: int, h: int) -> str | None:
    if not h:
        return None
    if w >= 3600 or h >= 2000:
        return "4K"
    if w >= 2500 or h >= 1400:
        return "1440p"
    if w >= 1800 or h >= 1000:
        return "1080p"
    if w >= 1200 or h >= 700:
        return "720p"
    return f"{h}p"


def channel_label(raw: str) -> str:
    raw = (raw or "").lower()
    for key, label in (("7.1", "7.1"), ("5.1", "5.1"), ("stereo", "Stereo"), ("mono", "Mono")):
        if raw.startswith(key):
            return label
    return raw


class HeadlessPlayer:
    """libmpv with no window and no sound. Reusable: open() can be called again."""

    def __init__(self):
        import mpv
        self._p = mpv.MPV(vo="null", ao="null", pause=True, hr_seek="yes", keep_open="yes")

    def open(self, path, timeout: float = 8.0) -> bool:
        p = self._p
        p.command("stop")  # clears the previous file's duration so we do not read stale values
        time.sleep(0.05)
        p.play(str(path))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if p.duration and p.width:
                return True
            time.sleep(0.05)
        return bool(p.duration)

    def info(self) -> dict:
        p = self._p
        audio = p.audio_params or {}
        layout = " ".join(x for x in (channel_label(audio.get("channels", "")),
                                      (p.audio_codec_name or "").upper()) if x)
        fmt = p.video_format or ""
        fps = p.container_fps or p.estimated_vf_fps
        return {"duration": int(p.duration or 0),
                "frame_rate": round(float(fps), 3) if fps else None,
                "resolution": resolution_label(p.width or 0, p.height or 0),
                "codec": _CODECS.get(fmt, fmt.upper() or None),
                "audio_layout": layout or None}

    def frame_at(self, seconds: float):
        """Raw frame as a PIL image, straight into RAM (nothing is written to disk)."""
        p = self._p
        p.command("seek", seconds, "absolute+exact")
        time.sleep(0.05)
        for _ in range(60):
            if not p.seeking:
                break
            time.sleep(0.05)
        return p.screenshot_raw()

    def close(self) -> None:
        try:
            self._p.terminate()
        except Exception:
            log.debug("mpv terminate failed", exc_info=True)


def probe(path, player: HeadlessPlayer | None = None) -> dict:
    """Technical fields for media_items. Without libmpv only the container is known."""
    result = {"duration": None, "resolution": None, "codec": None, "audio_layout": None, "frame_rate": None,
              "container": Path(path).suffix.lower()}
    own = None
    try:
        hp = player or (own := HeadlessPlayer())
        if hp.open(path):
            result.update(hp.info())
    except Exception:
        log.warning("could not probe %s (is libmpv installed?)", path, exc_info=True)
    finally:
        if own:
            own.close()
    return result


def grab_frames(path, duration: float = 0.0) -> list:
    """4 frames at 10/30/50/70 % of the file, as PIL images held in RAM."""
    hp = HeadlessPlayer()
    try:
        if not hp.open(path):
            return []
        duration = duration or hp.info()["duration"]
        return [hp.frame_at(duration * f) for f in FRACTIONS] if duration else []
    finally:
        hp.close()
