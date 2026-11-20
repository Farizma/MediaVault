"""Convert a video as it plays, for a browser that cannot play the file itself (an iPhone and MKV, say) or a
connection too slow for it (watching away from home).

ffmpeg makes an HLS stream (the format Safari plays natively, and every other browser through the page's player):
H.264 video at the chosen height and AAC stereo sound, in 4-second pieces written to a scratch folder as fast as
the PC can make them. The graphics card does the work when it can (NVIDIA NVENC, AMD AMF, Intel Quick Sync), else
the processor (libx264). A conversion nobody has asked for in a minute is stopped and its folder removed.

ffmpeg is an optional download (Settings > About & Updates, or the Streaming page's button), kept in bin/ffmpeg/.
"""
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

QUALITIES = {"1080": (1080, "6M", "12M"), "720": (720, "3M", "6M"), "480": (480, "1200k", "2400k")}  # height, rate, buffer
SEGMENT = 4
IDLE = 60                  # seconds without a request before a conversion is stopped
MAX_SESSIONS = 2           # conversions running at once (each one keeps a GPU encoder or CPU cores busy)
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_FILE = re.compile(r"^(?:index\.m3u8|seg\d{1,6}\.ts)$")
# what an iPhone (Safari) and most browsers play without help
DIRECT_EXTS = {".mp4", ".m4v", ".mov"}
DIRECT_CODECS = ("h264", "avc", "hevc", "h265", "x264", "x265")


def ffmpeg_path() -> Path | None:
    """bin/ffmpeg/ffmpeg.exe (downloaded), else an ffmpeg on PATH."""
    from utils import bin_dir
    own = bin_dir() / "ffmpeg" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if own.is_file():
        return own
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def plays_directly(item: dict) -> bool:
    """A file an iPhone plays as it is: MP4 / M4V / MOV with H.264 or HEVC video."""
    ext = os.path.splitext(item.get("file_path") or "")[1].lower()
    codec = re.sub(r"[^a-z0-9]", "", (item.get("codec") or "").lower())      # "H.264 / AVC" -> "h264avc"
    return ext in DIRECT_EXTS and (not codec or any(c in codec for c in DIRECT_CODECS))


_encoder_cache: list = []


def encoders(ffmpeg: Path) -> list[str]:
    """The H.264 encoders to try, fastest first: the graphics card's, then the processor's."""
    if not _encoder_cache:
        try:
            out = subprocess.run([str(ffmpeg), "-hide_banner", "-encoders"], capture_output=True, text=True,
                                 timeout=10, creationflags=NO_WINDOW).stdout
        except Exception:
            out = ""
        _encoder_cache.extend([e for e in ("h264_nvenc", "h264_amf", "h264_qsv") if re.search(rf"\b{e}\b", out)]
                              + ["libx264"])
    return list(_encoder_cache)


def command(ffmpeg: Path, src: str, out_dir: Path, quality: str, encoder: str, start: float = 0.0) -> list[str]:
    height, rate, buf = QUALITIES[quality]
    gop = str(SEGMENT * 30)
    cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.2f}"]
    cmd += ["-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
            "-vf", f"scale=-2:'min({height},ih)':flags=bicubic,format=yuv420p", "-c:v", encoder]
    if encoder == "libx264":
        cmd += ["-preset", "veryfast", "-profile:v", "high", "-sc_threshold", "0"]
    elif encoder == "h264_nvenc":
        cmd += ["-preset", "p4", "-profile:v", "high"]
    elif encoder == "h264_qsv":
        cmd += ["-preset", "faster", "-profile:v", "high"]
    cmd += ["-b:v", rate, "-maxrate", rate, "-bufsize", buf,
            "-g", gop, "-keyint_min", gop, "-force_key_frames", f"expr:gte(t,n_forced*{SEGMENT})",
            "-c:a", "aac", "-ac", "2", "-b:a", "160k",
            "-f", "hls", "-hls_time", str(SEGMENT), "-hls_list_size", "0", "-hls_playlist_type", "event",
            "-hls_flags", "independent_segments", "-hls_segment_filename", str(out_dir / "seg%d.ts"),
            str(out_dir / "index.m3u8")]
    return cmd


