"""Anime details from AniList (https://docs.anilist.co): a free GraphQL API, no key, always current.

Chosen over the anime-offline-database: that is a 40 MB+ JSON file refreshed weekly that Media Vault would have to
download and keep, while AniList answers each lookup directly and adds nothing to the app's size.
Rate limit: 90 requests a minute; a scan asks once per series (scraper.scrape_many already de-duplicates titles).
"""
import html
import json
import re
import time
import urllib.request

API = "https://graphql.anilist.co"
PERSON_OFFSET = 1_000_000_000      # AniList staff ids, kept apart from TMDB person ids in the shared photo cache

_FIELDS = """
  id idMal format episodes seasonYear isAdult
  title { english romaji native }
  startDate { year month day }
  description(asHtml: false)
  coverImage { extraLarge large }
  bannerImage
  genres
  averageScore
  characters(sort: [ROLE, RELEVANCE], perPage: 15) {
    edges { role node { name { full } } voiceActors(language: JAPANESE, sort: RELEVANCE) { id name { full } image { large } } }
  }
"""
_ONE = "query ($q: String, $y: Int) { Media(search: $q, type: ANIME, seasonYear: $y, sort: SEARCH_MATCH) {" + _FIELDS + "} }"
_ANY = "query ($q: String) { Media(search: $q, type: ANIME, sort: SEARCH_MATCH) {" + _FIELDS + "} }"
_BY_ID = "query ($id: Int) { Media(id: $id, type: ANIME) {" + _FIELDS + "} }"
_SEARCH = """query ($q: String) { Page(perPage: 12) { media(search: $q, type: ANIME, sort: SEARCH_MATCH) {
  id format seasonYear title { english romaji } description(asHtml: false) coverImage { medium large } } } }"""


class AniListError(Exception):
    pass


def _post(query: str, variables: dict, retries: int = 2) -> dict:
    body = json.dumps({"query": query, "variables": {k: v for k, v in variables.items() if v is not None}}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json", "Accept": "application/json",
                                                          "User-Agent": "MediaVault"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:              # AniList answers "not found" with a 404
                return {}
            if e.code == 429 and attempt < retries:
                time.sleep(int(e.headers.get("Retry-After") or 5))
                continue
            raise AniListError(f"AniList: HTTP {e.code}") from None
        except Exception as e:
            raise AniListError(f"AniList: {e}") from None
    if data.get("errors"):
        msg = data["errors"][0].get("message", "error")
        if "not found" in msg.lower():
            return {}
        raise AniListError(f"AniList: {msg}")
    return data.get("data") or {}


def _clean(text: str | None) -> str:
    """AniList descriptions carry <br> and <i>; keep plain text with paragraph breaks."""
    t = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\(Source:[^)]*\)\s*$", "", html.unescape(t)).strip()
    return re.sub(r"\n{3,}", "\n\n", t)


def _title(t: dict) -> str:
    return (t or {}).get("english") or (t or {}).get("romaji") or (t or {}).get("native") or ""


def _shape(m: dict) -> dict:
    """An AniList entry in the same shape as a TMDB hit (scraper._lookup / tmdb_details)."""
    sd = m.get("startDate") or {}
    date = "-".join(f"{v:02d}" if i else str(v) for i, v in enumerate(x for x in (sd.get("year"), sd.get("month"), sd.get("day")) if x))
    cast = []
    for e in ((m.get("characters") or {}).get("edges") or []):
        va = (e.get("voiceActors") or [None])[0]
        character = ((e.get("node") or {}).get("name") or {}).get("full") or ""
        if va and (va.get("name") or {}).get("full"):
            cast.append({"id": PERSON_OFFSET + int(va["id"]), "name": va["name"]["full"], "role": character,
                         "photo_url": (va.get("image") or {}).get("large")})
    cover = m.get("coverImage") or {}
    score = m.get("averageScore")
    return {"anilist_id": m.get("id"), "tmdb_id": None, "title": _title(m.get("title")), "release_date": date or None,
            "synopsis": _clean(m.get("description")) or None,
            "poster_url": cover.get("extraLarge") or cover.get("large"), "genres": list(m.get("genres") or []),
            "score": round(score / 10, 1) if score else None, "cast": cast[:15],
            "gallery_urls": [m["bannerImage"]] if m.get("bannerImage") else [],
            "collection_id": None, "collection_name": None, "collection_poster_url": None, "disc_url": None,
            "format": m.get("format"),
            # English (or romaji when there is no English title) is the title; the others ride along for display
            "romaji_title": (m.get("title") or {}).get("romaji"),
            "original_title": (m.get("title") or {}).get("native"),
            "certification": "18+" if m.get("isAdult") else None}


_TAIL = re.compile(r"\s+(?:\d{1,3}|ova|oad|ona|special|specials|uncensored|raw)$", re.I)


def lookup(title: str, year: str | None = None) -> dict | None:
    """The best match for a series or film title (with its year when that narrows it), or None. Adult titles are
    included. When nothing matches, a trailing episode number or "OVA" is dropped and it asks once more."""
    data = {}
    if year and str(year).isdigit():
        data = _post(_ONE, {"q": title, "y": int(year)})
    if not data.get("Media"):
        data = _post(_ANY, {"q": title})
    if not data.get("Media") and (short := _TAIL.sub("", title).strip()) and short != title:
        return lookup(short)
    return _shape(data["Media"]) if data.get("Media") else None


def details(anilist_id: int) -> dict:
    data = _post(_BY_ID, {"id": int(anilist_id)})
    if not data.get("Media"):
        raise AniListError("AniList has no entry with that id")
    return _shape(data["Media"])


def search(query: str) -> list[dict]:
    """Fix Scraped Data candidates, in the same shape as scraper.tmdb_search."""
    media = ((_post(_SEARCH, {"q": query}).get("Page") or {}).get("media")) or []
    return [{"id": str(m["id"]), "source": "anilist", "title": _title(m.get("title")),
             "year": str(m.get("seasonYear") or ""), "overview": _clean(m.get("description"))[:400],
             "thumb": (m.get("coverImage") or {}).get("large") or (m.get("coverImage") or {}).get("medium") or ""}
            for m in media]
