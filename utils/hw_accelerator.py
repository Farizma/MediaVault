"""GPU lookup (picks the playback core) and the 3 upscaling levels as player options."""
import ctypes
import os
import re
import sys
from dataclasses import dataclass

from utils import bin_dir

_DISCRETE = re.compile(r"nvidia|geforce|\brtx\b|\bgtx\b|radeon\s*(rx|pro)|\bamd\s*rx\b", re.I)
_RTX = re.compile(r"\brtx\b", re.I)
# integrated GPUs that handle mpv's GPU scaling well (Intel Arc / Iris Xe, AMD Radeon 600M-800M and "Radeon Graphics")
_MODERN_IGPU = re.compile(r"\barc\b|iris(\(r\))?\s*xe|radeon\s*\d{3,4}m\b|radeon\(tm\)\s*graphics|radeon graphics", re.I)
SHADER = "FSRCNNX_x2_8-0-4-1.glsl"  # level 2+ super-resolution; setup.download_shader() fetches it into bin/shaders/

# Dynamic-range compressor for "Reduce Loud Sounds". Tames explosions, lifts quiet dialogue.
MPV_NIGHT_FILTER = "lavfi=[acompressor=threshold=0.08:ratio=8:attack=20:release=300:makeup=2]"
LEVEL_NAMES = {1: "Standard", 2: "High Quality", 3: "AI Ultra"}


@dataclass(frozen=True)
class Hardware:
    gpus: tuple
    backend: str  # recommended core: "mpv" or "vlc"
    rtx: bool
    ram_gb: float = 0.0
    cores: int = 0
    level: int = 1  # recommended upscaling level
    why: str = ""


class _DisplayDevice(ctypes.Structure):  # DISPLAY_DEVICEW
    _fields_ = [("cb", ctypes.c_ulong), ("DeviceName", ctypes.c_wchar * 32), ("DeviceString", ctypes.c_wchar * 128),
                ("StateFlags", ctypes.c_ulong), ("DeviceID", ctypes.c_wchar * 128), ("DeviceKey", ctypes.c_wchar * 128)]


def gpu_names() -> list[str]:
    """Display adapter names straight from user32.EnumDisplayDevicesW (microseconds, no subprocess)."""
    if sys.platform != "win32":
        return []
    names, i = [], 0
    while True:
        dev = _DisplayDevice()
        dev.cb = ctypes.sizeof(dev)
        if not ctypes.windll.user32.EnumDisplayDevicesW(None, i, ctypes.byref(dev), 0):
            break
        if dev.DeviceString:
            names.append(dev.DeviceString)
        i += 1
    return names


def ram_gb() -> float:
    if sys.platform == "win32":
        class _Mem(ctypes.Structure):  # MEMORYSTATUSEX
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                       [(n, ctypes.c_ulonglong) for n in ("total", "avail", "pagefile", "availpage", "virt", "availvirt", "ext")]
        m = _Mem()
        m.dwLength = ctypes.sizeof(m)
        return m.total / 2 ** 30 if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)) else 0.0
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
    except (ValueError, OSError, AttributeError):
        return 0.0


def recommend(gpus, ram: float, cores: int) -> tuple[str, int, str]:
    """(core, upscaling level, reason) for this PC.
    mpv's GPU scaling needs a dedicated or recent integrated GPU; VLC is lighter on everything else.
    Level 3 (RTX Video Super Resolution) needs an RTX card; level 2 (shader upscaling) a dedicated GPU, or a
    recent integrated one with 16 GB RAM (it shares system memory)."""
    discrete = next((g for g in gpus if _DISCRETE.search(g)), None)
    igpu = next((g for g in gpus if _MODERN_IGPU.search(g)), None)
    if any(_RTX.search(g) for g in gpus):
        return "mpv", 3, f"{discrete} supports RTX Video Super Resolution"
    if discrete:
        return "mpv", 2, f"{discrete} is a dedicated GPU"
    if igpu and ram >= 16 and cores >= 6:
        return "mpv", 2, f"{igpu} with {ram:.0f} GB RAM handles shader upscaling"
    if igpu:
        return "mpv", 1, f"{igpu} plays well with mpv; upscaling kept light"
    return "vlc", 1, "No dedicated or recent integrated GPU found: VLC is the lighter engine"


def detect(gpus=None, ram=None, cores=None) -> Hardware:
    found = tuple(dict.fromkeys(gpu_names() if gpus is None else gpus))
    ram = ram_gb() if ram is None else ram
    cores = (os.cpu_count() or 0) if cores is None else cores
    core, level, why = recommend(found, ram, cores)
    return Hardware(found, core, any(_RTX.search(g) for g in found), round(ram, 1), cores, level, why)


def resolve(setting: str, recommended):
    """A Settings value: "" or "auto" means the recommendation, anything else is the person's override."""
    return recommended if setting in ("", "auto", None) else setting


def mpv_options(level: int, rtx: bool, hdr_display: bool = False) -> dict:
    """python-mpv keyword options for an upscaling level. Level 3 needs an RTX GPU, else falls to 2.
    hdr_display: send HDR untouched to an HDR screen, which needs the gpu-next renderer (D3D11 on Windows)."""
    level = max(1, min(3, level))
    if level == 3 and not rtx:
        level = 2
    opts = {"vo": "gpu", "hwdec": "auto-safe", "scale": "bilinear", "cscale": "bilinear",
            "tone_mapping": "bt.2390", "hdr_compute_peak": "yes"}  # HDR to SDR on every level
    if level >= 2:
        opts |= {"scale": "spline36", "cscale": "spline36", "dscale": "mitchell"}
        shader = bin_dir() / "shaders" / SHADER
        if shader.exists():
            opts["glsl_shaders"] = str(shader)
    if level == 3:
        # D3D11 surface so the driver can run NVIDIA RTX Video Super Resolution.
        opts |= {"vo": "gpu-next", "gpu_api": "d3d11", "hwdec": "d3d11va",
                 "vf": "d3d11vpp=scaling-mode=nvidia"}
    if hdr_display:
        opts["vo"] = "gpu-next"
        if sys.platform == "win32":
            opts["gpu_api"] = "d3d11"   # Windows HDR output goes through a D3D11 swap chain
    return opts


def vlc_args(night: bool = False) -> list[str]:
    args = ["--no-video-title-show", "--avcodec-hw=any", "--quiet"]
    if night:
        args.append("--audio-filter=compressor")
    return args
