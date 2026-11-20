"""Watch on other devices.

1. Any browser on your Wi-Fi (phone, tablet, TV browser, another PC): a small local web server with your
   library and a player. Off until you switch it on; every link carries a random secret that changes each time,
   and files are only ever looked up by their library id (never by a path from the request).
   Remote access (Settings > Streaming): your own devices anywhere, through Tailscale (a private network between
   them; nothing is opened to the internet). They sign in with a password once; the link's secret is kept.
   Files a browser cannot play, or too big for a home upload, convert as they play (utils/transcode.py).
2. Chromecast / Google TV (pychromecast) and AirPlay (Apple TV, AirPlay 2 TVs; pyatv): the device is told to
   play the file from that same server. Both libraries are optional; Settings offers to install them.

Formats: browsers and both cast targets play MP4 / M4V / MOV (H.264, and HEVC on newer devices) and WebM.
MKV and AVI play in some browsers and on Chromecast only partly; Apple TV refuses them.
"""
import asyncio
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote

import database as db

log = logging.getLogger(__name__)
PORT = 8765
CHUNK = 1 << 20
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MIME = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
        ".mkv": "video/x-matroska", ".avi": "video/x-msvideo", ".ts": "video/mp2t", ".m2ts": "video/mp2t"}
CASTABLE = {".mp4", ".m4v", ".mov", ".webm"}


