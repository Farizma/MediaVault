"""Library health: duplicate copies, missing episodes, missing artwork and folder status.

Reports only. Nothing here deletes or moves a file; the person decides (Show in folder, Ignore)."""
import os
import re
from collections import defaultdict

import database as db
from utils import scraper

_SE = re.compile(r"S(\d{1,2})E(\d{1,3})", re.I)
_QUALITY = {"4k": 4, "1080": 3, "720": 2, "sd": 1, "": 0}


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def _size_mb(path: str) -> int:
    try:
        return round(os.path.getsize(path) / 2 ** 20)
    except OSError:
        return 0


def duplicates(items: list[dict], quality_of) -> list[dict]:
    """The same film (title + year) or the same episode (series + SxxEyy) more than once.
    The best copy is the highest quality class, then the bigger file (more bitrate)."""
    groups = defaultdict(list)
    for it in items:
        if it["media_type"] == "show":
            m = _SE.search(it["title"])
            if not m:
                continue
            key = f"show:{_norm(db.series_title(it['title']))}:s{int(m.group(1))}e{int(m.group(2))}"
        else:
            key = f"{it['media_type']}:{_norm(it['title'])}:{(it['release_date'] or '')[:4]}"
        groups[key].append(it)
    out = []
    for key, copies in groups.items():
        if len(copies) < 2:
            continue
        files = [{"uuid": c["uuid"], "path": c["file_path"], "resolution": c["resolution"] or "?",
                  "codec": c["codec"] or "", "sizeMb": _size_mb(c["file_path"]),
                  "rank": _QUALITY.get(quality_of(c["resolution"]), 0)} for c in copies]
        best = max(files, key=lambda f: (f["rank"], f["sizeMb"]))
        for f in files:
            f["best"] = f is best
        out.append({"key": key, "title": copies[0]["title"], "files": sorted(files, key=lambda f: -f["rank"])})
    return sorted(out, key=lambda d: d["title"].lower())


def missing_episodes(items: list[dict]) -> list[dict]:
    """Gaps in each season's numbering, per series folder (S01E01, E02, E04 -> E03 is missing)."""
    seasons = defaultdict(lambda: defaultdict(set))
    names = {}
    for it in items:
        m = _SE.search(it["title"]) if it["media_type"] == "show" else None
        if m:
            folder = os.path.dirname(it["file_path"])
            seasons[folder][int(m.group(1))].add(int(m.group(2)))
            names[folder] = db.series_title(it["title"]).strip() or os.path.basename(folder)
    out = []
    for folder, by_season in seasons.items():
        gaps = [f"S{s:02d}E{e:02d}" for s, eps in sorted(by_season.items())
                for e in range(1, max(eps) + 1) if e not in eps]
        if gaps:
            out.append({"key": folder, "title": names[folder], "missing": gaps})
    return sorted(out, key=lambda d: d["title"].lower())


def missing_artwork(cards: list[dict]) -> list[dict]:
    """Library cards with no front cover (scraped, captured or your own)."""
    return sorted(({"key": c["key"], "title": c["title"], "path": c["file_path"]}
                   for c in cards if not scraper.cover_path(c).exists()), key=lambda d: d["title"].lower())


def folders(items: list[dict]) -> list[dict]:
    """Each watched folder: reachable? how many titles, how many files no longer where the library expects."""
    by_dir = defaultdict(list)
    for it in items:
        by_dir[it["parent_directory_id"]].append(it)
    out = []
    for d in db.list_directories():
        online = os.path.isdir(d["folder_path"])
        files = by_dir.get(d["id"], [])
        missing = [f["file_path"] for f in files if not os.path.exists(f["file_path"])] if online else []
        out.append({"id": d["id"], "name": d["tab_name"], "path": d["folder_path"], "online": online,
                    "titles": len(files), "missing": len(missing), "examples": missing[:3]})
    return out


def report(quality_of, ignored_now: dict[str, set]) -> dict:
    """Everything for Settings > Library health, minus what was ignored (for now, or for good)."""
    items = db.list_media(None)
    cards = db.list_library(None, sets=False)

    def keep(kind, rows):
        hidden = db.ignored(kind) | ignored_now.get(kind, set())
        return [r for r in rows if r["key"] not in hidden]

    return {"duplicates": keep("duplicate", duplicates(items, quality_of)),
            "episodes": keep("missing_episode", missing_episodes(items)),
            "artwork": keep("missing_art", missing_artwork(cards)),
            "folders": folders(items)}
