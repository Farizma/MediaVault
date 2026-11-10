"""Metadata scraper: filename cleanse, JSON APIs (TMDB, then OMDb), 3 requests at a time.

Outcome per title is one of:
  dict            found
  None            the API answered and has no match  -> caller records it in failed_scrapes
  ScrapeError     network / key problem               -> caller retries later, records nothing
"""
import asyncio
import io
import json
import logging
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NamedTuple

import database as db

log = logging.getLogger(__name__)

CONCURRENCY = 3
ASSET_DIR = ".vault-assets"
POSTER_BOX = (360, 540)  # largest image that ever reaches the UI cache
FANART_BOX = (960, 540)  # only for frames the user captures for the billboard

GENRES = {28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime", 99: "Documentary",
          18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
          9648: "Mystery", 10749: "Romance", 878: "Science Fiction", 10770: "TV Movie", 53: "Thriller",
          10752: "War", 37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
          10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk",
          10768: "War & Politics"}


class ScrapeError(Exception):
    pass


class Parsed(NamedTuple):
    title: str
    year: str | None
    season: int | None
    episode: int | None


# ------------------------------------------------------------ 1. filename cleansing

_GROUP = re.compile(r"\[[^\]]*\]")
_SXE = re.compile(r"[Ss](\d{1,2})[ ._-]?[Ee](\d{1,3})")
_YEAR = re.compile(r"[\s(]((?:19|20)\d{2})\b")
_JUNK = re.compile(r"\b(?:480p|576p|720p|1080p|1440p|2160p|4k|uhd|bluray|blu-ray|brrip|bdrip|web-?dl|webrip|"
                   r"hdrip|dvdrip|hdtv|x264|x265|h\.?26[45]|hevc|avc|aac|ac3|eac3|dts|ddp?5?|hdr10?\+?|"
                   r"remux|proper|repack|extended|unrated|imax|10bit)\b", re.I)


