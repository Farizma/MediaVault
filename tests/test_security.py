"""Network-facing safety: the LAN streaming server, everything downloaded, and scraped text."""
import hashlib
import io
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
import setup  # noqa: E402
from utils import components, scraper, streaming  # noqa: E402


class StreamServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        root = Path(tempfile.mkdtemp())
        did = db.add_directory(str(root), "S", True)
        video = root / "x.mp4"
        video.write_bytes(os.urandom(4096))
        cls.uid = db.file_id(str(video))
        db.add_items([{"uuid": cls.uid, "file_path": db.norm(str(video)), "parent_directory_id": did,
                       "title": "x'\"><script>alert(1)</script><img src=x onerror=alert(2)>", "media_type": "movie"}])
        cls.srv = streaming.StreamServer()
        with mock.patch.object(streaming, "lan_ip", return_value="127.0.0.1"):
            cls.srv.start(port=0)
        host, port = cls.srv._srv.server_address[:2]
        cls.base = f"http://{host}:{port}/{cls.srv.token}/"

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def get(self, url, **h):
        return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=5)

    def test_library_page_cannot_run_a_title(self):
        r = self.get(self.base)
        page = r.read().decode()
        self.assertNotIn("<script>", page)
        self.assertNotRegex(page, r"<[^>]*\son\w+\s*=")   # no event-handler attribute anywhere (the title is text)
        self.assertIn("&lt;script&gt;", page)
        csp = r.headers["Content-Security-Policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertNotIn("script-src", csp)                # no scripts at all
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r.headers["Referrer-Policy"], "no-referrer")
        self.assertNotIn("Python", r.headers["Server"])

    def test_missing_poster_is_a_blank_picture(self):
        r = self.get(self.base + "poster/" + self.uid)
        self.assertEqual(r.headers["Content-Type"], "image/svg+xml")

    def test_range_past_the_end_is_clamped(self):
        r = self.get(self.base + "v/" + self.uid, Range="bytes=4000-999999")
        self.assertEqual(r.status, 206)
        self.assertEqual(len(r.read()), 96)
        self.assertEqual(r.headers["Content-Range"], "bytes 4000-4095/4096")

    def test_bad_token_and_bad_methods(self):
        for url, method in ((self.base.replace(self.srv.token, "x" * len(self.srv.token)), "GET"), (self.base, "POST")):
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(urllib.request.Request(url, method=method, data=b"" if method == "POST" else None), timeout=5)
            self.assertEqual(e.exception.code, 404)

    def test_only_this_network(self):
        for ok in ("192.168.1.20", "10.0.0.5", "172.16.3.1", "169.254.1.1", "127.0.0.1", "fe80::1", "::ffff:192.168.0.2"):
            self.assertTrue(streaming._local_client(ok), ok)
        for bad in ("8.8.8.8", "1.1.1.1", "2001:4860::8888", "::ffff:8.8.8.8", "nonsense"):
            self.assertFalse(streaming._local_client(bad), bad)


