"""More places to take a title's details from, for Fix Scraped Data. Each gives search results ({id, source, title,
year, overview, thumb}) and details in the same shape as a TMDB hit (scraper.tmdb_details), so the window can show
them side by side and apply any field from any of them.

- TVmaze (TV series): free, no key. Synopsis, poster, backgrounds, cast; its TheTVDB id finds fanart.tv art.
- MyAnimeList, through Jikan (anime): free, no key. Synopsis, score, genres, themes, studios, age rating, pictures.
- Kitsu (anime): free, no key for public data. Synopsis, poster, cover (banner), rating, age rating, categories.
- fanart.tv (art only, with your key from Integrations & APIs): textless posters, backgrounds, banners and disc art,
  found by a result's TMDB id (films) or TheTVDB id (series). It is not searched by title.
"""
import urllib.parse

from utils import alttitles, scraper

LIMIT = 8
_get, _clean, safe = scraper._get_json, scraper.untag, scraper.safe_url


def _year(date) -> str:
    return (date or "")[:4]


# ------------------------------------------------------------------ TVmaze

def tvmaze_search(query: str) -> list[dict]:
    rows = _get(f"https://api.tvmaze.com/search/shows?q={urllib.parse.quote(query)}") or []
    out = []
    for r in rows[:LIMIT]:
        s = r.get("show") or {}
        out.append({"id": str(s.get("id")), "source": "tvmaze", "title": s.get("name") or "", "year": _year(s.get("premiered")),
                    "overview": _clean(s.get("summary") or "")[:400], "thumb": safe((s.get("image") or {}).get("medium")) or ""})
    return out


def tvmaze_details(show_id: int) -> dict:
    s = _get(f"https://api.tvmaze.com/shows/{int(show_id)}?embed[]=cast&embed[]=images")
    emb = s.get("_embedded") or {}
    images = emb.get("images") or []

    def by(kind):
        pics = [i for i in images if i.get("type") == kind]
        pics.sort(key=lambda i: not i.get("main"))
        return [u for u in (((i.get("resolutions") or {}).get("original") or {}).get("url") for i in pics) if safe(u)]
    cast = [{"id": None, "name": (c.get("person") or {}).get("name") or "", "role": (c.get("character") or {}).get("name") or "",
             "photo_url": ((c.get("person") or {}).get("image") or {}).get("medium")} for c in (emb.get("cast") or [])[:15]]
    backgrounds = by("background")
    return {"title": s.get("name") or "", "release_date": s.get("premiered"), "synopsis": _clean(s.get("summary") or "") or None,
            "poster_url": (by("poster") or [None])[0] or (s.get("image") or {}).get("original"),
            "banner_url": (backgrounds or by("banner") or [None])[0], "gallery_urls": backgrounds[:12],
            "genres": s.get("genres") or [], "score": (s.get("rating") or {}).get("average"), "certification": None,
            "cast": [c for c in cast if c["name"]], "tmdb_id": None, "anilist_id": None,
            "tvdb_id": (s.get("externals") or {}).get("thetvdb"), "imdb_id": (s.get("externals") or {}).get("imdb"),
            "collection_id": None, "collection_name": None, "kind": "show"}


# ------------------------------------------------------------------ MyAnimeList (Jikan)

_MAL_RATING = {"G": "G", "PG": "PG", "PG-13": "PG-13", "R": "R", "R+": "R+", "Rx": "18+"}


def mal_search(query: str) -> list[dict]:
    data = _get(f"https://api.jikan.moe/v4/anime?q={urllib.parse.quote(query)}&limit={LIMIT}").get("data") or []
    return [{"id": str(a.get("mal_id")), "source": "mal", "title": a.get("title_english") or a.get("title") or "",
             "year": str(a.get("year") or _year((a.get("aired") or {}).get("from"))),
             "overview": _clean(a.get("synopsis") or "")[:400],
             "thumb": safe(((a.get("images") or {}).get("jpg") or {}).get("image_url")) or ""} for a in data]


