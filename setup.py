"""Requirements check and installer. main.py calls run_setup() before anything else.

What it checks, every launch (takes milliseconds when everything is present):
  * Python 3.10+ and 64-bit
  * Python packages: PySide6, python-mpv, python-vlc, watchdog, pillow, py7zr
  * video runtimes: libmpv (dedicated GPUs) and libvlc (low-power GPUs), looked up in bin/ and PATH

If anything is missing, a setup window installs it (pip, then downloads into bin/) with live progress.
There is no skip button: the app starts only when everything required is in place. If one video
runtime cannot be installed but the other works, "Continue" appears and the app starts with that one.

The download helpers were written from the vendors' public layouts (GitHub releases API,
get.videolan.org) and have NOT been run against the live servers.
"""
import ctypes
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

# (import name, pip name, minimum version). PySide6 6.5 is the first with MultiEffect.
PACKAGES = [("PySide6", "PySide6", "6.5"), ("mpv", "python-mpv", None), ("vlc", "python-vlc", None),
            ("watchdog", "watchdog", None), ("PIL", "pillow", None), ("py7zr", "py7zr", None)]  # py7zr is only the last-resort unpacker; tar.exe / 7-Zip come first
REQUIRED = {mod: dist for mod, dist, _ in PACKAGES}
EXTENSIONS = (".mp4", ".mkv", ".avi")
PROG_ID = "MediaVault.Video"
UA = {"User-Agent": "MediaVault/1.0"}
MPV_RELEASES = "https://api.github.com/repos/zhongfly/mpv-winbuild/releases/latest"
MPV_ASSET = re.compile(r"mpv-dev-x86_64-\d{8}-git-[0-9a-f]+\.7z$")
VLC_INDEX = "https://get.videolan.org/vlc/last/win64/"
SHADER_URL = "https://github.com/igv/FSRCNN-TensorFlow/releases/download/1.1/FSRCNNX_x2_8-0-4-1.glsl"
SHADER_SHA256 = "e800dbc5c1c95185cc82216c597724533ff5f2880179f256eef600f03e8dc2ae"      # release 1.1 never changes
# the stand-alone 7-Zip console, only used when tar.exe and an installed 7-Zip both fail. It is RUN, so it is pinned:
# a fixed release from 7-Zip's own GitHub, checked against this hash before it is started.
SEVENZR_URL = "https://github.com/ip7z/7zip/releases/download/24.09/7zr.exe"
SEVENZR_SHA256 = "d2c0045523cf053a6b43f9315e9672fc2535f06aeadd4ffa53c729cd8b2b6dfe"
MAX_DOWNLOAD = 600 << 20         # nothing Media Vault fetches is near this; a runaway response is cut off
UPDATE_EVERY = 7 * 24 * 3600
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW: no black console flashes while pip runs


def _frozen() -> bool:
    return getattr(sys, "frozen", False)


def _file_log(message: str) -> None:
    """setup.log in %LOCALAPPDATA%/MediaVault. pythonw has no console, so this is where failures go."""
    try:
        from database import data_dir
        with open(data_dir() / "setup.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n")
    except Exception:
        pass


# ------------------------------------------------------------------ 1. what is required

@dataclass
class Item:
    name: str
    kind: str                      # "system" | "python" | "runtime"
    required: bool
    check: Callable[[], bool]
    pip: str = ""                  # pip requirement for kind == "python"
    runtime: str = ""              # "mpv" | "vlc" for kind == "runtime"
    ok: bool = False
    detail: str = ""

    def recheck(self) -> bool:
        try:
            self.ok = bool(self.check())
        except Exception as e:
            self.ok, self.detail = False, str(e)
        return self.ok


