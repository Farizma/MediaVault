"""Library view, health report, portable backups and the streaming server."""
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

import database as db  # noqa: E402
from ui.dashboard import library_view, quality_of  # noqa: E402
from utils import backup_manager, health, streaming  # noqa: E402


def _card(uid, title, **kw):
    c = {"uuid": uid, "title": title, "synopsis": "", "release_date": "", "codec": "", "resolution": "",
         "file_path": f"/m/{title}.mkv", "is_completed": 0, "last_position": 0, "duration": 0, "added_at": ""}
    c.update(kw)
    return c


class LibraryViewTests(unittest.TestCase):
    def test_quality_classes(self):
        self.assertEqual(quality_of("3840x1606"), "4k")
        self.assertEqual(quality_of("1920x800"), "1080")
        self.assertEqual(quality_of("2160p"), "4k")
        self.assertEqual(quality_of("720p"), "720")
        self.assertEqual(quality_of("640x480"), "sd")
        self.assertEqual(quality_of(None), "")

    def test_search_filter_sort(self):
        cards = [_card("a", "Arrival", resolution="3840x2160", release_date="2016-11-11", is_completed=1),
                 _card("b", "Blade Runner", resolution="1920x800", release_date="1982-06-25"),
                 _card("c", "Collateral", resolution="1920x1080", release_date="2004-08-06", synopsis="a cab ride")]
        index = {"b": {"genres": ["Sci-Fi"]}, "a": {"genres": ["Sci-Fi"]}}
        self.assertEqual([c["uuid"] for c in library_view(cards, index, query="CAB")], ["c"])
        self.assertEqual([c["uuid"] for c in library_view(cards, index, genre="Sci-Fi", unwatched=True)], ["b"])
        self.assertEqual([c["uuid"] for c in library_view(cards, index, quality="1080")], ["b", "c"])
        self.assertEqual([c["uuid"] for c in library_view(cards, index, sort="year")], ["a", "c", "b"])
        self.assertEqual(library_view(cards, index, query="arrival 2016")[0]["uuid"], "a")


class HealthTests(unittest.TestCase):
    def test_duplicates_pick_best_copy(self):
        items = [{"uuid": "1", "title": "Dune", "media_type": "movie", "release_date": "2021", "file_path": "/x/a.mkv",
                  "resolution": "1920x800", "codec": "H.264"},
                 {"uuid": "2", "title": "Dune", "media_type": "movie", "release_date": "2021", "file_path": "/x/b.mkv",
                  "resolution": "3840x1600", "codec": "HEVC"},
                 {"uuid": "3", "title": "Dune", "media_type": "movie", "release_date": "1984", "file_path": "/x/c.mkv",
                  "resolution": "720p", "codec": ""}]
        dups = health.duplicates(items, quality_of)
        self.assertEqual(len(dups), 1)
        best = [f for f in dups[0]["files"] if f["best"]]
        self.assertEqual(best[0]["uuid"], "2")

    def test_missing_episodes(self):
        items = [{"title": f"Show S01E0{e}", "media_type": "show", "file_path": f"/tv/Show/S01E0{e}.mkv"} for e in (1, 2, 5)]
        gaps = health.missing_episodes(items)
        self.assertEqual(gaps[0]["missing"], ["S01E03", "S01E04"])


class LibraryFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.root = Path(tempfile.mkdtemp())
        cls.did = db.add_directory(str(cls.root), "R8", True)
        cls.video = cls.root / "clip.mp4"
        cls.video.write_bytes(bytes(range(256)) * 40)
        cls.uid = db.file_id(str(cls.video))
        db.add_items([{"uuid": cls.uid, "file_path": db.norm(str(cls.video)), "parent_directory_id": cls.did,
                       "title": "Clip", "media_type": "movie", "duration": 1, "resolution": "1080p",
                       "codec": "H.264", "container": ".mp4", "audio_layout": "Stereo"}])


class StreamingTests(LibraryFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srv = streaming.StreamServer()
        cls.srv.start(port=0)
        host, port = cls.srv._srv.server_address[:2]       # it listens on this network's address, not 127.0.0.1
        cls.base = f"http://{host}:{port}/{cls.srv.token}/"

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()

    def _get(self, url, **headers):
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5)

    def test_wrong_token_is_404(self):
        bad = self.base.replace(self.srv.token, "nope")
        with self.assertRaises(urllib.error.HTTPError) as e:
            self._get(bad + "v/" + self.uid)
        self.assertEqual(e.exception.code, 404)

    def test_path_instead_of_uuid_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self._get(self.base + "v/..%2F..%2Fetc%2Fpasswd")
        self.assertEqual(e.exception.code, 404)

    def test_full_and_range(self):
        data = self.video.read_bytes()
        self.assertEqual(self._get(self.base + "v/" + self.uid).read(), data)
        r = self._get(self.base + "v/" + self.uid, Range="bytes=10-19")
        self.assertEqual(r.status, 206)
        self.assertEqual(r.read(), data[10:20])
        r = self._get(self.base + "v/" + self.uid, Range="bytes=-5")
        self.assertEqual(r.read(), data[-5:])
        with self.assertRaises(urllib.error.HTTPError) as e:
            self._get(self.base + "v/" + self.uid, Range=f"bytes={len(data)}-")
        self.assertEqual(e.exception.code, 416)

    def test_library_page_lists_title(self):
        self.assertIn(b"Clip", self._get(self.base).read())


class PortableBackupTests(LibraryFixture):
    def test_round_trip_and_rejects_bad_files(self):
        assets = self.root / ".vault-assets"
        assets.mkdir(exist_ok=True)
        (assets / "clip.poster.webp").write_bytes(b"RIFFfake")
        out = Path(tempfile.mkdtemp()) / "lib.mvault"
        counts = backup_manager.export_portable(out)
        self.assertGreaterEqual(counts["files"], 1)
        (assets / "clip.poster.webp").unlink()
        res = backup_manager.import_portable(out)
        self.assertTrue((assets / "clip.poster.webp").exists())
        self.assertGreaterEqual(res["art"], 1)
        self.assertTrue(backup_manager.pending_restore_path().exists())
        backup_manager.pending_restore_path().unlink()

        junk = out.with_name("junk.mvault")
        with zipfile.ZipFile(junk, "w") as z:
            z.writestr("hello.txt", "hi")
        with self.assertRaises(ValueError):
            backup_manager.import_portable(junk)


if __name__ == "__main__":
    unittest.main()
