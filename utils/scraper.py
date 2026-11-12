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
from utils import alttitles

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
                   r"remux|proper|repack|extended|unrated|uncensored|imax|10bit)\b", re.I)


# anime releases: "[Group] Title - 07 (1080p)", "Title - 07v2", "Title S2 - 07", "Title Ep 07", "Title E07",
# "Title Episode 1", "Title - Episode 01", "Title OVA 1", and a zero-padded "Title 01"
_ANIME_EP = re.compile(r"(?:\s(?:S|Season\s?)(\d{1,2}))?\s(?:-\s(?:Episode\s?|Ep\.?\s?)?|Episode\s?|Ep\.?\s?|OVA\s?|OAD\s?|E|#|(?=0\d))"
                       r"(\d{1,4})(?:v\d)?(?=\s|$|[(\[])", re.I)
_SEASON_DIR = re.compile(r"^(?:season|s)\s*(\d{1,2})$", re.I)


def clean_name(filename: str, fallback: str = "") -> Parsed:
    """'The.Movie.2019.1080p.BluRay.x264-GRP.mkv' -> Parsed('The Movie', '2019', None, None).
    'Show S01E02' and anime style '[Group] Show - 02 (1080p)' are episodes; a 'Season 2' folder sets the season."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = re.sub(r"[._]+", " ", _GROUP.sub(" ", stem))
    season = episode = year = None
    if m := _SXE.search(stem):
        season, episode, stem = int(m[1]), int(m[2]), stem[:m.start()]
    elif (m := _ANIME_EP.search(stem)) and not _YEAR.fullmatch(" " + m[2]):
        episode = int(m[2])
        season = int(m[1]) if m[1] else None
        if season is None and (d := _SEASON_DIR.match(os.path.basename(os.path.dirname(filename)).strip())):
            season = int(d[1])
        stem = stem[:m.start()]
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


MAX_JSON = 16 << 20
MAX_IMAGE = 25 << 20              # bytes of one downloaded picture
MAX_PIXELS = 60_000_000           # pixels of one picture (a "decompression bomb" is refused, not unpacked)
_TAG = re.compile(r"<[^>]{0,500}>")


def untag(value):
    """Scraped text is shown as text: markup in it (from a community-edited source, or a hostile one) is dropped,
    so Qt never renders it as rich text (which can load remote or local images). Lists and dicts are walked."""
    if isinstance(value, str):
        return _TAG.sub("", value).replace("<", "\u2039").replace(">", "\u203a") if "<" in value or ">" in value else value
    if isinstance(value, list):
        return [untag(v) for v in value]
    if isinstance(value, dict):
        return {k: (v if k.endswith(("url", "urls")) else untag(v)) for k, v in value.items()}
    return value


def _plain(fn):
    """Decorator: whatever this scraper function returns is passed through untag, and result thumbnails must be HTTPS."""
    import functools

    @functools.wraps(fn)
    def run(*a, **kw):
        out = untag(fn(*a, **kw))
        for row in out if isinstance(out, list) else []:
            if isinstance(row, dict) and "thumb" in row:
                row["thumb"] = safe_url(row["thumb"]) or ""
        return out
    return run


def safe_url(url) -> str | None:
    """A picture address from a scraped answer: HTTPS only (urllib would also open file:// and http://)."""
    return url if isinstance(url, str) and url.lower().startswith("https://") and len(url) < 2000 else None


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "MediaVault/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read(MAX_JSON + 1)[:MAX_JSON])
    except Exception as e:
        raise ScrapeError(str(e).replace(url, "<url>")) from None  # keep the API key out of logs


@_plain
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
            "score": _score(r), "original_title": _original(r)}


def _original(r: dict) -> str | None:
    """The title in its own language and alphabet, when that is not simply the English one."""
    orig = r.get("original_title") or r.get("original_name")
    shown = r.get("title") or r.get("name")
    return orig if orig and orig.casefold() != (shown or "").casefold() else None


