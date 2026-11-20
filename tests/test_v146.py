"""1.4.0: Remote access through Tailscale (a password, a kept link, a QR code, add to home screen) and converting
video as it streams (ffmpeg, HLS)."""
import http.client
import json
import os
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from utils import streaming, transcode  # noqa: E402


class AddressTests(unittest.TestCase):
    def test_who_counts_as_what(self):
        self.assertTrue(streaming._tailnet("100.101.102.103"))
        self.assertTrue(streaming._tailnet("fd7a:115c:a1e0::1"))
        self.assertFalse(streaming._tailnet("192.168.1.5"))
        self.assertTrue(streaming._local_client("192.168.1.5"))
        self.assertFalse(streaming._local_client("100.101.102.103"))      # Tailscale is not "this network"
        self.assertFalse(streaming._local_client("8.8.8.8"))
        self.assertFalse(streaming._local_client("nonsense"))

    def test_passwords(self):
        h = streaming.hash_password("correct horse")
        self.assertTrue(h.startswith("pbkdf2$"))
        self.assertTrue(streaming.check_password("correct horse", h))
        self.assertFalse(streaming.check_password("wrong", h))
        self.assertFalse(streaming.check_password("x", "garbage"))
        self.assertNotEqual(h, streaming.hash_password("correct horse"))     # salted


