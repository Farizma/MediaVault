"""1.3.6: subtabs from a folder's subfolders, and actors you add (with a photo shared by every title)."""
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
from PIL import Image  # noqa: E402
from tests.test_v133 import make_dashboard  # noqa: E402
from ui import dashboard  # noqa: E402
from utils import scraper  # noqa: E402


def fresh_library():
    db.init_db()
    with db._tx() as c:
        for t in ("media_items", "scanned_directories", "cast_members", "custom_people"):
            c.execute(f"DELETE FROM {t}")
    db.set_setting("hidden_nosubtab_dirs", "")
    db.set_setting("excluded_subfolders", "")
    root = Path(tempfile.mkdtemp())
    dir_id = db.add_directory(str(root), "Movies", False)
    rows = []
    for rel in ("top.mkv", "English/a.mkv", "English/Deep/b.mkv", "japanese/c.mkv"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
        rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": dir_id,
                     "title": p.stem, "media_type": "movie"})
    db.add_items(rows)
    return root, dir_id, [r["uuid"] for r in rows]


class SubtabTests(unittest.TestCase):
    def setUp(self):
        self.root, self.dir, self.uids = fresh_library()
        self.d = make_dashboard()

    def titles(self):
        return sorted(r["title"] for r in self.d.library._rows)

    def test_rows(self):
        self.assertEqual(dashboard.subtab_rows(str(self.root), db.list_media(self.dir)),
                         [{"rel": "English", "name": "English", "count": 2}, {"rel": "japanese", "name": "japanese", "count": 1}])
        self.assertEqual(dashboard.subtab_rows(str(self.root), [{"file_path": str(self.root / "x.mkv")}]), [])

    def test_choosing_a_subtab_filters_the_grid_only(self):
        self.d.selectTab(self.dir)
        self.assertEqual([r["name"] for r in self.d.subtabs], ["English", "japanese"])
        self.assertEqual(self.titles(), ["a", "b", "c", "top"])
        self.d.selectSubtab("English")
        self.assertEqual(self.d.subtab, "English")
        self.assertEqual(self.titles(), ["a", "b"])                     # and what is in its subfolders
        self.d.selectTab(-1)
        self.assertEqual((self.d.subtabs, self.d.subtab), ([], ""))      # the All tab has none
        self.assertEqual(len(self.d.library._rows), 4)
        self.d.selectTab(self.dir)
        self.assertEqual(self.titles(), ["a", "b"])                     # each tab keeps its subtab
        self.d.selectSubtab("")
        self.assertEqual(len(self.d.library._rows), 4)

    def test_off_per_folder_and_gone_subfolder(self):
        self.d.selectTab(self.dir)
        self.d.selectSubtab("japanese")
        db.set_excluded_subfolders(self.dir, ["japanese"])
        self.d.reload()
        self.assertEqual((self.d.subtab, [r["rel"] for r in self.d.subtabs]), ("", ["English"]))
        self.d.toggleHidden("nosubtab_dirs", str(self.dir))
        self.assertEqual(self.d.subtabs, [])
        self.assertFalse(next(x for x in self.d.directories() if x["id"] == self.dir)["subtabs"])


class ActorTests(unittest.TestCase):
    def setUp(self):
        self.root, self.dir, self.uids = fresh_library()
        self.d = make_dashboard()
        self.photo = self.root / "face.png"
        Image.new("RGB", (300, 400), "red").save(self.photo)

    def cast(self, uid):
        return [(p["name"], p["role"]) for p in db.get_cast(uid)]

    def test_add_to_many_with_a_photo(self):
        db.set_cast(self.uids[0], [{"id": 42, "name": "Ann Lee", "role": "Pilot"}])
        n = self.d.addActor(self.uids[:3], "  Sam   Field ", "Narrator", str(self.photo))
        self.assertEqual(n, 3)
        pid = db.person_named("sam field")                               # the same person everywhere, any case
        self.assertGreaterEqual(pid, db.CUSTOM_PERSON_OFFSET)
        self.assertEqual(self.cast(self.uids[0]), [("Ann Lee", "Pilot"), ("Sam Field", "Narrator")])
        self.assertEqual(self.cast(self.uids[2]), [("Sam Field", "Narrator")])
        self.assertTrue(scraper.custom_person_photo_path(pid).exists())
        self.assertEqual(self.d.addActor(self.uids[:1], "Sam Field", "", ""), 0)   # already there
        self.assertEqual(db.people("sam")[0]["titles"], 3)

    def test_existing_person_and_photo_override(self):
        db.set_cast(self.uids[0], [{"id": 42, "name": "Ann Lee", "role": "Pilot"}])
        self.d.addActor([self.uids[1]], "ann lee", "", "")
        self.assertEqual(db.get_cast(self.uids[1])[0]["person_id"], 42)   # the scraped Ann Lee, not a new one
        cached = scraper.person_photo_path(42)
        cached.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (10, 10)).save(cached, "WEBP")
        with mock.patch.object(dashboard, "pick_image", lambda *a: str(self.photo)):
            self.assertTrue(self.d.setActorPhoto("Ann Lee"))
        self.assertEqual(scraper.person_photo_path(42), scraper.custom_person_photo_path(42))   # yours wins
        self.assertEqual(self.d._cast_list(db.get_media(self.uids[1]))[0]["id"], 42)

    def test_remove_and_bad_photo(self):
        self.d.addActor([self.uids[0]], "Kim", "", "")
        self.d.removeActor(self.uids[0], "Kim")
        self.assertEqual(db.get_cast(self.uids[0]), [])
        junk = self.root / "not.png"
        junk.write_text("no")
        self.assertEqual(self.d.addActor([self.uids[0]], "Kim", "", str(junk)), 0)
        self.assertEqual(db.get_cast(self.uids[0]), [])
        self.assertEqual(self.d.addActor([self.uids[0]], "   ", "", ""), 0)

    def test_no_id_cast_gets_one(self):
        db.set_cast(self.uids[0], [{"id": None, "name": "Omar", "role": ""}])
        pid = db.give_person_id("Omar")
        self.assertEqual(db.get_cast(self.uids[0])[0]["person_id"], pid)


if __name__ == "__main__":
    unittest.main()