CERT_COUNTRY = "US"
_CERT_ORDER = (3, 4, 5, 6, 2, 1)          # theatrical, digital, physical, TV, limited, premiere


def certification(r: dict, kind: str) -> str | None:
    """The US age rating from a details response: PG-13, R, TV-MA ... (None when TMDB has none)."""
    if kind == "show":
        for c in (r.get("content_ratings") or {}).get("results") or []:
            if c.get("iso_3166_1") == CERT_COUNTRY and (c.get("rating") or "").strip():
                return c["rating"].strip()
        return None
    for c in (r.get("release_dates") or {}).get("results") or []:
        if c.get("iso_3166_1") == CERT_COUNTRY:
            dates = sorted((d for d in c.get("release_dates") or [] if (d.get("certification") or "").strip()),
                           key=lambda d: _CERT_ORDER.index(d.get("type")) if d.get("type") in _CERT_ORDER else 9)
            if dates:
                return dates[0]["certification"].strip()
    return None


def _score(r: dict) -> float | None:
    """TMDB vote average (0-10), only when enough people voted for it to mean something."""
    avg, votes = r.get("vote_average"), r.get("vote_count") or 0
    return round(float(avg), 1) if avg and votes >= 5 else None


IMG = "https://image.tmdb.org/t/p/"


def _tmdb_json(path: str, key: str, **q) -> dict:
    return _get_json(f"https://api.themoviedb.org/3/{path}?{urllib.parse.urlencode({'api_key': key, **q})}")


_LINKS = (
    (re.compile(r"themoviedb\.org/(movie|tv)/(\d+)", re.I), "tmdb"),
    (re.compile(r"anilist\.co/anime/(\d+)", re.I), "anilist"),
    (re.compile(r"myanimelist\.net/anime/(\d+)", re.I), "mal"),
    (re.compile(r"imdb\.com/(?:[a-z]{2}/)?title/(tt\d{5,10})", re.I), "omdb"),
)


def parse_link(text: str) -> dict | None:
    """A TMDB, AniList, MyAnimeList or IMDb page address pasted into Fix Scraped Data: {"source", "id", "kind"}.
    TMDB episode and season pages count as their series ("/tv/90395-x/season/1/episode/1" -> series 90395)."""
    text = (text or "").strip()
    if not text or " " in text:
        return None
    for pattern, source in _LINKS:
        m = pattern.search(text)
        if m:
            if source == "tmdb":
                return {"source": "tmdb", "id": m.group(2), "kind": "show" if m.group(1).lower() == "tv" else "movie"}
            return {"source": source, "id": m.group(1), "kind": None}
    return None


@_plain
def tmdb_search(kind: str, query: str, year: str, key: str) -> list[dict]:
    """Fix Scraped Data: up to 12 TMDB candidates for a title (adult titles included: you are searching by hand)."""
    if not key:
        raise ScrapeError("TMDB needs an API key (Settings \u203A Integrations & APIs)")
    path = "search/tv" if kind == "show" else "search/movie"
    year_key = "first_air_date_year" if kind == "show" else "year"
    data = _tmdb_json(path, key, query=query, include_adult="true", **({year_key: year} if year else {}))
    out = []
    for r in (data.get("results") or [])[:12]:
        poster = r.get("poster_path")
        out.append({"id": str(r.get("id")), "source": "tmdb", "title": r.get("title") or r.get("name") or "",
                    "year": (r.get("release_date") or r.get("first_air_date") or "")[:4],
                    "overview": r.get("overview") or "",
                    "thumb": f"{IMG}w185{poster}" if poster else ""})
    return out


