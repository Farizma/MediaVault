"""1.0.6: tag suggestions, adult OVAs as box sets, words-only AniList retry, MAL pictures, whole-cover wrap."""
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw  # noqa: E402

import database as db  # noqa: E402
import watcher  # noqa: E402
from utils import anilist, boxwrap, scraper  # noqa: E402

OVA = {"anilist_id": 115138, "mal_id": None, "title": "Ane wa Yanmama Junyuu-chuu", "format": "OVA", "certification": "18+",
       "release_date": "2020-01-31", "synopsis": "s", "genres": ["Hentai"], "score": 7.4, "cast": [], "gallery_urls": [],
       "poster_url": None, "collection_id": None, "collection_name": None, "original_title": None, "romaji_title": None}


class OvaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()

    def test_rules(self):
        self.assertTrue(anilist.is_adult_ova(OVA))
        self.assertFalse(anilist.is_adult_ova({**OVA, "certification": None}))     # a normal OVA stays a series
        self.assertFalse(anilist.is_adult_ova({**OVA, "format": "TV"}))
        self.assertEqual(anilist.ova_set_id(OVA), anilist.OVA_SET_OFFSET + 115138)

    def test_new_files_become_a_box_set(self):
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "H", True, source="anilist")
        paths = []
        for n in (1, 2, 10):
            p = os.path.join(root, f"Ane wa Yanmama Junyuu-chuu - Episode {n:02d}.mp4")
            open(p, "w").close()
            paths.append(p)

        async def fake_many(jobs, keys, source):
            return [OVA for _ in jobs]
        with mock.patch.object(scraper, "scrape_many", side_effect=fake_many), mock.patch.object(watcher, "_headless", return_value=None):
            watcher.index_paths(db.get_directory(did), paths)
        items = db.list_media(did)
        self.assertEqual({i["media_type"] for i in items}, {"movie"})
        self.assertEqual({i["collection_id"] for i in items}, {anilist.ova_set_id(OVA)})
        films = db.films_in_set(anilist.ova_set_id(OVA))
        self.assertEqual([f["title"] for f in films], ["Ane wa Yanmama Junyuu-chuu #1", "Ane wa Yanmama Junyuu-chuu #2",
                                                       "Ane wa Yanmama Junyuu-chuu #10"])          # natural order

    def test_series_already_indexed_is_converted(self):
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "H2", True, source="anilist")
        rows = []
        for n in (1, 2):
            p = os.path.join(root, f"x{n}.mp4")
            open(p, "w").close()
            rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did,
                         "title": f"Old Name S01E{n:02d}", "media_type": "show"})
        db.add_items(rows)
        items = db.list_media(did)
        self.assertTrue(watcher._ova_to_set(items, OVA, db.cast_owner(items[0])))
        after = {i["title"]: i for i in db.list_media(did)}
        self.assertEqual(set(after), {"Ane wa Yanmama Junyuu-chuu #1", "Ane wa Yanmama Junyuu-chuu #2"})
        self.assertTrue(all(i["media_type"] == "movie" for i in after.values()))


class LookupTests(unittest.TestCase):
    def test_words_only_retry(self):
        asked = []

        def fake(q, v, retries=2):
            asked.append(v["q"])
            return {"Media": {"id": 1, "title": {"romaji": "Boku ni Sefure ga Dekita Riyuu"}, "startDate": {}}} \
                if v["q"] == "Boku ni Sefure ga Dekita Riyuu" else {}
        with mock.patch.object(anilist, "_post", side_effect=fake):
            hit = anilist.lookup("Boku ni Sefure ga Dekita Riyuu!")
        self.assertEqual(hit["title"], "Boku ni Sefure ga Dekita Riyuu")
        self.assertEqual(asked, ["Boku ni Sefure ga Dekita Riyuu!", "Boku ni Sefure ga Dekita Riyuu"])

    def test_mal_pictures(self):
        body = json.dumps({"data": [{"jpg": {"image_url": "https://cdn.myanimelist.net/a.jpg", "large_image_url": "https://cdn.myanimelist.net/a-l.jpg"}},
                                    {"jpg": {"image_url": "http://insecure/b.jpg"}}]}).encode()

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        anilist._mal_fetch.cache_clear()
        with mock.patch("urllib.request.urlopen", return_value=R(body)):
            self.assertEqual(anilist.mal_pictures(40000), ("https://cdn.myanimelist.net/a-l.jpg",))
        anilist._mal_fetch.cache_clear()
        with mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertEqual(anilist.mal_pictures(40000), ())
        self.assertEqual(anilist.mal_pictures(None), ())