def _vt(version: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", version)[:3])


def _package_ok(module: str, dist: str, minimum) -> bool:
    if _frozen():  # a packaged EXE already carries its packages
        return True
    if importlib.util.find_spec(module) is None:
        return False
    if not minimum:
        return True
    try:
        return _vt(importlib.metadata.version(dist)) >= _vt(minimum)
    except importlib.metadata.PackageNotFoundError:
        return False


def _python_ok() -> bool:
    return sys.version_info >= (3, 10) and sys.maxsize > 2 ** 32


def has_lib(name: str) -> bool:
    """True when python-mpv / python-vlc can load their DLL (they raise on import when it is missing)."""
    if name in sys.modules:
        return True
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def scan() -> list[Item]:
    """Every requirement with its current state. Also puts bin/ on the DLL search path first."""
    import utils
    utils.use_bin_dir()
    items = [Item(f"Python {sys.version_info.major}.{sys.version_info.minor}, 64-bit, 3.10 or newer",
                  "system", True, _python_ok)]
    for module, dist, minimum in PACKAGES:
        spec = dist + (f">={minimum}" if minimum else "")
        items.append(Item(dist, "python", True, lambda m=module, d=dist, v=minimum: _package_ok(m, d, v), pip=spec))
    items.append(Item("libmpv (video engine, dedicated GPUs)", "runtime", False, lambda: has_lib("mpv"), runtime="mpv"))
    items.append(Item("libvlc (video engine, low-power GPUs)", "runtime", False, lambda: has_lib("vlc"), runtime="vlc"))
    for item in items:
        item.recheck()
    return items


def can_start(items) -> bool:
    """All required items present, and at least one video engine works."""
    return all(i.ok for i in items if i.required) and any(i.ok for i in items if i.kind == "runtime")


# ------------------------------------------------------------------ 2. installing

def _python_exe() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))  # pythonw cannot give pip a console
    return str(exe)


def _run(cmd: list[str], log) -> list[str]:
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                         creationflags=NO_WINDOW if sys.platform == "win32" else 0)
    tail = []
    for line in p.stdout:
        line = line.strip()
        if line:
            log(line)
            tail.append(line)
    if p.wait():
        raise RuntimeError("\n".join(tail[-6:]) or f"exit code {p.returncode}")
    return tail


def pip_install(specs: list[str], log=print) -> None:
    base = [_python_exe(), "-m", "pip"]
    try:
        _run(base + ["--version"], lambda _l: None)
    except Exception:
        log("pip is missing: installing it")
        _run([_python_exe(), "-m", "ensurepip", "--upgrade"], log)
    log("pip install " + " ".join(specs))
    _run(base + ["install", "--disable-pip-version-check", *specs], log)
    importlib.invalidate_caches()


def _https(url: str) -> str:
    """Only ever HTTPS (urllib would also open file:// and plain http://)."""
    if not url.lower().startswith("https://"):
        raise ValueError(f"refusing a non-HTTPS address: {url[:80]}")
    return url


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(_https(url), headers=UA), timeout=30) as r:
        return r.read(8 << 20).decode("utf-8", "ignore")


