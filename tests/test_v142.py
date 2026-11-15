"""1.3.7: folder-cards tabs (Artists), box sets from "Part 1 / Ep 1" names, and tabs that do not track watched."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402
from tests.test_v133 import make_dashboard  # noqa: E402
from ui import dashboard  # noqa: E402

FILES = ("loose.mp4", "Ann/Lucy Part 1.mp4", "Ann/Lucy Part 2.mp4", "Ann/Solo.mp4", "Ann/Shorts/Mona Ep 1.mp4",
         "Ann/Shorts/Mona Ep.2.mp4", "Bea/Lucy Part 1.mp4", "Bea/Trip.mp4", "Cy/Only Part 1.mp4")


def library():
    db.init_db()
    with db._tx() as c:
        for t in ("media_items", "scanned_directories", "watch_history"):
            c.execute(f"DELETE FROM {t}")
    for k in ("folders_dirs", "nowatch_dirs", "partsets_dirs", "nosubtab_dirs"):
        db.set_setting(f"hidden_{k}", "")
    for k in ("folder_favs", "folder_sort", "excluded_subfolders"):
        db.set_setting(k, "")
    db.set_setting("group_collections", "1")
    root = Path(tempfile.mkdtemp())
    dir_id = db.add_directory(str(root), "Artists", False)
    rows = []
    for rel in FILES:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
        title = "Mona" if "Mona" in rel else p.stem          # what clean_name leaves of "Mona Ep 1"
        rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": dir_id, "title": title,
                     "media_type": "clip"})
    db.add_items(rows)
    return root, dir_id, {r["file_path"][len(db.norm(root)) + 1:]: r["uuid"] for r in rows}


class PartTests(unittest.TestCase):
    def test_names(self):
        self.assertEqual(db.part_name("Lucy Part 2"), ("Lucy", 2))
        self.assertEqual(db.part_name("Mona - Ep.02 - finale"), ("Mona", 2))
        self.assertEqual(db.part_name("Mona Episode 10"), ("Mona", 10))
        self.assertEqual(db.part_name("Bunny pt3"), ("Bunny", 3))
        for t in ("Part 1", "Departure 2", "Apartment 3", "The Party 2", "Trip"):
            self.assertIsNone(db.part_name(t), t)

    def test_grouping_per_subfolder(self):
        root, d, u = library()
        self.assertEqual(db.group_parts(d), 2)
        ann = db.get_media(u[os.path.join("Ann", "Lucy Part 1.mp4")])
        self.assertGreaterEqual(ann["collection_id"], db.PART_SET_OFFSET)
        self.assertEqual(ann["collection_name"], "Lucy")
        self.assertIsNone(db.get_media(u[os.path.join("Bea", "Lucy Part 1.mp4")])["collection_id"])   # another artist
        self.assertIsNone(db.get_media(u[os.path.join("Cy", "Only Part 1.mp4")])["collection_id"])    # one part only
        mona = db.get_media(u[os.path.join("Ann", "Shorts", "Mona Ep 1.mp4")])
        self.assertEqual(mona["title"], "Mona Ep 1")                       # its part number put back in the title
        cards = {c["title"]: c for c in db.list_library(d)}
        self.assertEqual(cards["Lucy"]["films"], 2)                          # clips make a box set too
        self.assertEqual([f["title"] for f in db.films_in_set(ann["collection_id"])], ["Lucy Part 1", "Lucy Part 2"])
        db.ungroup_parts(d)
        self.assertIsNone(db.get_media(ann["uuid"])["collection_id"])

    def test_your_own_sets_are_left_alone(self):
        root, d, u = library()
        uid = u[os.path.join("Ann", "Lucy Part 1.mp4")]
        with db._tx() as c:
            c.execute("UPDATE media_items SET collection_id=-7, collection_name='Mine' WHERE uuid=?", (uid,))
        db.group_parts(d)
        self.assertEqual(db.get_media(uid)["collection_id"], -7)


class FolderCardTests(unittest.TestCase):
    def setUp(self):
        self.root, self.dir, self.u = library()
        self.d = make_dashboard()
        self.d.toggleHidden("folders_dirs", str(self.dir))
        self.d.selectTab(self.dir)

    def test_cards_and_opening_them(self):
        self.assertTrue(self.d.folderMode)
        self.assertEqual([(c["rel"], c["count"]) for c in self.d.folderCards],
                         [("*", 9), ("~", 1), ("Ann", 5), ("Bea", 2), ("Cy", 1)])
        self.assertEqual(self.d.library._rows, [])                          # on the cards: no grid
        self.d.selectSubtab("Bea")
        self.assertEqual(sorted(r["title"] for r in self.d.library._rows), ["Lucy Part 1", "Trip"])
        self.d.selectSubtab("~")
        self.assertEqual([r["title"] for r in self.d.library._rows], ["loose"])
        self.d.selectSubtab("*")
        self.assertEqual(len(self.d.library._rows), 9)
        self.d.selectSubtab("")
        self.assertEqual(self.d.library._rows, [])

    def test_sort_and_pins(self):
        self.d.setFolderSort("count")
        self.assertEqual([c["rel"] for c in self.d.folderCards][2:], ["Ann", "Bea", "Cy"])
        self.d.toggleFolderFav("Cy")
        self.assertEqual([c["rel"] for c in self.d.folderCards][2:], ["Cy", "Ann", "Bea"])
        self.assertTrue(self.d.folderCards[2]["fav"])
        self.d.setFolderSort("bogus")
        self.assertEqual(self.d.folderSort, "count")

    def test_part_sets_switch(self):
        self.d.toggleHidden("partsets_dirs", str(self.dir))
        self.d.selectSubtab("Ann")
        self.assertIn("Lucy", [r["title"] for r in self.d.library._rows])
        self.assertTrue(next(x for x in self.d.directories() if x["id"] == self.dir)["partSets"])
        self.d.toggleHidden("partsets_dirs", str(self.dir))
        self.d.reload()
        self.assertNotIn("Lucy", [r["title"] for r in self.d.library._rows])


class NoWatchTests(unittest.TestCase):
    def test_no_progress_in_a_tab_that_does_not_track(self):
        root, d, u = library()
        uid = u["loose.mp4"]
        db.set_watched([uid], True)
        dash = make_dashboard()
        dash.selectTab(d)
        self.assertTrue(next(r for r in dash.library._rows if r["key"] == uid)["done"])
        dash.toggleHidden("nowatch_dirs", str(d))
        self.assertFalse(dash.trackWatched)
        self.assertFalse(next(r for r in dash.library._rows if r["key"] == uid)["done"])
        dash.selectTab(-1)
        self.assertTrue(dash.trackWatched)
        self.assertFalse(next(r for r in dash.library._rows if r["key"] == uid)["done"])   # in the All tab too


class CardRowsTests(unittest.TestCase):
    def test_folder_cards_without_art(self):
        root, d, _ = library()
        items = db.list_media(d)
        rows = dashboard.subtab_rows(str(root), items)
        cards = dashboard.folder_cards(d, str(root), items, rows, True, "name")
        self.assertEqual([c["kind"] for c in cards[:2]], ["all", "loose"])
        self.assertEqual(cards[2]["covers"], [])
        self.assertEqual(cards[2]["picture"], "")


if __name__ == "__main__":
    unittest.main()
