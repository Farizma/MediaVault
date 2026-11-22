"""1.4.2: the phone pages: resume and watched sync, series and box-set pages, search, subtitles, folder cards,
Liquid Glass styling."""
import http.client
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from utils import streaming, webui  # noqa: E402


class PhoneTests(unittest.TestCase):
    """This network, so the link alone is enough (Remote access off)."""

    def setUp(self):
        db.init_db()
        with db._tx() as c:
            for t in ("media_items", "scanned_directories", "watch_history"):
                c.execute(f"DELETE FROM {t}")
        for k in ("private_dirs", "nowatch_dirs", "folders_dirs", "all_dirs"):
            db.set_setting(f"hidden_{k}", "")
        db.set_setting("remote_access", "")
        self.root = Path(tempfile.mkdtemp())
        self.films = db.add_directory(str(self.root / "Films"), "Films", True)
        self.shows = db.add_directory(str(self.root / "Shows"), "Shows", True)
        self.art = db.add_directory(str(self.root / "Artists"), "Artists", False)
        self.u = {}

        def add(d, rel, title, kind, **kw):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"0" * 100)
            row = {"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": d, "title": title,
                   "media_type": kind, "duration": 3000, **kw}
            db.add_items([row])
            self.u[title] = row["uuid"]
            return p
        self.film = add(self.films, "Films/Arrival.mkv", "Arrival", "movie", synopsis="Aliens <b>land</b>.")
        add(self.films, "Films/Dune.mkv", "Dune", "movie", collection_id=7, collection_name="Dune Collection",
            release_date="2021")
        add(self.films, "Films/Dune 2.mkv", "Dune: Part Two", "movie", collection_id=7, collection_name="Dune Collection",
            release_date="2024")
        add(self.shows, "Shows/Severance/S01E01.mkv", "Severance S01E01", "show")
        add(self.shows, "Shows/Severance/S01E02.mkv", "Severance S01E02", "show")
        add(self.art, "Artists/Ann/a.mp4", "Ann one", "clip")
        add(self.art, "Artists/Bea/b.mp4", "Bea one", "clip")
        (self.root / "Films" / "Arrival.en.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        self.srv = streaming.StreamServer()
        with mock.patch.object(streaming, "lan_ip", return_value="127.0.0.1"):
            self.srv.start(0)
        self.t = self.srv.token
        self.no_ffmpeg = mock.patch.object(self.srv.transcoder, "available", return_value=False)
        self.no_ffmpeg.start()
        self.no_embedded = mock.patch.object(webui, "embedded_subtitles", return_value=[])
        self.no_embedded.start()

    def tearDown(self):
        self.no_ffmpeg.stop()
        self.no_embedded.stop()
        self.srv.stop()

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=10)
        c.request("GET", path)
        r = c.getresponse()
        return r, r.read().decode("utf-8", "ignore")

    def post(self, path, data):
        c = http.client.HTTPConnection("127.0.0.1", self.srv.port, timeout=10)
        c.request("POST", path, body=json.dumps(data), headers={"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        return r

    def test_library_groups_series_and_sets_and_searches(self):
        r, body = self.get(f"/{self.t}/")
        self.assertEqual(r.status, 200)
        self.assertIn('class="glass', body)                                   # Liquid Glass
        self.assertIn(f"/{self.t}/series/", body)                             # one card for the series
        self.assertIn(f"/{self.t}/set/7", body)                               # one card for the box set
        self.assertNotIn(">Dune: Part Two<", body)
        self.assertIn("Aliens" if False else "Arrival", body)
        r, body = self.get(f"/{self.t}/?q=arri")
        self.assertIn("Arrival", body)
        self.assertNotIn("Severance", body)
        self.assertIn('value="arri"', body)

    def test_series_and_set_pages(self):
        r, body = self.get(f"/{self.t}/series/{self.u['Severance S01E02']}")
        self.assertEqual(r.status, 200)
        self.assertIn("2 episodes", body)
        self.assertIn(f"/{self.t}/watch/{self.u['Severance S01E01']}", body)
        r, body = self.get(f"/{self.t}/set/7")
        self.assertIn("Dune Collection", body)
        self.assertLess(body.index("Dune</b>"), body.index("Dune: Part Two</b>"))
        self.assertEqual(self.get(f"/{self.t}/set/999")[0].status, 404)

    def test_progress_resume_and_watched(self):
        uid = self.u["Arrival"]
        self.assertEqual(self.post(f"/{self.t}/progress/{uid}", {"pos": 1200, "dur": 3000}).status, 204)
        self.assertEqual(db.get_media(uid)["last_position"], 1200)
        r, body = self.get(f"/{self.t}/watch/{uid}")
        self.assertIn('data-resume="1200"', body)                             # the file itself: the browser seeks
        self.assertIn("Resume 20:00", body)
        self.assertIn("Aliens &lt;b&gt;land&lt;/b&gt;.", body)                # escaped
        r, body = self.get(f"/{self.t}/")
        self.assertIn("Continue Watching", body)
        self.post(f"/{self.t}/progress/{uid}", {"pos": 2950, "dur": 3000})
        self.assertTrue(db.get_media(uid)["is_completed"])
        self.assertEqual(self.post(f"/{self.t}/progress/{uid}", {"pos": "x"}).status, 400)
        self.assertEqual(self.post(f"/{self.t}/progress/{uid}", {"pos": 99999, "dur": 3000}).status, 400)
        self.assertEqual(self.post(f"/wrong/progress/{uid}", {"pos": 1}).status, 404)

    def test_converted_resume_starts_there(self):
        uid = self.u["Arrival"]
        db.save_progress(uid, 600, False)
        with mock.patch.object(self.srv.transcoder, "available", return_value=True):
            r, body = self.get(f"/{self.t}/watch/{uid}")
        self.assertIn(f'data-src="/{self.t}/hls/{uid}/1080/600/index.m3u8" data-offset="600" data-resume="0"', body)

    def test_tabs_that_do_not_track_or_are_private(self):
        db.set_hidden("nowatch_dirs", {self.films})
        uid = self.u["Arrival"]
        self.assertEqual(self.post(f"/{self.t}/progress/{uid}", {"pos": 100, "dur": 3000}).status, 404)
        r, body = self.get(f"/{self.t}/watch/{uid}")
        self.assertIn('data-report=""', body)
        db.set_hidden("private_dirs", {self.films})
        self.assertEqual(self.get(f"/{self.t}/watch/{uid}")[0].status, 404)
        self.assertEqual(self.get(f"/{self.t}/set/7")[0].status, 404)
        self.assertNotIn("Arrival", self.get(f"/{self.t}/")[1])

    def test_subtitles(self):
        uid = self.u["Arrival"]
        r, body = self.get(f"/{self.t}/watch/{uid}")
        self.assertIn(f'<track kind="subtitles" src="/{self.t}/sub/{uid}/0" srclang="en" label="EN" default>', body)
        r, vtt = self.get(f"/{self.t}/sub/{uid}/0")
        self.assertEqual(r.getheader("Content-Type"), "text/vtt; charset=utf-8")
        self.assertIn("00:00:01.000 --> 00:00:02.000", vtt)
        self.assertEqual(self.get(f"/{self.t}/sub/{uid}/5")[0].status, 404)

    def test_folder_cards_tab(self):
        db.set_hidden("folders_dirs", {self.art})
        r, body = self.get(f"/{self.t}/?tab={self.art}")
        self.assertIn('class="grid folders"', body)
        self.assertIn("All videos", body)
        self.assertIn(f"?tab={self.art}&amp;folder=Ann", body)
        r, body = self.get(f"/{self.t}/?tab={self.art}&folder=Bea")
        self.assertIn("Bea one", body)
        self.assertNotIn("Ann one", body)
        self.assertEqual(self.get(f"/{self.t}/folderpic/{self.art}/..")[0].status, 404)

    def test_next_episode_and_assets(self):
        r, body = self.get(f"/{self.t}/watch/{self.u['Severance S01E01']}")
        self.assertIn(f'data-next href="/{self.t}/watch/{self.u["Severance S01E02"]}"', body)
        r, css = self.get("/style.css")
        self.assertIn("backdrop-filter", css)
        self.assertEqual(self.get(f"/{self.t}/wide/{self.u['Arrival']}")[0].status, 200)


class VttTests(unittest.TestCase):
    def test_srt_to_vtt(self):
        self.assertEqual(webui.srt_to_vtt("﻿1\r\n00:00:01,500 --> 00:00:02,000\r\nHi\r\n"),
                         "WEBVTT\n\n1\n00:00:01.500 --> 00:00:02.000\nHi\n")
        self.assertTrue(webui.srt_to_vtt("WEBVTT\n\nx").startswith("WEBVTT\n\nx"))


if __name__ == "__main__":
    unittest.main()
