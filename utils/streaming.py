"""Watch on other devices.

1. Any browser on your Wi-Fi (phone, tablet, TV browser, another PC): a small local web server with your
   library and a player. Off until you switch it on; every link carries a random secret that changes each time,
   and files are only ever looked up by their library id (never by a path from the request).
2. Chromecast / Google TV (pychromecast) and AirPlay (Apple TV, AirPlay 2 TVs; pyatv): the device is told to
   play the file from that same server. Both libraries are optional; Settings offers to install them.

Formats: browsers and both cast targets play MP4 / M4V / MOV (H.264, and HEVC on newer devices) and WebM.
MKV and AVI play in some browsers and on Chromecast only partly; Apple TV refuses them.
"""
import asyncio
import hmac
import html
import ipaddress
import logging
import mimetypes
import os
import re
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote

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


def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{margin:0;background:#000;color:#F5F5F7;font:15px -apple-system,system-ui,'Segoe UI',sans-serif}}
header{{position:sticky;top:0;padding:14px 18px;background:rgba(28,28,30,.8);backdrop-filter:blur(20px);font-weight:800}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:16px;padding:18px}}
a{{color:inherit;text-decoration:none}} .c img,.c .n{{width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:12px;background:#1C1C1E;display:block}}
.c .n{{display:flex;align-items:center;justify-content:center;text-align:center;padding:8px;box-sizing:border-box}}
.c p{{margin:8px 2px 0;font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
video{{width:100%;max-height:80vh;background:#000}} .w{{padding:18px}} .m{{color:#8E8E93;font-size:13px}}
</style></head><body><header>Media Vault</header>{body}</body></html>""".encode("utf-8")


# No scripts, frames, forms or outside resources: the pages are plain links, posters and one <video>.
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'; "
                               "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",          # the secret in the address never leaves in a Referer
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
}
# an empty poster for titles without one (instead of the old inline script, which a title could break out of)
_BLANK = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 3"/>'


def _local_client(addr: str) -> bool:
    """Only devices on this network: private, link-local or loopback addresses (never the internet, even when
    this PC has a public address or a port is forwarded)."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_link_local or ip.is_loopback


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

    def _deny(self):
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):  # noqa: N802
        self._deny()

    def do_POST(self):  # noqa: N802
        self._deny()

    def do_GET(self):  # noqa: N802 (http.server naming)
        if not _local_client(self.client_address[0]) or len(self.path) > 300:
            return self._deny()
        parts = [unquote(p) for p in self.path.split("?")[0].strip("/").split("/")]
        if not parts or not hmac.compare_digest(parts[0].encode(), self.server.token.encode()):
            return self._deny()
        try:
            if len(parts) == 1:
                return self._library()
            kind, uid = parts[1], parts[2] if len(parts) > 2 else ""
            if not _UUID.match(uid):
                return self._deny()
            item = db.get_media(uid)
            if not item:
                return self._deny()
            if kind == "v":
                return self._file(item["file_path"], MIME.get(os.path.splitext(item["file_path"])[1].lower(), "application/octet-stream"))
            if kind == "poster":
                from utils import scraper
                p = scraper.cover_path(item)
                return self._file(str(p), "image/webp") if p.exists() else self._send(_BLANK, "image/svg+xml")
            if kind == "watch":
                t = self.server.token
                body = (f'<div class="w"><video controls autoplay playsinline src="/{t}/v/{uid}"></video>'
                        f'<h2>{html.escape(item["title"])}</h2><p class="m">{html.escape(item["synopsis"] or "")}</p>'
                        f'<p><a href="/{t}/">‹ Library</a></p></div>')
                return self._send(_page(item["title"], body), "text/html; charset=utf-8")
            return self._deny()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            db.close_thread_connection()

    def _send(self, data: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _library(self):
        t = self.server.token
        cards = []
        for c in db.list_library(None, sets=False):
            uid = c["uuid"]
            cards.append(f'<a class="c" href="/{t}/watch/{uid}"><img loading="lazy" alt="" src="/{t}/poster/{uid}">'
                         f'<p>{html.escape(c["title"])}</p></a>')
        self._send(_page("Media Vault", f'<div class="grid">{"".join(cards)}</div>'), "text/html; charset=utf-8")

    def _file(self, path: str, ctype: str):
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


class StreamServer:
    """The local server. start() picks a new secret each time; stop() closes it."""

    def __init__(self):
        self._srv = None
        self.token = ""

    @property
    def running(self) -> bool:
        return self._srv is not None

    def start(self, port: int = PORT) -> str:
        if self._srv:
            return self.base_url()
        self.token = secrets.token_urlsafe(18)
        host = lan_ip()                          # this network's address only, not every interface (VPNs, public ones)
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
        threading.Thread(target=self._srv.serve_forever, daemon=True, name="stream-server").start()
        return self.base_url()

    def stop(self):
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None
            self.token = ""

    def base_url(self) -> str:
        return f"http://{lan_ip()}:{self._srv.server_address[1]}/{self.token}/" if self._srv else ""

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
