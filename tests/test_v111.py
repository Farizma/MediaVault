"""1.1.1: a click outside a text box saves it and ends the edit; every title has the pencil / check mark."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QML = b"""
import QtQuick
import QtQuick.Controls
Item {
    width: 400; height: 300
    property int saved: 0
    Item {
        objectName: "home"; property bool focusHome: true
        anchors.fill: parent
        TextField { objectName: "field"; x: 10; y: 10; width: 200; height: 40
            onActiveFocusChanged: if (!activeFocus) parent.parent.saved++ }
        Popup { objectName: "pop"; x: 10; y: 200; width: 100; height: 60; visible: true; closePolicy: Popup.NoAutoClose }
    }
}
"""


class ClickAwayTests(unittest.TestCase):
    def test_click_outside_ends_the_edit(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQuick import QQuickView
        from PySide6.QtTest import QTest
        QGuiApplication.instance() or QGuiApplication([])
        from ui.clickaway import ClickAway
        qml = Path(tempfile.mkdtemp()) / "t.qml"
        qml.write_bytes(QML)
        view = QQuickView()
        view.setSource(qml.as_uri())
        view.show()
        f = ClickAway()
        view.installEventFilter(f)
        root = view.rootObject()
        field = [i for i in root.findChildren(type(root)) if i.objectName() == "field"][0]
        home = [i for i in root.findChildren(type(root)) if i.objectName() == "home"][0]

        def click(x, y):
            QTest.mouseClick(view, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
            QTest.qWait(20)
        field.forceActiveFocus(); QTest.qWait(20)
        click(50, 25)                                   # in the box: still editing
        self.assertTrue(field.hasActiveFocus())
        click(60, 225)                                  # in a popup (a suggestion): still editing
        self.assertTrue(field.hasActiveFocus())
        click(300, 150)                                 # empty space: saved, focus home
        self.assertFalse(field.hasActiveFocus())
        self.assertEqual(root.property("saved"), 1)
        self.assertTrue(home.hasActiveFocus())


class PencilTests(unittest.TestCase):
    def test_every_title_has_the_pencil(self):
        qml = (ROOT / "ui" / "DetailView.qml").read_text(encoding="utf-8")
        pencil = qml[qml.index("id: pencil"):qml.index("id: pencil") + 200]
        self.assertNotIn("visible: root.d.isSet", pencil)
        self.assertIn("readonly property bool picker: !root.renaming", qml)
        self.assertIn("readonly property bool focusHome: true", qml)
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("engine.rootObjects()[0].installEventFilter(app.click_away)", main)

    def test_in_workflow(self):
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tests.test_v111", wf)


if __name__ == "__main__":
    unittest.main()
