"""Settings > Components: every tool Media Vault uses, the version on this PC, and whether a newer one exists.

The installed EXE carries its Python packages inside it, so those update together with Media Vault; libmpv,
libVLC and the upscaling shader live in bin/ and update on their own. A source install (python main.py)
updates its packages with pip.
"""
import importlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import version

UA = {"User-Agent": f"MediaVault/{version.VERSION}"}

# id, name, what it does, pip name (python packages), optional
PACKAGES = [
    ("pyside6", "PySide6 (Qt)", "Windows, animations and the 3D box", "PySide6", False),
    ("python-mpv", "python-mpv", "Talks to libmpv", "python-mpv", False),
    ("python-vlc", "python-vlc", "Talks to libVLC", "python-vlc", False),
    ("watchdog", "watchdog", "Notices new files in your folders", "watchdog", False),
    ("pillow", "Pillow", "Covers, posters and actor photos", "pillow", False),
    ("py7zr", "py7zr", "Unpacks the libmpv download", "py7zr", False),
    ("pychromecast", "PyChromecast", "Chromecast (optional add-on)", "pychromecast", True),
    ("pyatv", "pyatv", "AirPlay (optional add-on)", "pyatv", True),
]


def frozen() -> bool:
    return getattr(sys, "frozen", False)


def _vt(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def newer(latest: str, installed: str) -> bool:
    return bool(latest) and _vt(latest) > _vt(installed)


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, "Accept": "application/vnd.github+json"}), timeout=15) as r:
        return json.load(r)


def _dist_version(dist: str) -> str:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _libvlc_version() -> str:
    try:
        import vlc
        return (vlc.libvlc_get_version() or b"").decode(errors="replace").split()[0]
    except Exception:
        return ""


def inventory() -> list[dict]:
    """What is on this PC. Each row: id, name, role, installed (version or ""), kind, optional, updatable."""
    import setup
    from utils import bin_dir
    import utils
    utils.use_bin_dir()
    rows = [{"id": "app", "name": "Media Vault", "role": "This app", "installed": version.VERSION, "kind": "app"},
            {"id": "python", "name": "Python", "role": "Runs Media Vault" + (" (built in)" if frozen() else ""),
             "installed": "%d.%d.%d" % sys.version_info[:3], "kind": "bundled" if frozen() else "system"}]
    try:
        from PySide6 import QtCore
        qt = QtCore.qVersion()
    except Exception:
        qt = ""
    mpv_file = bin_dir() / "mpv.version"
    mpv_build = mpv_file.read_text(encoding="utf-8").strip() if mpv_file.exists() else ""
    mpv_date = re.search(r"(\d{8})", mpv_build)
    has_mpv = setup.has_lib("mpv")
    rows.append({"id": "libmpv", "name": "libmpv", "role": "Main video engine (dedicated GPUs, upscaling, HDR)",
                 "installed": (mpv_date[1][:4] + "-" + mpv_date[1][4:6] + "-" + mpv_date[1][6:] if mpv_date else "installed")
                 if has_mpv else "", "build": mpv_build, "kind": "runtime"})
    rows.append({"id": "libvlc", "name": "libVLC", "role": "Second video engine (low-power GPUs)",
                 "installed": _libvlc_version() if setup.has_lib("vlc") else "", "kind": "runtime"})
    from utils.hw_accelerator import SHADER
    shader = bin_dir() / "shaders" / SHADER
    rows.append({"id": "shader", "name": "FSRCNNX shader", "role": "High-quality upscaling (MPV)",
                 "installed": "1.1" if shader.is_file() else "", "kind": "runtime", "optional": True})
    for pid, name, role, dist, optional in PACKAGES:
        installed = _dist_version(dist)
        if pid == "pyside6" and qt:
            installed = (installed or "") + (f" · Qt {qt}" if installed else f"Qt {qt}")
        rows.append({"id": pid, "name": name, "role": role, "installed": installed, "pip": dist,
                     "kind": "bundled" if frozen() and not optional else "python", "optional": optional})
    for r in rows:
        r.setdefault("optional", False)
        r.setdefault("latest", "")
        r.setdefault("status", "ok" if r["installed"] else ("optional" if r["optional"] else "missing"))
    return rows


def _pip_outdated() -> dict:
    """{pip name (lower): newest version} for packages pip can update. Source installs only."""
    from setup import NO_WINDOW, _python_exe
    out = subprocess.run([_python_exe(), "-m", "pip", "list", "--outdated", "--format=json"], capture_output=True,
                         text=True, timeout=180, creationflags=NO_WINDOW if sys.platform == "win32" else 0)
    return {p["name"].lower(): p["latest_version"] for p in json.loads(out.stdout or "[]")} if out.returncode == 0 else {}