class WrapTests(unittest.TestCase):
    def sleeve(self, w=800, h=540, left=380, right=420):
        img = Image.new("RGB", (w, h), (200, 120, 140))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, left - 1, h], fill=(40, 60, 120))           # back
        d.rectangle([left, 0, right - 1, h], fill=(250, 250, 250))    # spine
        for y in range(20, h, 60):                                     # busy art, so not every column is an edge
            d.ellipse([500, y, 560, y + 40], fill=(90, 30, 30))
            d.text((60, y), "Back cover text", fill=(255, 255, 255))
        return img

    def test_finds_the_spine(self):
        self.assertTrue(boxwrap.is_wrap(self.sleeve()))
        self.assertFalse(boxwrap.is_wrap(Image.new("RGB", (378, 540))))
        left, right = boxwrap.find_spine(self.sleeve())
        self.assertLessEqual(abs(left - 380), 2)
        self.assertLessEqual(abs(right - 420), 2)

    def test_plain_image_uses_proportions(self):
        left, right = boxwrap.find_spine(Image.new("RGB", (800, 540), (10, 10, 10)))
        self.assertAlmostEqual((left + right) / 2, 400, delta=2)
        self.assertAlmostEqual(right - left, 540 * 14 / 190, delta=2)

    def test_split_faces(self):
        faces = boxwrap.split(self.sleeve())
        self.assertEqual(faces["front"].getpixel((10, 10)), (200, 120, 140))
        self.assertEqual(faces["back"].getpixel((5, 5)), (40, 60, 120))
        self.assertGreater(faces["spine"].height, faces["spine"].width * 8)


class TagNameTests(unittest.TestCase):
    def test_most_used_first_no_computed(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        db.init_db()
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "T", True)
        uid = {}
        for n in ("a", "b"):
            p = os.path.join(root, n + ".mkv")
            open(p, "w").close()
            uid[n] = db.file_id(p)
            db.add_items([{"uuid": uid[n], "file_path": db.norm(p), "parent_directory_id": did, "title": n, "media_type": "movie"}])
        for u, t in [("a", "Rewatch"), ("b", "Rewatch"), ("a", "Kids"), ("a", "auto:4K"), ("a", "genre:Drama")]:
            db.add_tag(uid[u], t)
        d = Dashboard(types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None),
                      LibraryModel(), TabsModel(), FrameProvider())
        names = d.tagNames()
        self.assertEqual(names[:2], ["Rewatch", "Kids"])
        self.assertNotIn("auto:4K", names)
        self.assertNotIn("genre:Drama", names)


if __name__ == "__main__":
    unittest.main()


class AniListTagsAndStudios(unittest.TestCase):
    MEDIA = {"genres": ["Hentai"], "tags": [
        {"name": "MILF", "rank": 97}, {"name": "Twist", "rank": 90, "isMediaSpoiler": True},
        {"name": "Cheating", "rank": 79}, {"name": "Minor detail", "rank": 40}],
        "studios": {"edges": [{"isMain": False, "node": {"name": "Bunny Walker", "isAnimationStudio": True}},
                              {"isMain": True, "node": {"name": "T-REX", "isAnimationStudio": True}},
                              {"isMain": False, "node": {"name": "Some TV", "isAnimationStudio": False}}]}}

    def test_genres_take_relevant_tags_without_spoilers(self):
        self.assertEqual(anilist._genres(self.MEDIA), ["Hentai", "MILF", "Cheating"])

    def test_studios(self):
        self.assertEqual(anilist._studios(self.MEDIA), ["T-REX", "Bunny Walker"])
        many = {"studios": {"edges": [{"isMain": True, "node": {"name": "Toei Animation", "isAnimationStudio": True}}] +
                            [{"isMain": False, "node": {"name": f"S{i}", "isAnimationStudio": True}} for i in range(5)]}}
        self.assertEqual(anilist._studios(many), ["Toei Animation"])        # a long series: just the main studio

    def test_studio_tags_are_kept_and_not_yours(self):
        db.init_db()
        root = tempfile.mkdtemp()
        did = db.add_directory(root, "S", True)
        p = os.path.join(root, "a.mkv")
        open(p, "w").close()
        uid = db.file_id(p)
        db.add_items([{"uuid": uid, "file_path": db.norm(p), "parent_directory_id": did, "title": "a", "media_type": "movie"}])
        db.add_tag(uid, "Mine")
        db.set_tag_group([uid], "studio:", ["T-REX", "T-REX", "Bunny Walker"])
        db.set_tag_group([uid], "genre:", ["Hentai", "MILF"])
        self.assertEqual(sorted(db.tags_for(uid)), ["Mine", "genre:Hentai", "genre:MILF", "studio:Bunny Walker", "studio:T-REX"])
        self.assertNotIn("studio:T-REX", db.user_tags())
        from utils import tagrules
        tagrules.retag_all()
        self.assertIn("studio:T-REX", db.tags_for(uid))                      # computed tags change; studios stay
        rule = tagrules.clean({"field": "studio", "test": "is", "value": "t-rex", "tag": "X"})
        self.assertTrue(tagrules.matches(rule, db.get_media(uid), db.search_index()[uid]))


