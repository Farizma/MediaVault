"""DVD / Blu-ray box art kept next to the videos, found while scraping.

No online source publishes case scans (TMDB and fanart.tv have posters and disc art, not sleeves), so the place to
look is beside the file: "Heat-cover.jpg", "Heat-dvdcover.png", "Heat-back.jpg"; and in a folder that holds one
film, or a series folder, plain "cover.jpg", "dvd.png", "back.jpg". A whole-sleeve scan (back | spine | front) is
cut into its three faces; a narrower one becomes the front. It becomes the title's own box art, so it shows over the
scraped poster. Each file is used once: your own art is never replaced, and Reset in View More is not undone by the
next scrape.
"""
import logging
import os
from collections import defaultdict
from pathlib import Path

from PIL import Image

import database as db
from utils import boxwrap, scraper

log = logging.getLogger(__name__)

COVER = ("cover", "dvdcover", "dvd-cover", "dvd", "bluray", "blu-ray", "boxart", "box", "case", "sleeve", "front")
BACK = ("back", "backcover", "back-cover", "dvdback", "dvd-back")


def _first(folder: Path, names) -> Path | None:
    for name in names:
        for ext in scraper.IMAGE_EXTS:
            p = folder / (name + ext)
            if p.is_file():
                return p
    return None


def find(video: str, generic: bool) -> dict:
    """{"cover": path or None, "back": path or None} for one video. generic: plain names ("cover.jpg") count too."""
    p = Path(video)
    folder, stem = p.parent, p.stem
    out = {}
    for kind, names in (("cover", COVER), ("back", BACK)):
        own = [f"{stem}{sep}{n}" for n in names for sep in ("-", ".", " - ", "_")]
        out[kind] = _first(folder, own + (list(names) if generic else []))
    return out


def _marker(item: dict) -> Path:
    return scraper.banner_path(item).with_name(
        "_series.boxart-src" if item["media_type"] == "show" else f"{scraper._stem(item)}.boxart-src")


def apply(items: list[dict], found: dict) -> list[str]:
    """Use found box art for these items (a film, or every episode of a series). Returns the faces set."""
    cover, back = found.get("cover"), found.get("back")
    if not (cover or back) or not items:
        return []
    sig = "|".join(f"{p}:{os.path.getmtime(p):.0f}" for p in (cover, back) if p)
    mark = _marker(items[0])
    try:
        if mark.read_text(encoding="utf-8") == sig:
            return []                                 # used before (and perhaps reset since): leave it
    except OSError:
        pass
    mine = any(f(items[0]).exists() for f in (scraper.custom_front_path, scraper.custom_back_path, scraper.custom_spine_path))
    done = []
    if not mine:                                      # your own box art always wins
        from ui.dashboard import save_box_art
        try:
            if cover:
                with Image.open(cover) as img:
                    img.load()
                    if boxwrap.is_wrap(img):
                        for face, part in boxwrap.split(img).items():
                            save_box_art(part, items, face)
                            done.append(face)
                    else:
                        save_box_art(img, items, "front")
                        done.append("front")
            if back and "back" not in done:
                with Image.open(back) as img:
                    img.load()
                    save_box_art(img, items, "back")
                    done.append("back")
        except Exception:
            log.warning("box art next to %s could not be used", items[0]["file_path"], exc_info=True)
            return []
    mark.parent.mkdir(parents=True, exist_ok=True)
    mark.write_text(sig, encoding="utf-8")
    return done


def scan(directory: dict, only: set | None = None) -> int:
    """Look beside every film and series of a folder (only: just these file ids). Returns titles that got box art."""
    by_folder = defaultdict(list)
    for it in db.list_media(directory["id"]):
        if it["media_type"] != "clip":
            by_folder[os.path.dirname(it["file_path"])].append(it)
    got = 0
    for folder, items in by_folder.items():
        shows = [i for i in items if i["media_type"] == "show"]
        films = [i for i in items if i["media_type"] == "movie"]
        if shows and (only is None or any(i["uuid"] in only for i in shows)):
            # a series: one sleeve for the whole folder (plain names, or named after the folder)
            name = Path(folder).name
            found = {"cover": _first(Path(folder), [f"{name}-{n}" for n in COVER] + list(COVER)),
                     "back": _first(Path(folder), [f"{name}-{n}" for n in BACK] + list(BACK))}
            got += bool(apply(shows, found))
        for f in films:
            if only is None or f["uuid"] in only:
                got += bool(apply([f], find(f["file_path"], generic=len(items) == 1)))
    return got
