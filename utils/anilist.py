"""Anime details from AniList (https://docs.anilist.co): a free GraphQL API, no key, always current.

Chosen over the anime-offline-database: that is a 40 MB+ JSON file refreshed weekly that Media Vault would have to
download and keep, while AniList answers each lookup directly and adds nothing to the app's size.
Rate limit: 90 requests a minute; a scan asks once per series (scraper.scrape_many already de-duplicates titles).
"""
import functools
import html
import json
import re
import time
import urllib.request

from utils import alttitles
from utils.scraper import _plain

API = "https://graphql.anilist.co"
PERSON_OFFSET = 1_000_000_000      # AniList staff ids, kept apart from TMDB person ids in the shared photo cache

_FIELDS = """
  id idMal format episodes seasonYear isAdult
  title { english romaji native }
  synonyms
  startDate { year month day }
  description(asHtml: false)
  coverImage { extraLarge large }
  bannerImage
  genres
  tags { name rank isGeneralSpoiler isMediaSpoiler }
  studios { edges { isMain node { name isAnimationStudio } } }
  averageScore
  characters(sort: [ROLE, RELEVANCE], perPage: 15) {
    edges { role node { name { full } } voiceActors(language: JAPANESE, sort: RELEVANCE) { id name { full } image { large } } }
  }
"""
_ONE = "query ($q: String, $y: Int) { Media(search: $q, type: ANIME, seasonYear: $y, sort: SEARCH_MATCH) {" + _FIELDS + "} }"
_ANY = "query ($q: String) { Media(search: $q, type: ANIME, sort: SEARCH_MATCH) {" + _FIELDS + "} }"
_BY_ID = "query ($id: Int) { Media(id: $id, type: ANIME) {" + _FIELDS + "} }"
_BY_MAL = "query ($id: Int) { Media(idMal: $id, type: ANIME) { id } }"
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


TAG_MIN_RANK = 60     # AniList tags this relevant or more become genre tags (spoilers never)
TAG_MAX = 12


def _genres(m: dict) -> list[str]:
    """AniList's genres, then its tags (most relevant first). Adult titles have one genre ("Hentai"): what they
    are about is in the tags."""
    out = list(m.get("genres") or [])
    for t in sorted(m.get("tags") or [], key=lambda t: -(t.get("rank") or 0)):
        if len(out) >= TAG_MAX:
            break
        if (t.get("rank") or 0) >= TAG_MIN_RANK and not (t.get("isGeneralSpoiler") or t.get("isMediaSpoiler")) \
                and t.get("name") and t["name"] not in out:
            out.append(t["name"])
    return out


def _studios(m: dict) -> list[str]:
    """The studio(s) that made it: the main studio, plus the other animation studios when there are only a few
    (a long series credits dozens for single episodes)."""
    edges = (m.get("studios") or {}).get("edges") or []
    main = [e["node"]["name"] for e in edges if e.get("isMain") and (e.get("node") or {}).get("name")]
    anim = [e["node"]["name"] for e in edges if (e.get("node") or {}).get("isAnimationStudio") and e["node"].get("name")]
    both = list(dict.fromkeys(main + anim))
    return both if len(both) <= 3 else (main or anim[:1])


def _title(t: dict) -> str:
    return (t or {}).get("english") or (t or {}).get("romaji") or (t or {}).get("native") or ""


@_plain
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
    return {"anilist_id": m.get("id"), "mal_id": m.get("idMal"), "tmdb_id": None, "title": _title(m.get("title")), "release_date": date or None,
            "synopsis": _clean(m.get("description")) or None,
            "poster_url": cover.get("extraLarge") or cover.get("large"), "genres": _genres(m), "studios": _studios(m),
            "score": round(score / 10, 1) if score else None, "cast": cast[:15],
            "gallery_urls": [m["bannerImage"]] if m.get("bannerImage") else [],
            "collection_id": None, "collection_name": None, "collection_poster_url": None, "disc_url": None,
            "format": m.get("format"),
            # English (or romaji when there is no English title) is the title; the others ride along for display
            "romaji_title": (m.get("title") or {}).get("romaji"),
            "original_title": (m.get("title") or {}).get("native"),
            "alt_titles": alttitles.dumps(alttitles.from_anilist(m.get("title"), m.get("synonyms"))),
            "certification": "18+" if m.get("isAdult") else None}


_TAIL = re.compile(r"\s+(?:\d{1,3}|ova|oad|ona|special|specials|uncensored|raw)$", re.I)


