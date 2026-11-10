"""Windows only (skipped elsewhere): registry round trip and GPU lookup."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@unittest.skipUnless(sys.platform == "win32", "needs Windows")
class WindowsTests(unittest.TestCase):
    def test_file_types_register_and_unregister(self):
        import winreg

        import setup
        setup.register_file_types((".mvtest",))
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{setup.PROG_ID}\shell\open\command") as k:
            self.assertIn("%1", winreg.QueryValueEx(k, None)[0])
        setup.unregister_file_types((".mvtest",))
        with self.assertRaises(FileNotFoundError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{setup.PROG_ID}")

    def test_gpu_lookup_returns_adapter_names(self):
        from utils import hw_accelerator
        names = hw_accelerator.gpu_names()
        self.assertTrue(names and all(isinstance(n, str) for n in names))

    def test_libmpv_probe_reads_a_real_file(self):  # set MV_TEST_VIDEO to any video file
        import os

        from utils import media_probe
        video = os.environ.get("MV_TEST_VIDEO")
        if not video:
            self.skipTest("set MV_TEST_VIDEO")
        info = media_probe.probe(video)
        self.assertTrue(info["duration"] and info["resolution"])


if __name__ == "__main__":
    unittest.main()