class UpdateInUseTests(unittest.TestCase):
    def test_dll_in_use_is_moved_aside_then_cleaned(self):
        import setup
        d = Path(tempfile.mkdtemp())
        (d / "mpv-2.dll").write_text("old")
        (d / "new.dll").write_text("new")
        real = setup.shutil.copy
        calls = []

        def copy(src, dst):              # the first copy fails as if Windows had the DLL loaded
            calls.append(dst)
            if len(calls) == 1:
                raise PermissionError(13, "Permission denied")
            return real(src, dst)
        with mock.patch.object(setup.shutil, "copy", side_effect=copy):
            setup._place(d / "new.dll", d / "mpv-2.dll")
        self.assertEqual((d / "mpv-2.dll").read_text(), "new")
        self.assertEqual(len(list(d.glob("mpv-2.dll.old-*"))), 1)
        setup.clean_replaced(d)
        self.assertEqual(list(d.glob("*.old-*")), [])

    def test_vlc_waits_when_in_use(self):
        import setup
        d = Path(tempfile.mkdtemp())
        (d / "vlc").mkdir()
        (d / "vlc" / "libvlc.dll").write_text("old")
        (d / "vlc.new").mkdir()
        (d / "vlc.new" / "libvlc.dll").write_text("new")
        setup.clean_replaced(d)              # next start: the staged copy goes in
        self.assertEqual((d / "vlc" / "libvlc.dll").read_text(), "new")
        self.assertFalse((d / "vlc.new").exists())


class ClosingTests(unittest.TestCase):
    def test_window_close_goes_through_backend(self):
        root = Path(__file__).resolve().parent.parent
        self.assertIn("onClosing: Backend.windowClosing()", (root / "ui" / "Main.qml").read_text(encoding="utf-8"))
        self.assertNotIn("closing.connect", (root / "main.py").read_text(encoding="utf-8"))
        from ui.dashboard import Dashboard
        self.assertTrue(hasattr(Dashboard, "windowClosing"))


class AltTitleTests(unittest.TestCase):
    def test_anilist_groups(self):
        from utils import alttitles
        g = alttitles.from_anilist({"english": "Spirited Away", "romaji": "Sen to Chihiro no Kamikakushi", "native": "千と千尋の神隠し"},
                                   ["Le Voyage de Chihiro", "千与千寻", "Унесённые призраками", "Spirited Away", "SA"])
        self.assertEqual(g["english"], ["Spirited Away"])
        self.assertEqual(g["romanized"], ["Sen to Chihiro no Kamikakushi"])
        self.assertEqual(g["native"], ["千と千尋の神隠し"])
        self.assertEqual(g["other"], ["Le Voyage de Chihiro", "千与千寻", "Унесённые призраками"])   # duplicates and nicknames go

    def test_kana_is_native_for_anime_with_a_latin_native_title(self):
        from utils import alttitles
        g = alttitles.from_anilist({"english": "ONE PIECE", "romaji": "ONE PIECE", "native": "ONE PIECE"}, ["ワンピース", "Ван-Пис"])
        self.assertEqual((g["native"], g["other"]), (["ワンピース"], ["Ван-Пис"]))

    def test_tmdb_groups_by_language(self):
        from utils import alttitles
        r = {"original_language": "ko", "original_title": "기생충", "title": "Parasite",
             "translations": {"translations": [{"iso_639_1": "en", "data": {"title": "Parasite"}},
                                               {"iso_639_1": "fr", "data": {"title": "Parasite (FR)"}},
                                               {"iso_639_1": "ko", "data": {"title": "기생충"}}]},
             "alternative_titles": {"titles": [{"iso_3166_1": "KR", "title": "Gisaengchung", "type": "Romanization"},
                                               {"iso_3166_1": "US", "title": "Parasite: Black and White", "type": ""}]}}
        g = alttitles.from_tmdb(r)
        self.assertEqual(g["native"], ["기생충"])
        self.assertEqual(g["english"], ["Parasite", "Parasite: Black and White"])
        self.assertEqual(g["romanized"], ["Gisaengchung"])
        self.assertEqual(g["other"], ["Parasite (FR)"])

    def test_display_hides_what_is_shown_and_search_finds_all(self):
        from utils import alttitles
        text = alttitles.dumps({"english": ["Spirited Away"], "romanized": ["Sen to Chihiro no Kamikakushi"],
                                "native": ["千と千尋の神隠し"], "other": ["El Viaje de Chihiro"]})
        rows = alttitles.for_display(text, ("Spirited Away", "千と千尋の神隠し"))
        self.assertEqual([r["group"] for r in rows], ["romanized", "other"])
        self.assertIn("El Viaje de Chihiro", alttitles.haystack(text))
        self.assertEqual(alttitles.for_display(None), [])
        self.assertIsNone(alttitles.dumps(alttitles.empty()))

    def test_search_matches_an_alternate_title(self):
        from ui.dashboard import library_view
        from utils import alttitles
        card = {"key": "k", "uuid": "u", "title": "Spirited Away", "media_type": "movie", "synopsis": "", "release_date": "2001", "file_path": "/x/s.mkv",
                "alt_titles": alttitles.dumps({"other": ["El Viaje de Chihiro"]})}
        self.assertEqual(len(library_view([card], {}, query="viaje")), 1)