class DownloadTests(unittest.TestCase):
    def test_only_https(self):
        for url in ("file:///C:/Windows/win.ini", "http://example.com/x.png", "ftp://x/y"):
            with self.assertRaises(Exception):
                scraper.fetch_image(url)
            with self.assertRaises(ValueError):
                setup._https(url)

    def test_oversized_picture_refused(self):
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with mock.patch("urllib.request.urlopen", return_value=R(b"0" * (scraper.MAX_IMAGE + 10))):
            with self.assertRaises(scraper.ScrapeError):
                scraper.fetch_image("https://image.tmdb.org/x.jpg")

    def test_decompression_bomb_refused(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("1", (12000, 12000)).save(buf, "PNG")          # tiny file, 144 million pixels

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with mock.patch("urllib.request.urlopen", return_value=R(buf.getvalue())):
            with self.assertRaises(Exception):
                scraper.fetch_image("https://image.tmdb.org/bomb.png")

    def test_pinned_downloads(self):
        self.assertTrue(setup.SEVENZR_URL.startswith("https://github.com/ip7z/7zip/releases/download/"))
        self.assertEqual(len(setup.SEVENZR_SHA256), 64)
        self.assertEqual(len(setup.SHADER_SHA256), 64)
        src = Path(setup.__file__).read_text(encoding="utf-8")
        self.assertIn("_download(SEVENZR_URL, exe, log, SEVENZR_SHA256)", src)
        self.assertNotIn("7-zip.org/a/7zr.exe", src)

    def test_checksum_mismatch_deletes(self):
        data = b"payload"

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        d = Path(tempfile.mkdtemp()) / "f"
        with mock.patch("urllib.request.urlopen", return_value=R(data)):
            with self.assertRaises(RuntimeError):
                setup._download("https://github.com/x/y", d, lambda *_: None, "0" * 64)
        self.assertFalse(d.exists())

    def test_app_installer_must_match_github_checksum(self):
        url = "https://github.com/Farizma/MediaVault/releases/download/v9.9.9/MediaVault_v9.9.9_setup.exe"
        body = b"MZ fake installer"

        class R(io.BytesIO):
            headers = {"Content-Length": str(len(body))}
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: R(body)):
            with self.assertRaises(IOError):
                components.download_setup(url, "MediaVault_v9.9.9_setup.exe", sha256="0" * 64)
            good = components.download_setup(url, "MediaVault_v9.9.9_setup.exe", sha256=hashlib.sha256(body).hexdigest())
        self.assertEqual(good.read_bytes(), body)
        self.assertNotEqual(good.parent, Path(tempfile.gettempdir()))          # its own private folder
        with mock.patch.object(components, "asset_digest", return_value=""):
            with self.assertRaises(ValueError):                                 # no checksum published: not run
                components.download_setup(url, "MediaVault_v9.9.9_setup.exe")
        with self.assertRaises(ValueError):
            components.download_setup(url, "..\\evil.exe", sha256="0" * 64)

    def test_pip_rollback_version_is_only_a_version(self):
        from utils import rollback
        with mock.patch.object(rollback, "previous", return_value="1.0 --index-url=https://evil"), \
                mock.patch.object(components, "frozen", return_value=False), mock.patch("setup.pip_install") as pip:
            with self.assertRaises(ValueError):
                components.rollback_component("watchdog")
        pip.assert_not_called()


class ScrapedTextTests(unittest.TestCase):
    def test_markup_is_dropped_urls_kept(self):
        hit = {"title": "Nice <img src='file:///C:/x.png'>Title", "synopsis": "<b>Bold</b> a < b",
               "poster_url": "https://x/<1>.jpg", "cast": [{"name": "<a href=x>Actor</a>", "photo_url": "https://p"}],
               "genres": ["<i>Drama</i>"]}
        out = scraper.untag(hit)
        self.assertEqual(out["title"], "Nice Title")
        self.assertEqual(out["synopsis"], "Bold a \u2039 b")
        self.assertEqual(out["poster_url"], "https://x/<1>.jpg")
        self.assertEqual(out["cast"][0]["name"], "Actor")
        self.assertEqual(out["genres"], ["Drama"])

    def test_search_results_only_https_thumbs(self):
        fake = {"results": [{"id": 1, "title": "<b>A</b>", "poster_path": "/p.jpg"}]}
        with mock.patch.object(scraper, "_get_json", return_value=fake):
            out = scraper.tmdb_search("movie", "a", "", "KEY")
        self.assertEqual(out[0]["title"], "A")
        self.assertTrue(out[0]["thumb"].startswith("https://"))
        from utils import anilist
        with mock.patch.object(anilist, "_post", return_value={"Page": {"media": [
                {"id": 2, "title": {"romaji": "<script>x</script>B"}, "coverImage": {"large": "file:///etc/passwd"}}]}}):
            res = anilist.search("b")
        self.assertEqual((res[0]["title"], res[0]["thumb"]), ("xB", ""))


if __name__ == "__main__":
    unittest.main()
