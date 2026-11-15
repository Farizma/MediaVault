"""Adult scenes and movies from ThePornDB (https://theporndb.net): a REST API with a free personal token.

A file is matched by its name ("Site - Scene Title", "site.24.03.15.title") together with its OpenSubtitles hash,
which ThePornDB keeps for many releases: a hash hit is exact whatever the file is called. Scenes are asked first,
then full movies. The answer comes back in the same shape as a TMDB hit (scraper._lookup).
"""
import json
import os
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

from utils import scraper

API = "https://api.theporndb.net"
PERSON_OFFSET = 3_000_000_000      # performer ids, apart from TMDB and AniList people in the shared photo cache
SET_OFFSET = 3_000_000_000         # box sets by site (studio), apart from TMDB collections and AniList OVA sets
MATCH_MIN = 0.6                    # share of a result's title words that the file name must contain


class TPDBError(Exception):
    pass


def _get(path: str, key: str, retries: int = 2) -> dict:
    req = urllib.request.Request(API + path, headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                                                      "User-Agent": "MediaVault"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read(scraper.MAX_JSON + 1)[:scraper.MAX_JSON]) or {}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            if e.code == 429 and attempt < retries:
                time.sleep(min(int(e.headers.get("Retry-After") or 5), 30))
                continue
            if e.code in (401, 403):
                raise TPDBError("ThePornDB refused the API token (Settings › Integrations & APIs)") from None
            raise TPDBError(f"ThePornDB: HTTP {e.code}") from None
        except Exception as e:
            raise TPDBError(f"ThePornDB: {e}") from None
    return {}


def oshash(path: str) -> str | None:
    """The OpenSubtitles hash: the file size plus the first and last 64 KB summed as 64-bit numbers."""
    try:
        size = os.path.getsize(path)
        if size < 2 * 65536:
            return None
        total = size
        with open(path, "rb") as f:
            for at in (0, size - 65536):
                f.seek(at)
                total += sum(struct.unpack("<8192Q", f.read(65536)))
        return f"{total & 0xFFFFFFFFFFFFFFFF:016x}"
    except OSError:
        return None


def _url(v) -> str | None:
    """A picture, given as a URL, a {size: URL} map (largest wanted) or a list of either."""
    if isinstance(v, str):
        return scraper.safe_url(v)
    if isinstance(v, dict):
        for k in ("full", "large", "original", "medium", "small", "url"):
            if (u := _url(v.get(k))):
                return u
        return next((u for x in v.values() if (u := _url(x))), None)
    if isinstance(v, list):
        return next((u for x in v if (u := _url(x))), None)
    return None


def _num(v) -> int | None:
    return v if isinstance(v, int) else int(v) if isinstance(v, str) and v.isdigit() else None


def _person_id(p: dict) -> int:
    n = _num(p.get("_id"))
    return PERSON_OFFSET + (n if n is not None else zlib.crc32(str(p.get("id") or p.get("name")).encode()))


@scraper._plain
def _shape(s: dict, kind: str = "scenes") -> dict:
    """A ThePornDB scene or movie in the shape of a TMDB hit."""
    site = s.get("site") or {}
    studios = [site.get("name")] if site.get("name") else []
    for up in ("network", "parent"):
        if (n := (site.get(up) or {}).get("name")) and n not in studios:
            studios.append(n)
    cast = []
    for p in s.get("performers") or []:
        who = p.get("parent") or p          # the performer's main profile, when the site uses another name
        if who.get("name"):
            cast.append({"id": _person_id(who), "name": who["name"],
                         "role": p["name"] if p.get("name") and p["name"] != who["name"] else "",
                         "photo_url": _url(who.get("image")) or _url(p.get("image"))})
    back = _url(s.get("background")) or _url(s.get("backgrounds"))
    sid = _num(site.get("id"))
    return {"tpdb_id": f"{kind}:{s.get('id') or s.get('_id')}", "tmdb_id": None, "anilist_id": None,
            "title": s.get("title") or "", "release_date": s.get("date") or None,
            "synopsis": (s.get("description") or "").strip() or None,
            "poster_url": _url(s.get("poster")) or _url(s.get("posters")) or _url(s.get("image")) or back,
            "banner_url": back, "gallery_urls": [back] if back else [],
            "genres": list(dict.fromkeys(t["name"] for t in s.get("tags") or [] if t.get("name")))[:15],
            "studios": studios, "cast": cast[:15], "score": None, "certification": "18+",
            "collection_id": SET_OFFSET + sid if sid is not None and site.get("name") else None,
            "collection_name": site.get("name") or None, "collection_poster_url": None, "disc_url": None,
            "original_title": None, "romaji_title": None, "alt_titles": None}


_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _fits(s: dict, name: str, file_hash: str | None) -> bool:
    """A result is taken when it carries this file's hash, or most of its title's words are in the file name."""
    if file_hash and any(str(h.get("hash", "")).lower() == file_hash for h in s.get("hashes") or [] if isinstance(h, dict)):
        return True
    want = _words(s.get("title"))
    return bool(want) and len(want & _words(name)) / len(want) >= MATCH_MIN


def query_name(path: str) -> str:
    """The file name ThePornDB's parser reads: release group tags and quality words dropped, dots kept."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = scraper._GROUP.sub(" ", stem)
    stem = scraper._JUNK.split(stem, maxsplit=1)[0]
    return re.sub(r"\s{2,}", " ", stem).strip(" .-_") or os.path.splitext(os.path.basename(path))[0]


def lookup(path: str, key: str) -> dict | None:
    """The best scene (then movie) for a file, or None."""
    if not key:
        raise TPDBError("no ThePornDB API token configured")
    name, h = query_name(path), oshash(path)
    for kind in ("scenes", "movies"):
        q = {"parse": name, "limit": 10}
        if h and kind == "scenes":
            q["hash"] = h
        found = (_get(f"/{kind}?" + urllib.parse.urlencode(q), key).get("data")) or []
        if isinstance(found, dict):
            found = [found]
        hit = next((s for s in found if isinstance(s, dict) and _fits(s, name, h)), None)
        if hit:
            return _shape(hit, kind)
    return None


def details(ident: str, key: str) -> dict:
    """ident: "scenes:<id>" or "movies:<id>" (a bare id is a scene)."""
    kind, _, num = ident.rpartition(":")
    kind = kind if kind in ("scenes", "movies") else "scenes"
    data = _get(f"/{kind}/{urllib.parse.quote(num, safe='')}", key).get("data")
    if not isinstance(data, dict):
        raise TPDBError("ThePornDB has no entry with that id")
    return _shape(data, kind)


def search(query: str, key: str) -> list[dict]:
    """Fix Scraped Data candidates, in the same shape as scraper.tmdb_search."""
    if not key:
        return []
    out = []
    for kind in ("scenes", "movies"):
        found = _get(f"/{kind}?" + urllib.parse.urlencode({"q": query, "limit": 12}), key).get("data") or []
        for s in found if isinstance(found, list) else []:
            if not isinstance(s, dict) or not s.get("id"):
                continue
            site = (s.get("site") or {}).get("name")
            out.append({"id": f"{kind}:{s['id']}", "source": "tpdb",
                        "title": scraper.untag((f"{site} · " if site else "") + (s.get("title") or "")),
                        "year": (s.get("date") or "")[:4],
                        "overview": scraper.untag((s.get("description") or "")[:400]),
                        "thumb": _url(s.get("poster")) or _url(s.get("image")) or ""})
    return out