class SecretTests(unittest.TestCase):
    def test_keys_go_through_dpapi(self):
        from utils import secret
        db.init_db()
        fake_box = {}

        def protect(t):
            if not t or t.startswith(secret.PREFIX):
                return t
            fake_box[t[::-1]] = t
            return secret.PREFIX + t[::-1]

        def unprotect(t):
            return fake_box.get(t[len(secret.PREFIX):], "") if t and t.startswith(secret.PREFIX) else (t or "")
        with mock.patch.object(secret, "protect", side_effect=protect), mock.patch.object(secret, "unprotect", side_effect=unprotect):
            db.set_setting("tmdb_key", "abc123")
            stored = db.conn().execute("SELECT value FROM settings WHERE key='tmdb_key'").fetchone()["value"]
            self.assertEqual(stored, secret.PREFIX + "321cba")              # never written in plain text
            self.assertEqual(db.get_setting("tmdb_key"), "abc123")
            db.set_setting("theme", "midnight")                             # other settings are untouched
            self.assertEqual(db.conn().execute("SELECT value FROM settings WHERE key='theme'").fetchone()["value"], "midnight")

    def test_plain_values_pass_through_off_windows(self):
        from utils import secret
        with mock.patch.object(secret, "available", return_value=False):
            self.assertEqual(secret.protect("k"), "k")
            self.assertEqual(secret.unprotect("k"), "k")
            self.assertEqual(secret.unprotect(secret.PREFIX + "AAAA"), "")     # cannot decrypt here: empty, asked again

    def test_old_plain_keys_are_encrypted_on_start(self):
        from utils import secret
        db.init_db()
        with db._tx() as c:
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('omdb_key', 'plain')")
        with mock.patch.object(secret, "available", return_value=True), \
                mock.patch.object(secret, "protect", side_effect=lambda t: secret.PREFIX + "x" if t else t):
            self.assertGreaterEqual(db.protect_secrets(), 1)
        self.assertTrue(db.conn().execute("SELECT value FROM settings WHERE key='omdb_key'").fetchone()["value"].startswith(secret.PREFIX))

    @unittest.skipUnless(sys.platform == "win32", "DPAPI is Windows only")
    def test_real_dpapi_round_trip(self):
        from utils import secret
        enc = secret.protect("my-key-123")
        self.assertTrue(enc.startswith(secret.PREFIX))
        self.assertNotIn("my-key-123", enc)
        self.assertEqual(secret.unprotect(enc), "my-key-123")


