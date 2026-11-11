"""Discord status ("Watching ...") over Discord's local IPC pipe. No extra library and no network: the Discord
app on this PC does the rest. Off by default. Personal clips never show a title.

Levels: minimal ("Watching a movie"), title (title, year, episode, paused), full (+ elapsed / remaining bar).
Your own wording for both lines ({title} {year} {episode} {type}), and privacy: adult titles, chosen tags and whole
folders can show only "Watching a video" or nothing at all, and the status can clear while paused.
Discord needs an application id: create an app named "Media Vault" at discord.com/developers/applications and
paste its id in Settings > Integrations (or set DEFAULT_APP_ID for your builds).
"""
import json
import logging
import os
import queue
import re
import socket
import struct
import sys
import threading
import time
import uuid

log = logging.getLogger(__name__)

DEFAULT_APP_ID = ""
LEVELS = ("minimal", "title", "full")
MIN_GAP = 4.0          # Discord accepts 5 updates per 20 s; one every 4 s at most stays under it
RETRY = 30.0           # Discord not running: look again this often


def _pipe_paths():
    if sys.platform == "win32":
        return [rf"\\.\pipe\discord-ipc-{i}" for i in range(10)]
    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    dirs = [base, os.path.join(base, "app/com.discordapp.Discord"), os.path.join(base, "snap.discord")]
    return [os.path.join(d, f"discord-ipc-{i}") for d in dirs for i in range(10)]


class _Conn:
    """One open pipe (Windows) or unix socket, speaking Discord's framing: op, length, JSON."""

    def __init__(self, app_id: str, paths=None):
        self.f = self.sock = None
        for p in paths or _pipe_paths():
            try:
                if sys.platform == "win32":
                    self.f = open(p, "r+b", buffering=0)
                else:
                    if not os.path.exists(p):
                        continue
                    self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    self.sock.settimeout(5)
                    self.sock.connect(p)
                break
            except OSError:
                self.f = self.sock = None
        if not (self.f or self.sock):
            raise ConnectionError("Discord is not running")
        self.send(0, {"v": 1, "client_id": app_id})
        op, data = self.recv()
        if op != 1 or data.get("evt") != "READY":
            self.close()
            raise ConnectionError(data.get("message") or "Discord refused the application id")

    def _write(self, b: bytes):
        if self.f:
            self.f.write(b)
        else:
            self.sock.sendall(b)

    def _read(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = self.f.read(n - len(out)) if self.f else self.sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError("Discord closed the connection")
            out += chunk
        return out

    def send(self, op: int, payload: dict):
        body = json.dumps(payload).encode()
        self._write(struct.pack("<II", op, len(body)) + body)

    def recv(self):
        op, n = struct.unpack("<II", self._read(8))
        return op, json.loads(self._read(n) or b"{}")

    def close(self):
        for h in (self.f, self.sock):
            try:
                if h:
                    h.close()
            except OSError:
                pass


DEFAULTS = {
    "discord_details": "{title} ({year})",   # first line; {title} {year} {episode} {type}
    "discord_state": "{episode}",            # second line
    "discord_paused": "show",                # show: "Paused" on the second line; clear: no status while paused
    "discord_hide_adult": "1",               # adult titles show as "Watching a video"
    "discord_image_text": "Media Vault",     # the tooltip on the image
}
PLACEHOLDERS = ("title", "year", "episode", "type")
ADULT_RATINGS = {"18+", "R18+", "R18", "NC-17", "X", "XXX", "AO", "Adults Only"}
ADULT_GENRES = {"hentai", "erotica", "adult"}
FOLDER_MODES = ("show", "generic", "off")    # per folder: title as usual / only "Watching a video" / nothing at all


def fill(template: str, info: dict) -> str:
    """A status line from a template. Unknown {words} are left out; a placeholder with no value takes empty
    brackets and dangling separators with it ("Title ()" -> "Title")."""
    kind = info.get("kind", "movie")
    values = {"title": info.get("title") or "", "year": info.get("year") or "", "episode": info.get("episode") or "",
              "type": {"movie": "Movie", "show": "Series"}.get(kind, "Video")}
    out = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1).lower(), ""), template or "")
    out = re.sub(r"[(\[]\s*[)\]]", "", out)                 # "()" and "[]" left by an empty value
    out = re.sub(r"\s*([\u00B7|\-\u2013\u2014:,])\s*(?=$|[\u00B7|\-\u2013\u2014:,])", "", out)
    out = re.sub(r"^\s*[\u00B7|\-\u2013\u2014:,]\s*|\s*[\u00B7|\-\u2013\u2014:,]\s*$", "", out)
    return " ".join(out.split())[:128]


def privacy(item: dict | None, tags, folder_modes: dict, hide_adult: bool, hidden_tags) -> str:
    """How much Discord may see of this title: "show", "generic" ("Watching a video") or "off" (no status)."""
    if not item:
        return "generic"
    mode = folder_modes.get(str(item.get("parent_directory_id")), "show")
    if mode == "off":
        return "off"
    tags = set(tags or ())
    if mode == "generic" or (item.get("media_type") == "clip"):
        return "generic"
    if hide_adult and ((item.get("certification") or "") in ADULT_RATINGS
                       or any(t.lower().removeprefix("genre:") in ADULT_GENRES for t in tags if t.startswith("genre:"))):
        return "generic"
    if tags & set(hidden_tags or ()):
        return "generic"
    return "show"