def _download(url: str, dest: Path, log, sha256: str | None = None) -> None:
    log(f"Downloading {url}")
    digest, done, mark = hashlib.sha256(), 0, 5
    with urllib.request.urlopen(urllib.request.Request(_https(url), headers=UA), timeout=60) as r, open(dest, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            digest.update(chunk)
            f.write(chunk)
            done += len(chunk)
            if done > MAX_DOWNLOAD:
                raise RuntimeError(f"download from {url} is far larger than expected: stopped")
            if done >> 20 >= mark:
                log(f"  {done >> 20} MB downloaded")
                mark += 5
    if sha256 and digest.hexdigest().lower() != sha256.lower():
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch for {url}: refusing to use the file")


class _Scratch:
    """Temp folder that never raises on cleanup. On Windows an antivirus scan or a lingering handle can
    keep a fresh download locked for a moment (WinError 32), and TemporaryDirectory would turn that
    into a failed install even though the work was done."""

    def __enter__(self) -> str:
        self.path = tempfile.mkdtemp(prefix="mediavault-")
        return self.path

    def __exit__(self, *exc) -> None:
        for _ in range(5):
            shutil.rmtree(self.path, ignore_errors=True)
            if not Path(self.path).exists():
                return
            time.sleep(0.5)


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for member in zf.namelist():
        target = (dest / member).resolve()
        if root != target and root not in target.parents:  # zip-slip guard
            raise ValueError(f"unsafe path in archive: {member}")
    zf.extractall(dest)


def _aside(path: Path) -> None:
    """Move a file or folder out of the way, even while Windows has it loaded (a DLL in use can be renamed, not
    overwritten). The leftover is deleted at the next start (clean_replaced)."""
    if path.exists():
        path.rename(path.with_name(f"{path.name}.old-{int(time.time() * 1000)}"))


def _place(src: Path, dest: Path) -> None:
    """Put a new file where an old one may be in use."""
    try:
        shutil.copy(src, dest)
    except PermissionError:
        _aside(dest)
        shutil.copy(src, dest)


def clean_replaced(bin_dir: Path) -> None:
    """At start-up: delete what updates moved aside (nothing has them loaded any more), and finish a libVLC update
    that had to wait (its folder was in use)."""
    if not bin_dir.is_dir():
        return
    staged = bin_dir / "vlc.new"
    if staged.is_dir():
        try:
            _aside(bin_dir / "vlc")
            staged.rename(bin_dir / "vlc")
        except OSError:
            pass
    for old in list(bin_dir.glob("*.old-*")) + list((bin_dir / "shaders").glob("*.old-*")):
        try:
            shutil.rmtree(old) if old.is_dir() else old.unlink()
        except OSError:
            pass


def download_vlc(bin_dir: Path, log=print) -> bool:
    """Returns False when the new libVLC waits for the next start (the current one is in use)."""
    name = re.search(r'href="(vlc-[\d.]+-win64\.zip)"', _fetch_text(VLC_INDEX))
    if not name:
        raise RuntimeError("could not find the VLC zip on get.videolan.org")
    try:
        expected = _fetch_text(VLC_INDEX + name[1] + ".sha256").split()[0]  # videolan publishes <zip>.sha256
    except Exception:
        expected = None
        log("No checksum published for VLC: relying on HTTPS only")
    with _Scratch() as tmp:
        archive, out = Path(tmp) / "vlc.zip", Path(tmp) / "x"
        _download(VLC_INDEX + name[1], archive, log, expected)
        with zipfile.ZipFile(archive) as zf:
            _safe_extract(zf, out)
        new = bin_dir / "vlc.new"
        shutil.rmtree(new, ignore_errors=True)
        shutil.move(str(next(out.iterdir())), str(new))
    try:                       # never delete a libVLC that is loaded: half of it would go and the rest stay locked
        _aside(bin_dir / "vlc")
    except OSError:
        log("libVLC is in use: the new version goes in when Media Vault starts again")
        return False
    new.rename(bin_dir / "vlc")
    return True


def _latest_mpv() -> dict:
    assets = json.loads(_fetch_text(MPV_RELEASES))["assets"]
    asset = next((a for a in assets if MPV_ASSET.search(a["browser_download_url"])), None)
    if not asset:
        raise RuntimeError("no libmpv dev build found in the latest release")
    return asset


def _extract_7z(archive: Path, member_suffixes: tuple, out: Path, log) -> Path:
    """Pull one file out of a .7z. The libmpv builds use the BCJ2 filter, which py7zr cannot read, so try
    Windows' own tar.exe (libarchive), an installed 7-Zip, then the small official 7zr.exe, then py7zr."""
    import os
    out.mkdir(parents=True, exist_ok=True)
    flags = NO_WINDOW if sys.platform == "win32" else 0

    def find() -> Path | None:
        return next((p for p in out.rglob("*") if p.is_file() and p.name.lower().endswith(member_suffixes)), None)

    tools = []
    root = os.environ.get("SystemRoot", r"C:\Windows")
    for tar in (Path(root) / "System32" / "tar.exe", shutil.which("tar")):
        if tar and Path(tar).exists():
            tools.append(("tar", [str(tar), "-xf", str(archive), "-C", str(out), "--wildcards", "*.dll"]))
    for sevenzip in (shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if sevenzip and Path(sevenzip).exists():
            tools.append(("7-Zip", [str(sevenzip), "x", "-y", f"-o{out}", str(archive), "*.dll", "-r"]))
    tried = []
    for name, cmd in tools:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=flags)
        if r.returncode == 0 and find():
            return find()
        tried.append(f"{name}: {(r.stderr or r.stdout).strip()[-120:]}")
    try:  # last resorts: the official stand-alone 7-Zip console (HTTPS, from 7-zip.org), then py7zr
        exe = out.parent / "7zr.exe"
        _download(SEVENZR_URL, exe, log, SEVENZR_SHA256)       # a mismatch deletes it before it can run
        r = subprocess.run([str(exe), "x", "-y", f"-o{out}", str(archive), "*.dll", "-r"],
                           capture_output=True, text=True, errors="replace", creationflags=flags)
        if r.returncode == 0 and find():
            return find()
        tried.append(f"7zr: {(r.stderr or r.stdout).strip()[-120:]}")
    except Exception as e:
        tried.append(f"7zr download: {e}")
    try:
        import py7zr
        with py7zr.SevenZipFile(archive) as z:
            names = [n for n in z.getnames() if n.lower().endswith(member_suffixes)]
        with py7zr.SevenZipFile(archive) as z:
            z.extract(path=out, targets=names[:1])
        if find():
            return find()
    except Exception as e:
        tried.append(f"py7zr: {e}")
    raise RuntimeError("could not unpack the libmpv archive. " + " | ".join(tried))


def download_mpv(bin_dir: Path, log=print) -> None:
    asset = _latest_mpv()
    digest = (asset.get("digest") or "").removeprefix("sha256:")
    if not digest:
        log("No checksum published for libmpv: relying on HTTPS from github.com only")
    with _Scratch() as tmp:
        archive = Path(tmp) / "mpv.7z"
        _download(asset["browser_download_url"], archive, log, digest or None)
        dll = _extract_7z(archive, ("libmpv-2.dll", "mpv-2.dll"), Path(tmp) / "out", log)
        for name in ("libmpv-2.dll", "mpv-2.dll"):  # python-mpv looks for either name
            _place(dll, bin_dir / name)              # the one Media Vault has loaded is moved aside, not overwritten
    (bin_dir / "mpv.version").write_text(asset["name"], encoding="utf-8")


def download_shader(bin_dir: Path, log=print) -> Path:
    """FSRCNNX super-resolution shader for upscaling level 2+. Optional, so it is not part of setup.
    Fetched over HTTPS from the author's repository and checked against the release's known SHA-256."""
    dest = bin_dir / "shaders" / "FSRCNNX_x2_8-0-4-1.glsl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    _download(SHADER_URL, tmp, log, SHADER_SHA256)
    tmp.replace(dest)
    return dest


def _install_runtime(name: str, log) -> None:
    if sys.platform != "win32":
        raise RuntimeError("automatic download is Windows-only: install libmpv / VLC with your package manager")
    import utils
    target = utils.writable_bin()
    (download_mpv if name == "mpv" else download_vlc)(target, log)
    utils.use_bin_dir()


def install_missing(items: list[Item], log=print, progress=lambda item, state: None) -> list[Item]:
    """Install everything that is not ok. progress(item, 'working' | 'ok' | 'failed'). Returns what is still not ok."""
    def say(message):
        _file_log(message)
        log(message)

    for item in items:
        if item.kind == "system" and not item.ok:
            item.detail = "Install 64-bit Python 3.10 or newer from python.org, then start Media Vault again."
            progress(item, "failed")

    pending = [i for i in items if i.kind == "python" and not i.ok]
    if pending:
        for item in pending:
            progress(item, "working")
        try:
            pip_install([i.pip for i in pending], say)
        except Exception as e:
            say(f"pip failed: {e}")
            for item in pending:
                item.detail = str(e)
        for item in pending:
            progress(item, "ok" if item.recheck() else "failed")

    packages_ready = all(i.ok for i in items if i.kind == "python")
    for item in [i for i in items if i.kind == "runtime" and not i.ok]:
        if not packages_ready:
            item.detail = "Waiting for the Python packages above."
            progress(item, "failed")
            continue
        progress(item, "working")
        try:
            _install_runtime(item.runtime, say)
        except Exception as e:
            say(f"{item.name}: {e}")
            item.detail = str(e)
        progress(item, "ok" if item.recheck() else "failed")
        if not item.ok and not item.detail:
            item.detail = "Downloaded, but could not be loaded. See setup.log."
    return [i for i in items if not i.ok]


def repair(log=print) -> list[str]:
    """Re-check and install anything missing (Settings > Install missing components). Returns names still missing."""
    return [i.name for i in install_missing(scan(), log)]


# ------------------------------------------------------------------ 3. the setup window

def _skip_marker() -> Path:
    from database import data_dir
    return data_dir() / "setup.skipped"


def _recently_skipped(days: int = 7) -> bool:
    try:
        return (datetime.now().timestamp() - _skip_marker().stat().st_mtime) < days * 86400
    except OSError:
        return False


def _message(text: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, text, "Media Vault", 0x10)
    else:
        print(text)


def _failure_text(items) -> str:
    return "\n".join(f"- {i.name}: {i.detail or 'not available'}" for i in items if not i.ok and (i.required or i.detail))


def _setup_silent(items) -> bool:
    install_missing(items, log=lambda _m: None)
    if not can_start(items):
        _message("Media Vault could not install what it needs:\n\n" + _failure_text(items) +
                 "\n\nDetails: %LOCALAPPDATA%\\MediaVault\\setup.log")
    return can_start(items)


def _setup_window(items):
    """Returns True to start the app, False to quit, None when no window can be shown (no tkinter / display)."""
    try:
        import queue
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
    except Exception:
        return None

    BG, FG, MUTED, GREEN, RED, AMBER = "#1C1C1E", "#F5F5F7", "#8E8E93", "#34C759", "#FF453A", "#FF9F0A"
    width = 600
    height = 250 + 30 * len(items)
    root.title("Media Vault Setup")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.geometry(f"{width}x{height}+{(root.winfo_screenwidth() - width) // 2}+{(root.winfo_screenheight() - height) // 3}")
    state = {"go": False, "closed": False}
    events: queue.Queue = queue.Queue()

    head = tk.Label(root, bg=BG, fg=FG, font=("Segoe UI", 15, "bold"), anchor="w")
    head.pack(fill="x", padx=24, pady=(20, 2))
    sub = tk.Label(root, bg=BG, fg=MUTED, font=("Segoe UI", 10), anchor="w", justify="left", wraplength=550)
    sub.pack(fill="x", padx=24)
    table = tk.Frame(root, bg=BG)
    table.pack(fill="x", padx=24, pady=10)
    labels = {}
    for item in items:
        row = tk.Frame(table, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=item.name, bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side="left")
        labels[id(item)] = tk.Label(row, bg=BG, font=("Segoe UI", 10, "bold"))
        labels[id(item)].pack(side="right")
    bar = ttk.Progressbar(root, mode="indeterminate", length=552)
    bar.pack(padx=24, pady=(4, 6))
    detail = tk.Label(root, bg=BG, fg=MUTED, font=("Consolas", 9), anchor="w", justify="left", wraplength=550)
    detail.pack(fill="x", padx=24)
    buttons = tk.Frame(root, bg=BG)
    buttons.pack(side="bottom", fill="x", padx=24, pady=16)

    def paint(item, status):
        text, color = {"ok": ("Ready", GREEN), "working": ("Installing...", AMBER),
                       "failed": ("Failed", RED), "missing": ("Missing", AMBER)}[status]
        labels[id(item)].config(text=text, fg=color)

    def close():
        state["closed"] = True
        root.destroy()

    def quit_app():
        state["go"] = False
        close()

    def go_on():
        _skip_marker().write_text("continued", encoding="utf-8")  # do not show the window again for a week
        state["go"] = True
        close()

    def finish():
        bar.stop()
        left = [i for i in items if not i.ok]
        if not left:
            head.config(text="Everything is installed")
            sub.config(text="Starting Media Vault...")
            root.after(600, lambda: (state.update(go=True), close()))
            return
        head.config(text="Setup could not finish")
        sub.config(text=_failure_text(items) or "Some items are missing.")
        for child in buttons.winfo_children():
            child.destroy()
        tk.Button(buttons, text="Quit", width=10, command=quit_app).pack(side="right", padx=(8, 0))
        if can_start(items):
            tk.Button(buttons, text="Continue anyway", width=16, command=go_on).pack(side="right", padx=(8, 0))
        tk.Button(buttons, text="Retry", width=10, command=start).pack(side="right")

    def start():
        for child in buttons.winfo_children():
            child.destroy()
        tk.Button(buttons, text="Quit", width=10, command=quit_app).pack(side="right")
        head.config(text="Installing what Media Vault needs")
        sub.config(text="This can take a few minutes the first time. Keep this window open.")
        for item in items:
            item.recheck()
            paint(item, "ok" if item.ok else "missing")
        bar.start(12)
        threading.Thread(target=lambda: (install_missing(
            items, log=lambda m: events.put(("log", m)), progress=lambda i, s: events.put(("state", i, s))),
            events.put(("done",))), daemon=True, name="setup").start()

    def pump():
        if state["closed"]:
            return
        try:
            while True:
                event = events.get_nowait()
                if event[0] == "log":
                    detail.config(text=event[1][-260:])
                elif event[0] == "state":
                    paint(event[1], event[2])
                else:
                    finish()
        except queue.Empty:
            pass
        root.after(100, pump)

    root.protocol("WM_DELETE_WINDOW", quit_app)
    root.after(0, start)
    root.after(100, pump)
    root.mainloop()
    return state["go"]


def run_setup() -> bool:
    """Check everything; install what is missing. True when the app may start."""
    items = scan()
    if all(i.ok for i in items):
        return True
    _file_log("missing: " + ", ".join(i.name for i in items if not i.ok))
    if can_start(items) and _recently_skipped():
        return True  # only the second video engine is missing and the person chose to continue recently
    go = _setup_window(items)
    return _setup_silent(items) if go is None else go


# ------------------------------------------------------------------ 4. update daemon

def check_updates(log=print) -> dict:
    """{'packages': [names with a newer release], 'mpv': newer libmpv asset name or None}. Changes nothing."""
    found = {"packages": [], "mpv": None, "app": None}
    try:  # Media Vault itself: the newest release on GitHub
        from utils import components
        rel = components.app_release()
        if components.newer(rel["version"], components.version.VERSION):
            found["app"] = rel["version"]
    except Exception as e:
        log(f"Media Vault update check skipped: {e}")
    if not _frozen():
        out = subprocess.run([_python_exe(), "-m", "pip", "list", "--outdated", "--format=json"],
                             capture_output=True, text=True, timeout=180,
                             creationflags=NO_WINDOW if sys.platform == "win32" else 0)
        ours = {p.lower() for p in REQUIRED.values()}
        if out.returncode == 0:
            found["packages"] = [p["name"] for p in json.loads(out.stdout or "[]") if p["name"].lower() in ours]
    try:
        import utils
        installed = utils.bin_dir() / "mpv.version"
        latest = _latest_mpv()["name"]
        if installed.exists() and installed.read_text(encoding="utf-8").strip() != latest:
            found["mpv"] = latest
    except Exception as e:
        log(f"libmpv update check skipped: {e}")
    return found


def apply_updates(found: dict, log=print) -> None:
    import utils
    if found.get("packages") and not _frozen():
        pip_install(["-U", *found["packages"]], log)
    if found.get("mpv"):
        download_mpv(utils.bin_dir(), log)


class UpdateDaemon(threading.Thread):
    """Checks weekly and calls on_found(result) when something is newer. It never installs by itself."""

    def __init__(self, on_found, every: float = UPDATE_EVERY):
        super().__init__(daemon=True, name="updates")
        self.on_found, self.every = on_found, every
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        while not self._stop_event.wait(60):  # first check one minute after start-up
            try:
                found = check_updates(lambda *_: None)
                if found["packages"] or found["mpv"] or found.get("app"):
                    self.on_found(found)
            except Exception:
                pass  # offline or rate limited: try again next week
            if self._stop_event.wait(self.every):
                break


# ------------------------------------------------------------------ 5. Windows file associations

def _open_command() -> str:
    if _frozen():
        return f'"{sys.executable}" "%1"'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    main = Path(__file__).resolve().with_name("main.py")
    return f'"{pyw if pyw.exists() else sys.executable}" "{main}" "%1"'


def register_file_types(extensions=EXTENSIONS) -> None:
    """Adds Media Vault to 'Open with' for each extension.

    Written under HKEY_CURRENT_USER\\Software\\Classes, which Windows merges into HKEY_CLASSES_ROOT.
    This needs no administrator rights. Windows 10/11 let only the PERSON pick the default app
    (Settings > Apps > Default apps); no program may set it silently. That is a Windows rule.
    """
    if sys.platform != "win32":
        return
    import winreg
    classes = r"Software\Classes"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{PROG_ID}") as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "Media Vault video")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{PROG_ID}\shell\open\command") as k:
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, _open_command())
    for ext in extensions:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}\OpenWithProgids") as k:
            winreg.SetValueEx(k, PROG_ID, 0, winreg.REG_NONE, b"")
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


def file_types_command() -> str | None:
    """The command Windows runs for "Open with › Media Vault", or None when Media Vault is not offered there."""
    if sys.platform != "win32":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\shell\open\command") as k:
            return winreg.QueryValueEx(k, None)[0]
    except OSError:
        return None


def refresh_file_types() -> bool:
    """At start-up: if Media Vault is offered in "Open with" but the entry points at another copy (it was moved or
    reinstalled elsewhere), point it at this one. Returns True when it is offered."""
    cmd = file_types_command()
    if cmd is None:
        return False
    if cmd != _open_command():
        register_file_types()
    return True


def unregister_file_types(extensions=EXTENSIONS) -> None:
    """Undo register_file_types(): removes only what it wrote."""
    if sys.platform != "win32":
        return
    import winreg
    classes = r"Software\Classes"
    for ext in extensions:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}\OpenWithProgids", 0,
                                winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, PROG_ID)
        except FileNotFoundError:
            pass
    for sub in (r"shell\open\command", r"shell\open", "shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{PROG_ID}" + (f"\\{sub}" if sub else ""))
        except FileNotFoundError:
            pass
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


if __name__ == "__main__":
    sys.exit(0 if run_setup() else 1)