def lan_ip() -> str:
    """This PC's address on the local network (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


_STYLE = """body{margin:0;background:#000;color:#F5F5F7;font:15px -apple-system,system-ui,'Segoe UI',sans-serif;
-webkit-text-size-adjust:100%}
header{position:sticky;top:0;z-index:2;padding:14px 18px;padding-top:max(14px,env(safe-area-inset-top));
background:rgba(28,28,30,.82);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);font-weight:800;display:flex;gap:14px;align-items:center}
header a{font-weight:600;color:#8E8E93;font-size:14px} header a.on{color:#fff}
.tabs{display:flex;gap:6px;overflow-x:auto;padding:12px 18px 0;scrollbar-width:none}
.tabs a{flex:none;padding:7px 13px;border-radius:999px;background:#1C1C1E;font-size:13px;font-weight:600;color:#C7C7CC}
.tabs a.on{background:#fff;color:#000}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:16px;padding:18px}
a{color:inherit;text-decoration:none} .c img{width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:12px;background:#1C1C1E;display:block}
.c p{margin:8px 2px 0;font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
video{width:100%;max-height:78vh;background:#000;display:block} .w{padding:0 0 30px} .w .t{padding:0 18px}
.m{color:#8E8E93;font-size:13px} .q{display:flex;gap:6px;flex-wrap:wrap;padding:12px 18px 0}
.q a{padding:6px 12px;border-radius:9px;background:#1C1C1E;font-size:13px;font-weight:600}.q a.on{background:#0A84FF}
form{max-width:320px;margin:18vh auto 0;padding:0 24px;display:flex;flex-direction:column;gap:12px}
input{font:inherit;padding:13px 14px;border-radius:12px;border:1px solid #38383A;background:#1C1C1E;color:#fff}
button{font:inherit;font-weight:700;padding:13px;border:0;border-radius:12px;background:#fff;color:#000}
.err{color:#FF453A;font-size:13px;text-align:center} h1{font-size:28px;margin:0 0 4px;text-align:center}"""


def _page(title: str, body: str, header: str = "Media Vault", script: bool = False) -> bytes:
    return (f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="Media Vault">
<meta name="theme-color" content="#000000"><link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon.png"><link rel="icon" href="/icon.png">
<title>{html.escape(title)}</title><style>{_STYLE}</style>"""
            + ("<script src=\"/hls.min.js\" defer></script><script src=\"/player.js\" defer></script>" if script else "")
            + f"</head><body><header>{header}</header>{body}</body></html>").encode("utf-8")


# No outside resources, frames or inline scripts: the pages are links, posters, a sign-in form and one <video>
# (whose player, for converted streams, is hls.js served from this PC).
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; img-src 'self'; media-src 'self' blob:; style-src 'unsafe-inline'; "
                               "script-src 'self'; connect-src 'self'; manifest-src 'self'; "
                               "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",          # the secret in the address never leaves in a Referer
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
}
# an empty poster for titles without one (instead of the old inline script, which a title could break out of)
_BLANK = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 3"/>'
WEB = Path(__file__).resolve().parent.parent / "ui" / "web"
ICON = Path(__file__).resolve().parent.parent / "ui" / "brand" / "icon-256.png"
_MANIFEST = json.dumps({"name": "Media Vault", "short_name": "Media Vault", "start_url": "/", "display": "standalone",
                        "background_color": "#000000", "theme_color": "#000000",
                        "icons": [{"src": "/icon.png", "sizes": "256x256", "type": "image/png"}]}).encode()
_PLAYER_JS = b"""document.querySelectorAll('video[data-src]').forEach(function (v) {
  var src = v.getAttribute('data-src');
  if (!/\\.m3u8$/.test(src) || v.canPlayType('application/vnd.apple.mpegurl')) { v.src = src; return; }
  if (window.Hls && Hls.isSupported()) { var h = new Hls({ enableWorker: false }); h.loadSource(src); h.attachMedia(v); }
  else { v.src = src; }
});"""
QUALITY_NAMES = {"orig": "Original", "1080": "1080p", "720": "720p", "480": "480p"}

# Tailscale: a private network between your own devices (100.64.0.0/10 and fd7a:115c:a1e0::/48)
_TAILSCALE = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
LOGIN_TRIES = 5                # wrong passwords from one address ...
LOGIN_WINDOW = 600             # ... in this many seconds, and it must wait


def _ip(addr: str):
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
    except ValueError:
        return None
    return ip.ipv4_mapped if ip.version == 6 and ip.ipv4_mapped else ip


def _local_client(addr: str) -> bool:
    """Only devices on this network: private, link-local or loopback addresses (never the internet, even when
    this PC has a public address or a port is forwarded)."""
    ip = _ip(addr)
    return bool(ip) and (ip.is_private or ip.is_link_local or ip.is_loopback) and not _tailnet(addr)


def _tailnet(addr: str) -> bool:
    ip = _ip(addr)
    return bool(ip) and any(ip in n for n in _TAILSCALE if n.version == ip.version)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        kind, salt, want = stored.split("$")
    except (AttributeError, ValueError):
        return False
    return kind == "pbkdf2" and hmac.compare_digest(hash_password(password, bytes.fromhex(salt)).split("$")[2], want)


class _Handler(BaseHTTPRequestHandler):
    server_version = "MediaVault"
    sys_version = ""                           # no Python version in the Server header
    timeout = 30                               # a client that stops talking does not hold a thread forever

    def log_message(self, fmt, *args):  # quiet: no request lines in the app log
        pass

    def end_headers(self):
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        super().end_headers()

    def _deny(self, code: int = 404):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -- who may ask: this network (with the link), and with Remote access on, your Tailscale devices (signed in)
    def _remote(self) -> bool:
        return _tailnet(self.client_address[0])

    def _allowed_client(self) -> bool:
        return _local_client(self.client_address[0]) or (self.server.remote and self._remote())

    def _cookie_ok(self) -> bool:
        m = re.search(r"(?:^|;\s*)mv=([0-9a-f]{64})", self.headers.get("Cookie", ""))
        return bool(m) and hmac.compare_digest(m[1], self.server.session)

    def do_HEAD(self):  # noqa: N802
        self._deny()

    def do_POST(self):  # noqa: N802
        if not self._allowed_client() or self.path != "/login" or not self.server.password:
            return self._deny()
        ip = self.client_address[0]
        now = time.monotonic()
        fails = [t for t in self.server.fails.get(ip, []) if now - t < LOGIN_WINDOW]
        if len(fails) >= LOGIN_TRIES:
            return self._login(f"Too many tries. Wait {int((LOGIN_WINDOW - (now - fails[0])) // 60) + 1} minutes.", 429)
        n = min(int(self.headers.get("Content-Length") or 0), 2048)
        form = parse_qs(self.rfile.read(n).decode("utf-8", "ignore"))
        if not check_password((form.get("password") or [""])[0], self.server.password):
            fails.append(now)
            self.server.fails[ip] = fails
            time.sleep(1)                          # slows guessing down a little more
            return self._login("Wrong password.", 401)
        self.server.fails.pop(ip, None)
        self.send_response(303)
        self.send_header("Set-Cookie", f"mv={self.server.session}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax")
        self.send_header("Location", f"/{self.server.token}/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _login(self, error: str = "", code: int = 200):
        body = ('<form method="post" action="/login"><h1>Media Vault</h1><p class="m" style="text-align:center">'
                'Enter the password you set in Settings \u203A Streaming.</p>'
                '<input type="password" name="password" autocomplete="current-password" placeholder="Password" autofocus required>'
                '<button type="submit">Open library</button>'
                + (f'<p class="err">{html.escape(error)}</p>' if error else "") + "</form>")
        data = _page("Media Vault", body)
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 (http.server naming)
        if not self._allowed_client() or len(self.path) > 400:
            return self._deny()
        path, _, query = self.path.partition("?")
        q = parse_qs(query)
        try:
            # public: what a home-screen icon needs, and the player script (nothing about your library)
            if path == "/manifest.webmanifest":
                return self._send(_MANIFEST, "application/manifest+json")
            if path == "/icon.png":
                return self._file(str(ICON), "image/png") if ICON.exists() else self._deny()
            if path in ("/hls.min.js", "/player.js"):
                data = (WEB / "hls.min.js").read_bytes() if path == "/hls.min.js" else _PLAYER_JS
                return self._send(data, "text/javascript", cache=True)
            if path in ("/", ""):                  # the address to remember: signs you in, then opens the library
                if self._cookie_ok():
                    return self._redirect(f"/{self.server.token}/")
                return self._login() if self.server.password else self._deny()
            parts = [unquote(p) for p in path.strip("/").split("/")]
            if not hmac.compare_digest(parts[0].encode(), self.server.token.encode()):
                return self._deny()
            if self._remote() and not self._cookie_ok():
                return self._redirect("/")
            if len(parts) == 1:
                return self._library((q.get("tab") or [""])[0])
            kind, uid = parts[1], parts[2] if len(parts) > 2 else ""
            if not _UUID.match(uid):
                return self._deny()
            item = db.get_media(uid)
            if not item or item.get("parent_directory_id") in db.private_dirs():
                return self._deny()
            if kind == "v":
                return self._file(item["file_path"], MIME.get(os.path.splitext(item["file_path"])[1].lower(), "application/octet-stream"))
            if kind == "poster":
                from utils import scraper
                p = scraper.cover_path(item)
                return self._file(str(p), "image/webp") if p.exists() else self._send(_BLANK, "image/svg+xml")
            if kind == "hls" and len(parts) == 5:
                f = self.server.transcoder.file((uid, parts[3]), item["file_path"], parts[3], parts[4])
                if not f:
                    return self._deny()
                return self._file(str(f), "application/vnd.apple.mpegurl" if f.suffix == ".m3u8" else "video/mp2t",
                                  cache=f.suffix == ".ts")
            if kind == "watch":
                return self._watch(item, (q.get("q") or [""])[0])
            return self._deny()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            db.close_thread_connection()

    def _redirect(self, where: str):
        self.send_response(303)
        self.send_header("Location", where)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send(self, data: bytes, ctype: str, cache: bool = False):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _header(self, current: str = "") -> str:
        return f'<a href="/{self.server.token}/" class="on">Media Vault</a>'

    def _library(self, tab: str):
        t = self.server.token
        hidden = set(db.private_dirs())                     # private tabs never show here
        dirs = [d for d in db.list_directories() if d["id"] not in hidden]
        tab_id = int(tab) if tab.isdigit() and any(d["id"] == int(tab) for d in dirs) else None
        tabs = [f'<a href="/{t}/"{" class=on" if tab_id is None else ""}>All</a>'] + [
            f'<a href="/{t}/?tab={d["id"]}"{" class=on" if d["id"] == tab_id else ""}>{html.escape(d["tab_name"])}</a>'
            for d in dirs]
        cards = []
        for c in db.list_library(tab_id, sets=False):
            if c.get("parent_directory_id") in hidden:
                continue
            uid = c["uuid"]
            cards.append(f'<a class="c" href="/{t}/watch/{uid}"><img loading="lazy" alt="" src="/{t}/poster/{uid}">'
                         f'<p>{html.escape(c["title"])}</p></a>')
        self._send(_page("Media Vault", f'<nav class="tabs">{"".join(tabs)}</nav><div class="grid">{"".join(cards)}</div>',
                         self._header()), "text/html; charset=utf-8")

    def _watch(self, item: dict, quality: str):
        """The player: the file itself, or converted (1080p / 720p / 480p) when ffmpeg is here. Away from home the
        default is 720p (a home upload is slow); a file an iPhone cannot play converts at 1080p."""
        from utils import transcode
        t, uid = self.server.token, item["uuid"]
        can = self.server.transcoder.available()
        direct = transcode.plays_directly(item)
        if quality not in QUALITY_NAMES or (quality != "orig" and not can):
            quality = ("720" if self._remote() else "orig" if direct else "1080") if can else "orig"
        src = f"/{t}/v/{uid}" if quality == "orig" else f"/{t}/hls/{uid}/{quality}/index.m3u8"
        choices = "".join(f'<a href="/{t}/watch/{uid}?q={k}"{" class=on" if k == quality else ""}>{v}</a>'
                          for k, v in QUALITY_NAMES.items() if k == "orig" or can)
        note = ""
        if quality == "orig" and not direct:
            note = ('<p class="m">This file may not play in this browser. ' + (
                "Pick 1080p or 720p to convert it as it plays." if can else
                "Install ffmpeg in Media Vault (Settings \u203A Streaming) to convert it as it plays.") + "</p>")
        body = (f'<div class="w"><video controls autoplay playsinline data-src="{src}"></video>'
                f'<div class="q">{choices}</div><div class="t"><h2>{html.escape(item["title"])}</h2>{note}'
                f'<p class="m">{html.escape(item["synopsis"] or "")}</p>'
                f'<p><a href="/{t}/">\u2039 Library</a></p></div></div>')
        self._send(_page(item["title"], body, self._header(), script=True), "text/html; charset=utf-8")

    def _file(self, path: str, ctype: str, cache: bool = False):
        """Range requests, so players can seek."""
        size = os.path.getsize(path)
        start, end = 0, size - 1
        m = re.fullmatch(r"bytes=(\d{0,18})-(\d{0,18})", self.headers.get("Range", "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else end
            else:
                start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                return self.end_headers()
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if cache:
            self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(CHUNK, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)


def tailscale() -> dict:
    """Is Tailscale on this PC, and its address there: {installed, running, ip, name}. name: its MagicDNS name
    (pc.tail1234.ts.net), "" when MagicDNS is off."""
    import shutil
    import subprocess
    exe = shutil.which("tailscale") or next((p for p in (r"C:\Program Files\Tailscale\tailscale.exe",
                                                        r"C:\Program Files (x86)\Tailscale\tailscale.exe")
                                             if os.path.isfile(p)), None)
    out = {"installed": bool(exe), "running": False, "ip": "", "name": ""}
    if exe:
        try:
            r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=6,
                               creationflags=0x08000000 if os.name == "nt" else 0)
            st = json.loads(r.stdout or "{}")
            me = st.get("Self") or {}
            ips = [i for i in me.get("TailscaleIPs") or [] if "." in i]
            out.update(running=st.get("BackendState") == "Running", ip=ips[0] if ips else "",
                       name=(me.get("DNSName") or "").rstrip("."))
        except Exception:
            log.debug("tailscale status", exc_info=True)
    if not out["ip"]:                               # no CLI answer: this PC's own addresses in Tailscale's range
        try:
            for fam, *_, addr in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                if _tailnet(addr[0]):
                    out.update(ip=addr[0], running=True)
                    break
        except OSError:
            pass
    return out


class StreamServer:
    """The server. Without Remote access: this network's address only, a new secret each start. With it: every
    address (so Tailscale reaches it), a secret kept between starts, and a password for your other devices."""

    def __init__(self):
        from utils.transcode import Transcoder
        self._srv = None
        self.token = ""
        self.transcoder = Transcoder()

    @property
    def running(self) -> bool:
        return self._srv is not None

    @staticmethod
    def remote_on() -> bool:
        return db.get_setting("remote_access", "") == "1" and bool(db.get_setting("stream_password", ""))

    def start(self, port: int = PORT) -> str:
        if self._srv:
            return self.base_url()
        remote = self.remote_on()
        if remote:
            self.token = db.get_setting("remote_token", "") or ""
            if not self.token:
                self.token = secrets.token_urlsafe(18)
                db.set_setting("remote_token", self.token)
        else:
            self.token = secrets.token_urlsafe(18)
        # this network's address only, unless Remote access is on: then every one (Tailscale has its own); the
        # handler still turns away anything that is neither this network nor your Tailscale devices
        host = "0.0.0.0" if remote else lan_ip()
        for p in (port, 0):                      # the usual port, else any free one
            try:
                self._srv = ThreadingHTTPServer((host, p), _Handler)
                break
            except OSError:
                continue
        if not self._srv:
            raise OSError("could not open a port for streaming")
        self._srv.daemon_threads = True
        self._srv.token = self.token
        self._srv.remote = remote
        self._srv.password = db.get_setting("stream_password", "") or "" if remote else ""
        self._srv.session = hmac.new(self.token.encode(), b"session", hashlib.sha256).hexdigest()
        self._srv.fails = {}
        self._srv.transcoder = self.transcoder
        threading.Thread(target=self._srv.serve_forever, daemon=True, name="stream-server").start()
        return self.base_url()

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None
            self.token = ""
        self.transcoder.stop_all()

    def restart(self):
        if self._srv:
            self.stop()
            self.start()

    @property
    def port(self) -> int:
        return self._srv.server_address[1] if self._srv else PORT

    def base_url(self) -> str:
        return f"http://{lan_ip()}:{self.port}/{self.token}/" if self._srv else ""

    def file_url(self, uid: str) -> str:
        return self.base_url() + "v/" + quote(uid)


# ------------------------------------------------------------ cast targets (optional libraries)

def support() -> dict:
    """Which cast libraries are installed."""
    import importlib.util
    return {"chromecast": importlib.util.find_spec("pychromecast") is not None,
            "airplay": importlib.util.find_spec("pyatv") is not None}


def discover(timeout: float = 5.0) -> list[dict]:
    """Chromecasts and AirPlay receivers on the network: [{id, name, kind, model}]."""
    found = []
    have = support()
    if have["chromecast"]:
        try:
            import pychromecast
            casts, browser = pychromecast.get_chromecasts(timeout=timeout)
            pychromecast.discovery.stop_discovery(browser)
            for c in casts:
                info = c.cast_info
                found.append({"id": f"cc:{info.uuid}", "name": info.friendly_name, "kind": "Chromecast", "model": info.model_name or ""})
        except Exception:
            log.exception("Chromecast discovery failed")
    if have["airplay"]:
        try:
            import pyatv
            from pyatv.const import Protocol

            async def scan():
                return await pyatv.scan(asyncio.get_running_loop(), timeout=int(timeout))
            for conf in asyncio.run(scan()):
                if conf.get_service(Protocol.AirPlay):
                    found.append({"id": f"ap:{conf.identifier}", "name": conf.name, "kind": "AirPlay",
                                  "model": str(conf.device_info.model_str or "")})
        except Exception:
            log.exception("AirPlay discovery failed")
    return found


def cast(device_id: str, url: str, title: str, mime: str) -> None:
    """Tell a device to play url. Raises with a readable message when it cannot."""
    if device_id.startswith("cc:"):
        import uuid as _uuid

        import pychromecast
        casts, browser = pychromecast.get_listed_chromecasts(uuids=[_uuid.UUID(device_id[3:])])
        pychromecast.discovery.stop_discovery(browser)
        if not casts:
            raise RuntimeError("that Chromecast is no longer on the network")
        cc = casts[0]
        cc.wait(timeout=10)
        cc.media_controller.play_media(url, mime, title=title)
        cc.media_controller.block_until_active(timeout=10)
    elif device_id.startswith("ap:"):
        import pyatv

        async def go():
            loop = asyncio.get_running_loop()
            confs = await pyatv.scan(loop, identifier=device_id[3:], timeout=5)
            if not confs:
                raise RuntimeError("that AirPlay device is no longer on the network")
            atv = await pyatv.connect(confs[0], loop)
            try:
                await atv.stream.play_url(url)
            finally:
                atv.close()
        asyncio.run(go())
    else:
        raise ValueError("unknown device")