@_plain
def tmdb_details(kind: str, tmdb_id: int, key: str) -> dict:
    """Everything for one title by id, in the same shape as a search hit, plus its collection (films only)."""
    credits = "aggregate_credits" if kind == "show" else "credits"
    ratings = "content_ratings" if kind == "show" else "release_dates"
    r = _tmdb_json(f"{'tv' if kind == 'show' else 'movie'}/{int(tmdb_id)}", key,
                   append_to_response=f"{credits},images,{ratings},alternative_titles,translations", include_image_language="null,en")
    poster, coll = r.get("poster_path"), r.get("belongs_to_collection") or {}
    return {"tmdb_id": r.get("id"), "title": r.get("title") or r.get("name"),
            "release_date": r.get("release_date") or r.get("first_air_date"),
            "synopsis": r.get("overview"),
            "poster_url": f"{IMG}w500{poster}" if poster else None,
            "genres": [g["name"] for g in r.get("genres") or [] if g.get("name")],
            "score": _score(r),
            "collection_id": coll.get("id"), "collection_name": coll.get("name"),
            "collection_poster_url": f"{IMG}w500{coll['poster_path']}" if coll.get("poster_path") else None,
            "banner_url": _best_backdrop(r.get("images") or {}),
            "collection_banner_url": f"{IMG}original{coll['backdrop_path']}" if coll.get("backdrop_path") else None,
            "cast": _cast((r.get(credits) or {}).get("cast") or []),
            "gallery_urls": _backdrops(r.get("images") or {}) + (episode_stills(r, key) if kind == "show" else []),
            "certification": certification(r, kind), "original_title": _original(r), "romaji_title": None,
            "alt_titles": alttitles.dumps(alttitles.from_tmdb(r))}


GALLERY_MAX = 6            # a film: its best backdrops
GALLERY_MAX_SERIES = 18    # a series: its backdrops, then episode stills
STILL_SEASONS = 3          # stills from the first seasons only (one request each)


def episode_stills(r: dict, key: str) -> list[str]:
    """A series' episode images (TMDB "stills"), in episode order: one request per season, first seasons first.
    Best effort: a season that fails is skipped."""
    seasons = sorted(s["season_number"] for s in r.get("seasons") or [] if (s.get("season_number") or 0) > 0)
    out = []
    for n in seasons[:STILL_SEASONS]:
        try:
            season = _tmdb_json(f"tv/{int(r['id'])}/season/{n}", key)
        except ScrapeError:
            continue
        for ep in season.get("episodes") or []:
            if ep.get("still_path"):
                out.append(f"{IMG}original{ep['still_path']}")
        if len(out) >= GALLERY_MAX_SERIES:
            break
    return out[:GALLERY_MAX_SERIES]


def _best_backdrop(images: dict) -> str | None:
    """The banner: the highest-rated backdrop with no text on it (TMDB's "no language", like
    /images/backdrops?image_language=xx&image_sort=rating.desc), else the highest-rated of any language."""
    shots = [b for b in images.get("backdrops") or [] if b.get("file_path")]
    if not shots:
        return None
    best = sorted(shots, key=lambda b: (b.get("iso_639_1") not in (None, "", "xx"), -(b.get("vote_average") or 0),
                                        -(b.get("vote_count") or 0)))[0]
    return f"{IMG}original{best['file_path']}"


def _backdrops(images: dict) -> list[str]:
    """The best-voted wide stills (no text on them first), for the Gallery and the recommended carousel."""
    shots = sorted(images.get("backdrops") or [], key=lambda b: (b.get("iso_639_1") is not None, -(b.get("vote_average") or 0)))
    return [f"{IMG}w1280{b['file_path']}" for b in shots[:GALLERY_MAX] if b.get("file_path")]


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
    return _omdb_shape(r)


@_plain
def _omdb_shape(r: dict) -> dict:
    poster = r.get("Poster")
    try:
        imdb = round(float(r.get("imdbRating")), 1)
    except (TypeError, ValueError):
        imdb = None
    rated = (r.get("Rated") or "").strip()
    return {"certification": rated if rated and rated not in ("N/A", "Not Rated", "Unrated") else None,
            "original_title": None, "romaji_title": None, "score": imdb, "title": r.get("Title"), "release_date": r.get("Released") if r.get("Released") != "N/A" else r.get("Year"),
            "synopsis": r.get("Plot") if r.get("Plot") != "N/A" else None,
            "poster_url": poster if poster and poster != "N/A" else None,
            "genres": [g.strip() for g in (r.get("Genre") or "").split(",") if g.strip() and g != "N/A"],
            "imdb_id": r.get("imdbID"), "tmdb_id": None, "cast": [], "gallery_urls": [],
            "collection_id": None, "collection_name": None, "collection_poster_url": None}


