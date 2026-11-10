"""Shared paths. Importing this package puts bin/ on the DLL search path,
so libmpv / libvlc downloaded by setup.py are found by python-mpv / python-vlc."""
import os
import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def bin_dir() -> Path:
    """bin/ next to the app when writable, else under %LOCALAPPDATA%/MediaVault (Program Files)."""
    local = app_dir() / "bin"
    if local.is_dir() or os.access(app_dir(), os.W_OK):
        return local
    from database import data_dir
    return data_dir() / "bin"


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
