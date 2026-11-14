"""1.3.1: DVD box art beside the files is found while scraping; wheel scrolling glides and passes over sideways rows
and text boxes; the synopsis box resizes from its corner."""
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
from utils import boxart, scraper  # noqa: E402


class BoxArtTests(unittest.TestCase):
    def setUp(self):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.instance() or QGuiApplication([])
        db.init_db()
        with db._tx() as c:
            for t in ("media_items", "scanned_directories"):
                c.execute(f"DELETE FROM {t}")
        self.root = Path(tempfile.mkdtemp())
        self.dir = db.add_directory(str(self.root), "Films", True)
        (self.root / "Solo").mkdir()
        (self.root / "Show").mkdir()
        rows = []
        for rel, kind in (("Heat.mkv", "movie"), ("Alien.mkv", "movie"), ("Solo/Solo.mkv", "movie"),
                          ("Show/Show S01E01.mkv", "show"), ("Show/Show S01E02.mkv", "show")):
            p = self.root / rel
            p.write_bytes(b"")
            rows.append({"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": self.dir,
                         "title": p.stem, "media_type": kind})
        db.add_items(rows)
        self.heat, self.alien, self.solo, self.e1, self.e2 = (db.get_media(r["uuid"]) for r in rows)

    @staticmethod
    def sleeve(path, w=1480, h=1000):
        """A whole cover: blue back | white spine | red front, as a sleeve lies flat."""
        img = Image.new("RGB", (w, h), "blue")
        img.paste((255, 255, 255), (int(w * 0.475), 0, int(w * 0.525), h))
        img.paste((255, 0, 0), (int(w * 0.525), 0, w, h))
        img.save(path)

    def colour(self, path):
        return Image.open(path).convert("RGB").resize((1, 1)).getpixel((0, 0))

    def test_sleeve_named_after_the_film(self):
        self.sleeve(self.root / "Heat-dvdcover.jpg")
        Image.new("RGB", (300, 300), "green").save(self.root / "cover.jpg")   # several films here: a plain name is not Heat's
        self.assertEqual(boxart.scan(db.get_directory(self.dir)), 1)
        front, back = scraper.custom_front_path(self.heat), scraper.custom_back_path(self.heat)
        self.assertTrue(front.exists() and back.exists() and scraper.custom_spine_path(self.heat).exists())
        self.assertGreater(self.colour(front)[0], 200)                      # red front
        self.assertGreater(self.colour(back)[2], 200)                       # blue back
        self.assertFalse(scraper.custom_front_path(self.alien).exists())
        self.assertEqual(boxart.scan(db.get_directory(self.dir)), 0)       # used once
        front.unlink(); back.unlink(); scraper.custom_spine_path(self.heat).unlink()    # Reset in View More
        self.assertEqual(boxart.scan(db.get_directory(self.dir)), 0)       # ... stays reset

    def test_plain_names_in_a_folder_of_one(self):
        Image.new("RGB", (540, 760), "red").save(self.root / "Solo" / "cover.png")
        Image.new("RGB", (540, 760), "blue").save(self.root / "Solo" / "back.jpg")
        boxart.scan(db.get_directory(self.dir))
        self.assertGreater(self.colour(scraper.custom_front_path(self.solo))[0], 200)
        self.assertGreater(self.colour(scraper.custom_back_path(self.solo))[2], 200)
        self.assertFalse(scraper.custom_spine_path(self.solo).exists())    # a front only: the spine is drawn as before

    def test_a_series_sleeve_covers_every_episode(self):
        self.sleeve(self.root / "Show" / "Show-boxart.webp")
        boxart.scan(db.get_directory(self.dir))
        for ep in (self.e1, self.e2):
            self.assertTrue(scraper.custom_front_path(ep).exists())

    def test_your_own_art_wins(self):
        Image.new("RGB", (540, 760), "green").save(scraper.custom_front_path(self.heat).parent.mkdir(parents=True, exist_ok=True) or scraper.custom_front_path(self.heat))
        self.sleeve(self.root / "Heat-cover.jpg")
        boxart.scan(db.get_directory(self.dir))
        self.assertGreater(self.colour(scraper.custom_front_path(self.heat))[1], 100)   # still green
        self.assertFalse(scraper.custom_back_path(self.heat).exists())

    def test_fetch_missing_looks_even_without_a_key(self):
        import watcher
        self.sleeve(self.root / "Alien-cover.jpg")
        with mock.patch.object(scraper, "api_keys", return_value={"tmdb": "", "omdb": "", "fanart": ""}):
            self.assertEqual(watcher.fetch_missing(db.get_directory(self.dir)), 1)
        self.assertTrue(scraper.custom_front_path(self.alien).exists())

    def test_a_broken_file_is_skipped(self):
        (self.root / "Heat-cover.jpg").write_bytes(b"not an image")
        self.assertEqual(boxart.scan(db.get_directory(self.dir)), 0)