@_plain
def omdb_search(kind: str, query: str, year: str, key: str) -> list[dict]:
    """Fix Scraped Data candidates from OMDb (IMDb data); the id is the IMDb id ("tt0113277")."""
    q = {"apikey": key, "s": query, "type": "series" if kind == "show" else "movie", **({"y": year} if year else {})}
    r = _get_json(f"https://www.omdbapi.com/?{urllib.parse.urlencode(q)}")
    if r.get("Response") != "True":
        if "invalid api key" in str(r.get("Error", "")).lower():
            raise ScrapeError("OMDb rejected the API key")
        return []
    return [{"id": str(x.get("imdbID")), "source": "omdb", "title": x.get("Title") or "", "year": (x.get("Year") or "")[:4],
             "overview": "", "thumb": x["Poster"] if (x.get("Poster") or "N/A") != "N/A" else ""}
            for x in (r.get("Search") or [])[:8] if x.get("imdbID")]


def omdb_details(imdb_id: str, key: str) -> dict:
    r = _get_json(f"https://www.omdbapi.com/?{urllib.parse.urlencode({'apikey': key, 'i': imdb_id, 'plot': 'full'})}")
    if r.get("Response") != "True":
        raise ScrapeError(f"OMDb: {r.get('Error') or 'no entry with that id'}")
    return _omdb_shape(r)


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


def _lookup(kind: str, p: Parsed, keys: dict, source: str = "tmdb") -> dict | None:
    if source == "anilist":                  # anime folders: AniList, no key needed
        from utils import anilist
        try:
            return anilist.lookup(p.title, p.year)
        except anilist.AniListError as e:
            raise ScrapeError(str(e)) from None
    if not (keys.get("tmdb") or keys.get("omdb")):
        raise ScrapeError("no API key configured")
    if keys.get("tmdb") and (hit := _tmdb(kind, p, keys["tmdb"])):
        if hit.get("tmdb_id"):
            try:   # one more request: the search result has no cast, and does not say which collection a film is in
                d = tmdb_details(kind, hit["tmdb_id"], keys["tmdb"])
                hit.update({k: d[k] for k in ("collection_id", "collection_name", "collection_poster_url", "cast", "gallery_urls",
                                              "certification", "original_title", "alt_titles", "banner_url",
                                              "collection_banner_url")})
                if kind == "show":
                    hit["collection_id"] = hit["collection_name"] = None
            except ScrapeError:
                pass
        hit["disc_url"] = disc_url(hit.get("tmdb_id"), keys.get("fanart", "")) if kind == "movie" else None
        return hit
    return _omdb(kind, p, keys["omdb"]) if keys.get("omdb") else None


async def scrape_many(jobs: list[tuple[str, Parsed]], keys: dict, source: str = "tmdb") -> list:
    """jobs = [(media_type, Parsed)]. Same show/title is asked once (memory cache)."""
    sem = asyncio.Semaphore(CONCURRENCY)
    unique = list(dict.fromkeys((k, p.title, p.year) for k, p in jobs))

    async def one(kind, title, year):
        async with sem:
            try:
                return await asyncio.to_thread(_lookup, kind, Parsed(title, year, None, None), keys, source)
            except ScrapeError as e:
                return e

    answers = dict(zip(unique, await asyncio.gather(*(one(*u) for u in unique))))
    return [answers[(k, p.title, p.year)] for k, p in jobs]


# ------------------------------------------------------------ 3. images and sidecar paths