def mal_details(mal_id: int) -> dict:
    a = _get(f"https://api.jikan.moe/v4/anime/{int(mal_id)}/full").get("data") or {}
    from utils import anilist
    names = lambda key: [g.get("name") for g in a.get(key) or [] if g.get("name")]   # noqa: E731
    rating = (a.get("rating") or "").split(" - ")[0].strip()
    english = a.get("title_english")
    synonyms = [t.get("title") for t in a.get("titles") or [] if t.get("type") not in ("Default", "Japanese", "English")]
    return {"title": english or a.get("title") or "", "release_date": ((a.get("aired") or {}).get("from") or "")[:10] or None,
            "synopsis": _clean((a.get("synopsis") or "").replace("[Written by MAL Rewrite]", "")).strip() or None,
            "poster_url": ((a.get("images") or {}).get("jpg") or {}).get("large_image_url"), "banner_url": None,
            "gallery_urls": list(anilist.mal_pictures(int(mal_id), limit=12)),
            "genres": names("genres") + names("themes") + names("explicit_genres"), "studios": names("studios"),
            "score": a.get("score"), "certification": _MAL_RATING.get(rating),
            "romaji_title": a.get("title"), "original_title": a.get("title_japanese"),
            "alt_titles": alttitles.dumps(alttitles.from_anilist({"english": english, "romaji": a.get("title"),
                                                                   "native": a.get("title_japanese")}, synonyms)),
            "cast": [], "tmdb_id": None, "anilist_id": None, "mal_id": int(mal_id),
            "collection_id": None, "collection_name": None, "kind": "show" if a.get("type") in ("TV", "OVA", "ONA") else "movie"}


# ------------------------------------------------------------------ Kitsu

KITSU = "https://kitsu.app/api/edge"


def _kitsu_title(at: dict) -> str:
    t = at.get("titles") or {}
    return t.get("en") or t.get("en_us") or at.get("canonicalTitle") or t.get("en_jp") or ""


def kitsu_search(query: str) -> list[dict]:
    data = _get(f"{KITSU}/anime?filter[text]={urllib.parse.quote(query)}&page[limit]={LIMIT}").get("data") or []
    return [{"id": str(a.get("id")), "source": "kitsu", "title": _kitsu_title(a.get("attributes") or {}),
             "year": _year((a.get("attributes") or {}).get("startDate")),
             "overview": _clean((a.get("attributes") or {}).get("synopsis") or "")[:400],
             "thumb": safe(((a.get("attributes") or {}).get("posterImage") or {}).get("small")) or ""} for a in data]


def kitsu_details(kitsu_id) -> dict:
    data = _get(f"{KITSU}/anime/{urllib.parse.quote(str(kitsu_id))}?include=categories")
    at = (data.get("data") or {}).get("attributes") or {}
    cats = [(c.get("attributes") or {}).get("title") for c in data.get("included") or [] if c.get("type") == "categories"]
    t = at.get("titles") or {}
    score = at.get("averageRating")
    age = {"G": "G", "PG": "PG", "R": "R", "R18": "18+"}.get(at.get("ageRating") or "")
    return {"title": _kitsu_title(at), "release_date": at.get("startDate"), "synopsis": _clean(at.get("synopsis") or "") or None,
            "poster_url": (at.get("posterImage") or {}).get("original"), "banner_url": (at.get("coverImage") or {}).get("original"),
            "gallery_urls": [u for u in [(at.get("coverImage") or {}).get("original")] if u],
            "genres": [c for c in cats if c][:12], "score": round(float(score) / 10, 1) if score else None, "score_scale": "percent",
            "certification": age, "romaji_title": t.get("en_jp"), "original_title": t.get("ja_jp"),
            "alt_titles": alttitles.dumps(alttitles.from_anilist({"english": t.get("en"), "romaji": t.get("en_jp"),
                                                                   "native": t.get("ja_jp")}, at.get("abbreviatedTitles") or [])),
            "cast": [], "tmdb_id": None, "anilist_id": None, "kitsu_id": str(kitsu_id),
            "collection_id": None, "collection_name": None, "kind": "movie" if at.get("subtype") == "movie" else "show"}


# ------------------------------------------------------------------ fanart.tv (art only)

def _best(items) -> list[str]:
    items = [i for i in items or [] if safe(i.get("url"))]
    items.sort(key=lambda i: (i.get("lang") not in ("en", "00", ""), -int(i.get("likes") or 0)))
    return [i["url"] for i in items]


def fanart_details(kind: str, ident, key: str) -> dict | None:
    """kind "movie" (ident: TMDB id) or "show" (ident: TheTVDB id). None when fanart.tv has nothing for it."""
    if not (key and ident):
        return None
    path = f"movies/{int(ident)}" if kind == "movie" else f"tv/{int(ident)}"
    try:
        d = _get(f"https://webservice.fanart.tv/v3/{path}?api_key={urllib.parse.quote(key)}")
    except scraper.ScrapeError:
        return None
    if kind == "movie":
        posters, backs, discs = _best(d.get("movieposter")), _best(d.get("moviebackground")), _best(d.get("moviedisc"))
    else:
        posters, backs, discs = _best(d.get("tvposter")), _best(d.get("showbackground")), []
    if not (posters or backs or discs):
        return None
    return {"title": d.get("name") or "", "poster_url": (posters or [None])[0], "banner_url": (backs or [None])[0],
            "gallery_urls": backs[:12], "disc_url": (discs or [None])[0], "art_only": True}