class WheelTests(unittest.TestCase):
    """Real wheel events through a window: a page with a text box and a sideways row inside it."""

    PAGE = """
import QtQuick
import QtQuick.Controls
import "%s"
Item {
    width: 600; height: 400
    Flickable {
        id: page; objectName: "page"; anchors.fill: parent; contentHeight: 3000
        SmoothWheel { view: page; step: 200 }
        Area { objectName: "area"; x: 20; y: 20; width: 300; height: 100; text: Array(80).join("line of text\\n") }
        ListView { id: row; objectName: "row"; x: 20; y: 160; width: 400; height: 80
                   orientation: ListView.Horizontal; interactive: false
                   SideWheel { view: row } SideWheel { view: row; shift: true }
                   model: 30; delegate: Rectangle { width: 100; height: 80 } }
    }
}"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QObject, QUrl
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQuick import QQuickView
        from PySide6.QtTest import QTest
        import ui
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        f = Path(tempfile.mkdtemp()) / "page.qml"
        f.write_text(cls.PAGE % (ROOT / "ui").as_uri())
        cls.view = QQuickView()
        cls.view.rootContext().setContextProperty("Theme", ui.THEME)
        cls.view.setSource(QUrl.fromLocalFile(str(f)))
        assert not cls.view.errors(), [e.toString() for e in cls.view.errors()]
        cls.view.show()
        QTest.qWait(100)
        root = cls.view.rootObject()
        cls.page, cls.area, cls.row = (root.findChild(QObject, n) for n in ("page", "area", "row"))

    def wheel(self, x, y, dy=0, dx=0, pixel=False, shift=False):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QGuiApplication, QWheelEvent
        pos = QPointF(x, y)
        d = QPoint(dx, dy)
        ev = QWheelEvent(pos, self.view.mapToGlobal(pos.toPoint()), d if pixel else QPoint(), d,
                         Qt.NoButton, Qt.ShiftModifier if shift else Qt.NoModifier, Qt.NoScrollPhase, False)
        QGuiApplication.sendEvent(self.view, ev)

    def settle(self, ms=400):
        from PySide6.QtTest import QTest
        QTest.qWait(ms)

    def setUp(self):
        self.page.setProperty("contentY", 0)
        self.row.setProperty("contentX", 0)
        for i in self.items(self.area):                       # nobody is typing in the text box
            if "TextArea" in i.metaObject().className():
                i.setProperty("focus", False)
        self.area.property("contentItem").setProperty("contentY", 0)
        self.settle(50)

    @classmethod
    def items(cls, i):
        yield i
        for c in i.childItems():
            yield from cls.items(c)

    def y(self):
        return self.page.property("contentY")

    def test_notches_and_small_steps_glide_to_the_same_place(self):
        self.wheel(500, 300, -120); self.settle()
        self.assertAlmostEqual(self.y(), 200, delta=1)
        self.wheel(500, 300, 120); self.settle()
        for _ in range(10):                                   # a smooth-scrolling mouse: 10 steps of 24 = 2 notches
            self.wheel(500, 300, -24)
        self.settle()
        self.assertAlmostEqual(self.y(), 400, delta=1)

    def test_glide_moves_a_little_every_frame(self):
        from PySide6.QtTest import QTest
        self.wheel(500, 300, -120)
        seen = []
        for _ in range(10):
            QTest.qWait(16)
            seen.append(self.y())
        self.assertEqual(seen, sorted(seen))
        self.assertGreaterEqual(len({round(v) for v in seen if 0 < v < 199}), 3)   # passes through, no jump to the end

    def test_touchpad_follows_the_fingers(self):
        self.wheel(500, 300, -40, pixel=True); self.settle(30)
        self.assertEqual(self.y(), 40)

    def test_the_page_scrolls_over_a_sideways_row_and_a_text_box(self):
        self.wheel(100, 200, -120); self.settle()
        self.assertAlmostEqual(self.y(), 200, delta=1)
        self.assertEqual(self.row.property("contentX"), 0)
        self.page.setProperty("contentY", 0); self.settle(50)
        self.wheel(100, 70, -120); self.settle()
        self.assertAlmostEqual(self.y(), 200, delta=1)

    def test_the_row_scrolls_sideways(self):
        self.wheel(100, 200, 0, -120); self.settle(50)
        self.assertEqual(self.row.property("contentX"), 120)
        self.wheel(100, 200, -120, shift=True); self.settle(50)
        self.assertEqual(self.row.property("contentX"), 240)
        self.assertEqual(self.y(), 0)

    def test_a_text_box_you_are_typing_in_scrolls_its_text(self):
        field = next(i for i in self.items(self.area) if "TextArea" in i.metaObject().className())
        field.forceActiveFocus(); self.settle(30)
        self.wheel(100, 70, -120); self.settle()
        self.assertGreater(self.area.property("contentItem").property("contentY"), 0)
        self.assertEqual(self.y(), 0)


class ResizeTests(unittest.TestCase):
    """The synopsis box's corner grip: drag to change its height; the height is remembered."""

    PAGE = """
import QtQuick
import QtQuick.Layouts
import "%s"
Item {
    width: 500; height: 500
    ColumnLayout {
        width: 400
        Area { objectName: "area"; Layout.fillWidth: true; Layout.preferredHeight: 104; resizable: true; sizeKey: "synopsis_box_height"
               text: "Some words" }
        Rectangle { objectName: "below"; Layout.fillWidth: true; Layout.preferredHeight: 20 }
    }
}"""

    def make(self):
        from PySide6.QtCore import QObject, QUrl, Slot
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQuick import QQuickView
        from PySide6.QtTest import QTest
        import ui
        QGuiApplication.instance() or QGuiApplication([])

        class Backend(QObject):
            store = self.store

            @Slot(str, result=str)
            def setting(self, k):
                return self.store.get(k, "")

            @Slot(str, str)
            def setSetting(self, k, v):
                self.store[k] = v
        self.backend = Backend()
        f = Path(tempfile.mkdtemp()) / "page.qml"
        f.write_text(self.PAGE % (ROOT / "ui").as_uri())
        view = QQuickView()
        view.rootContext().setContextProperty("Theme", ui.THEME)
        view.rootContext().setContextProperty("Backend", self.backend)
        view.setSource(QUrl.fromLocalFile(str(f)))
        self.assertFalse(view.errors(), [e.toString() for e in view.errors()])
        view.show()
        QTest.qWait(100)
        return view, view.rootObject().findChild(QObject, "area"), view.rootObject().findChild(QObject, "below")

    def drag(self, view, area, dy):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtTest import QTest
        p = area.mapToScene(QPointF(area.property("width") - 8, area.property("height") - 8)).toPoint()
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, p)
        for i in range(1, 6):
            QTest.mouseMove(view, QPoint(p.x(), p.y() + dy * i // 5))
            QTest.qWait(10)
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, QPoint(p.x(), p.y() + dy))
        QTest.qWait(50)

    def test_drag_the_corner(self):
        self.store = {}
        view, area, below = self.make()
        self.assertEqual(area.property("height"), 104)
        self.drag(view, area, 120)
        self.assertEqual(area.property("height"), 224)
        self.assertGreaterEqual(below.property("y"), 224)                 # what is under it moves down
        self.assertEqual(self.store["synopsis_box_height"], "224")
        self.drag(view, area, -400)
        self.assertEqual(area.property("height"), 72)                      # never smaller than a few lines

    def test_the_height_is_remembered(self):
        self.store = {"synopsis_box_height": "300"}
        view, area, _ = self.make()
        self.assertEqual(area.property("height"), 300)


if __name__ == "__main__":
    unittest.main()
