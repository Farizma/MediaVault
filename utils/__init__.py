"""Shared paths. Importing this package puts bin/ on the DLL search path,
so libmpv / libvlc downloaded by setup.py are found by python-mpv / python-vlc."""
import os
import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


SEEDED = ".copied-from-app"          # in the per-user bin/: the app's own bin/ was copied here (see writable_bin)


def _user_bin() -> Path:
    from database import data_dir
    return data_dir() / "bin"


def _writable(folder: Path) -> bool:
    """A real write test: os.access does not see Windows permissions (Program Files says yes, then refuses)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".mv-write-{os.getpid()}"
        probe.write_bytes(b"x")
        probe.unlink()
        # a folder too: a drive's own permissions can let you add files where only an administrator makes folders
        # (bin/shaders, bin/.previous were refused while a file was not)
        sub = folder / f".mv-dir-{os.getpid()}"
        sub.mkdir()
        sub.rmdir()
        return True
    except OSError:
        return False


def bin_dir() -> Path:
    """Where libmpv, libVLC and the shader are: bin/ next to the app, or under %LOCALAPPDATA%/MediaVault when the
    app's folder cannot be written (Program Files) or once an update had to move them there."""
    user = _user_bin()
    if (user / SEEDED).exists():
        return user
    local = app_dir() / "bin"
    if local.is_dir() or os.access(app_dir(), os.W_OK):
        return local
    return user


def writable_bin(force: bool = False) -> Path:
    """bin/ for an update or a rollback. An all-users copy (Program Files) cannot be written without administrator
    rights: copy what it has into your own bin/ once, and keep everything there from now on (bin_dir follows).
    force: the app's bin/ took a new file but then refused to change one setup put there (a folder on another drive
    lets you add files, not touch the administrator's): move to your own bin/ anyway."""
    import shutil
    b = bin_dir()
    if not force and _writable(b):
        return b
    if b == _user_bin():
        return b
    user = _user_bin()
    user.mkdir(parents=True, exist_ok=True)
    if b.is_dir() and b != user:
        shutil.copytree(b, user, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".previous", ".mv-write-*"))
    (user / SEEDED).write_text(str(b), encoding="utf-8")
    use_bin_dir()
    return user


def use_bin_dir() -> None:
    b = bin_dir()
    if not b.is_dir():
        return
    os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(b))
    vlc = b / "vlc"
    if vlc.is_dir():
        os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(vlc / "libvlc.dll"))
        os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(vlc / "plugins"))


use_bin_dir()