class DiscordTests(unittest.TestCase):
    def test_templates(self):
        from utils.discord_presence import fill
        self.assertEqual(fill("{title} ({year})", {"title": "Heat", "year": "1995"}), "Heat (1995)")
        self.assertEqual(fill("{title} ({year})", {"title": "Severance", "year": ""}), "Severance")
        self.assertEqual(fill("{type} · {episode}", {"kind": "movie"}), "Movie")
        self.assertEqual(fill("Now: {title} {nope}", {"title": "X"}), "Now: X")

    def test_privacy_rules(self):
        from utils.discord_presence import privacy
        item = {"parent_directory_id": 3, "media_type": "movie", "certification": "PG-13"}
        self.assertEqual(privacy(item, [], {}, True, []), "show")
        self.assertEqual(privacy({**item, "certification": "18+"}, [], {}, True, []), "generic")
        self.assertEqual(privacy({**item, "certification": "18+"}, [], {}, False, []), "show")
        self.assertEqual(privacy(item, ["genre:Hentai"], {}, True, []), "generic")
        self.assertEqual(privacy(item, ["Private"], {}, True, ["Private"]), "generic")
        self.assertEqual(privacy(item, [], {"3": "off"}, True, []), "off")
        self.assertEqual(privacy(item, [], {"3": "generic"}, True, []), "generic")
        self.assertEqual(privacy({**item, "media_type": "clip"}, [], {}, True, []), "generic")

    def test_activity(self):
        from utils.discord_presence import activity
        info = {"title": "Heat", "year": "1995", "kind": "movie", "paused": False, "position": 60, "duration": 600}
        self.assertEqual(activity({**info, "privacy": "off"}, "full"), None)
        self.assertEqual(activity({**info, "privacy": "generic"}, "full")["details"], "Watching a video")
        self.assertNotIn("Heat", str(activity({**info, "privacy": "generic"}, "full")))
        self.assertIsNone(activity({**info, "paused": True}, "title", opts={"discord_paused": "clear"}))
        a = activity(info, "full", now=1000, opts={"discord_details": "Watching {title}", "discord_state": "{type}",
                                                    "discord_image_text": "My PC"})
        self.assertEqual((a["details"], a["state"], a["assets"]["large_text"]), ("Watching Heat", "Movie", "My PC"))
        self.assertIn("timestamps", a)

    def test_settings_slots(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        db.init_db()
        presence = mock.Mock()
        app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=presence, play=lambda *a: None)
        d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())
        d.setDiscordFolder(7, "off")
        d.setDiscordHiddenTag("Private", True)
        p = d.discordPrivacy()
        self.assertEqual((p["folders"], p["tags"]), ({"7": "off"}, ["Private"]))
        d.setDiscordFolder(7, "show")
        d.setDiscordHiddenTag("Private", False)
        self.assertEqual(d.discordPrivacy()["folders"], {})
        self.assertTrue(presence.configure.called)
        pv = d.discordPreview("{title} — {type}", "{episode}", "show")
        self.assertEqual((pv["movie"], pv["showState"]), ("Blade Runner 2049 — Movie", "S01E02"))


class OpenWithTests(unittest.TestCase):
    def test_toggle_reads_windows_not_a_constant(self):
        qml = (Path(__file__).resolve().parent.parent / "ui" / "SettingsView.qml").read_text(encoding="utf-8")
        self.assertIn("checked: Backend.fileTypesOn()", qml)

    def test_refresh_repoints_a_moved_copy(self):
        import setup
        with mock.patch.object(setup, "file_types_command", return_value='"D:\\\\Old\\\\MediaVault.exe" "%1"'), \
                mock.patch.object(setup, "_open_command", return_value='"E:\\\\New\\\\MediaVault.exe" "%1"'), \
                mock.patch.object(setup, "register_file_types") as reg:
            self.assertTrue(setup.refresh_file_types())
        reg.assert_called_once()
        with mock.patch.object(setup, "file_types_command", return_value=None), mock.patch.object(setup, "register_file_types") as reg:
            self.assertFalse(setup.refresh_file_types())          # not offered: stays that way
        reg.assert_not_called()

    def test_uninstall_cleans_up(self):
        iss = (Path(__file__).resolve().parent.parent / "installer.iss").read_text(encoding="utf-8")
        self.assertIn('Subkey: "Software\\Classes\\MediaVault.Video"; Flags: uninsdeletekey dontcreatekey', iss)


class WheelClickTests(unittest.TestCase):
    def test_middle_button_toggles_full_screen(self):
        hud = (Path(__file__).resolve().parent.parent / "player" / "Hud.qml").read_text(encoding="utf-8")
        self.assertIn("acceptedButtons: Qt.LeftButton | Qt.MiddleButton", hud)
        self.assertIn("m.button === Qt.MiddleButton && !root.cropping && !root.pip", hud)
        self.assertIn("if (m.button !== Qt.LeftButton) return", hud)       # a wheel click never pauses
