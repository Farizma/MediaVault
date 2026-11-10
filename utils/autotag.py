"""Automatic tags from where a file is and what its name says. Stored as "auto:<tag>" so they can be refreshed
without touching the tags you typed, and shown like any other tag (you can remove them).

From the folders: every folder between the library folder and the file ("Movies/Action/Heat.mkv" -> Action),
except season folders and a folder that is just the title (Heat (1995)/Heat.mkv).
From the file name: resolution, HDR / Dolby Vision, source (Blu-ray, Remux, Web, DVD), video codec, audio format,
edition (Director's Cut, Extended, IMAX, ...), 3D, multi-language, the release group of an anime file, and the decade.
"""
import os
import re

PREFIX = "auto:"

_SEASON = re.compile(r"^(season|series|s)\s*\d{1,2}$|^specials?$", re.I)
_YEAR = re.compile(r"(?<!\d)(19[2-9]\d|20[0-4]\d)(?!\d)")

# (pattern on the file name, tag). The first match of a group wins, so put specific spellings first.
GROUPS = [
    [(r"2160p|\b4k\b|\buhd\b", "4K"), (r"1080[pi]", "1080p"), (r"\b720p\b", "720p"), (r"\b(480|576)p\b", "SD")],
    [(r"\b(dv|dovi|dolby[ ._-]?vision)\b", "Dolby Vision"), (r"\bhdr10\+", "HDR10+"), (r"\bhdr(10)?\b", "HDR"), (r"\bhlg\b", "HLG")],
    [(r"\bremux\b", "Remux"), (r"\b(blu[ ._-]?ray|bdrip|brrip|bd25|bd50)\b", "Blu-ray"),
     (r"\b(web[ ._-]?dl|webrip|web)\b", "Web"), (r"\bhdtv\b", "TV"), (r"\b(dvdrip|dvd)\b", "DVD")],
    [(r"\b(x265|h[ ._]?265|hevc)\b", "HEVC"), (r"\bav1\b", "AV1"), (r"\b(x264|h[ ._]?264|avc)\b", "H.264")],
    [(r"\batmos\b", "Atmos"), (r"\btruehd\b", "TrueHD"), (r"\bdts[ ._-]?(hd|x|ma)\b", "DTS-HD"), (r"\bdts\b", "DTS"),
     (r"\b(ddp|dd\+|eac3)\b", "Dolby Digital Plus"), (r"\b(ac3|dd5)\b", "Dolby Digital"), (r"\bflac\b", "FLAC")],
    [(r"director'?s[ ._-]?cut", "Director's Cut"), (r"\bextended\b", "Extended"), (r"\bunrated\b", "Unrated"),
     (r"\btheatrical\b", "Theatrical"), (r"\bimax\b", "IMAX"), (r"\bremaster(ed)?\b", "Remastered"),
     (r"\bcriterion\b", "Criterion"), (r"special[ ._-]?edition", "Special Edition"), (r"\buncut\b", "Uncut")],
    [(r"\b(3d|h?sbs|h?ou)\b", "3D")],
    [(r"\bmulti\b", "Multi-language"), (r"\bdual[ ._-]?audio\b|\bdual\b", "Dual audio")],
]
_GROUPS = [[(re.compile(p, re.I), t) for p, t in g] for g in GROUPS]
_RELEASE = re.compile(r"^\[([^\]]{2,30})\]")          # anime fansub / release group: "[SubsPlease] Title - 07.mkv"


def _same_as_title(folder: str, stem: str) -> bool:
    simple = lambda s: re.sub(r"[^a-z0-9]+", "", _YEAR.sub("", s.lower()))
    f, t = simple(folder), simple(stem)
    return bool(f) and (f == t or t.startswith(f) or f.startswith(t))


def tags_for(path: str, root: str, show: bool = False) -> list[str]:
    """Tag names (without the prefix) for one file under the library folder `root`. For a series episode the
    series' own folder (the one above any season folder) is its name, not a tag."""
    rel = os.path.relpath(path, root) if root else os.path.basename(path)
    parts = [p for p in re.split(r"[\\/]+", rel) if p and p not in (".", "..")]
    name, folders = (parts[-1], parts[:-1]) if parts else (os.path.basename(path), [])
    stem = os.path.splitext(name)[0]
    if show:
        kept = [f for f in folders if not _SEASON.match(f.strip())]
        if kept:
            series = kept[-1]
            folders = [f for f in folders if f != series]
    out = []
    for f in folders:
        if f.startswith(".") or _SEASON.match(f.strip()) or _same_as_title(f, stem):
            continue
        out.append(f.strip())
    text = stem.replace("_", " ")
    for group in _GROUPS:
        for rx, tag in group:
            if rx.search(text):
                out.append(tag)
                break
    m = _RELEASE.match(name)
    if m:
        out.append(f"Release: {m[1].strip()}")
    years = _YEAR.findall(text)
    if years:
        out.append(f"{years[-1][:3]}0s")
    seen, unique = set(), []
    for t in out:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique.append(t)
    return unique
