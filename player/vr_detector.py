"""Finds stereoscopic / VR tags in a filename, and how to show such a video on an ordinary screen.

Tags (any separator, any case): `3D`, `SBS` / `LR`, `TB` / `OU`, `180`, `360`, `VR` (alone it means 180 side by side,
the usual VR video), `VR180`, `VR360`, `FISHEYE` / `FISHEYE190` / `MKX200` / `MKX220` / `RF52` (fisheye lenses),
`3DH` (side by side), `3DV` (top-bottom). `FSBS` / `FTB` for full-size stereo.

Views (key `v` in the player):
  look  VR (180, 360, fisheye): one eye, projected flat, and you look around by dragging (Ctrl + wheel zooms)
  left  a 3D film: the left eye as a flat picture
  sbs   both eyes side by side, untouched, for a 3D display or a headset mirroring the desktop (top-bottom is
        converted to side by side first). Headset-native output (OpenXR) is a separate project.
"""
import math
import os
import re
from typing import NamedTuple


class VRInfo(NamedTuple):
    projection: str  # "flat" (3D movie) | "180" | "360" | "fisheye"
    layout: str      # "mono" | "sbs" | "tb"
    full: bool       # full-size stereo (no rescale after the eye split)
    lens: int = 180  # fisheye: the lens's field of view in degrees


_SPLIT = re.compile(r"[\s._\-\[\]()]+")
_FISHEYE = re.compile(r"^(?:FISHEYE|MKX|RF)(\d{2,3})?$")
DEFAULT_FOV = 100.0
FOV_RANGE = (40.0, 140.0)


def detect(path: str) -> VRInfo | None:
    tokens = {t.upper() for t in _SPLIT.split(os.path.splitext(os.path.basename(path))[0]) if t}
    lens = 0
    for t in tokens:
        if (m := _FISHEYE.match(t)):
            num = int(m[1]) if m[1] else 0
            lens = num if not t.startswith("RF") and 150 <= num <= 240 else 190     # RF52: Canon's dual 190° lens
    if lens:
        projection = "fisheye"
    elif tokens & {"360", "VR360"}:
        projection = "360"
    elif tokens & {"180", "VR180", "VR"}:
        projection = "180"
    elif tokens & {"3D", "3DH", "3DV"}:
        projection = "flat"
    else:
        return None
    full = bool(tokens & {"FSBS", "FTB"})
    if tokens & {"SBS", "HSBS", "FSBS", "LR", "3DH"}:
        layout = "sbs"
    elif tokens & {"TB", "HTB", "FTB", "OU", "HOU", "3DV"}:
        layout = "tb"
    elif projection == "360":
        layout = "mono"                       # 360 is mostly mono; stereo 360 says TB
    else:
        layout = "sbs"                        # a bare "3D", "VR" or "180" is almost always side by side
    return VRInfo(projection, layout, full, lens or 180)


# the formats you can pick in the player (when a file's name does not say, or says it wrong): code, label, info
FORMATS = (
    ("2d", "2D", None),
    ("3d_sbs", "3D side by side", VRInfo("flat", "sbs", False)),
    ("3d_tb", "3D top-bottom", VRInfo("flat", "tb", False)),
    ("180_sbs", "180\u00B0 side by side", VRInfo("180", "sbs", False)),
    ("180_tb", "180\u00B0 top-bottom", VRInfo("180", "tb", False)),
    ("180_mono", "180\u00B0 mono", VRInfo("180", "mono", False)),
    ("360_mono", "360\u00B0 mono", VRInfo("360", "mono", False)),
    ("360_tb", "360\u00B0 top-bottom", VRInfo("360", "tb", False)),
    ("360_sbs", "360\u00B0 side by side", VRInfo("360", "sbs", False)),
    ("fisheye_sbs", "Fisheye 190\u00B0 side by side", VRInfo("fisheye", "sbs", False, 190)),
    ("fisheye200_sbs", "Fisheye 200\u00B0 side by side", VRInfo("fisheye", "sbs", False, 200)),
)
_BY_CODE = {c: i for c, _, i in FORMATS}


