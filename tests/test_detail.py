"""The View More data, through the real Dashboard (the screenshot harness uses a stand-in, so it cannot catch these)."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import database as db  # noqa: E402


class DetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtGui import QGuiApplication
        cls.qapp = QGuiApplication.instance() or QGuiApplication([])
        from ui.dashboard import Dashboard, LibraryModel, TabsModel
        from ui.dvd_box import FrameProvider
        db.init_db()
        cls.root = tempfile.mkdtemp()
        did = db.add_directory(cls.root, "D", True)

        def row(name, kind="movie", sub="", **kw):
            folder = os.path.join(cls.root, sub) if sub else cls.root
            os.makedirs(folder, exist_ok=True)
            p = os.path.join(folder, f"{name}.mkv")
            open(p, "w").close()
            r = {"uuid": db.file_id(p), "file_path": db.norm(p), "parent_directory_id": did, "title": name, "media_type": kind,
                 "duration": 6000, "resolution": "1920x1080", "codec": "H.264", "container": ".mkv", "audio_layout": "5.1"}
            r.update(kw)
            return r
        rows = [row("Heat", release_date="1995", score=8.3),
                row("Dune", collection_id=7, collection_name="Dune Collection", release_date="2021"),
                row("Dune Two", collection_id=7, collection_name="Dune Collection", release_date="2024"),
                row("Show S01E01", "show", "Show"), row("Show S01E02", "show", "Show")]
        db.add_items(rows)
        cls.movie, cls.show_folder = rows[0]["uuid"], os.path.dirname(rows[3]["file_path"])
        db.set_cast(cls.movie, [{"id": 1, "name": "Al Pacino", "role": "Hanna"}])
        app = types.SimpleNamespace(engine=types.SimpleNamespace(hw=None), presence=None, play=lambda *a: None)
        cls.d = Dashboard(app, LibraryModel(), TabsModel(), FrameProvider())

    def test_movie(self):
        r = self.d.detail(self.movie)
        self.assertEqual(r["title"], "Heat")
        self.assertEqual(r["cast"][0]["name"], "Al Pacino")
        self.assertIn({"label": "File type", "value": ".mkv"}, r["facts"])
        self.assertEqual(r["score"], 8.3)
        self.assertTrue(r["canMatch"] and r["canSet"])

    def test_series(self):
        r = self.d.detail("show:" + self.show_folder)
        self.assertTrue(r["isShow"])
        self.assertEqual(len(r["episodes"]), 2)

    def test_box_set_and_each_film(self):
        r = self.d.detail("set:7")
        self.assertTrue(r["isSet"])
        self.assertEqual([s["label"] for s in r["slides"]], ["Box set", "Film 1 of 2", "Film 2 of 2"])
        for s in r["slides"][1:]:
            film = self.d.detail(s["uuid"])          # what the carousel loads for the right-hand pane
            self.assertEqual(film["title"], s["title"])
            self.assertEqual(film["boxSet"]["key"], "set:7")


class NoShadowedMethodsTests(unittest.TestCase):
    def test_no_class_defines_a_method_twice(self):
        import ast
        root = Path(__file__).resolve().parent.parent
        dupes = []
        for f in root.rglob("*.py"):
            if "tests" in f.parts or "build" in f.parts:
                continue
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ClassDef):
                    seen = set()
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            # @x.setter re-defines a property on purpose
                            setter = any(isinstance(d, ast.Attribute) and d.attr in ("setter", "deleter") for d in item.decorator_list)
                            if item.name in seen and not setter:
                                dupes.append(f"{f.name}: {node.name}.{item.name}")
                            seen.add(item.name)
        self.assertEqual(dupes, [])


if __name__ == "__main__":
    unittest.main()
