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
    from utils import rollback
    waiting = rollback.pending()
    for r in rows:
        r["previous"] = "" if r["id"] in ("app", "python") or r.get("kind") == "bundled" else rollback.previous(r["id"])
        r["rollbackPending"] = r["id"] in waiting
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


def asset_digest(url: str) -> str:
    """The SHA-256 GitHub publishes for one of this repo's release files ("" if it has none)."""
    for r in _get_json(version.RELEASES_API.rsplit("/", 1)[0] + "?per_page=30"):
        for a in r.get("assets") or []:
            if a.get("browser_download_url") == url:
                return (a.get("digest") or "").removeprefix("sha256:").lower()
    return ""


def previous_release() -> dict:
    """The newest release older than this one that has a setup file (what "Roll back" installs), or {}."""
    best = {}
    for r in _get_json(version.RELEASES_API.rsplit("/", 1)[0] + "?per_page=30"):
        tag = (r.get("tag_name") or "").lstrip("vV")
        if r.get("draft") or r.get("prerelease") or not newer(version.VERSION, tag):
            continue
        asset = next((a for a in r.get("assets") or [] if a.get("name", "").lower().endswith("_setup.exe")), None)
        if asset and (not best or newer(tag, best["version"])):
            best = {"version": tag, "page": r.get("html_url") or "", "setup": asset["browser_download_url"], "setupName": asset["name"]}
    return best


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
    if frozen():
        try:
            prev = previous_release()
            by["app"].update(previous=prev.get("version", ""), previousSetup=prev.get("setup", ""),
                             previousName=prev.get("setupName", ""))
        except Exception as e:
            log(f"previous release: {e}")
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


def _installed(component: str) -> str:
    row = next((r for r in inventory() if r["id"] == component), None)
    return (row or {}).get("installed", "")


def update(component: str, log=print) -> str:
    """Install or update one component. Returns a sentence for the toast. What was there is kept for a rollback."""
    import setup
    from utils import rollback, writable_bin
    before = _installed(component)
    if before:
        if component in rollback.PARTS:
            rollback.snapshot(component, before)
        elif any(p[0] == component and not (frozen() and not p[4]) for p in PACKAGES):
            rollback.remember_pip(component, before)
    if component == "libmpv":
        setup.download_mpv(writable_bin(), log)
        return "libmpv updated. Restart Media Vault to use it."
    if component == "libvlc":
        setup.download_vlc(writable_bin(), log)
        return "libVLC updated. Restart Media Vault to use it."
    if component == "shader":
        setup.download_shader(writable_bin(), log)
        return "Upscaling shader installed."
    pkg = next((p for p in PACKAGES if p[0] == component), None)
    if pkg:
        if frozen() and not pkg[4]:
            return f"{pkg[1]} is built into Media Vault and updates with it."
        setup.pip_install(["-U", pkg[3]], log)
        return f"{pkg[1]} updated. Restart Media Vault to use it."
    raise ValueError(f"unknown component {component}")


def rollback_component(component: str, log=print) -> str:
    """Put back the version a component had before its last update. Returns a sentence for the toast."""
    import setup
    from utils import rollback
    want = rollback.previous(component)
    if not want:
        raise ValueError("there is no earlier version kept for this")
    if component in rollback.PARTS:
        rollback.request(component, _installed(component))
        return f"Restart Media Vault to finish going back to {want}."
    pkg = next((p for p in PACKAGES if p[0] == component), None)
    if not pkg or (frozen() and not pkg[4]):
        raise ValueError(f"{component} cannot be rolled back on its own")
    if not re.fullmatch(r"[0-9][0-9A-Za-z.+!-]{0,40}", want):        # a version number, nothing pip could read as an option
        raise ValueError("the kept version number is not valid")
    now = _installed(component)
    setup.pip_install([f"{pkg[3]}=={want}"], log)
    rollback.remember_pip(component, now)              # rolling back again undoes it
    return f"{pkg[1]} is back on {want}. Restart Media Vault to use it."


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _writable(folder: Path) -> bool:
    probe = folder / f".mv-write-{os.getpid()}"
    try:
        probe.write_bytes(b"x")
        probe.unlink()
        return True
    except OSError:
        return False


APP_ID = "{6F1C2D4E-8A3B-4C7D-9E21-5B0F7A9C3D18}"     # installer.iss AppId


def installed_for_all_users(folder: Path) -> bool | None:
    """How this copy was installed, from setup's own uninstall entry: True for all users (HKLM), False for you only
    (HKCU), None when there is no entry for this folder (a portable copy). An update must run in the same mode, or
    setup installs a second copy of its registration, with a second desktop shortcut."""
    if sys.platform != "win32":
        return None
    import ntpath
    import winreg
    sub = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
    want = ntpath.normcase(ntpath.normpath(str(folder)))
    for hive, view, mode in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, True),
                             (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, True),
                             (winreg.HKEY_CURRENT_USER, 0, False)):
        try:
            with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | view) as k:
                where = winreg.QueryValueEx(k, "InstallLocation")[0]
        except OSError:
            continue
        if ntpath.normcase(ntpath.normpath(where)) == want:
            return mode
    return None


def setup_arguments(folder: Path, all_users: bool) -> str:
    """No wizard: install over this copy, in its own folder, then start Media Vault again. Setup closes Media
    Vault if it is still running. For a copy installed for all users, Windows asks for permission once (UAC)."""
    args = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH",
            f'/DIR="{folder}"', f'/LOG="{Path(tempfile.gettempdir()) / "MediaVault_update.log"}"']
    args.append("/ALLUSERS" if all_users else "/CURRENTUSER")      # never left to setup's guess
    return " ".join(args)


def download_setup(url: str, name: str, progress=lambda done, total: None, sha256: str | None = None) -> Path:
    """Download a release's setup.exe (only this repo's GitHub releases, only an .exe) into a private temp folder,
    and check it against the SHA-256 GitHub publishes for it. Setup is run silently right after, so a file that
    does not match is deleted, never started."""
    import hashlib
    if not url.lower().startswith(f"https://github.com/{version.REPO}/releases/download/".lower()) \
            or not re.fullmatch(r"[A-Za-z0-9_.\-]{1,120}\.exe", name) or ".." in name:
        raise ValueError("refusing to download an installer from an unexpected address")
    want = asset_digest(url) if sha256 is None else sha256.lower()
    if not want:
        raise ValueError("GitHub lists no checksum for this installer, so it was not installed. Download it from the release page.")
    dest = Path(tempfile.mkdtemp(prefix="mediavault-update-")) / name     # not a shared, guessable temp path
    digest = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r, open(dest, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if done > 1 << 30:
                raise IOError("the download is far larger than a Media Vault installer")
            progress(done, total)
    if (total and dest.stat().st_size != total) or digest.hexdigest() != want:
        dest.unlink(missing_ok=True)
        raise IOError("the installer did not match GitHub's checksum, so it was deleted and not run")
    return dest


def run_setup(path: Path) -> None:
    """Start the downloaded setup in the background, with no wizard (see setup_arguments). Media Vault quits
    right after; setup replaces its files and starts it again."""
    if sys.platform != "win32":
        raise OSError("the installer only runs on Windows")
    folder = install_dir()
    # ShellExecute, not subprocess: setup asks Windows to elevate itself for an all-users copy, and only
    # ShellExecute can show that prompt
    mode = installed_for_all_users(folder)
    os.startfile(str(path), "open", setup_arguments(folder, all_users=not _writable(folder) if mode is None else mode))   # noqa: S606
