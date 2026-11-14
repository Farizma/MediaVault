"""Rename video files on disk to match their library titles: "Heat (1995).mkv", "Severance S01E02 - Half Loop.mkv".

plan() only describes; apply() renames the file, its artwork and subtitles beside it, and moves everything the library
knows about it to the new name. Folders are never renamed."""
import logging
import os
import re
from pathlib import Path

import database as db
from utils import scraper

log = logging.getLogger(__name__)

_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
SIDECARS = (".srt", ".ass", ".ssa", ".sub", ".vtt", ".idx", ".nfo")


def clean(name: str) -> str:
    """A name Windows accepts: no reserved characters, no trailing dot or space."""
    name = re.sub(r"\s+", " ", _BAD.sub(" ", name.replace(":", " -"))).strip(" .")
    return f"_{name}" if name.lower() in _RESERVED else name[:180]


def wanted(item: dict) -> str | None:
    """The file name (no extension) this title should have. None: leave it alone (a personal clip, no title)."""
    if item["media_type"] == "clip" or not (item.get("title") or "").strip():
        return None
    if item["media_type"] == "show":
        se = scraper.season_episode(item["title"])
        if not se:
            return None
        name = f"{db.series_title(item['title'])} S{se[0]:02d}E{se[1]:02d}"
        if item.get("episode_title"):
            name += f" - {item['episode_title']}"
        return clean(name)
    year = (item.get("release_date") or "")[:4]
    return clean(f"{item['title']} ({year})" if year.isdigit() else item["title"])


def plan(items: list[dict]) -> list[dict]:
    """One row per file that would change: {uuid, folder, old, new, problem}. problem "" = it can be renamed."""
    rows, taken = [], set()
    for it in items:
        src = Path(it["file_path"])
        stem = wanted(it)
        if not stem or stem == src.stem:
            continue
        dst = src.with_name(stem + src.suffix.lower())
        key = os.path.normcase(str(dst))
        problem = ""
        if not src.exists():
            problem = "The file is not there (drive unplugged?)"
        elif key in taken or (dst.exists() and os.path.normcase(str(src)) != key):
            problem = "Another file already has this name"
        taken.add(key)
        rows.append({"uuid": it["uuid"], "folder": str(src.parent), "old": src.name, "new": dst.name, "problem": problem})
    return rows


def _companions(src: Path, new_stem: str) -> list[tuple[Path, Path]]:
    """What carries the old name beside the video: its artwork in .vault-assets, subtitles, a spine image."""
    out = []
    assets = src.parent / scraper.ASSET_DIR
    for folder, exts in ((assets, None), (src.parent, SIDECARS + scraper.IMAGE_EXTS)):
        if not folder.is_dir():
            continue
        for p in folder.iterdir():
            rest = p.name[len(src.stem):]
            if p == src or not p.name.startswith(src.stem) or rest[:1] not in (".", "-"):
                continue                                     # "Heat 2.mkv" is not a companion of "Heat.mkv"
            if exts and p.suffix.lower() not in exts:
                continue
            out.append((p, p.with_name(new_stem + rest)))
    return out


def apply(rows: list[dict], step=lambda name: None) -> tuple[int, list[str]]:
    """Rename what plan() listed (rows with a problem are skipped). Returns (renamed, errors)."""
    done, errors = 0, []
    for r in rows:
        if r.get("problem"):
            continue
        src, dst = Path(r["folder"]) / r["old"], Path(r["folder"]) / r["new"]
        step(r["new"])
        item = db.get_media(r["uuid"])
        if not item or db.norm(item["file_path"]) != db.norm(str(src)) or (dst.exists() and not src.samefile(dst)):
            errors.append(f"{r['old']}: changed since the preview")
            continue
        companions = _companions(src, dst.stem)
        # the library first: the folder watcher sees the rename a moment later and must find the title under its new name
        new_id = db.move_item(r["uuid"], str(dst))
        try:
            os.rename(src, dst)
        except OSError as e:
            db.move_item(new_id, str(src))
            errors.append(f"{r['old']}: {e.strerror or e}")
            continue
        for a, b in companions:
            try:
                if not b.exists():
                    os.rename(a, b)
            except OSError:
                log.warning("could not rename %s", a, exc_info=True)
        done += 1
    return done, errors
