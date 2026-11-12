"""Build the Windows EXE, sign it, and wrap it in an installer. Run on Windows:  python build_installer.py

  1. icon.ico   the committed app icon (ui/brand/icon.svg, rendered at 16-256 px); a fallback is drawn if missing
  2. PyInstaller one-folder build  ->  dist/MediaVault/MediaVault.exe
  3. signing    only if MV_SIGN_SHA1 (certificate thumbprint) or MV_SIGN_PFX + MV_SIGN_PASSWORD is set
  4. installer  Inno Setup (iscc) on installer.iss  ->  dist/MediaVault_v<version>_setup.exe

The version comes from version.py. The GitHub workflow (.github/workflows/release.yml) runs this on a Windows
runner when a tag v<version> is pushed, and attaches the setup to the release.

Not run in the sandbox this project was written in. The first real build may need a --hidden-import
for whatever PyInstaller reports, or Qt QML modules added with --collect-all PySide6 if the HUD or
the 3D box are missing in the packaged app.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from version import VERSION  # noqa: E402
EXE = ROOT / "dist" / "MediaVault" / "MediaVault.exe"


def make_icon(path: Path) -> None:
    """Blue-to-green rounded square with a white play triangle."""
    from PIL import Image, ImageDraw
    size = 256
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            px[x, y] = (int(0 + 52 * t), int(122 + 77 * t), int(255 - 168 * t))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=58, fill=255)
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon.paste(grad, (0, 0), mask)
    ImageDraw.Draw(icon).polygon([(98, 72), (98, 184), (190, 128)], fill="white")
    icon.save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def command() -> list[str]:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", "MediaVault", "--paths", str(ROOT), "--icon", str(ROOT / "icon.ico"),
           "--collect-submodules", "watchdog",
           # Settings > Components reads package versions from their metadata, which PyInstaller leaves out by default
           *[a for d in ("PySide6", "python-mpv", "python-vlc", "watchdog", "pillow", "py7zr", "pychromecast", "pyatv")
             for a in ("--copy-metadata", d)],
           # Chromecast and AirPlay ship inside the app: the installed app has no Python for pip to install them into
           # (pyatv loads its protocols by name, so every submodule and data file comes along)
           "--collect-all", "pychromecast", "--collect-all", "pyatv", "--exclude-module", "numpy",
           "--hidden-import", "PySide6.QtMultimedia",
           "--hidden-import", "PySide6.QtQuickControls2", "--hidden-import", "PySide6.QtWidgets",
           "--add-data", f"{ROOT / 'ui'}{os.pathsep}ui",          # QML files
           "--add-data", f"{ROOT / 'player'}{os.pathsep}player"]  # Hud.qml
    if (ROOT / "bin").is_dir():  # libmpv / libvlc / shaders already downloaded: ship them
        cmd += ["--add-data", f"{ROOT / 'bin'}{os.pathsep}bin"]
    return cmd + [str(ROOT / "main.py")]


def sign(exe: Path) -> bool:
    thumb, pfx = os.environ.get("MV_SIGN_SHA1"), os.environ.get("MV_SIGN_PFX")
    if not (thumb or pfx):
        print("Not signing: set MV_SIGN_SHA1 (certificate thumbprint) or MV_SIGN_PFX + MV_SIGN_PASSWORD.")
        return False
    args = ["signtool", "sign", "/fd", "sha256", "/tr", "http://timestamp.digicert.com", "/td", "sha256"]
    args += ["/sha1", thumb] if thumb else ["/f", pfx, "/p", os.environ.get("MV_SIGN_PASSWORD", "")]
    subprocess.run(args + [str(exe)], check=True)
    return True


def find_iscc() -> str | None:
    found = shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        for sub in (r"Inno Setup 6\ISCC.exe", r"Programs\Inno Setup 6\ISCC.exe"):
            if base and (Path(base) / sub).exists():
                return str(Path(base) / sub)
    return None


def installer() -> Path | None:
    iscc = find_iscc()
    if not iscc:
        print("Inno Setup 6 (iscc) not found: install it from jrsoftware.org to build the setup.")
        return None
    subprocess.run([iscc, f"/DAppVersion={VERSION}", str(ROOT / "installer.iss")], check=True, cwd=ROOT)
    out = ROOT / "dist" / f"MediaVault_v{VERSION}_setup.exe"
    sign(out)
    return out


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Build on Windows: the EXE bundles Windows-only libraries.")
    if not (ROOT / "icon.ico").exists():
        make_icon(ROOT / "icon.ico")
    subprocess.run(command(), check=True, cwd=ROOT)
    signed = sign(EXE)
    setup_exe = installer()
    print("Done:", EXE, "(signed)" if signed else "(unsigned)", "|", setup_exe or "no installer")