def clean_name(filename: str, fallback: str = "") -> Parsed:
    """'The.Movie.2019.1080p.BluRay.x264-GRP.mkv' -> Parsed('The Movie', '2019', None, None)."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = re.sub(r"[._]+", " ", _GROUP.sub(" ", stem))
    season = episode = year = None
    if m := _SXE.search(stem):
        season, episode, stem = int(m[1]), int(m[2]), stem[:m.start()]
    if years := list(_YEAR.finditer(stem)):
        year, stem = years[-1][1], stem[:years[-1].start()]
    stem = _JUNK.split(stem, maxsplit=1)[0]
    title = re.sub(r"\s{2,}", " ", stem).strip(" -(")
    return Parsed(title or fallback or os.path.splitext(os.path.basename(filename))[0], year, season, episode)


# ------------------------------------------------------------ 2. JSON APIs

def api_keys() -> dict:
    return {"tmdb": os.environ.get("TMDB_API_KEY") or db.get_setting("tmdb_key") or "",
            "omdb": os.environ.get("OMDB_API_KEY") or db.get_setting("omdb_key") or "",
            "fanart": os.environ.get("FANART_API_KEY") or db.get_setting("fanart_key") or ""}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "MediaVault/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except Exception as e:
        raise ScrapeError(str(e).replace(url, "<url>")) from None  # keep the API key out of logs


def _tmdb(kind: str, p: Parsed, key: str) -> dict | None:
    path = "search/tv" if kind == "show" else "search/movie"
    year_key = "first_air_date_year" if kind == "show" else "year"
    q = {"api_key": key, "query": p.title, **({year_key: p.year} if p.year else {})}
    data = _get_json(f"https://api.themoviedb.org/3/{path}?{urllib.parse.urlencode(q)}")
    if not data.get("results") and p.year:  # year is sometimes part of the title ("Wonder Woman 1984")
        q.pop(year_key)
        data = _get_json(f"https://api.themoviedb.org/3/{path}?{urllib.parse.urlencode(q)}")
    r = (data.get("results") or [None])[0]
    if not r:
        return None
    poster = r.get("poster_path")
    return {"tmdb_id": r.get("id"), "title": r.get("title") or r.get("name"),
            "release_date": r.get("release_date") or r.get("first_air_date"),
            "synopsis": r.get("overview"),
            "poster_url": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
            "genres": [GENRES[i] for i in r.get("genre_ids", []) if i in GENRES],
            "score": _score(r)}


def _score(r: dict) -> float | None:
    """TMDB vote average (0-10), only when enough people voted for it to mean something."""
    avg, votes = r.get("vote_average"), r.get("vote_count") or 0
    return round(float(avg), 1) if avg and votes >= 5 else None


IMG = "https://image.tmdb.org/t/p/"


def _tmdb_json(path: str, key: str, **q) -> dict:
    return _get_json(f"https://api.themoviedb.org/3/{path}?{urllib.parse.urlencode({'api_key': key, **q})}")


def tmdb_search(kind: str, query: str, year: str, key: str) -> list[dict]:
    """Fix match: up to 12 candidates for a title (TMDB only; OMDb has no search with ids)."""
    if not key:
        raise ScrapeError("Fix match needs a TMDB API key (Settings \u203A Integrations)")
    path = "search/tv" if kind == "show" else "search/movie"
    year_key = "first_air_date_year" if kind == "show" else "year"
    data = _tmdb_json(path, key, query=query, **({year_key: year} if year else {}))
    out = []
    for r in (data.get("results") or [])[:12]:
        poster = r.get("poster_path")
        out.append({"tmdbId": r.get("id"), "title": r.get("title") or r.get("name") or "",
                    "year": (r.get("release_date") or r.get("first_air_date") or "")[:4],
                    "overview": r.get("overview") or "",
                    "thumb": f"{IMG}w185{poster}" if poster else ""})
    return out


def tmdb_details(kind: str, tmdb_id: int, key: str) -> dict:
    """Everything for one title by id, in the same shape as a search hit, plus its collection (films only)."""
    credits = "aggregate_credits" if kind == "show" else "credits"
    r = _tmdb_json(f"{'tv' if kind == 'show' else 'movie'}/{int(tmdb_id)}", key, append_to_response=credits)
    poster, coll = r.get("poster_path"), r.get("belongs_to_collection") or {}
    return {"tmdb_id": r.get("id"), "title": r.get("title") or r.get("name"),
            "release_date": r.get("release_date") or r.get("first_air_date"),
            "synopsis": r.get("overview"),
            "poster_url": f"{IMG}w500{poster}" if poster else None,
            "genres": [g["name"] for g in r.get("genres") or [] if g.get("name")],
            "score": _score(r),
            "collection_id": coll.get("id"), "collection_name": coll.get("name"),
            "collection_poster_url": f"{IMG}w500{coll['poster_path']}" if coll.get("poster_path") else None,
            "cast": _cast((r.get(credits) or {}).get("cast") or [])}


CAST_MAX = 15


def _cast(people: list[dict]) -> list[dict]:
    """Top-billed actors: id, name, the part they play, and a photo URL (TMDB profile picture, if any).
    Series (aggregate credits) list several roles per actor; the one with the most episodes is shown."""
    out = []
    for p in people[:CAST_MAX]:
        roles = p.get("roles")
        role = max(roles, key=lambda r: r.get("episode_count") or 0).get("character") if roles else p.get("character")
        out.append({"id": p.get("id"), "name": p.get("name") or "", "role": role or "",
                    "photo_url": f"{IMG}w185{p['profile_path']}" if p.get("profile_path") else None})
    return [c for c in out if c["name"]]


def save_round(img, dest: Path, size: int = 160) -> None:
    """A face for a round avatar: square crop from the top third (where faces are), cut to a circle with a soft
    edge, transparent outside. Done once here, so drawing it needs no GPU mask."""
    from PIL import Image, ImageDraw, ImageOps
    img = ImageOps.fit(img.convert("RGB"), (size, size), Image.Resampling.LANCZOS, centering=(0.5, 0.3))
    big = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    out = img.convert("RGBA")
    out.putalpha(big.resize((size, size), Image.Resampling.LANCZOS))
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, "WEBP", quality=80)


def person_photo_path(person_id) -> Path:
    """Actor photos are shared by every title they appear in: one file per person in the app cache."""
    return db.data_dir() / "cache" / "people" / f"{int(person_id)}.webp"


def save_person_photos(cast: list[dict]) -> None:
    for c in cast:
        if not (c.get("id") and c.get("photo_url")):
            continue
        dest = person_photo_path(c["id"])
        if dest.exists():
            continue
        try:
            save_round(fetch_image(c["photo_url"]), dest)
        except Exception:
            logging.getLogger(__name__).warning("photo failed for %s", c["name"], exc_info=True)


def _omdb(kind: str, p: Parsed, key: str) -> dict | None:
    q = {"apikey": key, "t": p.title, "type": "series" if kind == "show" else "movie",
         **({"y": p.year} if p.year else {})}
    r = _get_json(f"https://www.omdbapi.com/?{urllib.parse.urlencode(q)}")
    if r.get("Response") != "True":
        if "invalid api key" in str(r.get("Error", "")).lower():
            raise ScrapeError("OMDb rejected the API key")
        return None
    poster = r.get("Poster")
    try:
        imdb = round(float(r.get("imdbRating")), 1)
    except (TypeError, ValueError):
        imdb = None
    return {"score": imdb, "title": r.get("Title"), "release_date": r.get("Released") if r.get("Released") != "N/A" else r.get("Year"),
            "synopsis": r.get("Plot") if r.get("Plot") != "N/A" else None,
            "poster_url": poster if poster and poster != "N/A" else None,
            "genres": [g.strip() for g in (r.get("Genre") or "").split(",") if g.strip() and g != "N/A"]}


def disc_url(tmdb_id, key: str) -> str | None:
    """fanart.tv disc art for a film (by TMDB id): the most-liked disc, English or language-free first.
    fanart.tv has no disc art for TV series."""
    if not (tmdb_id and key):
        return None
    try:
        data = _get_json(f"https://webservice.fanart.tv/v3/movies/{int(tmdb_id)}?api_key={urllib.parse.quote(key)}")
    except ScrapeError:
        return None
    discs = [d for d in data.get("moviedisc") or [] if str(d.get("url", "")).startswith("https://")]
    discs.sort(key=lambda d: (d.get("lang") not in ("en", "00", ""), -int(d.get("likes") or 0)))
    return discs[0]["url"] if discs else None


def _lookup(kind: str, p: Parsed, keys: dict) -> dict | None:
    if not (keys.get("tmdb") or keys.get("omdb")):
        raise ScrapeError("no API key configured")
    if keys.get("tmdb") and (hit := _tmdb(kind, p, keys["tmdb"])):
        if hit.get("tmdb_id"):
            try:   # one more request: the search result has no cast, and does not say which collection a film is in
                d = tmdb_details(kind, hit["tmdb_id"], keys["tmdb"])
                hit.update({k: d[k] for k in ("collection_id", "collection_name", "collection_poster_url", "cast")})
                if kind == "show":
                    hit["collection_id"] = hit["collection_name"] = None
            except ScrapeError:
                pass
        hit["disc_url"] = disc_url(hit.get("tmdb_id"), keys.get("fanart", "")) if kind == "movie" else None
        return hit
    return _omdb(kind, p, keys["omdb"]) if keys.get("omdb") else None


async def scrape_many(jobs: list[tuple[str, Parsed]], keys: dict) -> list:
    """jobs = [(media_type, Parsed)]. Same show/title is asked once (memory cache)."""
    sem = asyncio.Semaphore(CONCURRENCY)
    unique = list(dict.fromkeys((k, p.title, p.year) for k, p in jobs))

    async def one(kind, title, year):
        async with sem:
            try:
                return await asyncio.to_thread(_lookup, kind, Parsed(title, year, None, None), keys)
            except ScrapeError as e:
                return e

    answers = dict(zip(unique, await asyncio.gather(*(one(*u) for u in unique))))
    return [answers[(k, p.title, p.year)] for k, p in jobs]


# ------------------------------------------------------------ 3. images and sidecar paths

def fetch_image(url: str):
    from PIL import Image
    req = urllib.request.Request(url, headers={"User-Agent": "MediaVault/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return Image.open(io.BytesIO(r.read()))


def save_webp(img, dest: Path, box=POSTER_BOX) -> None:
    """Shrink to `box`, WebP quality 70. Pillow runs on the CPU; this is not GPU downscaling."""
    img = img.convert("RGB")
    img.thumbnail(box)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.parent.name == ASSET_DIR and sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(dest.parent), 0x2)  # hidden
    img.save(dest, "WEBP", quality=70)


def _assets(item: dict) -> Path:
    if item["media_type"] == "clip":  # personal clips: central cache, not next to the file
        return db.data_dir() / "cache"
    return Path(item["file_path"]).parent / ASSET_DIR


def _stem(item: dict) -> str:
    return item["uuid"] if item["media_type"] == "clip" else Path(item["file_path"]).stem


def poster_path(item: dict) -> Path:
    return _assets(item) / f"{_stem(item)}.webp"


def fanart_path(item: dict) -> Path:
    return _assets(item) / f"{_stem(item)}.fanart.webp"


def custom_front_path(item: dict) -> Path:
    """Box art the user picked. Shown instead of the scraped poster; deleting it brings the scraped one back."""
    return _assets(item) / f"{_stem(item)}.front.webp"


def custom_back_path(item: dict) -> Path:
    return _assets(item) / f"{_stem(item)}.back.webp"


def custom_spine_path(item: dict) -> Path:
    return _assets(item) / f"{_stem(item)}.spine.webp"


SPINE_NAMES = ("{stem}-spine", "{stem}.spine", "spine")  # beside the video; no online source publishes spines
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def spine_path(item: dict) -> Path | None:
    """Spine art: the user's own first, then an image found next to the video (Movie-spine.jpg, spine.png, ...).
    None: the box draws a spine from the title."""
    custom = custom_spine_path(item)
    if custom.exists():
        return custom
    if item["media_type"] == "clip":
        return None
    folder, stem = Path(item["file_path"]).parent, Path(item["file_path"]).stem
    for name in SPINE_NAMES:
        for ext in IMAGE_EXTS:
            p = folder / (name.format(stem=stem) + ext)
            if p.is_file():
                return p
    return None


def disc_path(item: dict) -> Path:
    """Disc art from fanart.tv."""
    return _assets(item) / f"{_stem(item)}.discart.webp"


def custom_disc_path(item: dict) -> Path:
    return _assets(item) / f"{_stem(item)}.disc.webp"


def disc_art(item: dict) -> Path | None:
    """What the disc shows: your own disc art, else the scraped disc, else the front cover. None: plain silver."""
    for p in (custom_disc_path(item), disc_path(item), cover_path(item)):
        if p.exists():
            return p
    return None


def collection_item(cid: int, name: str = "", synopsis: str = "") -> dict:
    """A stand-in item for a collection's box art: lives in the app cache, keyed 'set-<id>', so the usual
    poster / custom front, back, spine and disc paths all work for it."""
    return {"uuid": f"set-{int(cid)}", "media_type": "clip", "file_path": "", "title": name, "synopsis": synopsis}


def save_collection_poster(cid, url: str, cache: dict | None = None, force: bool = False) -> None:
    """The box set's poster, once (a scan may meet the same collection many times)."""
    dest = poster_path(collection_item(cid))
    if dest.exists() and not force:
        return
    try:
        img = cache.get(url) if cache is not None else None
        if img is None:
            img = fetch_image(url)
            if cache is not None:
                cache[url] = img
        save_webp(img, dest)
    except Exception:
        logging.getLogger(__name__).warning("collection poster failed for %s", cid, exc_info=True)


def cover_path(item: dict) -> Path:
    """The front cover to show: the user's own art if set, else the scraped / captured poster."""
    custom = custom_front_path(item)
    return custom if custom.exists() else poster_path(item)
