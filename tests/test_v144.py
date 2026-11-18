"""1.3.8: every file and folder chooser is Windows' own Explorer dialog (Qt's only as the fallback)."""
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

import ui  # noqa: E402
from utils import native_dialog  # noqa: E402


class FilterTests(unittest.TestCase):
    def test_qt_filters_become_windows_ones(self):
        self.assertEqual(native_dialog.parse_filter("Images (*.png *.jpg);;All files (*)"),
                         [("Images", "*.png;*.jpg"), ("All files", "*")])
        self.assertEqual(native_dialog.parse_filter("Media Vault backup (*.mvault *.zip)"),
                         [("Media Vault backup", "*.mvault;*.zip")])
        self.assertEqual(native_dialog.parse_filter(""), [])

    def test_guid(self):
        g = native_dialog.GUID.of(native_dialog.IID_IShellItem)
        self.assertEqual((hex(g.Data1), hex(g.Data2), list(g.Data4)[:2]), ("0x43826d1e", "0xe718", [0xbc, 0x55]))

    @unittest.skipIf(sys.platform == "win32", "elsewhere only")
    def test_not_windows_means_unavailable(self):
        self.assertIsNone(native_dialog.open_files("t"))
        self.assertIsNone(native_dialog.open_folder("t"))
        self.assertIsNone(native_dialog.save_file("t", "/tmp/x.mvault"))


class ChooserTests(unittest.TestCase):
    def test_the_explorer_dialog_is_used_first(self):
        with mock.patch.object(native_dialog, "open_files", return_value=["C:/a.png"]) as of, \
                mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName") as qt:
            self.assertEqual(ui.pick_image("/nowhere", "Choose"), "C:/a.png")
        qt.assert_not_called()
        title, start, filt, many, owner = of.call_args[0]
        self.assertEqual((title, many, owner), ("Choose", False, ui.DIALOG_OWNER))
        self.assertIn("*.png", filt)
        with mock.patch.object(native_dialog, "open_files", return_value=[]):
            self.assertEqual(ui.pick_image(), "")                                  # cancelled: no Qt dialog after it
        with mock.patch.object(native_dialog, "open_folder", return_value="C:/Media"):
            self.assertEqual(ui.pick_folder(), str(Path("C:/Media")))
        with mock.patch.object(native_dialog, "save_file", return_value="C:/b.mvault"):
            self.assertEqual(ui.save_file("Save", "C:/x.mvault", "Media Vault backup (*.mvault)"), "C:/b.mvault")

    def test_qt_when_explorer_is_unavailable(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        with mock.patch.object(native_dialog, "open_files", return_value=None), \
                mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileNames", return_value=(["a", "b"], "")):
            self.assertEqual(ui.pick_images("/x"), ["a", "b"])
        with mock.patch.object(native_dialog, "open_folder", return_value=None), \
                mock.patch("PySide6.QtWidgets.QFileDialog.getExistingDirectory", return_value=""):
            self.assertEqual(ui.pick_folder(), "")
        with mock.patch.object(native_dialog, "save_file", return_value=None), \
                mock.patch("PySide6.QtWidgets.QFileDialog.getSaveFileName", return_value=("/x.mvault", "")):
            self.assertEqual(ui.save_file("Save", "/y.mvault"), "/x.mvault")

    def test_no_chooser_builds_its_own_qt_dialog(self):
        src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "ui").glob("*.py"))
        self.assertNotIn("QFileDialog(", src)                       # an instance is what fell back to Qt's own look
        self.assertNotIn("QFileDialog.get", (ROOT / "ui" / "dashboard.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