def latest_vlc() -> str:
    from setup import VLC_INDEX, _fetch_text
    m = re.search(r'href="vlc-([\d.]+)-win64\.zip"', _fetch_text(VLC_INDEX))
    return m[1] if m else ""


def app_release() -> dict:
    """The newest Media Vault release on GitHub: version, page, setup download (None if none is attached), notes."""
    r = _get_json(version.RELEASES_API)
    tag = (r.get("tag_name") or "").lstrip("vV")
    want = version.SETUP_NAME.format(version=tag).lower()
    assets = r.get("assets") or []
    setup_asset = next((a for a in assets if a.get("name", "").lower() == want), None) or \
        next((a for a in assets if a.get("name", "").lower().endswith("_setup.exe")), None)
    return {"version": tag, "page": r.get("html_url") or version.RELEASES_PAGE, "notes": (r.get("body") or "")[:2000],
            "setup": setup_asset.get("browser_download_url") if setup_asset else None,
            "setupName": setup_asset.get("name") if setup_asset else ""}


def check(rows: list[dict], log=lambda *_: None) -> list[dict]:
    """Fill in `latest` and `status` (ok / update / missing / optional / error) by asking each source.
    Each source failing (offline, rate limited) marks only its own rows."""
    import setup
    by = {r["id"]: r for r in rows}

    def mark(r, latest):
        r["latest"] = latest or ""
        if not r["installed"]:
            r["status"] = "optional" if r["optional"] else "missing"
        elif latest and newer(latest, r["installed"].split(" ")[0]):
            r["status"] = "update"
        else:
            r["status"] = "ok"

    try:
        rel = app_release()
        mark(by["app"], rel["version"])
        by["app"].update(page=rel["page"], setup=rel["setup"] or "", notes=rel["notes"])
    except Exception as e:
        by["app"].update(status="error", error=f"GitHub: {e}")
        log(f"app check: {e}")
    try:
        latest = setup._latest_mpv()["name"]
        r = by["libmpv"]
        d = re.search(r"(\d{8})", latest)
        r["latest"] = (d[1][:4] + "-" + d[1][4:6] + "-" + d[1][6:]) if d else latest
        r["status"] = "missing" if not r["installed"] else ("update" if r.get("build") and r["build"] != latest else "ok")
    except Exception as e:
        by["libmpv"].update(status="error" if by["libmpv"]["installed"] else "missing", error=str(e))
    try:
        mark(by["libvlc"], latest_vlc())
    except Exception as e:
        by["libvlc"].update(error=str(e))
    if not frozen():
        try:
            outdated = _pip_outdated()
            for r in rows:
                if r.get("pip"):
                    mark(r, outdated.get(r["pip"].lower(), r["installed"].split(" ")[0]))
        except Exception as e:
            log(f"pip check: {e}")
    return rows


def update(component: str, log=print) -> str:
    """Install or update one component. Returns a sentence for the toast."""
    import setup
    from utils import bin_dir
    if component == "libmpv":
        setup.download_mpv(bin_dir(), log)
        return "libmpv updated. It is used from the next video."
    if component == "libvlc":
        setup.download_vlc(bin_dir(), log)
        return "libVLC updated. Restart Media Vault to use it."
    if component == "shader":
        setup.download_shader(bin_dir(), log)
        return "Upscaling shader installed."
    pkg = next((p for p in PACKAGES if p[0] == component), None)
    if pkg:
        if frozen() and not pkg[4]:
            return f"{pkg[1]} is built into Media Vault and updates with it."
        setup.pip_install(["-U", pkg[3]], log)
        return f"{pkg[1]} updated. Restart Media Vault to use it."
    raise ValueError(f"unknown component {component}")


def download_setup(url: str, name: str, progress=lambda done, total: None) -> Path:
    """Download a release's setup.exe to the temp folder (only from GitHub, only an .exe)."""
    if not url.lower().startswith(f"https://github.com/{version.REPO}/releases/download/".lower()) or not name.lower().endswith(".exe"):
        raise ValueError("refusing to download an installer from an unexpected address")
    dest = Path(tempfile.gettempdir()) / os.path.basename(name)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r, open(dest, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            progress(done, total)
    if total and dest.stat().st_size != total:
        raise IOError("the download was cut short")
    return dest


def run_setup(path: Path) -> None:
    """Start the installer. It finds the current install folder itself (same app id) and asks to close Media Vault."""
    if sys.platform == "win32":
        os.startfile(str(path))   # noqa: S606  (opens the Windows installer wizard)
    else:
        raise OSError("the installer only runs on Windows")