def by_code(code: str):
    """The VRInfo for a format code (None for 2D); KeyError for an unknown code."""
    return _BY_CODE[code]


def code_of(info: VRInfo | None) -> str:
    """The closest format code for a detected file (full-size stereo and odd lenses map to the nearest)."""
    if info is None:
        return "2d"
    if info.projection == "fisheye":
        return "fisheye200_sbs" if info.lens >= 200 else "fisheye_sbs"
    code = ("3d" if info.projection == "flat" else info.projection) + "_" + info.layout
    return code if code in _BY_CODE else "2d"


def views(info: VRInfo | None) -> tuple:
    if info is None:
        return ()
    first = "left" if info.projection == "flat" else "look"
    return (first, "sbs") if info.layout != "mono" else (first,)


def label(info: VRInfo | None) -> str:
    if info is None:
        return ""
    if info.projection == "flat":
        return "3D"
    return {"180": "VR 180°", "360": "VR 360°", "fisheye": f"VR fisheye {info.lens}°"}[info.projection]


def clamp_look(yaw: float, pitch: float, fov: float, info: VRInfo | None) -> tuple:
    """Yaw wraps on 360; on 180 and fisheye it stops where the picture ends. Pitch stays between the poles."""
    fov = max(FOV_RANGE[0], min(FOV_RANGE[1], fov))
    if info is not None and info.projection == "360":
        yaw = (yaw + 180.0) % 360.0 - 180.0
    else:
        half = (info.lens if info and info.projection == "fisheye" else 180) / 2
        edge = max(0.0, half - fov / 2 * 0.6)
        yaw = max(-edge, min(edge, yaw))
    pitch = max(-85.0, min(85.0, pitch))
    return round(yaw, 2), round(pitch, 2), round(fov, 2)


def v_fov(fov: float, aspect: float = 16 / 9) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(fov) / 2) / aspect))


def mpv_filter(info: VRInfo | None, view: str = "left", yaw: float = 0.0, pitch: float = 0.0,
               fov: float = DEFAULT_FOV) -> str | None:
    """Value for mpv's `vf` property (software, for vo=gpu), or None for ordinary video / pass-through.
    The look view is labelled @vr, so its yaw, pitch and field of view can change without rebuilding it."""
    if info is None:
        return None
    if view == "sbs":
        return "lavfi=[stereo3d=in=abl:out=sbsl]" if info.layout == "tb" else None
    graph = []
    if info.layout == "sbs":
        graph.append("stereo3d=in=sbsl:out=ml")
        if not info.full and info.projection == "flat":
            graph.append("scale=iw*2:ih")
    elif info.layout == "tb":
        graph.append("stereo3d=in=abl:out=ml")
        if not info.full and info.projection == "flat":
            graph.append("scale=iw:ih*2")
    if info.projection != "flat":
        src = {"180": "input=hequirect", "360": "input=equirect",
               "fisheye": f"input=fisheye:ih_fov={info.lens}:iv_fov={info.lens}"}[info.projection]
        graph.append(f"v360={src}:output=flat:w=1920:h=1080:yaw={yaw}:pitch={pitch}"
                     f":h_fov={fov}:v_fov={v_fov(fov):.2f}")
    graph.append("setsar=1")
    return ("@vr:" if info.projection != "flat" else "") + "lavfi=[" + ",".join(graph) + "]"


SHADER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vr_view.glsl")


def shader_opts(info: VRInfo, yaw: float, pitch: float, fov: float) -> str:
    """Values for the GPU look-around shader (vr_view.glsl), as mpv's glsl-shader-opts."""
    proj = {"180": 0, "360": 1, "fisheye": 2}[info.projection]
    layout = {"mono": 0, "sbs": 1, "tb": 2}[info.layout]
    return f"proj={proj},stereo={layout},lens={float(info.lens)},yaw={float(yaw)},pitch={float(pitch)},fov={float(fov)}"
