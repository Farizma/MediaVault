"""Version, GitHub release check, installer download guard."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

import version  # noqa: E402
from utils import components  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_semver_and_compare(self):
        self.assertRegex(version.VERSION, r"^\d+\.\d+\.\d+$")
        self.assertTrue(components.newer("1.0.1", "1.0.0"))
        self.assertTrue(components.newer("1.10.0", "1.9.9"))
        self.assertFalse(components.newer("1.0.0", "1.0.0"))
        self.assertFalse(components.newer("", "1.0.0"))

    def test_installer_and_build_agree(self):
        root = Path(__file__).resolve().parent.parent
        iss = (root / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("OutputBaseFilename=MediaVault_v{#AppVersion}_setup", iss)
        self.assertIn("PrivilegesRequiredOverridesAllowed=dialog commandline", iss)
        self.assertEqual(version.SETUP_NAME.format(version="1.0.0"), "MediaVault_v1.0.0_setup.exe")


class ReleaseCheckTests(unittest.TestCase):
    def test_reads_latest_release(self):
        fake = {"tag_name": "v1.2.0", "html_url": "https://github.com/Farizma/MediaVault/releases/tag/v1.2.0", "body": "Notes",
                "assets": [{"name": "other.zip", "browser_download_url": "x"},
                           {"name": "MediaVault_v1.2.0_setup.exe",
                            "browser_download_url": "https://github.com/Farizma/MediaVault/releases/download/v1.2.0/MediaVault_v1.2.0_setup.exe"}]}
        with mock.patch.object(components, "_get_json", return_value=fake):
            r = components.app_release()
        self.assertEqual(r["version"], "1.2.0")
        self.assertTrue(r["setup"].endswith("MediaVault_v1.2.0_setup.exe"))

    def test_check_marks_app_update(self):
        rows = [{"id": "app", "installed": "1.0.0", "optional": False, "status": "ok", "latest": ""},
                {"id": "libmpv", "installed": "", "optional": False, "status": "missing", "latest": ""},
                {"id": "libvlc", "installed": "", "optional": False, "status": "missing", "latest": ""}]
        rel = {"version": "1.1.0", "page": "p", "setup": "s", "notes": ""}
        with mock.patch.object(components, "app_release", return_value=rel), \
                mock.patch("setup._latest_mpv", side_effect=OSError("offline")), \
                mock.patch.object(components, "latest_vlc", side_effect=OSError("offline")), \
                mock.patch.object(components, "frozen", return_value=True):
            out = components.check(rows)
        self.assertEqual((out[0]["status"], out[0]["latest"]), ("update", "1.1.0"))
        self.assertEqual(out[1]["status"], "missing")

    def test_download_only_from_this_repo(self):
        with self.assertRaises(ValueError):
            components.download_setup("https://evil.example/MediaVault_v9_setup.exe", "MediaVault_v9_setup.exe")
        with self.assertRaises(ValueError):
            components.download_setup("https://github.com/Farizma/MediaVault/releases/download/v9/x.zip", "x.zip")


if __name__ == "__main__":
    unittest.main()