def activity(info: dict | None, level: str, now: float | None = None, opts: dict | None = None) -> dict | None:
    """What Discord shows. info: title, kind (movie / show / clip), episode ("S01E02"), year, position,
    duration, paused, speed, privacy ("show" / "generic" / "off"). None: the status is cleared."""
    o = {**DEFAULTS, **(opts or {})}
    if not info or info.get("privacy") == "off":
        return None
    if info.get("paused") and o["discord_paused"] == "clear":
        return None
    kind = info.get("kind", "movie")
    noun = {"movie": "a movie", "show": "a show"}.get(kind, "a video")
    act = {"type": 3, "assets": {"large_image": "logo", "large_text": (o["discord_image_text"] or "Media Vault")[:128]}}
    if level == "minimal" or kind == "clip" or info.get("privacy") == "generic":   # personal or private: no name
        act["details"] = f"Watching {noun}" if info.get("privacy") != "generic" or level == "minimal" else "Watching a video"
        if info.get("paused"):
            act["state"] = "Paused"
        return act
    act["details"] = fill(o["discord_details"], {**info, "year": info.get("year") if kind == "movie" else ""}) \
        or (info.get("title") or "")[:120]
    state = fill(o["discord_state"], info)
    if info.get("paused"):
        state = " \u00B7 ".join(p for p in (state, "Paused") if p)
    if state:
        act["state"] = state[:128]
    if level == "full" and not info.get("paused") and info.get("duration"):
        now = time.time() if now is None else now
        speed = info.get("speed") or 1.0
        start = now - info.get("position", 0) / speed
        act["timestamps"] = {"start": int(start), "end": int(start + info["duration"] / speed)}
    return act


class Presence:
    """Runs on its own thread. update() is cheap and can be called on every player tick: only changes are sent,
    at most one every MIN_GAP seconds, and the latest state always wins."""

    def __init__(self, get_setting, connect=_Conn):
        self._get, self._connect = get_setting, connect
        self._q: queue.Queue = queue.Queue()
        self._info = None
        self._sent_key = "unsent"
        self.status = "Off"
        self.enabled, self.level, self.app_id = False, "title", ""
        self.opts: dict = dict(DEFAULTS)
        self._thread = None
        self.configure()

    def configure(self):
        self.enabled = self._get("discord", "0") == "1"
        level = self._get("discord_detail", "title")
        self.level = level if level in LEVELS else "title"
        self.app_id = (self._get("discord_app_id", "") or DEFAULT_APP_ID).strip()
        self.opts = {k: self._get(k, v) if self._get(k, None) is not None else v for k, v in DEFAULTS.items()}
        if self.enabled and not self.app_id.isdigit():
            self.status = "Needs a Discord application ID"
        elif not self.enabled:
            self.status = "Off"
        if self.enabled and self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="discord")
            self._thread.start()
        self._q.put("config")

    def update(self, info: dict | None):
        self._info = info
        self._q.put("info")

    def _key(self, act):
        if not act:
            return None
        k = dict(act)
        ts = k.pop("timestamps", None)    # a few seconds of drift is not worth an update; a seek is
        return json.dumps(k, sort_keys=True), (ts or {}).get("start", 0) // 15

    def _loop(self):
        conn, last, last_try = None, 0.0, 0.0
        while True:
            try:
                self._q.get(timeout=MIN_GAP)
            except queue.Empty:
                pass
            while not self._q.empty():          # coalesce: only the newest state matters
                self._q.get_nowait()
            want = activity(self._info, self.level, opts=self.opts) if self.enabled else None
            if not self.enabled or not self.app_id.isdigit():
                if conn:                         # turned off: clear the status, then let go of the pipe
                    try:
                        conn.send(1, {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid(), "activity": None},
                                      "nonce": str(uuid.uuid4())})
                    except OSError:
                        pass
                    conn.close()
                    conn, self._sent_key = None, "unsent"
                continue
            want_key = self._key(want)
            if want_key == self._sent_key:
                continue
            if time.monotonic() - last < MIN_GAP:
                self._q.put("again")
                time.sleep(MIN_GAP - (time.monotonic() - last))
                continue
            try:
                if conn is None:
                    if time.monotonic() - last_try < RETRY and last_try:
                        continue
                    last_try = time.monotonic()
                    conn = self._connect(self.app_id)
                conn.send(1, {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid(), "activity": want},
                              "nonce": str(uuid.uuid4())})
                conn.recv()
                self._sent_key, last = want_key, time.monotonic()
                self.status = "Connected"
            except (OSError, ConnectionError, ValueError, struct.error) as e:
                self.status = "Discord is not running" if "not running" in str(e) else f"Discord: {e}"
                if conn:
                    conn.close()
                conn, self._sent_key = None, "unsent"