class _Session:
    def __init__(self, proc: subprocess.Popen, folder: Path, encoder: str):
        self.proc, self.folder, self.encoder = proc, folder, encoder
        self.used = time.monotonic()


class Transcoder:
    """Running conversions, one per (file, quality, start)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[tuple, _Session] = {}
        self._bad: set[str] = set()              # encoders that failed on this PC (no such graphics card)
        self._root = Path(tempfile.gettempdir()) / "MediaVault-stream"
        self._reaper = None

    def available(self) -> bool:
        return ffmpeg_path() is not None

    def file(self, key: tuple, src: str, quality: str, name: str, start: float = 0.0) -> Path | None:
        """A file of the HLS stream (index.m3u8 or segN.ts), starting the conversion if needed. None: not there
        (no ffmpeg, a bad name, or ffmpeg failed)."""
        if quality not in QUALITIES or not _FILE.match(name):
            return None
        ffmpeg = ffmpeg_path()
        if not ffmpeg:
            return None
        with self._lock:
            s = self._sessions.get(key)
            if s is None:
                s = self._start(key, ffmpeg, src, quality, start)
                if s is None:
                    return None
            s.used = time.monotonic()
        path = s.folder / name
        # the playlist and each piece appear as ffmpeg writes them: wait a little for the next one
        end = time.monotonic() + (20 if name == "index.m3u8" else 12)
        while time.monotonic() < end:
            if path.exists() and (name != "index.m3u8" or "#EXTINF" in path.read_text(errors="ignore")):
                if name.endswith(".ts") and not self._complete(s, name):
                    time.sleep(0.2)
                    continue
                return path
            if s.proc.poll() is not None and not path.exists():
                if s.proc.returncode and name == "index.m3u8" and s.encoder != "libx264":
                    log.warning("%s failed here; converting with the processor instead", s.encoder)
                    self._bad.add(s.encoder)
                    with self._lock:
                        self._stop(key)
                        s = self._start(key, ffmpeg, src, quality, start)
                    if s is None:
                        return None
                    path = s.folder / name
                    continue
                return None
            time.sleep(0.2)
        return path if path.exists() else None

    @staticmethod
    def _complete(s: _Session, name: str) -> bool:
        """A piece is whole once the playlist lists it (or ffmpeg has finished)."""
        if s.proc.poll() is not None:
            return True
        try:
            return name in (s.folder / "index.m3u8").read_text(errors="ignore")
        except OSError:
            return False

    def _start(self, key, ffmpeg, src, quality, start) -> _Session | None:
        while len(self._sessions) >= MAX_SESSIONS:          # the oldest one makes room
            self._stop(min(self._sessions, key=lambda k: self._sessions[k].used))
        encoder = next((e for e in encoders(ffmpeg) if e not in self._bad), "libx264")
        folder = self._root / f"{abs(hash(key)):x}"
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.Popen(command(ffmpeg, src, folder, quality, encoder, start), stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        except OSError:
            log.exception("ffmpeg did not start")
            return None
        s = self._sessions[key] = _Session(proc, folder, encoder)
        if self._reaper is None:
            self._reaper = threading.Thread(target=self._reap, daemon=True, name="transcode-reaper")
            self._reaper.start()
        return s

    def _stop(self, key):
        s = self._sessions.pop(key, None)
        if s:
            if s.proc.poll() is None:
                s.proc.kill()
                try:
                    s.proc.wait(5)
                except subprocess.TimeoutExpired:
                    pass
            shutil.rmtree(s.folder, ignore_errors=True)

    def _reap(self):
        while True:
            time.sleep(10)
            with self._lock:
                for k in [k for k, s in self._sessions.items() if time.monotonic() - s.used > IDLE]:
                    self._stop(k)
                if not self._sessions:
                    self._reaper = None
                    return

    def stop_all(self):
        with self._lock:
            for k in list(self._sessions):
                self._stop(k)
        shutil.rmtree(self._root, ignore_errors=True)