def fetch_image(url: str):
    """One picture from a scraped address: HTTPS only, at most MAX_IMAGE bytes and MAX_PIXELS pixels."""
    import warnings

    from PIL import Image
    if not safe_url(url):
        raise ScrapeError("refusing a picture address that is not HTTPS")
    req = urllib.request.Request(url, headers={"User-Agent": "MediaVault/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise ScrapeError("picture is too large")
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        img = Image.open(io.BytesIO(data))
        img.load()
    return img


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


BANNER_BOX = (1920, 1080)


def banner_path(item: dict) -> Path:
    """A title's (or, through collection_item, a box set's) banner: one wide image for View More and the
    recommended carousel. A series has one for all its episodes."""
    if item["media_type"] == "show":
        return Path(item["file_path"]).parent / ASSET_DIR / "_series.banner.webp"
    return _assets(item) / f"{_stem(item)}.banner.webp"


def save_banner(item: dict, url: str | None, force: bool = False) -> bool:
    if not safe_url(url):
        return False
    dest = banner_path(item)
    if dest.exists() and not force:
        return True
    try:
        save_webp(fetch_image(url), dest, box=BANNER_BOX)
        return True
    except Exception:
        log.warning("banner failed: %s", url, exc_info=True)
        return False


def tmdb_banner_for(titles: list[str], year: str | None, key: str) -> str | None:
    """The best TMDB backdrop for a title known by other names (an AniList series or OVA): searched as a series,
    then as a film, by each name in turn; the year narrows it when given."""
    for title in [t for t in dict.fromkeys(titles) if t]:
        for kind in ("show", "movie"):
            path, year_key = ("search/tv", "first_air_date_year") if kind == "show" else ("search/movie", "year")
            try:
                data = _tmdb_json(path, key, query=title, include_adult="true", **({year_key: year} if year else {}))
                hits = data.get("results") or []
                if not hits and year:
                    hits = _tmdb_json(path, key, query=title, include_adult="true").get("results") or []
                if not hits:
                    continue
                images = _tmdb_json(f"{'tv' if kind == 'show' else 'movie'}/{int(hits[0]['id'])}/images", key,
                                    include_image_language="null,xx,en,ja")
            except ScrapeError:
                continue
            url = _best_backdrop(images)
            if url:
                return url
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


def gallery_dir(item: dict) -> Path:
    """A title's Gallery: wide images (scraped stills, or your own) shown in View More and behind the recommended
    carousel. One per film, one per series (every episode shares it), in the app cache for personal clips."""
    if item["media_type"] == "show":
        return Path(item["file_path"]).parent / ASSET_DIR / "_series.gallery"
    return _assets(item) / f"{_stem(item)}.gallery"


GALLERY_BOX = (1280, 720)


def gallery_images(item: dict) -> list[Path]:
    """Your own images first (c-*.webp, in the order added), then the scraped ones (s-*.webp)."""
    d = gallery_dir(item)
    if not d.is_dir():
        return []
    files = sorted(p for p in d.iterdir() if p.suffix.lower() == ".webp")
    return [p for p in files if p.name.startswith("c-")] + [p for p in files if not p.name.startswith("c-")]


def save_gallery(item: dict, urls: list[str], replace: bool = False) -> int:
    """Download scraped Gallery images (s-01.webp ...). Your own images are never touched. Returns how many saved."""
    d = gallery_dir(item)
    if replace and d.is_dir():
        for p in d.glob("s-*.webp"):
            p.unlink(missing_ok=True)
    saved = 0
    limit = GALLERY_MAX_SERIES if item.get("media_type") == "show" else GALLERY_MAX
    for i, url in enumerate(urls[:limit], 1):
        dest = d / f"s-{i:02d}.webp"
        if dest.exists():
            continue
        try:
            save_webp(fetch_image(url), dest, box=GALLERY_BOX)
            saved += 1
        except Exception:
            logging.getLogger(__name__).warning("gallery image failed: %s", url, exc_info=True)
    return saved


def cover_path(item: dict) -> Path:
    """The front cover to show: the user's own art if set, else the scraped / captured poster."""
    custom = custom_front_path(item)
    return custom if custom.exists() else poster_path(item)