JIKAN = "https://api.jikan.moe/v4/anime/{}/pictures"


@functools.lru_cache(maxsize=256)      # the episodes of an OVA box set ask for the same title's pictures
def _mal_fetch(mal_id: int, limit: int) -> tuple:
    req = urllib.request.Request(JIKAN.format(mal_id), headers={"User-Agent": "MediaVault", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:          # a failure raises, so it is not cached
        data = json.load(r).get("data") or []
    urls = []
    for p in data:
        u = (p.get("jpg") or {}).get("large_image_url") or (p.get("jpg") or {}).get("image_url")
        if u and u.startswith("https://") and u not in urls:
            urls.append(u)
    return tuple(urls[:limit])


def mal_pictures(mal_id, limit: int = 5) -> tuple:
    """More Gallery images: MyAnimeList's pictures for a title, through Jikan (an open-source, keyless MAL API).
    Best effort: any failure (offline, rate limit) gives none."""
    if not mal_id:
        return ()
    try:
        return _mal_fetch(int(mal_id), limit)
    except Exception:
        return ()


def gallery_urls(hit: dict) -> list[str]:
    """The AniList banner, then MyAnimeList pictures."""
    own = list(hit.get("gallery_urls") or [])
    return own + [u for u in mal_pictures(hit.get("mal_id")) if u not in own]


OVA_SET_OFFSET = 2_000_000_000     # box set ids for adult OVAs, apart from TMDB collection ids (and yours, below 0)


def is_adult_ova(hit: dict | None) -> bool:
    """An adult OVA: every episode is its own release with its own cover, so its files become films in a box set
    named after it ("Title #1", "Title #2") instead of a series with seasons."""
    return bool(hit) and hit.get("format") == "OVA" and hit.get("certification") == "18+" and bool(hit.get("anilist_id"))


def ova_set_id(hit: dict) -> int:
    return OVA_SET_OFFSET + int(hit["anilist_id"])


def lookup(title: str, year: str | None = None) -> dict | None:
    """The best match for a series or film title (with its year when that narrows it), or None. Adult titles are
    included. When nothing matches, a trailing episode number or "OVA" is dropped and it asks once more."""
    data = {}
    if year and str(year).isdigit():
        data = _post(_ONE, {"q": title, "y": int(year)})
    if not data.get("Media"):
        data = _post(_ANY, {"q": title})
    if not data.get("Media") and (short := _TAIL.sub("", title).strip()) and short != title:
        return lookup(short)                # a trailing episode number or "OVA" first: "Title-Name 1" -> "Title-Name"
    if not data.get("Media") and (plain := " ".join(re.sub(r"[^\w\s]", " ", title).split())) != title:
        return lookup(plain, year)          # words only: "Title-Name" -> "Title Name", "Title: Sub" -> "Title Sub"
    if not data.get("Media") and 2 <= len(title.split()) <= 3 and (joined := title.replace(" ", "")) != title:
        data = _post(_ANY, {"q": joined})     # a short name split by the file name: "Drop Out" -> "DropOut"
    return _shape(data["Media"]) if data.get("Media") else None


def from_mal(mal_id: int) -> int:
    """The AniList id for a MyAnimeList id (a pasted MAL link)."""
    data = _post(_BY_MAL, {"id": int(mal_id)})
    if not (data.get("Media") or {}).get("id"):
        raise AniListError("AniList has no entry for that MyAnimeList page")
    return int(data["Media"]["id"])


def details(anilist_id: int) -> dict:
    data = _post(_BY_ID, {"id": int(anilist_id)})
    if not data.get("Media"):
        raise AniListError("AniList has no entry with that id")
    return _shape(data["Media"])


@_plain
def search(query: str) -> list[dict]:
    """Fix Scraped Data candidates, in the same shape as scraper.tmdb_search."""
    media = []
    plain = " ".join(re.sub(r"[^\w\s]", " ", query).split())
    for q in dict.fromkeys([query, plain, plain.replace(" ", "") if 2 <= len(plain.split()) <= 3 else plain]):
        media = ((_post(_SEARCH, {"q": q}).get("Page") or {}).get("media")) or []
        if media:                            # by hand too: punctuation, then a split short name, can hide a match
            break
    return [{"id": str(m["id"]), "source": "anilist", "title": _title(m.get("title")),
             "year": str(m.get("seasonYear") or ""), "overview": _clean(m.get("description"))[:400],
             "thumb": (m.get("coverImage") or {}).get("large") or (m.get("coverImage") or {}).get("medium") or ""}
            for m in media]
