"""Finds stereoscopic / VR tags in a filename and builds the mpv filter that splits the frame.

Tags: `_3D_SBS`, `_3D_TB`, `_180_TB`, `_180_SBS`, `_360`, `_360_TB`. Add `FSBS` / `FTB` for
full-width / full-height stereo; plain SBS and TB are assumed to be the common half-width kind.

Two views (key `v` in the player):
  left  one eye as a flat picture, for an ordinary monitor
  sbs   both eyes side by side, handed untouched to a 3D / VR display (top-bottom is converted
        to side-by-side first). Headset-native output (OpenXR) is a separate project.
"""
import os
import re
from typing import NamedTuple


class VRInfo(NamedTuple):
    projection: str  # "flat" (3D movie) | "180" | "360"
    layout: str      # "mono" | "sbs" | "tb"
    full: bool       # full-size stereo (no rescale after the eye split)


_SPLIT = re.compile(r"[\s._\-\[\]()]+")


def detect(path: str) -> VRInfo | None:
    tokens = {t.upper() for t in _SPLIT.split(os.path.splitext(os.path.basename(path))[0]) if t}
    projection = "180" if "180" in tokens else "360" if "360" in tokens else "flat" if "3D" in tokens else None
    if projection is None:
        return None
    full = bool(tokens & {"FSBS", "FTB"})
    if tokens & {"SBS", "HSBS", "FSBS", "LR"}:
        layout = "sbs"
    elif tokens & {"TB", "HTB", "FTB", "OU", "HOU"}:
        layout = "tb"
    else:
        layout = "sbs" if projection == "flat" else "mono"  # a bare "_3D" is almost always side-by-side
    return VRInfo(projection, layout, full)


VIEWS = ("left", "sbs")


def mpv_filter(info: VRInfo | None, view: str = "left") -> str | None:
    """Value for mpv's `vf` property, or None for ordinary video / pass-through."""
    if info is None:
        return None
    if view == "sbs":
        return "lavfi=[stereo3d=in=abl:out=sbsl]" if info.layout == "tb" else None
    graph = []
    if info.layout == "sbs":
        graph.append("stereo3d=in=sbsl:out=ml")
        if not info.full:
            graph.append("scale=iw*2:ih")
    elif info.layout == "tb":
        graph.append("stereo3d=in=abl:out=ml")
        if not info.full:
            graph.append("scale=iw:ih*2")
    if info.projection != "flat":
        src = "hequirect" if info.projection == "180" else "equirect"
        graph.append(f"v360=input={src}:output=flat:h_fov=100:v_fov=70")
    graph.append("setsar=1")
    return "lavfi=[" + ",".join(graph) + "]"
