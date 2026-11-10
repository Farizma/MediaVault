"""Pure-logic checks of setup.py. No network, no pip, no windows."""
import unittest
from unittest import mock

import setup


def item(name, kind, ok, required=True, **kw):
    it = setup.Item(name, kind, required, lambda: ok, **kw)
    it.recheck()
    return it


class SetupLogic(unittest.TestCase):
    def test_can_start_needs_one_runtime(self):
        base = [item("py", "system", True), item("pkg", "python", True)]
        self.assertFalse(setup.can_start(base + [item("mpv", "runtime", False, False), item("vlc", "runtime", False, False)]))
        self.assertTrue(setup.can_start(base + [item("mpv", "runtime", True, False), item("vlc", "runtime", False, False)]))

    def test_missing_package_blocks_start(self):
        items = [item("pkg", "python", False), item("mpv", "runtime", True, False)]
        self.assertFalse(setup.can_start(items))

    def test_install_missing_runs_pip_once_then_runtimes(self):
        state = {"pkg": False, "mpv": False}
        pkg = setup.Item("a", "python", True, lambda: state["pkg"], pip="a")
        pkg2 = setup.Item("b", "python", True, lambda: state["pkg"], pip="b")
        rt = setup.Item("mpv", "runtime", False, lambda: state["mpv"], runtime="mpv")
        items = [pkg, pkg2, rt]
        for i in items:
            i.recheck()

        def fake_pip(specs, log=print):
            self.assertEqual(specs, ["a", "b"])
            state["pkg"] = True

        def fake_rt(name, log):
            self.assertTrue(state["pkg"])  # packages first
            state["mpv"] = True

        with mock.patch.object(setup, "pip_install", fake_pip), mock.patch.object(setup, "_install_runtime", fake_rt), \
                mock.patch.object(setup, "_file_log"):
            left = setup.install_missing(items)
        self.assertEqual(left, [])

    def test_runtime_skipped_when_pip_failed(self):
        pkg = setup.Item("a", "python", True, lambda: False, pip="a")
        rt = setup.Item("mpv", "runtime", False, lambda: False, runtime="mpv")
        called = []
        with mock.patch.object(setup, "pip_install", side_effect=RuntimeError("offline")), \
                mock.patch.object(setup, "_install_runtime", lambda *a: called.append(1)), mock.patch.object(setup, "_file_log"):
            left = setup.install_missing([pkg, rt])
        self.assertEqual(len(left), 2)
        self.assertEqual(called, [])
        self.assertIn("offline", pkg.detail)

    def test_run_setup_instant_when_all_ok(self):
        ok = [item("x", "python", True)]
        with mock.patch.object(setup, "scan", return_value=ok), mock.patch.object(setup, "_setup_window") as w:
            self.assertTrue(setup.run_setup())
            w.assert_not_called()

    def test_run_setup_has_no_skip_when_required_missing(self):
        bad = [item("pkg", "python", False), item("mpv", "runtime", True, False)]
        with mock.patch.object(setup, "scan", return_value=bad), mock.patch.object(setup, "_file_log"), \
                mock.patch.object(setup, "_setup_window", return_value=False):
            self.assertFalse(setup.run_setup())

    def test_zip_slip_rejected(self):
        import io, tempfile, zipfile
        from pathlib import Path
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../evil.txt", "x")
        with zipfile.ZipFile(buf) as z, tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                setup._safe_extract(z, Path(d))


if __name__ == "__main__":
    unittest.main()