class ServerTests(unittest.TestCase):
    """The server on 127.0.0.1, with this test's requests counted as a Tailscale device."""

    def setUp(self):
        db.init_db()
        with db._tx() as c:
            for t in ("media_items", "scanned_directories"):
                c.execute(f"DELETE FROM {t}")
        root = Path(tempfile.mkdtemp())
        self.pub = db.add_directory(str(root / "pub"), "Films", False)
        self.priv = db.add_directory(str(root / "priv"), "Secret", False)
        db.set_hidden("private_dirs", {self.priv})
        rows = []
        for d, name in ((self.pub, "Film.mp4"), (self.priv, "Hidden.mkv")):
            p = root / ("pub" if d == self.pub else "priv") / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"0123456789" * 10)
            rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": d, "title": p.stem,
                         "media_type": "clip"})
        db.add_items(rows)
        self.film, self.hidden = rows[0]["uuid"], rows[1]["uuid"]
        db.set_setting("remote_access", "1")
        db.set_setting("stream_password", streaming.hash_password("swordfish1"))
        db.set_setting("remote_token", "")
        self.srv = streaming.StreamServer()
        with mock.patch.object(streaming, "lan_ip", return_value="127.0.0.1"):
            self.srv.start(0)
        self.patch = mock.patch.object(streaming, "_tailnet", side_effect=lambda a: a.startswith("127."))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.srv.stop()
        db.set_setting("remote_access", "")

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=10)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r, data

    def login(self, password):
        return self.req("POST", "/login", body=f"password={password}",
                        headers={"Content-Type": "application/x-www-form-urlencoded"})

    def test_sign_in_then_the_library(self):
        t = self.srv.token
        self.assertEqual(db.get_setting("remote_token"), t)                     # kept between starts
        r, body = self.req("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn(b'name="password"', body)
        r, _ = self.req("GET", f"/{t}/")
        self.assertEqual((r.status, r.getheader("Location")), (303, "/"))       # the link alone is not enough
        with mock.patch.object(streaming.time, "sleep"):
            r, body = self.login("nope")
        self.assertEqual(r.status, 401)
        r, _ = self.login("swordfish1")
        self.assertEqual((r.status, r.getheader("Location")), (303, f"/{t}/"))
        cookie = r.getheader("Set-Cookie").split(";")[0]
        self.assertIn("HttpOnly", r.getheader("Set-Cookie"))
        r, body = self.req("GET", f"/{t}/", headers={"Cookie": cookie})
        self.assertEqual(r.status, 200)
        self.assertIn(b"Film", body)
        self.assertNotIn(b"Hidden", body)                                       # private tabs never show
        self.assertNotIn(b"Secret", body)
        r, _ = self.req("GET", f"/{t}/watch/{self.hidden}", headers={"Cookie": cookie})
        self.assertEqual(r.status, 404)
        with mock.patch.object(self.srv.transcoder, "available", return_value=False):
            r, body = self.req("GET", f"/{t}/watch/{self.film}", headers={"Cookie": cookie})
        self.assertIn(f'data-src="/{t}/v/{self.film}"'.encode(), body)            # no ffmpeg: the file itself
        r, _ = self.req("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(r.getheader("Location"), f"/{t}/")
        r, body = self.req("GET", "/manifest.webmanifest")
        self.assertEqual(json.loads(body)["display"], "standalone")

    def test_wrong_passwords_lock_out(self):
        with mock.patch.object(streaming.time, "sleep"):
            for _ in range(streaming.LOGIN_TRIES):
                self.assertEqual(self.login("bad")[0].status, 401)
            r, body = self.login("swordfish1")
        self.assertEqual(r.status, 429)
        self.assertIn(b"Too many tries", body)

    def test_a_new_link_signs_everyone_out(self):
        r, _ = self.login("swordfish1")
        cookie = r.getheader("Set-Cookie").split(";")[0]
        old = self.srv.token
        db.set_setting("remote_token", "")
        with mock.patch.object(streaming, "lan_ip", return_value="127.0.0.1"):
            self.srv.stop()
            self.srv.start(0)
        self.assertNotEqual(self.srv.token, old)
        r, _ = self.req("GET", f"/{self.srv.token}/", headers={"Cookie": cookie})
        self.assertEqual((r.status, r.getheader("Location")), (303, "/"))

    def test_converted_stream_is_served(self):
        r, _ = self.login("swordfish1")
        cookie = r.getheader("Set-Cookie").split(";")[0]
        playlist = Path(tempfile.mkdtemp()) / "index.m3u8"
        playlist.write_text("#EXTM3U\n#EXTINF:4,\nseg0.ts\n")
        with mock.patch.object(self.srv.transcoder, "available", return_value=True), \
                mock.patch.object(self.srv.transcoder, "file", return_value=playlist) as f:
            r, body = self.req("GET", f"/{self.srv.token}/watch/{self.film}", headers={"Cookie": cookie})
            self.assertIn(f"/hls/{self.film}/720/index.m3u8".encode(), body)     # away from home: 720p
            self.assertIn(b'src="/hls.min.js"', body)
            r, body = self.req("GET", f"/{self.srv.token}/hls/{self.film}/720/index.m3u8", headers={"Cookie": cookie})
        self.assertEqual((r.status, r.getheader("Content-Type")), (200, "application/vnd.apple.mpegurl"))
        self.assertEqual(f.call_args[0][2:], ("720", "index.m3u8"))


class TranscodeTests(unittest.TestCase):
    def test_what_plays_directly(self):
        self.assertTrue(transcode.plays_directly({"file_path": "a.mp4", "codec": "H.264"}))
        self.assertTrue(transcode.plays_directly({"file_path": "a.MOV", "codec": "hevc"}))
        self.assertFalse(transcode.plays_directly({"file_path": "a.mkv", "codec": "h264"}))
        self.assertFalse(transcode.plays_directly({"file_path": "a.mp4", "codec": "mpeg2video"}))

    def test_command(self):
        cmd = transcode.command(Path("ffmpeg"), "in.mkv", Path("/o"), "720", "h264_nvenc", 30)
        self.assertEqual(cmd[cmd.index("-ss") + 1], "30.00")
        self.assertIn("scale=-2:'min(720,ih)':flags=bicubic,format=yuv420p", cmd)
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "h264_nvenc")
        self.assertEqual(cmd[-1], str(Path("/o") / "index.m3u8"))
        self.assertIn("aac", cmd)

    @unittest.skipIf(sys.platform == "win32", "a shell script stands in for ffmpeg")
    def test_a_conversion_runs_and_is_stopped(self):
        fake = Path(tempfile.mkdtemp()) / "ffmpeg"
        fake.write_text(textwrap.dedent("""\
            #!/bin/sh
            if [ "$2" = "-encoders" ]; then echo " V..... libx264"; exit 0; fi
            for last; do :; done
            dir=$(dirname "$last")
            printf 'x' > "$dir/seg0.ts"
            printf '#EXTM3U\\n#EXTINF:4,\\nseg0.ts\\n' > "$last"
            sleep 30
            """))
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        transcode._encoder_cache.clear()
        t = transcode.Transcoder()
        with mock.patch.object(transcode, "ffmpeg_path", return_value=fake):
            got = t.file(("u", "720"), "in.mkv", "720", "index.m3u8")
            self.assertTrue(got and "seg0.ts" in got.read_text())
            self.assertEqual(t.file(("u", "720"), "in.mkv", "720", "seg0.ts").read_bytes(), b"x")
            self.assertIsNone(t.file(("u", "720"), "in.mkv", "720", "../../etc/passwd"))
            self.assertIsNone(t.file(("u", "999"), "in.mkv", "999", "index.m3u8"))
            proc = t._sessions[("u", "720")].proc
            t.stop_all()
        time.sleep(0.2)
        self.assertIsNotNone(proc.poll())
        self.assertEqual(t._sessions, {})
        transcode._encoder_cache.clear()


class CleanupTests(unittest.TestCase):
    def test_leftovers_go_and_a_pause_is_not_cut_short(self):
        root = Path(tempfile.gettempdir()) / "MediaVault-stream" / "old"
        root.mkdir(parents=True, exist_ok=True)
        (root / "seg0.ts").write_bytes(b"x")
        transcode.Transcoder()
        self.assertFalse(root.exists())                       # a crash's leftovers are cleared at start
        self.assertGreaterEqual(transcode.IDLE, 10 * 60)      # a long pause keeps what is converted


class SetupTests(unittest.TestCase):
    def test_newest_stable_ffmpeg(self):
        import setup
        assets = [{"name": n, "browser_download_url": "https://x/" + n} for n in (
            "ffmpeg-master-latest-win64-gpl.zip", "ffmpeg-n7.1-latest-win64-gpl-7.1.zip",
            "ffmpeg-n8.0-latest-win64-gpl-8.0.zip", "ffmpeg-n8.0-latest-win64-lgpl-8.0.zip",
            "ffmpeg-n8.0-latest-linux64-gpl-8.0.tar.xz")]
        with mock.patch.object(setup, "_fetch_text", return_value=json.dumps({"assets": assets})):
            self.assertEqual(setup._latest_ffmpeg()["name"], "ffmpeg-n8.0-latest-win64-gpl-8.0.zip")

    def test_component_row(self):
        from utils import components
        row = next(r for r in components.inventory() if r["id"] == "ffmpeg")
        self.assertTrue(row["optional"])


class SettingsTests(unittest.TestCase):
    def test_password_and_switch(self):
        from tests.test_v133 import make_dashboard
        db.init_db()
        db.set_setting("stream_password", "")
        db.set_setting("remote_access", "")
        d = make_dashboard()
        with mock.patch.object(d, "refreshRemote"):
            self.assertEqual(d.setStreamPassword("short"), "Use at least 8 characters")
            self.assertEqual(d.setStreamPassword("long enough"), "")
            self.assertTrue(streaming.check_password("long enough", db.get_setting("stream_password")))
            with mock.patch.object(d, "setStreaming") as st:
                d.setRemoteAccess(True)
            st.assert_called_once_with(True)
            self.assertTrue(streaming.StreamServer.remote_on())
            d.setRemoteAccess(False)
        self.assertFalse(streaming.StreamServer.remote_on())
        self.assertFalse(d.stream.running)

    def test_qr(self):
        from ui import dashboard
        self.assertTrue(dashboard.qr_data_uri("http://pc.tail.ts.net:8765/").startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
