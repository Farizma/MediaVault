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
