"""Library models and the `Backend` controller that Dashboard.qml talks to."""
import json
import logging
import os
import random
import re
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, QObject, Qt, QTimer, Signal, Slot

import database as db
from utils import alttitles, backup_manager, health, hw_accelerator, media_probe, scraper, streaming
from PIL import Image, ImageOps

from . import dvd_box, file_url, pick_folder, pick_image

log = logging.getLogger(__name__)
BILLBOARD_SIZE = 8  # titles in the recommended carousel
SETTINGS = {"tmdb_key", "omdb_key", "night_mode", "reduce_motion", "upscale_level", "show_insights", "core", "theme",
            "custom_accent", "custom_highlight", "custom_page", "custom_surface", "custom_card", "custom_text",
            "custom_muted", "custom_amber", "custom_red", "auto_credits", "auto_tags",
            "fanart_key", "animated_theme", "hover_preview", "detail_order", "title_language", "group_collections", "discord", "discord_detail", "discord_app_id",
            "discord_details", "discord_state", "discord_paused", "discord_hide_adult", "discord_image_text",
            "discord_folders", "discord_hide_tags", "image_quality", "gpu_high_performance", "continue_watching", "lock_scope", "opensubtitles_key", "subtitle_language",
            "recently_added", "resume_prompt", "auto_lock_minutes", "lock_on_minimize", "show_missing_episodes", "pip_keep_library"}


TITLE_LANGUAGES = [("english", "English"), ("romaji", "Romaji"), ("original", "Original")]


def _same(a: str, b: str) -> bool:
    simple = lambda t: re.sub(r"[^0-9a-z]+", "", (t or "").casefold())
    return simple(a) == simple(b)


def title_pref() -> str:
    """Settings > Library > Titles: english, romaji or original (english before the library exists)."""
    try:
        return db.get_setting("title_language", "english") or "english"
    except Exception:
        return "english"


def display_titles(card: dict, pref: str | None = None) -> tuple[str, str]:
    """(title, small line under it) by the Titles setting: English (the stored title), Romaji or Original (its own
    language and alphabet). The line under it is the original title, or the English one when the original is shown;
    empty when they are the same. Series use the series name (no SxxEyy)."""
    pref = pref or title_pref()
    stored = card["title"]
    if card.get("media_type") == "show" and not card.get("key", "").startswith("set:"):
        stored = db.series_title(stored)
    original, romaji = card.get("original_title") or "", card.get("romaji_title") or ""
    if card.get("key", "").startswith("set:"):
        original = romaji = ""
    main = {"romaji": romaji or stored, "original": original or stored}.get(pref, stored)
    sub = stored if pref == "original" and original else (original or "")
    if pref == "romaji" and romaji and not original:
        sub = stored
    return main, ("" if _same(sub, main) else sub)


def set_synopsis(cid, films: list[dict]) -> str:
    """A box set's synopsis: the one written for it, else the one all its films share (an OVA's episodes carry the
    series synopsis), else none."""
    own = db.collection_synopsis(cid)
    if own:
        return own
    shared = {(f.get("synopsis") or "").strip() for f in films} - {""}
    return shared.pop() if len(shared) == 1 else ""


def banner_for(card: dict):
    """The wide picture for a title or box set: its banner (the best-rated TMDB backdrop), else the best scraped
    Gallery still, else any Gallery image. A box set without its own banner borrows its first film's. None if none."""
    key = card.get("key", "")
    if key.startswith("set:"):
        own = scraper.banner_path(scraper.collection_item(key[4:]))
        if own.exists():
            return own
        films = db.films_in_set(key[4:])
        return next((b for b in (banner_for(f) for f in films) if b), None)
    try:
        own = scraper.banner_path(card)
    except (KeyError, TypeError):
        return None
    if own.exists():
        return own
    gallery = scraper.gallery_images(card)
    return next((p for p in gallery if p.name.startswith("s-")), None) or (gallery[0] if gallery else None)


# Fix Scraped Data: what can be taken from which result, in the order the window lists them
MATCH_FIELDS = ("title", "year", "synopsis", "poster", "banner", "disc", "genres", "score", "rating", "titles", "cast", "boxset")
MATCH_SOURCES = ("tmdb", "anilist", "omdb", "tvmaze", "mal", "kitsu")
SET_FIELDS = ("title", "synopsis", "poster", "banner", "disc")     # what a box set's own page can take
HIDDEN_KINDS = ("all_dirs", "all_tags", "insights_dirs", "continue_dirs", "private_dirs", "recent_dirs")
UPLOAD_FIELDS = ("poster", "banner", "disc", "gallery")      # the "Upload file" tile in the window
PERCENT_SOURCES = ("anilist", "kitsu")                        # scores shown as a percentage
GALLERY_PICK_MAX = 40                                         # Gallery images offered per result, to pick one by one


def episode_row(e: dict) -> dict:
    """What a series' episode list shows for one episode: its number, name, synopsis, length and picture."""
    se = scraper.season_episode(e["title"])
    still = scraper.still_path(e)
    return {"season": se[0] if se else 0, "number": se[1] if se else 0, "name": e.get("episode_title") or "",
            "synopsis": e.get("episode_synopsis") or "", "length": duration_label(e["duration"]),
            "still": file_url(still) if still.exists() else ""}


def missing_rows(folder: str, eps: list[dict]) -> list[dict]:
    """Episodes the guide lists that are not on disk, as greyed rows of the episode list (off in Settings)."""
    if db.get_setting("show_missing_episodes", "1") == "0":
        return []
    have = {se for se in (scraper.season_episode(e["title"]) for e in eps) if se}
    return [{"uuid": "", "title": f"S{g['season']:02d}E{g['number']:02d}", "done": False, "progress": 0, "missing": True,
             "season": g["season"], "number": g["number"], "name": g["name"] or "", "synopsis": "", "length": "", "still": ""}
            for g in db.gaps(folder) if (g["season"], g["number"]) not in have]


def image_size(path) -> str:
    """"1920 \u00D7 1080" for a Gallery tile. Only the file's header is read."""
    try:
        with Image.open(path) as im:
            return f"{im.width} \u00D7 {im.height}"
    except (OSError, ValueError):
        return ""


def clock_label(seconds) -> str:
    s = int(seconds or 0)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def added_label(added_at: str, now) -> str:
    """"Added today" ... "Added 3 weeks ago"; "" once it is older than 30 days."""
    try:
        then = datetime.fromisoformat(added_at)
    except (TypeError, ValueError):
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    days = (now - then).days
    if days > 30:
        return ""
    if days < 1:
        return "Added today"
    if days < 7:
        return f"Added {days} day{'s' if days != 1 else ''} ago"
    return f"Added {days // 7} week{'s' if days // 7 != 1 else ''} ago"


def idle_seconds() -> float:
    """How long since the last key or mouse input anywhere on this PC (Windows keeps count). 0 where unknown."""
    try:
        import ctypes

        class LastInput(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        info = LastInput(ctypes.sizeof(LastInput), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000
    except (AttributeError, OSError):
        return 0.0


def _upload_path(choice) -> str | None:
    """A "file:<path>" choice from the window: the path, if it is an image file that exists, else None."""
    if not (isinstance(choice, str) and choice.startswith("file:")):
        return None
    path = choice[5:]
    return path if os.path.isfile(path) and os.path.splitext(path)[1].lower() in scraper.IMAGE_EXTS else None


def match_preview(h: dict) -> dict:
    """What one result offers for each field, for the Fix Scraped Data window (short: no full cast, no raw data)."""
    gallery = [u for u in h.get("gallery_urls") or [] if scraper.safe_url(u)]
    names = [c.get("name") for c in h.get("cast") or [] if c.get("name")]
    score = h.get("score")
    out = {
        "title": h.get("title") or "",
        "year": (h.get("release_date") or "")[:4],
        "synopsis": scraper.untag(h.get("synopsis") or ""),
        "poster": scraper.safe_url(h.get("poster_url")) or "",
        "banner": scraper.safe_url(h.get("banner_url")) or "",
        "gallery": gallery[:GALLERY_PICK_MAX], "galleryCount": len(gallery[:GALLERY_PICK_MAX]),
        "genres": ", ".join((h.get("genres") or []) + [f"{s} (studio)" for s in h.get("studios") or []]),
        "score": "" if score is None else (f"{round(score * 10)}%" if h.get("anilist_id") or h.get("score_scale") == "percent"
                                           else f"{score:.1f} / 10"),
        "disc": scraper.safe_url(h.get("disc_url")) or "",
        "rating": h.get("certification") or "",
        "titles": " \u00B7 ".join(t for t in (h.get("original_title"), h.get("romaji_title")) if t),
        "cast": ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else ""),
        "boxset": h.get("collection_name") or "",
    }
    return out


def art_item(card: dict) -> dict:
    """What a card's box art belongs to: a box set has its own (keyed by collection), everything else its file."""
    key = card.get("key", "")
    if key.startswith("set:"):
        return scraper.collection_item(key[4:], card.get("collection_name") or card["title"])
    return card


def duration_clock(seconds) -> str:
    s = int(seconds or 0)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def duration_label(seconds) -> str:
    if not seconds:
        return ""
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


_TINTS: dict[str, str] = {}


def tint_of(path: str) -> str:
    """The most vivid strong colour of an image (for animated themes), '#RRGGBB'; '' if unreadable. Cached."""
    if path in _TINTS:
        return _TINTS[path]
    import colorsys
    try:
        with Image.open(path) as im:
            small = im.convert("RGB").resize((48, 48))
        best, score = None, -1.0
        for count, rgb in small.quantize(8).convert("RGB").getcolors(64) or []:
            h, l, sat = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
            w = count * (sat + 0.05) * (1 - abs(l - 0.5) * 1.6)   # vivid, not too dark or too light
            if w > score:
                best, score = rgb, w
        out = "#%02X%02X%02X" % best if best else ""
    except Exception:
        out = ""
    _TINTS[path] = out
    return out


def conn_has_path(path: str) -> bool:
    return bool(db.conn().execute("SELECT 1 FROM media_items WHERE file_path=?", (db.norm(path),)).fetchone())


def billboard_deck(cards: list[dict], keep: list[str], size: int = BILLBOARD_SIZE) -> dict:
    """Random picks for the recommended carousel. Unfinished titles first; finished ones only fill a short deck.
    Titles from `keep` that are still unfinished stay, in order, so a library refresh does not reshuffle."""
    pref = title_pref()
    fresh = [c for c in cards if not c["is_completed"]]
    by_key = {c["key"]: c for c in fresh}
    deck = [by_key[k] for k in keep if k in by_key][:size]
    rest = [c for c in fresh if c["key"] not in {d["key"] for d in deck}]
    deck += random.sample(rest, min(len(rest), size - len(deck)))
    if len(deck) < size:  # tab where (almost) everything is watched: still show something
        done = [c for c in cards if c["is_completed"]]
        deck += random.sample(done, min(len(done), size - len(deck)))
    items = []
    for c in deck:
        art = banner_for(c) or next((p for p in (scraper.fanart_path(c), scraper.cover_path(c)) if p.exists()), None)
        length = f"{c['episodes']} episodes" if c["episodes"] else duration_label(c["duration"])
        meta = " · ".join(x for x in ((c["release_date"] or "")[:4], c["resolution"], c["codec"],
                                      c["audio_layout"], length) if x)
        title, subtitle = display_titles(c, pref)
        items.append({"key": c["key"], "title": title, "subtitle": subtitle, "meta": meta, "synopsis": c["synopsis"] or "",
                      "art": file_url(art) if art else ""})
    return {"visible": bool(items), "items": items}


CUSTOM_ART = {"front": scraper.custom_front_path, "back": scraper.custom_back_path, "spine": scraper.custom_spine_path,
              "disc": scraper.custom_disc_path}


def save_box_art(img, items: list[dict], face: str) -> None:
    """Centre-crop to the face's shape (135:190 cover, or a 14:190 spine) and save as the custom art of each item."""
    size = scraper._sized(dvd_box.SPINE_W_H if face == "spine" else (500, 500) if face == "disc" else dvd_box.FRONT_W_H)
    img = ImageOps.exif_transpose(img).convert("RGB")
    if face == "spine" and img.width > img.height:  # spines are often scanned lying down
        img = img.rotate(-90, expand=True)
    img = ImageOps.fit(img, size, Image.Resampling.LANCZOS)
    for item in filter(None, items):
        scraper.save_webp(img, CUSTOM_ART[face](item), box=size)


# ------------------------------------------------------------------ models

SORTS = [("title", "Title"), ("added", "Recently added"), ("year", "Year"), ("rating", "Your rating"),
         ("length", "Length"), ("unwatched", "Unwatched first")]
QUALITIES = [("4k", "4K UHD"), ("1080", "1080p HD"), ("720", "720p"), ("sd", "SD")]


def quality_of(resolution: str | None) -> str:
    """'3840x1606', '1920x800', '2160p' ... -> 4k / 1080 / 720 / sd ("" if unknown). Width decides, so scope films
    (wide and short) land in the right class."""
    nums = [int(n) for n in re.findall(r"\d{3,4}", resolution or "")]
    if not nums:
        return ""
    width = nums[0] if "x" in (resolution or "").lower() and len(nums) > 1 else nums[0] * 16 // 9
    return "4k" if width >= 3200 else "1080" if width >= 1800 else "720" if width >= 1200 else "sd"


def library_view(cards: list[dict], index: dict, query: str = "", sort: str = "title", genre: str = "",
                 quality: str = "", unwatched: bool = False, marked: set | None = None) -> list[dict]:
    """Search (every word must appear in the title, synopsis, tags, genres, notes, year or format), filter, sort."""
    words = query.lower().split()
    out = []
    for c in cards:
        info = index.get(c["uuid"], {})
        if unwatched and c["is_completed"]:
            continue
        if marked is not None and c["key"] not in marked:      # the Favourites / Watchlist filter
            continue
        if genre and genre not in info.get("genres", ()):
            continue
        if quality and quality_of(c["resolution"]) != quality:
            continue
        if words:
            hay = " ".join((c["title"], c.get("original_title") or "", c.get("romaji_title") or "", alttitles.haystack(c.get("alt_titles")), c.get("synopsis") or "", " ".join(info.get("tags", ())), " ".join(info.get("genres", ())),
                            info.get("note", ""), (c.get("release_date") or "")[:4], c.get("codec") or "", c.get("resolution") or "",
                            os.path.basename(c["file_path"]))).lower()
            if not all(w in hay for w in words):
                continue
        out.append(c)
    title = lambda c: c["title"].lower()
    keys = {
        "added": lambda c: (c.get("added_at") or "", title(c)),
        "year": lambda c: ((c.get("release_date") or "")[:4], title(c)),
        "rating": lambda c: (index.get(c["uuid"], {}).get("rating", 0), title(c)),
        "length": lambda c: (c["duration"] or 0, title(c)),
    }
    if sort in keys:
        out.sort(key=keys[sort], reverse=True)   # newest, latest, highest, longest first
    elif sort == "unwatched":
        out.sort(key=lambda c: (bool(c["is_completed"]), bool(c["last_position"]), title(c)))
    return out


class FolderIndex:
    """Which files exist, by listing each folder once (with each file's change time for the image URL). The grid
    asks about 4 to 13 files per card; on Windows each check is a trip to the disk, on the interface's own thread."""

    def __init__(self):
        self._dirs: dict[str, dict[str, int]] = {}

    def _listing(self, folder: str) -> dict[str, int]:
        got = self._dirs.get(folder)
        if got is None:
            got = {}
            try:
                with os.scandir(folder) as it:
                    for e in it:
                        try:
                            got[os.path.normcase(e.name)] = e.stat().st_mtime_ns    # cached by the listing on Windows
                        except OSError:
                            pass
            except OSError:          # missing folder, unplugged drive
                pass
            self._dirs[folder] = got
        return got

    def has(self, path) -> bool:
        p = os.fspath(path)
        return os.path.normcase(os.path.basename(p)) in self._listing(os.path.dirname(p))

    def url(self, path) -> str:
        """file:/// URL with ?v=<mtime>, like file_url, from the listing (no extra disk check)."""
        p = os.fspath(path)
        mtime = self._listing(os.path.dirname(p)).get(os.path.normcase(os.path.basename(p)))
        return file_url(p, bust=False) + (f"?v={mtime}" if mtime is not None else "")


class LibraryModel(QAbstractListModel):
    """One row per card. QML's GridView only creates delegates for what is on screen and recycles them."""
    KEY, TITLE, META, POSTER, PROGRESS, DONE, BADGE, VIDEO, DURATION, OFFLINE, SPINE, YEAR, DISC, SUBTITLE, FAV, WATCH = \
        (Qt.UserRole + i for i in range(1, 17))
    NAMES = {KEY: b"key", TITLE: b"title", META: b"meta", POSTER: b"poster", PROGRESS: b"progress",
             DONE: b"done", BADGE: b"badge", VIDEO: b"videoUrl", DURATION: b"durationMs",
             OFFLINE: b"offline", SPINE: b"spine", YEAR: b"year", DISC: b"disc", SUBTITLE: b"subtitle",
             FAV: b"favourite", WATCH: b"watchlist"}
    FIELDS = {KEY: "key", TITLE: "title", META: "meta", POSTER: "poster", PROGRESS: "progress", DONE: "done",
              BADGE: "badge", VIDEO: "video", DURATION: "duration_ms", OFFLINE: "offline", SPINE: "spine", YEAR: "year",
              DISC: "disc", SUBTITLE: "subtitle", FAV: "fav", WATCH: "watch"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict] = []
        self.view: dict = {}           # search / sort / filters (Dashboard.setView)
        self.spines = False            # look up spine art only while the shelf view is on (it costs file checks)
        self.title_pref = "english"    # Settings > Library > Titles (set by reload)
        self.private_closed: set = set()   # private folders not signed in to: their titles are left out everywhere
        self.mark = ""                 # "favourite" / "watchlist": show only those
        self._marks: dict = {}

    @Slot(int, int, result="QVariantList")
    def keysBetween(self, a: int, b: int):
        """The cards from row a to row b (Shift-click selects a range)."""
        lo, hi = max(0, min(a, b)), min(len(self._rows) - 1, max(a, b))
        return [r["key"] for r in self._rows[lo:hi + 1]]

    def roleNames(self):
        return self.NAMES

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        field = self.FIELDS.get(role)
        value = self._rows[index.row()][field] if field else None
        return scraper.untag(value) if isinstance(value, str) else value     # titles from before 1.0.6 too

    def _row(self, card: dict, online: bool, files: "FolderIndex") -> dict:
        row = self._card_row(card, online, files)
        row["fav"] = card["key"] in self._marks.get("favourite", ())
        row["watch"] = card["key"] in self._marks.get("watchlist", ())
        return row

    def _card_row(self, card: dict, online: bool, files: "FolderIndex") -> dict:
        art = art_item(card)
        poster = scraper.cover_path(art, files.has)
        if art is not card and not files.has(poster):
            poster = scraper.cover_path(card, files.has)        # box set without its own poster: the first film's
        shows, films = card["episodes"], card.get("films", 0)
        if films:
            progress = card["watched"] / films
        elif card["last_position"] and card["duration"] and not card["is_completed"]:
            progress = min(1.0, card["last_position"] / card["duration"])
        else:
            progress = card["watched"] / shows if shows else 0.0
        meta = " · ".join(x for x in ((card["release_date"] or "")[:4], card["resolution"] if not films else "",
                                      duration_label(card["duration"]) if not (shows or films) else "") if x)
        spine = scraper.spine_path(art, files.has) if (self.spines and online) else None
        title, subtitle = display_titles(card, self.title_pref)
        return {"key": card["key"], "title": title, "subtitle": subtitle, "meta": meta,
                "poster": files.url(poster) if online and files.has(poster) else "", "progress": progress,
                "done": bool(card["is_completed"]), "badge": f"{shows} episodes" if shows else f"{films} films" if films else "",
                "video": file_url(card["file_path"], bust=False), "duration_ms": int((card["duration"] or 0) * 1000),
                "offline": not online, "spine": files.url(spine) if spine else "", "year": (card["release_date"] or "")[:4],
                "disc": self._disc(art, files) if online else ""}

    @staticmethod
    def _disc(card, files: "FolderIndex") -> str:
        """Disc art only (your own or scraped); the card falls back to its poster itself."""
        for p in (scraper.custom_disc_path(card), scraper.disc_path(card)):
            if files.has(p):
                return files.url(p)
        return ""

    def reload(self, dir_id, fresh: bool = False) -> list[dict]:
        """Refresh the cards (searched, filtered, sorted by `view`). Returns ALL of the tab's cards, unfiltered,
        so the billboard picks from the whole tab without a second query. fresh: rebuild the list even if the
        cards are the same (a new tab: every card plays its entrance)."""
        self.title_pref = db.get_setting("title_language", "english") or "english"
        cards = db.list_library(dir_id)
        index = db.search_index()
        if self.private_closed:            # private folders you have not signed in to
            cards = [c for c in cards if c["parent_directory_id"] not in self.private_closed]
        if dir_id is None:                 # the All tab leaves out the folders and tags you chose to hide from it
            cards = db.visible_in_all(cards, index)
        self._marks = db.marks()
        online = {d["id"]: os.path.isdir(d["folder_path"]) for d in db.list_directories()}   # one check per folder
        marked = self._marks.get(self.mark) if self.mark else None
        shown = library_view(cards, index, **self.view, marked=marked) if (self.view or marked is not None) else cards
        files = FolderIndex()               # one listing per art folder instead of several file checks per card
        rows = [self._row(c, online.get(c["parent_directory_id"], True), files) for c in shown]
        if not fresh and rows == self._rows:
            return cards                   # nothing changed (View More or Settings closed without an edit)
        if not fresh and [r["key"] for r in rows] == [r["key"] for r in self._rows]:
            changed = [i for i, (a, b) in enumerate(zip(rows, self._rows)) if a != b]
            self._rows = rows  # same cards: refresh in place so the grid keeps its scroll position
            if changed:        # only the cards that changed redraw
                self.dataChanged.emit(self.index(changed[0]), self.index(changed[-1]))
            return cards
        # another change while the last one is still animating: interrupted view transitions can strand cards
        # half-faded or out of place, so rebuild the list at once instead
        busy = time.monotonic() - self._stepped_at < self.SETTLE
        if not fresh and not busy and self._step_to(rows):
            self._stepped_at = time.monotonic()
            return cards
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()
        return cards

    MAX_STEPS = 150      # more cards than this coming or going at once: rebuild the list instead
    SETTLE = 0.9         # seconds the grid's filter animation takes, start to finish
    _stepped_at = -1e9

    def _step_to(self, rows: list[dict]) -> bool:
        """A filter added or taken away: remove the cards that go and insert the ones that come, so the grid can
        animate them (fade out and close the gaps; open gaps and fade in). Only when the cards that stay keep their
        order (a new sort, or a different tab, rebuilds the list). Returns False when it cannot."""
        old, new = [r["key"] for r in self._rows], [r["key"] for r in rows]
        old_set, new_set = set(old), set(new)
        if [k for k in old if k in new_set] != [k for k in new if k in old_set]:
            return False
        if len(old_set - new_set) + len(new_set - old_set) > self.MAX_STEPS or not old_set & new_set:
            return False
        # the ones that go, from the end so the earlier positions stay valid; neighbours in one range together
        i = len(old) - 1
        while i >= 0:
            if old[i] in new_set:
                i -= 1
                continue
            j = i
            while j - 1 >= 0 and old[j - 1] not in new_set:
                j -= 1
            self.beginRemoveRows(QModelIndex(), j, i)
            del self._rows[j:i + 1]
            self.endRemoveRows()
            i = j - 1
        # the ones that come, in their places
        i = 0
        while i < len(new):
            if new[i] in old_set:
                i += 1
                continue
            j = i
            while j + 1 < len(new) and new[j + 1] not in old_set:
                j += 1
            self.beginInsertRows(QModelIndex(), i, j)
            self._rows[i:i] = rows[i:j + 1]
            self.endInsertRows()
            i = j + 1
        self._rows = rows          # the cards that stayed get their fresh data (progress, art)
        if rows:
            self.dataChanged.emit(self.index(0), self.index(len(rows) - 1))
        return True


class TabsModel(QAbstractListModel):
    ID, NAME, LOCKED = Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = [(-1, "All", False)]
        self.private_closed: set = set()

    def roleNames(self):
        return {self.ID: b"tabId", self.NAME: b"name", self.LOCKED: b"locked"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        tab_id, name, locked = self._rows[index.row()]
        return tab_id if role == self.ID else name if role == self.NAME else locked if role == self.LOCKED else None

    def reload(self):
        rows = [(-1, "All", False)] + [(d["id"], d["tab_name"], d["id"] in self.private_closed) for d in db.list_directories()]
        if rows == self._rows:             # the tab bar is not rebuilt (and does not flicker) for nothing
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()


# ------------------------------------------------------------------ controller

class Dashboard(QObject):
    """Exposed to QML as `Backend`."""
    needsSetupChanged = Signal()
    billboardChanged = Signal()
    insightsChanged = Signal()
    insightsVisibleChanged = Signal()
    libraryChanged = Signal()          # emit from any thread: the UI refreshes on the GUI thread
    toast = Signal(str)
    raiseWindow = Signal()
    recentChanged = Signal()
    minimizeWindow = Signal()          # picture in picture: only the small video window stays on screen
    thumbnailsReady = Signal(int)
    boxArtChanged = Signal(str)        # key whose covers changed: the open detail view reloads its textures
    offlineChanged = Signal()
    streamChanged = Signal()
    devicesFound = Signal("QVariantList")
    folderPicked = Signal(str, str)
    artPicked = Signal(str, str, str, str)       # key, face, image url, path: View More opens its crop editor
    componentsChecked = Signal("QVariantList")   # Settings > About & Updates, after a check or an update
    updateCountChanged = Signal()                # how many things have an update (badge on Settings)
    startupReadyChanged = Signal()               # the library is loaded: the opening vault may open
    lockedChanged = Signal()                     # Privacy lock: the lock screen shows / goes away
    lockChanged = Signal()                       # a sign-in was added or removed (Settings > Privacy)
    unlockResult = Signal(bool, str)             # ok, message for the lock screen
    _unlocked = Signal()                         # from a worker thread: open the library (on the main thread)
    continueChanged = Signal()                   # the Continue Watching row
    privateOpened = Signal(int)                  # signed in for a private tab: the dashboard switches to it (-1: none)
    undoOffered = Signal(str)                    # a message with an Undo button (Backend.undoLast)
    jobsChanged = Signal()                       # progress pills under the top bar (utils/progress.py)
    _progress = Signal("QVariantMap")            # from any thread: one job's new state, handled on the main thread
    _quitForUpdate = Signal()                    # from a worker thread: close Media Vault so setup can replace it
    appUpdateProgress = Signal(float)            # 0..1 while the new setup.exe downloads; -1 = failed              # path, suggested tab name
    matchResults = Signal(str, "QVariantList")   # key, candidates
    matchFailed = Signal(str, str)               # key, reason
    matchApplied = Signal(str, str)              # old key, new key (a film can join or leave a box set)
    matchDetailsReady = Signal(str, "QVariantList")   # key, every picked result's details (Fix Scraped Data, step 2)
    matchFilesPicked = Signal(str, str, "QVariantList")   # key, field, [{url, choice}] from "Upload file"
    assetsScanned = Signal("QVariantMap")                 # Settings > Storage: {total, unused, unusedCount, yours} in bytes
    _thumbnailsDone = Signal(str, object)

    def __init__(self, app, library: LibraryModel, tabs: TabsModel, frames: dvd_box.FrameProvider, parent=None):
        super().__init__(parent)
        self.app, self.library, self.tabs, self.frames = app, library, tabs, frames
        self._needs_setup = True
        self._tab = -1
        self._billboard, self._insights = {"visible": False, "items": []}, {}
        self._bb_keys: list[str] = []  # the carousel deck; kept across refreshes so it does not reshuffle
        self._ignored_now: dict[str, set] = {}   # Library health: hidden until Media Vault restarts
        self._offline: list[str] = []
        self.stream = streaming.StreamServer()
        self._devices: list = []
        self._insights_visible = False
        self._recent: list = []
        self._idle = QTimer(self)                 # auto-lock: a look at the clock every 20 seconds, nothing per event
        self._idle.setInterval(20_000)
        self._idle.timeout.connect(lambda: self.idle_check(idle_seconds()))
        self._idle.start()
        self._thumbs: list = []
        # a burst of changes (a scan adding files, the folder watcher) becomes one refresh, not one per event
        self._reload_soon = QTimer(self)
        self._reload_soon.setSingleShot(True)
        self._reload_soon.setInterval(80)
        self._reload_soon.timeout.connect(self.reload)
        self.libraryChanged.connect(self._reload_soon.start)
        self._thumbnailsDone.connect(self._store_thumbnails)
        self._update_count = 0
        self._startup_ready = False
        self.componentsChecked.connect(self._count_updates)
        self._quitForUpdate.connect(self._quit_for_update)     # queued: runs on the main thread
        self._locked = False
        self._unlocking = False
        self._match_hits: dict[str, dict] = {}                # Fix Scraped Data: key -> {pid: full details}
        self._private_open = False                            # signed in this session: private tabs show
        self._lock_reason, self._pending_tab = "app", -1
        self._continue: list = []
        self._undo = None
        self._guides: set = set()                             # series whose episode guide was asked for this session
        self.hwnd = None                                       # the library window: Windows' sign-in prompt sits on it
        self._unlocked.connect(self._set_unlocked)
        self._jobs: dict[int, dict] = {}
        self._progress.connect(self._on_progress)
        from utils import progress
        progress.subscribe(self._progress.emit)
        try:
            from utils import applock
            # "private": only the private tabs ask you to sign in; the rest of the library opens as usual
            self._locked = db.db_exists() and applock.enabled() and db.get_setting("lock_scope", "app") != "private"
        except Exception:
            log.exception("app lock")

    # -- properties
    @Property(bool, notify=startupReadyChanged)
    def startupReady(self):
        return self._startup_ready

    # -- progress pills: scraping, artwork and downloads (utils/progress.py)
    @Property("QVariantList", notify=jobsChanged)
    def jobs(self):
        return list(self._jobs.values())

    @Slot("QVariantMap")
    def _on_progress(self, event: dict):
        jid = int(event["id"])
        self._jobs[jid] = event
        if event.get("state") != "running":              # it stays a moment to show it finished, then goes
            QTimer.singleShot(1800 if event.get("state") == "done" else 4000, lambda: self._drop_job(jid))
        self.jobsChanged.emit()

    def _drop_job(self, jid: int):
        if self._jobs.pop(jid, None) is not None:
            self.jobsChanged.emit()

    # -- Privacy: the launch lock (utils/applock.py)
    @Property(bool, notify=lockedChanged)
    def locked(self):
        return self._locked

    def _set_unlocked(self):
        if self._locked:
            self._locked = False
            self._private_open = True                # one sign-in opens the private tabs too
            tab, self._pending_tab, self._lock_reason = self._pending_tab, -1, "app"
            self.lockedChanged.emit()
            if not self._needs_setup:
                self.reload()
                self.privateOpened.emit(tab)

    def private_closed(self) -> set:
        """Private folders whose titles are hidden right now."""
        if self._private_open:
            return set()
        try:
            from utils import applock
            return db.private_dirs() if applock.enabled() else set()
        except Exception:
            return set()

    @Property(str, notify=lockedChanged)
    def lockReason(self):
        return self._lock_reason

    @Slot(int)
    def requestPrivate(self, tab_id: int):
        """A private tab was clicked: ask to sign in (the lock screen, with a Cancel)."""
        if self._locked or not self.private_closed():
            return
        self._lock_reason, self._pending_tab, self._locked = "private", tab_id, True
        self.lockedChanged.emit()

    @Slot()
    def cancelLock(self):
        if self._locked and self._lock_reason == "private":
            self._locked, self._lock_reason, self._pending_tab = False, "app", -1
            self.lockedChanged.emit()

    @Slot(result="QVariantMap")
    def lockInfo(self):
        from utils import applock
        return applock.summary()

    @Slot(str)
    def unlockWithPassword(self, password: str):
        self._try_unlock(lambda a: a.check_password(password), "Wrong password")

    @Slot(str)
    def unlockWithKey(self, kind: str):
        """kind: "hello", "key", "phone", or "" for any saved one. Windows shows its own sign-in prompt."""
        self._try_unlock(lambda a: a.verify_key(kind or None, self.hwnd), "Sign-in was cancelled or not recognised")

    def _try_unlock(self, check, failed: str):
        if not self._locked or self._unlocking:
            return
        self._unlocking = True

        def work():
            from utils import applock
            try:
                ok = check(applock)
            except Exception as e:
                log.exception("unlock")
                ok, failed_msg = False, f"Could not sign in: {e}"
            else:
                failed_msg = failed
            self._unlocking = False
            if ok:
                self._unlocked.emit()
            self.unlockResult.emit(ok, "" if ok else failed_msg)
        threading.Thread(target=work, daemon=True, name="unlock").start()

    @Slot()
    def lockNow(self):
        """Settings > Privacy > Lock now: stop playback and show the lock screen."""
        self._lock_now()

    def _lock_now(self, quiet: bool = False):
        """quiet: auto-lock, which does nothing when there is nothing left to lock."""
        from utils import applock
        if not applock.enabled() or self._locked:
            return
        if quiet and db.get_setting("lock_scope", "app") == "private" and not (self._private_open and db.private_dirs()):
            return
        try:
            self.app.engine.stop()
        except Exception:
            log.warning("stop before lock", exc_info=True)
        self._private_open = False
        if db.get_setting("lock_scope", "app") == "private":     # only the private tabs close
            self.reload()
            self.privateOpened.emit(-1)
            self.toast.emit("Private tabs locked")
            return
        self._locked = True
        self.lockedChanged.emit()

    @Slot(str, result=str)
    def setLockPassword(self, password: str) -> str:
        """Returns "" when saved, else what is wrong with it."""
        from utils import applock
        try:
            applock.set_password(password)
        except ValueError as e:
            return str(e)
        self.lockChanged.emit()
        self.toast.emit("Password set: Media Vault asks for it when it starts")
        return ""

    @Slot()
    def clearLockPassword(self):
        from utils import applock
        applock.clear_password()
        self.lockChanged.emit()

    @Slot(str)
    def addLockKey(self, kind: str):
        def work():
            from utils import applock
            try:
                entry = applock.add_key(kind, self.hwnd)
                self.toast.emit(f"{entry['label']} added")
            except Exception as e:
                log.info("adding a sign-in did not complete", exc_info=True)
                self.toast.emit(f"Not added: {e}" if str(e) else "Not added: cancelled")
            self.lockChanged.emit()
        threading.Thread(target=work, daemon=True, name="add-passkey").start()

    @Slot(str)
    def removeLockKey(self, key_id: str):
        from utils import applock
        applock.remove_key(key_id)
        self.lockChanged.emit()

    @Slot()
    def turnOffLock(self):
        from utils import applock
        applock.reset()
        self.lockChanged.emit()
        self.toast.emit("Lock turned off")

    def mark_ready(self):
        if not self._startup_ready:
            self._startup_ready = True
            self.startupReadyChanged.emit()

    @Property(int, notify=updateCountChanged)
    def updateCount(self):
        return self._update_count

    @Slot("QVariantList")
    def _count_updates(self, rows):
        n = sum(1 for r in rows if r.get("status") == "update" and r.get("kind") not in ("bundled", "system"))
        if n != self._update_count:
            self._update_count = n
            self.updateCountChanged.emit()

    @Slot()
    def _quit_for_update(self):
        QTimer.singleShot(700, self.app.quit)

    @Property(bool, notify=needsSetupChanged)
    def needsSetup(self):
        return self._needs_setup

    @needsSetup.setter
    def needsSetup(self, value):
        if value != self._needs_setup:
            self._needs_setup = value
            self.needsSetupChanged.emit()

    @Property("QVariantMap", notify=billboardChanged)
    def billboard(self):
        return self._billboard

    @Property("QVariantMap", notify=insightsChanged)
    def insights(self):
        return self._insights

    @Property("QVariantList", notify=offlineChanged)
    def offlineFolders(self):
        """Names of watched folders that cannot be reached right now (drive unplugged, share not mounted)."""
        return self._offline

    @Property(bool, notify=insightsVisibleChanged)
    def insightsVisible(self):
        return self._insights_visible

    @Property(str, constant=True)
    def deviceInfo(self):
        h = self.app.engine.hw
        return f"{h.backend.upper()} core" + (f" ({h.gpus[0]})" if h.gpus else "")

    @Property(bool, constant=True)
    def rtx(self):
        return self.app.engine.hw.rtx

    # -- refresh
    @Slot()
    def reload(self):
        if self._needs_setup:
            return
        closed = self.private_closed()
        self.library.private_closed = self.tabs.private_closed = closed
        if self._tab in closed:
            self._tab = -1
        self.tabs.reload()
        cards = self.library.reload(None if self._tab < 0 else self._tab)
        self._refresh_billboard(cards)
        self._refresh_continue(cards)
        offline = [d["tab_name"] for d in db.list_directories() if not os.path.isdir(d["folder_path"])]
        if offline != self._offline:
            self._offline = offline
            self.offlineChanged.emit()
        self._refresh_insights()

    @Slot(str, str, str, str, bool)
    def setView(self, query: str, sort: str, genre: str, quality: str, unwatched: bool):
        """Search box and filter bar. Billboard and tabs are not affected."""
        self.library.view = {"query": query[:200], "sort": sort if sort in dict(SORTS) else "title", "genre": genre,
                             "quality": quality if quality in dict(QUALITIES) else "", "unwatched": bool(unwatched)}
        self.library.reload(None if self._tab < 0 else self._tab)

    @Slot(bool)
    def setShelf(self, on: bool):
        self.library.spines = on
        self.library.reload(None if self._tab < 0 else self._tab)

    @Slot(result="QVariantMap")
    def viewOptions(self):
        """Choices for the filter bar: sorts, qualities, and the genres found in the library."""
        genres = sorted({g for info in db.search_index().values() for g in info["genres"]}, key=str.lower)
        return {"sorts": [{"value": v, "label": l} for v, l in SORTS],
                "qualities": [{"value": "", "label": "Any quality"}] + [{"value": v, "label": l} for v, l in QUALITIES],
                "genres": [{"value": "", "label": "All genres"}] + [{"value": g, "label": g} for g in genres]}

    @Slot(int)
    def selectTab(self, tab_id: int):
        if tab_id in self.private_closed():
            return
        self._tab = tab_id
        self._bb_keys = []  # new tab, new random picks
        cards = self.library.reload(None if tab_id < 0 else tab_id, fresh=True)
        self._refresh_billboard(cards)
        self._refresh_continue(cards)

    # -- Continue Watching: what you stopped part-way, newest first (off in Settings, or per tab in its Configure)
    @Property("QVariantList", notify=continueChanged)
    def continueWatching(self):
        return self._continue

    def _refresh_continue(self, cards: list[dict]):
        rows = []
        if db.get_setting("continue_watching", "1") != "0" and self._tab not in set(db.hidden("continue_dirs")):
            files = FolderIndex()
            started = [c for c in cards if not c["is_completed"] and (
                (c["last_position"] or 0) > 10 or (c["watched"] and (c["episodes"] or c.get("films"))))]
            started.sort(key=lambda c: c.get("last_watched") or "", reverse=True)
            pref = self.library.title_pref
            for c in started[:12]:
                poster = scraper.cover_path(art_item(c), files.has)
                dur, pos = c["duration"] or 0, c["last_position"] or 0
                left = duration_label(max(0, dur - pos)) if pos > 10 and dur else ""
                what = db.episode_suffix(c["title"]).strip() if c["episodes"] else ""
                rows.append({"key": c["key"], "title": display_titles(c, pref)[0], "poster": files.url(poster) if files.has(poster) else "",
                             "progress": min(1.0, pos / dur) if dur and pos > 10 else 0.0,
                             "note": " \u00B7 ".join(x for x in (what or ("Next up" if pos <= 10 else ""), f"{left} left" if left else "") if x)})
        if rows != self._continue:
            self._continue = rows
            self.continueChanged.emit()
        self._refresh_recent(cards)

    # -- Recently Added: the newest titles in this tab (off in Settings, or per tab in its Configure)
    @Property("QVariantList", notify=recentChanged)
    def recentlyAdded(self):
        return self._recent

    def _refresh_recent(self, cards: list[dict]):
        rows = []
        if db.get_setting("recently_added", "1") != "0" and self._tab not in set(db.hidden("recent_dirs")):
            files = FolderIndex()
            pref = self.library.title_pref
            now = datetime.now(timezone.utc)
            new = sorted((c for c in cards if c.get("added_at")), key=lambda c: c["added_at"], reverse=True)
            for c in new[:12]:
                age = added_label(c["added_at"], now)
                if not age:                      # older than a month: not "recent" any more
                    break
                poster = scraper.cover_path(art_item(c), files.has)
                rows.append({"key": c["key"], "title": display_titles(c, pref)[0], "progress": 0.0, "note": age,
                             "poster": files.url(poster) if files.has(poster) else ""})
        if rows != self._recent:
            self._recent = rows
            self.recentChanged.emit()

    # -- resume or start over; a random pick
    @Slot(str, result=str)
    def resumeLabel(self, key: str) -> str:
        """"42:10" when this title was stopped part-way and Settings says to ask; "" = just play."""
        if db.get_setting("resume_prompt", "1") == "0":
            return ""
        item = db.get_media(key) if ":" not in key else self._target(key)
        if not item or item["is_completed"] or (item["last_position"] or 0) <= 10:
            return ""
        return clock_label(item["last_position"])

    @Slot(result=str)
    def surprise(self) -> str:
        """A random title from what the grid shows now (tab, filters, search); one you have not finished if there is one."""
        rows = self.library._rows
        pool = [r for r in rows if not r.get("done")] or rows
        return random.choice(pool)["key"] if pool else ""

    # -- auto-lock
    @Slot()
    def windowMinimized(self):
        engine = self.app.engine
        if db.get_setting("lock_on_minimize", "0") == "1" and not getattr(engine, "pip", False) and getattr(engine, "session", None) is None:
            self._lock_now(quiet=True)

    def idle_check(self, idle_seconds: float):
        try:
            minutes = float(db.get_setting("auto_lock_minutes", "0") or 0)
        except ValueError:
            minutes = 0
        if minutes > 0 and idle_seconds >= minutes * 60 and getattr(self.app.engine, "session", None) is None:
            self._lock_now(quiet=True)             # a film playing is not "away"

    # -- rename files on disk to match their titles
    @Slot("QVariantList", result="QVariantList")
    def renamePlan(self, keys):
        from utils import rename
        items = [it for k in keys for u in db.uuids_for(str(k)) if (it := db.get_media(u))]
        return rename.plan(items)

    @Slot("QVariantList")
    def renameApply(self, rows):
        from utils import progress, rename
        rows = [dict(r) for r in rows if not dict(r).get("problem")]
        if not rows:
            return

        def work():
            try:
                with progress.task(f"Renaming {len(rows)} file{'s' if len(rows) != 1 else ''}", total=len(rows)) as t:
                    done, errors = rename.apply(rows, lambda name: t.step(detail=name))
                self.toast.emit(f"Renamed {done} file{'s' if done != 1 else ''}" + (f" \u00B7 {len(errors)} skipped: {errors[0]}" if errors else ""))
            except Exception as e:
                log.exception("rename")
                self.toast.emit(f"Rename stopped: {e}")
            self.libraryChanged.emit()
        threading.Thread(target=work, daemon=True, name="rename").start()

    # -- your own order for the films of a box set
    @Slot(str, str, int)
    def moveFilm(self, set_key: str, uuid: str, to: int):
        if not set_key.startswith("set:"):
            return
        ids = [f["uuid"] for f in db.films_in_set(set_key[4:])]
        if uuid not in ids:
            return
        ids.remove(uuid)
        ids.insert(max(0, min(len(ids), to)), uuid)
        db.set_film_order(set_key[4:], ids)
        self.reload()

    @Slot(str)
    def resetFilmOrder(self, set_key: str):
        if set_key.startswith("set:"):
            db.set_film_order(set_key[4:], [])
            self.reload()

    @Slot(int, result=str)
    def tabName(self, tab_id: int) -> str:
        d = db.get_directory(tab_id) if tab_id >= 0 else None
        return d["tab_name"] if d else "All"

    @Slot(str, str)
    def setMarkFilter(self, kind: str, _unused: str = ""):
        """The Favourites / Watchlist pills: "" shows everything."""
        self.library.mark = kind if kind in db.MARKS else ""
        self.library.reload(None if self._tab < 0 else self._tab)

    # -- things done to one card or to a selection of them (right-click menu, selection bar)
    @Slot("QVariantList", bool)
    def setWatched(self, keys, done: bool):
        db.set_watched([u for k in keys for u in db.uuids_for(str(k))], done)
        self.reload()

    @Slot("QVariantList", str, bool)
    def setMark(self, keys, kind: str, on: bool):
        db.set_mark([str(k) for k in keys], kind, on)
        self.library.reload(None if self._tab < 0 else self._tab)

    @Slot("QVariantList", str, result=str)
    def groupIntoSet(self, keys, name: str) -> str:
        """Selected films into one new box set. Returns its key ("" when fewer than two films were selected)."""
        uids = [str(k) for k in keys if not str(k).startswith(("show:", "set:"))]
        films = [u for u in uids if (db.get_media(u) or {}).get("media_type") == "movie"]
        name = name.strip()
        if len(films) < 2 or not name:
            self.toast.emit("Select two or more films to make a box set")
            return ""
        cid = db.new_set_id()
        db.add_to_set(films, cid, name)
        self.reload()
        return f"set:{cid}"

    @Slot("QVariantList")
    def fetchMissingFor(self, keys):
        """Fetch missing details for the selected titles only."""
        uids = {u for k in keys for u in db.uuids_for(str(k))}
        dirs = {(db.get_media(u) or {}).get("parent_directory_id") for u in uids} - {None}

        def work():
            from watcher import fetch_missing
            n = 0
            for did in dirs:
                d = db.get_directory(did)
                try:
                    n += fetch_missing(d, only=uids) if d else 0
                except Exception as e:
                    log.exception("fetch missing (selection)")
                    self.toast.emit(f"Could not update: {e}")
            self.toast.emit(f"Updated {n} title{'s' if n != 1 else ''}" if n else "Nothing missing in the selection")
            self.libraryChanged.emit()
        threading.Thread(target=work, daemon=True, name="fetch-selection").start()

    # -- Undo: the last removal can be taken back for a few seconds
    def _offer_undo(self, message: str, undo):
        self._undo = undo
        self.undoOffered.emit(message)

    @Slot()
    def undoLast(self):
        undo, self._undo = self._undo, None
        if undo:
            try:
                undo()
            except Exception:
                log.exception("undo")
                self.toast.emit("Could not undo that")
            self.reload()

    # -- a series' episode guide: names, synopses and pictures (TMDB, else TVmaze), fetched once when it is opened
    @Slot(str)
    def fetchEpisodeGuide(self, key: str):
        if not key.startswith("show:") or key in self._guides:
            return
        self._guides.add(key)
        eps = db.episodes_in(key[5:])
        if not eps:
            return

        def work():
            try:
                seasons = {se[0] for se in (scraper.season_episode(e["title"]) for e in eps) if se}
                guide = scraper.episode_guide(db.series_title(eps[0]["title"]), eps[0].get("tmdb_id"), seasons, scraper.api_keys())
                if not guide:
                    return
                have = {se for se in (scraper.season_episode(e["title"]) for e in eps) if se}
                missing = [(s, n, g.get("name")) for (s, n), g in sorted(guide.items()) if s in seasons and (s, n) not in have]
                changed = [(m[0], m[1]) for m in missing] != [(g["season"], g["number"]) for g in db.gaps(key[5:])]
                db.set_gaps(key[5:], missing)
                todo = [e for e in eps if not (e.get("episode_title") and scraper.still_path(e).exists())]
                if (todo and scraper.save_episode_guide(todo, guide)) or changed:
                    self.boxArtChanged.emit(key)
            except Exception:
                log.warning("episode guide for %s", key, exc_info=True)
        threading.Thread(target=work, daemon=True, name="episode-guide").start()

    def start(self):
        self._insights_visible = db.get_setting("show_insights") == "1"
        self.insightsVisibleChanged.emit()
        self.needsSetup = False  # switches Main.qml from the wizard to the dashboard
        self.reload()
        self.mark_ready()        # the cards and the carousel are in: the opening vault can open

    def _refresh_billboard(self, cards: list[dict]):
        deck = billboard_deck(cards, self._bb_keys)
        self._bb_keys = [i["key"] for i in deck["items"]]
        if deck != self._billboard:         # unchanged: the carousel keeps its slide and timer
            self._billboard = deck
            self.billboardChanged.emit()

    def _refresh_insights(self):
        excluded = db.excluded_tags()
        data = db.analytics(excluded, excluded_dirs=set(db.hidden("insights_dirs")) | self.private_closed())
        h, m = divmod(data["total_minutes"], 60)
        insights = {
            "total": f"{h}h {m:02d}m",
            "streak": data["streak"], "bestStreak": data["best_streak"], "finished": data["finished"],
            "weeks": [{"label": d[5:].replace("-", "/"), "minutes": mins} for d, mins in data["weeks"]],
            "topTitles": [{"name": n, "minutes": mins} for n, mins in data["top_titles"]],
            "days": [{"label": d[8:], "minutes": mins} for d, mins in data["days"]],
            "genres": [{"name": n, "minutes": mins, "rating": r or 0} for n, mins, r in data["genres"]],
            "tags": [{"name": t, "hidden": t in excluded} for t in db.user_tags()],
            "folders": [{"id": d["id"], "name": d["tab_name"], "hidden": d["id"] in set(db.hidden("insights_dirs"))}
                        for d in db.list_directories()],
        }
        if insights != self._insights:
            self._insights = insights
            self.insightsChanged.emit()

    @Slot()
    def refreshInsights(self):
        """The Insights window: fresh numbers each time it opens (a film watched since counts)."""
        self._refresh_insights()

    @Slot()
    def toggleInsights(self):
        self._insights_visible = not self._insights_visible
        db.set_setting("show_insights", "1" if self._insights_visible else "0")
        self.insightsVisibleChanged.emit()

    @Slot(str)
    def toggleTag(self, tag: str):
        now = set(db.excluded_tags())
        now.symmetric_difference_update({tag})
        db.set_excluded_tags(now)
        self._refresh_insights()

    # -- playing
    def _target(self, key: str) -> dict | None:
        if key.startswith("show:") or key.startswith("set:"):
            items = db.episodes_in(key[5:]) if key.startswith("show:") else db.films_in_set(key[4:])
            return db.next_up(items) if items else None
        return db.get_media(key)

    def _art_items(self, key: str) -> list[dict]:
        """Items whose box art a change applies to: the box set itself, else every file of the card."""
        if key.startswith("set:"):
            films = db.films_in_set(key[4:])
            return [scraper.collection_item(key[4:], films[0]["collection_name"] if films else "")]
        return [i for i in (db.get_media(u) for u in db.uuids_for(key)) if i]

    @Slot(str)
    def play(self, key: str):
        item = self._target(key)
        if item:
            self.app.play(item["file_path"])

    # -- detail view
    @Slot(str, result="QVariantMap")
    def detail(self, key: str):
        return scraper.untag(self._detail(key))   # scraped text is only ever shown as text

    def _detail(self, key: str):
        item = self._target(key)
        if not item:
            return {}
        eps = db.episodes_in(key[5:]) if key.startswith("show:") else []
        films = db.films_in_set(key[4:]) if key.startswith("set:") else []
        if eps:
            item = {**item, "title": db.series_title(eps[0]["title"])}
        art = item
        if films:
            name = films[0]["collection_name"] or item["title"]
            own = set_synopsis(key[4:], films)
            item = {**item, "title": name, "release_date": films[0]["release_date"],
                    "synopsis": own or " \u00B7 ".join(f'{f["title"]} ({(f["release_date"] or "")[:4]})' if f["release_date"] else f["title"]
                                             for f in films)}
            art = {**scraper.collection_item(key[4:], name), "synopsis": item["synopsis"]}
        tex = dvd_box.box_textures(art)
        facts = [{"label": l, "value": v} for l, v in (
            ("Resolution", item["resolution"]), ("Codec", item["codec"]), ("File type", os.path.splitext(item["file_path"])[1].lower()),
            ("Audio", item["audio_layout"]),
            ("Frame rate", f"{item['frame_rate']:g} fps" if item.get("frame_rate") else ""),
            ("Length", duration_label(item["duration"])), ("Rated", item.get("certification") or "")) if v]
        if films:
            facts = [{"label": "Films", "value": str(len(films))},
                     {"label": "Length", "value": duration_label(sum(f["duration"] or 0 for f in films))}]
        resume = item["last_position"] > 10 and not item["is_completed"]
        shown, disc = display_titles({**item, "key": key}), scraper.disc_art(art)
        # a film in a box set shows (and edits) the set's synopsis
        in_set = set_synopsis(item["collection_id"], db.films_in_set(item["collection_id"])) \
            if not films and not eps and item.get("collection_id") is not None else None
        return {
            "key": key, "isShow": bool(eps), "isSet": bool(films), "kind": "show" if eps or item["media_type"] == "show" else "movie",
            "canMatch": item["media_type"] != "clip", "title": shown[0] if not films else item["title"],
            "subtitle": shown[1] if not films else "",
            "synopsis": (own if films else in_set if in_set is not None else item["synopsis"]) or "",
            # a film in a box set: its own episode name and synopsis (an OVA's "#2" is an episode of a series)
            "inSet": not films and not eps and item.get("collection_id") is not None,
            "episodeTitle": item.get("episode_title") or "",
            # until you write one: the film's own synopsis, when it is not the set's (a film of a TMDB collection)
            "episodeSynopsis": item.get("episode_synopsis") or ((item["synopsis"] or "") if in_set is not None and item["synopsis"] != in_set else ""),
            # every other title, grouped English / Romanized / Native / Other languages (not the ones shown above)
            "altTitles": [] if films else alttitles.for_display(item.get("alt_titles"), shown),
            "banner": file_url(b) if (b := banner_for({**item, "key": key})) else "",
            "year": (item["release_date"] or "")[:4], "facts": facts, "cover": tex["front"], "back": tex["back"],
            "customFront": tex["customFront"], "customBack": tex["customBack"],
            "spine": tex["spine"], "customSpine": tex["customSpine"],
            "disc": file_url(disc) if disc else "",
            "customDisc": scraper.custom_disc_path(art).exists(),
            "rating": db.get_rating(item["uuid"]), "note": db.get_note(item["uuid"]),
            "tags": [{"name": t, "genre": t.startswith("genre:"), "auto": t.startswith("auto:"), "studio": t.startswith("studio:")}
                     for t in db.tags_for(item["uuid"])
                     if not t.startswith("rating:")],
            "playLabel": "Resume" if resume else "Play",
            "resume": resume and not films,
            "resumeAt": duration_clock(item["last_position"]) if resume else "",
            "score": item.get("score") if not films else None,
            # AniList scores in %, not stars (a score you took from TMDB or IMDb for an AniList title stays stars)
            "scoreSource": "" if films else (item.get("score_source") if item.get("score_source") is not None
                                             else "anilist" if item.get("anilist_id") else ""),
            "order": db.detail_order(),
            "slides": self._slides(key, art, films) if films else [],
            "cast": [] if films else self._cast_list(item),
            "gallery": [] if films else [{"url": file_url(p), "name": p.name, "custom": p.name.startswith("c-"), "size": image_size(p)}
                                         for p in scraper.gallery_images(item)],
            "boxSet": ({"key": f"set:{item['collection_id']}", "name": item.get("collection_name") or ""}
                       if not films and not eps and item.get("collection_id") is not None else {}),
            "canSet": not films and item["media_type"] == "movie",
            "episodes": sorted([{"uuid": e["uuid"], "title": e["title"] + (f' \u2014 ({e["release_date"][:4]})' if films and e["release_date"] else "")
                          + (f' \u2014 {e["episode_title"]}' if films and e.get("episode_title") else ""),
                          "done": bool(e["is_completed"]),
                          **(episode_row(e) if eps else {}),
                          "progress": min(1.0, e["last_position"] / e["duration"]) if e["duration"] and not e["is_completed"] else 0}
                         for e in (eps or films)] + (missing_rows(key[5:], eps) if eps else []),
                        key=lambda r: (r.get("season", 0), r.get("number", 0)) if eps else 0),
        }

    # -- fix match: search TMDB by hand, then re-pull details and art for the chosen title
    def _is_anime(self, key: str) -> bool:
        item = self._target(key)
        d = db.get_directory(item["parent_directory_id"]) if item and item.get("parent_directory_id") else None
        return bool(d) and (d.get("source") or "tmdb") == "anilist"

    @Slot(str, str, str)
    def searchMatch(self, key: str, query: str, year: str):
        """Fix Scraped Data: ask every source that can answer (AniList always; TMDB and OMDb with a key) at once.
        The folder's own source comes first; one source failing does not hide the others."""
        kind = "show" if key.startswith("show:") else "movie"
        anime = self._is_anime(key)
        q, y = query.strip(), year.strip()
        keys = scraper.api_keys()

        link = scraper.parse_link(q)

        def from_link():
            """A pasted TMDB / AniList / MyAnimeList / IMDb page: that exact title, as the only result."""
            from utils import anilist
            try:
                if link["source"] in ("mal", "tvmaze", "kitsu"):
                    h = self._fetch_hit(key, link["source"], link["id"])
                    row = {"id": str(link["id"]), "source": link["source"]}
                elif link["source"] == "anilist":
                    aid = int(link["id"])
                    h = anilist.details(aid)
                    row = {"id": str(aid), "source": "anilist"}
                elif link["source"] == "tmdb":
                    if not keys.get("tmdb"):
                        raise scraper.ScrapeError("TMDB links need a TMDB API key (Settings \u203A Integrations & APIs)")
                    h = scraper.tmdb_details(link["kind"], int(link["id"]), keys["tmdb"])
                    row = {"id": f"{'tv' if link['kind'] == 'show' else 'movie'}:{link['id']}", "source": "tmdb"}
                else:
                    if not keys.get("omdb"):
                        raise scraper.ScrapeError("IMDb links need an OMDb API key (Settings \u203A Integrations & APIs)")
                    h = scraper.omdb_details(link["id"], keys["omdb"])
                    row = {"id": link["id"], "source": "omdb"}
                row.update(title=h.get("title") or "", year=(h.get("release_date") or "")[:4],
                           overview=(h.get("synopsis") or "")[:400], thumb=scraper.safe_url(h.get("poster_url")) or "")
                self.matchResults.emit(key, [row])
            except Exception as e:
                self.matchFailed.emit(key, str(e))

        def work():
            from concurrent.futures import ThreadPoolExecutor
            from utils import anilist
            from utils import sources
            jobs = {"anilist": lambda: anilist.search(q), "mal": lambda: sources.mal_search(q),
                    "kitsu": lambda: sources.kitsu_search(q)}
            if kind == "show":                           # TVmaze knows series only
                jobs["tvmaze"] = lambda: sources.tvmaze_search(q)
            if keys.get("tmdb"):
                jobs["tmdb"] = lambda: scraper.tmdb_search(kind, q, y, keys["tmdb"])
            if keys.get("omdb"):
                jobs["omdb"] = lambda: scraper.omdb_search(kind, q, y, keys["omdb"])
            order = (["anilist", "mal", "kitsu", "tmdb", "tvmaze", "omdb"] if anime
                     else ["tmdb", "tvmaze", "omdb", "anilist", "mal", "kitsu"])
            if key.startswith("set:") and keys.get("tmdb"):          # a box set: TMDB's collections first
                jobs["tmdbset"] = lambda: scraper.tmdb_collection_search(q, keys["tmdb"])
                order.insert(0, "tmdbset")
            from concurrent.futures import as_completed
            got, errors = {}, []
            with ThreadPoolExecutor(len(jobs)) as pool:
                futures = {pool.submit(fn): name for name, fn in jobs.items()}
                # results show as each site answers (a slow one does not hold the rest back), in the folder's order
                for f in as_completed(futures):
                    try:
                        got[futures[f]] = f.result()
                    except Exception as e:   # ScrapeError, AniListError, offline
                        errors.append(str(e))
                        continue
                    shown = [r for name in order for r in got.get(name, [])]
                    if shown:
                        self.matchResults.emit(key, shown)
            if not got or not any(got.values()):
                if errors and not got:
                    self.matchFailed.emit(key, "; ".join(errors))
                else:
                    self.matchResults.emit(key, [])
        if q:
            threading.Thread(target=from_link if link else work, daemon=True, name="match-search").start()

    def _fetch_hit(self, key: str, source: str, ident: str) -> dict:
        keys = scraper.api_keys()
        from utils import sources
        if source == "tvmaze":
            return sources.tvmaze_details(int(ident))
        if source == "mal":
            return sources.mal_details(int(ident))
        if source == "kitsu":
            return sources.kitsu_details(ident)
        if source == "fanart":                   # "movie:<TMDB id>" / "show:<TheTVDB id>"
            kind, _, num = ident.partition(":")
            return sources.fanart_details(kind, num, keys.get("fanart", "")) or {}
        if source == "anilist":
            from utils import anilist
            hit = anilist.details(int(ident))
            hit["gallery_urls"] = anilist.gallery_urls(hit)
            return hit
        if source == "omdb":
            return scraper.omdb_details(ident, keys["omdb"])
        # "tv:123" / "movie:123" (a pasted link names its kind, whatever this title was)
        kind, _, num = ident.rpartition(":")
        if kind == "collection":
            return scraper.tmdb_collection_details(int(num), keys["tmdb"])
        show = key.startswith("show:")
        return scraper.tmdb_details({"tv": "show", "movie": "movie"}.get(kind, "show" if show else "movie"), int(num), keys["tmdb"])

    @Slot(str, "QVariantList")
    def matchDetails(self, key: str, picks: list):
        """Fix Scraped Data, step 2: the full details of every result you picked, all at once, so you can choose
        field by field. Emits matchDetailsReady(key, [{pid, source, title, year, fields: {...}}])."""
        picks = [p for p in picks or [] if p.get("source") in MATCH_SOURCES and p.get("id")][:6]

        def work():
            from concurrent.futures import ThreadPoolExecutor
            jobs = {f"{p['source']}|{p['id']}": p for p in picks}
            with ThreadPoolExecutor(max(1, len(jobs))) as pool:
                futures = {pid: pool.submit(self._fetch_hit, key, p["source"], str(p["id"])) for pid, p in jobs.items()}
            hits, out, errors = {}, [], []
            for pid, f in futures.items():
                try:
                    hits[pid] = f.result()
                except Exception as e:
                    errors.append(f"{jobs[pid].get('title') or pid}: {e}")
            # fanart.tv: textless posters, backgrounds and disc art for the picked films (TMDB id) and series (TheTVDB id)
            fan_key = scraper.api_keys().get("fanart", "")
            if fan_key:
                from utils import sources
                wanted = {f"fanart|movie:{h['tmdb_id']}" for h in hits.values() if h.get("tmdb_id") and h.get("kind") == "movie"}
                wanted |= {f"fanart|show:{h['tvdb_id']}" for h in hits.values() if h.get("tvdb_id")}
                for pid in sorted(wanted):
                    kind, _, num = pid.split("|")[1].partition(":")
                    art = sources.fanart_details(kind, num, fan_key)
                    if art:
                        hits[pid] = art
            self._match_hits[key] = hits
            for pid, h in hits.items():
                out.append({"pid": pid, "source": pid.split("|")[0], "title": h.get("title") or "",
                            "year": (h.get("release_date") or "")[:4], "fields": match_preview(h)})
            if out:
                self.matchDetailsReady.emit(key, out)
            else:
                self.matchFailed.emit(key, "; ".join(errors) or "Nothing came back")
        threading.Thread(target=work, daemon=True, name="match-details").start()

    def _apply_set_parts(self, key: str, choices: dict, hits: dict):
        """Fix Scraped Data on a box set's own page: its name, synopsis, poster, banner and disc. Its films are not
        touched."""
        cid = key[4:]
        films = db.films_in_set(cid)
        if not films or not hits:
            self.matchFailed.emit(key, "Search again: the results have expired")
            return
        item = scraper.collection_item(cid, films[0].get("collection_name") or "")

        def pick(field):
            pid = choices.get(field)
            return hits.get(pid) if isinstance(pid, str) else None
        try:
            if (h := pick("title")) and h.get("title"):
                db.rename_collection(cid, h["title"])
            if (h := pick("synopsis")):
                db.set_collection_synopsis(cid, h.get("synopsis") or "")
            for field, face, url_key, path, box in (("poster", "front", "poster_url", scraper.poster_path, scraper.POSTER_BOX),
                                                    ("disc", "disc", "disc_url", scraper.disc_path, (500, 500))):
                if (f := _upload_path(choices.get(field))):
                    save_box_art(Image.open(f), [item], face)
                elif (h := pick(field)) and h.get(url_key):
                    scraper.save_webp(scraper.fetch_image(h[url_key]), path(item), box=box)
            if (f := _upload_path(choices.get("banner"))):
                scraper.save_webp(ImageOps.exif_transpose(Image.open(f)), scraper.banner_path(item), box=scraper.BANNER_BOX)
            elif (h := pick("banner")):
                scraper.save_banner(item, h.get("banner_url"), force=True)
        except Exception as e:
            log.exception("fix box set")
            self.matchFailed.emit(key, f"Could not apply: {e}")
            return
        self.toast.emit("Box set updated")
        self.libraryChanged.emit()
        self.boxArtChanged.emit(key)
        self.matchApplied.emit(key, key)

    @Slot(str, str)
    def pickMatchFiles(self, key: str, field: str):
        """Fix Scraped Data > "Upload file": choose your own picture for a field (several for the Gallery).
        Emits matchFilesPicked(key, field, [{url, choice}]); choice is what applyMatchParts takes for it."""
        if field not in UPLOAD_FIELDS:
            return

        def run():
            from . import pick_image, pick_images
            start = self._media_folder(key)
            paths = pick_images(start) if field == "gallery" else [p for p in [pick_image(start, f"Choose a {field}")] if p]
            ok = [p for p in paths if _upload_path("file:" + p)]
            if ok:
                self.matchFilesPicked.emit(key, field, [{"url": file_url(p, bust=False), "choice": "file:" + p} for p in ok])
        QTimer.singleShot(0, run)

    @Slot(str, "QVariantMap", str)
    def applyMatchParts(self, key: str, choices: dict, primary: str):
        """Fix Scraped Data, step 3: choices = {field: pid or "" (keep yours), "gallery": [pid, ...]}; primary: the
        result the title is linked to from now on (its TMDB / AniList id, so Fetch missing asks the right title)."""
        threading.Thread(target=self._apply_parts, args=(key, dict(choices or {}), primary), daemon=True,
                         name="match-apply").start()

    def _apply_parts(self, key: str, choices: dict, primary: str):
        from utils import anilist, progress
        hits = self._match_hits.get(key) or {}
        if key.startswith("set:"):
            return self._apply_set_parts(key, choices, hits)
        show = key.startswith("show:")
        items = [i for i in (db.get_media(u) for u in db.uuids_for(key)) if i]
        if not items or not hits:
            self.matchFailed.emit(key, "Search again: the results have expired")
            return
        uids = [i["uuid"] for i in items]
        main = hits.get(primary) or next(iter(hits.values()))

        def pick(field):
            pid = choices.get(field)
            return hits.get(pid) if isinstance(pid, str) else None

        def upload(field):          # a file you chose with "Upload file" for this field
            return _upload_path(choices.get(field)) if field in UPLOAD_FIELDS else None
        steps = [f for f in MATCH_FIELDS if pick(f) or upload(f)] + (["gallery"] if choices.get("gallery") or "galleryKeep" in choices else [])
        with progress.task(f"Applying scraped data \u00B7 {main.get('title') or ''}", total=len(steps) + 1) as t:
            # which title this is linked to: its ids, so later lookups (Fetch missing) ask about the right one
            tmdb_id = next((h.get("tmdb_id") for h in [main, *hits.values()] if h.get("tmdb_id")), None)
            anilist_id = main.get("anilist_id")
            with db._tx() as c:
                c.executemany("UPDATE media_items SET tmdb_id=?, anilist_id=? WHERE uuid=?", [(tmdb_id, anilist_id, u) for u in uids])
            db.clear_failed([db.file_hash(i["file_path"]) for i in items])
            t.step(detail="Linked")
            if (h := pick("title")):
                t.step(detail="Title")
                if show:
                    db.rename_series(key[5:], h["title"])
                else:
                    for u in uids:
                        db.update_media(u, title=h["title"])
            if (h := pick("year")):
                t.step(detail="Year")
                with db._tx() as c:
                    c.executemany("UPDATE media_items SET release_date=? WHERE uuid=?", [(h.get("release_date"), u) for u in uids])
            if (h := pick("synopsis")):
                t.step(detail="Synopsis")
                db.set_synopsis_many(uids, h.get("synopsis") or "")
            if (h := pick("genres")):
                t.step(detail="Genres")
                db.set_tag_group(uids, "genre:", h.get("genres") or [])
                db.set_tag_group(uids, "studio:", h.get("studios") or [])
            if (h := pick("score")):
                t.step(detail="Score")
                db.set_score(uids, h.get("score"))
                db.set_score_source(uids, "anilist" if h.get("anilist_id") else "kitsu" if h.get("kitsu_id") else "")
            if (h := pick("rating")):
                t.step(detail="Age rating")
                with db._tx() as c:
                    c.executemany("UPDATE media_items SET certification=? WHERE uuid=?", [(h.get("certification"), u) for u in uids])
            if (h := pick("titles")):
                t.step(detail="Other titles")
                with db._tx() as c:
                    c.executemany("UPDATE media_items SET original_title=?, romaji_title=?, alt_titles=? WHERE uuid=?",
                                  [(h.get("original_title"), h.get("romaji_title"), h.get("alt_titles"), u) for u in uids])
            if (h := pick("cast")):
                t.step(detail="Cast")
                db.set_cast(db.cast_owner(items[0]), h.get("cast") or [])
                scraper.save_person_photos(h.get("cast") or [])
            if (h := pick("boxset")) and not show:
                t.step(detail="Box set")
                own = items[0].get("collection_id") is not None and items[0]["collection_id"] < 0   # a set you made stays
                if not own:
                    with db._tx() as c:
                        c.executemany("UPDATE media_items SET collection_id=?, collection_name=? WHERE uuid=?",
                                      [(h.get("collection_id"), h.get("collection_name"), u) for u in uids])
                    if h.get("collection_id") and h.get("collection_poster_url"):
                        scraper.save_collection_poster(h["collection_id"], h["collection_poster_url"])
            if (f := upload("poster")):
                t.step(detail="Poster (your file)")
                save_box_art(Image.open(f), items, "front")              # yours: it shows over any scraped poster
            elif (h := pick("poster")):
                t.step(detail="Poster")
                try:
                    img = scraper.fetch_image(h["poster_url"])
                    for i in items:          # your own front cover (if any) still shows over it, as the window says
                        scraper.save_webp(img, scraper.poster_path(i))
                except Exception:
                    log.warning("fix match poster failed", exc_info=True)
            if (f := upload("disc")):
                t.step(detail="Disc (your file)")
                save_box_art(Image.open(f), items, "disc")
            elif (h := pick("disc")):
                t.step(detail="Disc")
                try:
                    img = scraper.fetch_image(h["disc_url"])
                    for i in items:
                        scraper.save_webp(img, scraper.disc_path(i), box=(500, 500))
                except Exception:
                    log.warning("fix match disc failed", exc_info=True)
            if (f := upload("banner")):
                t.step(detail="Banner (your file)")
                scraper.save_webp(ImageOps.exif_transpose(Image.open(f)), scraper.banner_path(items[0]), box=scraper.BANNER_BOX)
            elif (h := pick("banner")):
                t.step(detail="Banner")
                scraper.save_banner(items[0], h.get("banner_url"), force=True)
            # the Gallery, image by image: the current ones you kept, and each image you chose from any result
            picked = choices.get("gallery") or []
            offered = {u for h in hits.values() for u in h.get("gallery_urls") or []}
            urls = list(dict.fromkeys(u for u in picked if u in offered))          # only images a result offered
            files = [f for f in (_upload_path(p) for p in picked) if f]
            keep = choices.get("galleryKeep")
            if urls or files or keep is not None:
                t.step(detail="Gallery")
                d = scraper.gallery_dir(items[0])
                if keep is not None and d.is_dir():                  # the current images you left out go
                    for p in scraper.gallery_images(items[0]):
                        if p.name not in set(keep):
                            p.unlink(missing_ok=True)
                if urls:
                    scraper.add_gallery(items[0], urls)
                stamp = int(time.time() * 1000)
                for n, f in enumerate(files):            # your files: kept as yours, through any later scrape
                    try:
                        scraper.save_webp(ImageOps.exif_transpose(Image.open(f)), d / f"c-{stamp}-{n:02d}.webp", box=scraper.GALLERY_BOX)
                    except Exception:
                        log.warning("gallery upload %s", f, exc_info=True)
        new_key = key
        if show and pick("title") is main and anilist.is_adult_ova(main):   # an adult OVA: its episodes become a box set
            import watcher
            if watcher._ova_to_set([db.get_media(u) for u in uids], main, key):
                new_key = f"set:{anilist.ova_set_id(main)}"
        self.toast.emit(f"Updated from {', '.join(sorted({p.split('|')[0].replace('omdb', 'IMDb').replace('tmdb', 'TMDB').replace('anilist', 'AniList') for p in hits}))}")
        try:     # the new age rating and titles can change computed tags
            from utils import tagrules
            d = db.get_directory(items[0]["parent_directory_id"])
            if d:
                tagrules.retag_all([d])
        except Exception:
            log.warning("retag after fix match", exc_info=True)
        self.libraryChanged.emit()
        self.boxArtChanged.emit(key)
        self.matchApplied.emit(key, new_key)

    @staticmethod
    def _cast_list(item) -> list[dict]:
        out = []
        for p in db.get_cast(db.cast_owner(item)):
            photo = scraper.person_photo_path(p["person_id"]) if p["person_id"] else None
            out.append({"name": p["name"], "role": p["role"], "photo": file_url(photo) if photo and photo.exists() else ""})
        return out

    # -- box sets you edit: add a film to a set (or a new one), take it out, or ungroup a whole set
    @Slot(result="QVariantList")
    def boxSets(self):
        return [{"key": f"set:{b['id']}", "id": b["id"], "name": b["name"] or "Untitled", "films": b["films"]} for b in db.box_sets()]

    @Slot(str, int, str, result=str)
    def addToSet(self, key: str, cid: int, name: str) -> str:
        """cid 0 = a new set called `name`. Returns the set's key."""
        if key.startswith(("show:", "set:")):
            return ""
        if cid == 0:
            name = name.strip()
            if not name:
                return ""
            cid = db.new_set_id()
        else:
            name = next((b["name"] for b in db.box_sets() if b["id"] == cid), name)
        db.add_to_set([key], cid, name)
        self.toast.emit(f"Added to {name}")
        self.libraryChanged.emit()
        return f"set:{cid}"

    @Slot(str)
    def removeFromSet(self, uuid: str):
        was = db.get_media(uuid) or {}
        db.remove_from_set([uuid])
        self.libraryChanged.emit()
        if was.get("collection_id") is not None:
            self._offer_undo(f"Removed from {was.get('collection_name') or 'the box set'}",
                             lambda: db.add_to_set([uuid], was["collection_id"], was.get("collection_name") or ""))

    @Slot(str)
    def ungroupSet(self, key: str):
        if key.startswith("set:"):
            films = db.films_in_set(key[4:])
            db.remove_from_set([f["uuid"] for f in films])
            self.libraryChanged.emit()
            if films:
                name = films[0].get("collection_name") or ""
                self._offer_undo(f"Ungrouped {name or 'the box set'}",
                                 lambda: db.add_to_set([f["uuid"] for f in films], int(key[4:]), name))

    @staticmethod
    def _slide(key, item, label, uuid=""):
        tex = dvd_box.box_textures(item)
        disc = scraper.disc_art(item)
        return {"key": key, "uuid": uuid, "label": label, "title": display_titles({**item, "key": key})[0] if uuid else item["title"],
                "year": (item.get("release_date") or "")[:4], "cover": tex["front"], "back": tex["back"],
                "spine": tex["spine"], "disc": file_url(disc) if disc else "",
                "customFront": tex["customFront"], "customBack": tex["customBack"], "customSpine": tex["customSpine"],
                "customDisc": scraper.custom_disc_path(item).exists()}

    def _slides(self, key, art, films) -> list[dict]:
        """Box set carousel in View More: the set's own box first (it is what flew out of the card), then each film."""
        n = len(films)
        return [self._slide(key, {**art, "release_date": films[0]["release_date"]}, "Box set")] + [
            self._slide(f["uuid"], f, f"Film {i + 1} of {n}", f["uuid"]) for i, f in enumerate(films)]

    # -- Tag Manager (its own window): every tag, bulk tagging, and your rules
    @Slot(result="QVariantList")
    def tagSummary(self):
        out = []
        for t in db.tag_counts():
            name = t["name"]
            kind = "genre" if name.startswith("genre:") else "auto" if name.startswith("auto:") \
                else "studio" if name.startswith("studio:") else "user"
            out.append({"name": name, "label": name.split(":", 1)[1] if kind != "user" else name, "kind": kind, "count": t["n"]})
        return out

    @Slot(str, str, result="QVariantList")
    def taggingTitles(self, query: str, tag: str):
        """Titles for bulk tagging: one row per film, series or clip (box sets are split into their films)."""
        index = db.search_index()
        cards = db.list_library(None, sets=False)
        if query.strip():
            cards = library_view(cards, index, query=query)
        out = []
        for c in cards:
            uids = db.uuids_for(c["key"])
            tags = sorted({t for u in uids[:1] for t in db.tags_for(u) if not t.startswith("rating:")}, key=str.casefold)
            if tag and tag not in tags:
                continue
            title, subtitle = display_titles(c)
            poster = scraper.cover_path(c)
            out.append({"key": c["key"], "title": title, "subtitle": subtitle, "year": (c.get("release_date") or "")[:4],
                        "kind": c["media_type"], "poster": file_url(poster) if poster.exists() else "",
                        "tags": [t.split(":", 1)[1] if t.startswith(("auto:", "genre:", "studio:")) else t for t in tags]})
            if len(out) >= 2000:
                break
        return out

    @Slot("QVariantList", str, bool)
    def bulkTag(self, keys, tag: str, add: bool):
        tag = tag.strip()
        if not tag or tag.startswith(("auto:", "rating:")):
            return
        uids = [u for k in keys for u in db.uuids_for(str(k))]
        if add:
            db.add_tag_many(uids, tag)
        else:
            db.remove_tag_many(uids, tag)
        self.toast.emit(f"{'Tagged' if add else 'Untagged'} {len(keys)} title{'s' if len(keys) != 1 else ''}: {tag}")
        self._refresh_insights()
        self.libraryChanged.emit()

    @Slot(str, str)
    def renameTag(self, old: str, new: str):
        if old.startswith(("auto:", "rating:", "studio:")) or new.strip().startswith(("auto:", "rating:", "studio:")):
            return
        db.rename_tag(old, new)
        self.libraryChanged.emit()

    @Slot(str)
    def deleteTag(self, name: str):
        if name.startswith(("auto:", "studio:")):     # computed, and studios from AniList, stay
            return        # computed: change the rule or the names instead
        db.delete_tag(name)
        self._refresh_insights()
        self.libraryChanged.emit()

    @Slot(result="QVariantMap")
    def tagRules(self):
        from utils import tagrules
        return {"rules": tagrules.load(),
                "fields": [{"value": f, "label": l, "kind": k} for f, l, k in tagrules.FIELDS],
                "tests": [{"value": t, "label": l, "kinds": k} for t, l, k in tagrules.TESTS],
                "folders": [{"id": d["id"], "name": d["tab_name"]} for d in db.list_directories()],
                "names": db.get_setting("auto_tags", "1") != "0"}

    @Slot("QVariantList", result="QVariantList")
    def saveTagRules(self, rules):
        from utils import tagrules
        return tagrules.save([dict(r) for r in rules])

    @Slot("QVariantMap", result=int)
    def previewTagRule(self, rule):
        from utils import tagrules
        return tagrules.preview(dict(rule))

    @Slot()
    def applyTagRules(self):
        """Work out every computed tag again (names, age ratings, rules), on a worker thread."""
        def work():
            from utils import tagrules
            try:
                n = tagrules.retag_all()
                self.toast.emit(f"Tags worked out again: {n} title{'s' if n != 1 else ''} have computed tags")
            except Exception as e:
                log.exception("apply rules")
                self.toast.emit(f"Could not apply the rules: {e}")
            self._refresh_insights()
            self.libraryChanged.emit()
        self.toast.emit("Applying tag rules\u2026")
        threading.Thread(target=work, daemon=True, name="tag-rules").start()

    @Slot(str, bool)
    def playFrom(self, key: str, from_start: bool):
        """Play a card, an episode or a film (uuid); from_start ignores where you stopped last time."""
        item = self._target(key)
        if item:
            self.app.play(item["file_path"], from_start)

    @Slot(result="QVariantList")
    def detailSections(self):
        names = dict(db.DETAIL_SECTIONS)
        return [{"id": k, "label": names[k]} for k in db.detail_order()]

    @Slot(str)
    def playEpisode(self, uuid: str):
        item = db.get_media(uuid)
        if item:
            self.app.play(item["file_path"])

    @Slot(str, str)
    def setTitle(self, key: str, text: str):
        text = text.strip()
        if not text:
            return
        # with Titles set to Romaji or Original, the title you see (and edit) is that one
        pref = db.get_setting("title_language", "english") or "english"
        item = None if key.startswith("set:") else self._target(key)
        column = {"romaji": "romaji_title", "original": "original_title"}.get(pref)
        if column and item and item.get(column):
            with db._tx() as c:
                c.executemany(f"UPDATE media_items SET {column}=? WHERE uuid=?", [(text, u) for u in db.uuids_for(key)])
        elif key.startswith("show:"):
            db.rename_series(key[5:], text)
        elif key.startswith("set:"):
            db.rename_collection(key[4:], text)
        else:
            db.update_media(key, title=text)

    @Slot(str, str)
    def setSynopsis(self, key: str, text: str):
        if key.startswith("set:"):          # the box set's own page: not its films'
            db.set_collection_synopsis(key[4:], text)
            return
        db.set_synopsis_many(db.uuids_for(key), text)

    @Slot(str, str)
    def setEpisodeTitle(self, key: str, text: str):
        if not key.startswith(("show:", "set:")):
            db.set_episode(key, title=text.strip())

    @Slot(str, str)
    def setEpisodeSynopsis(self, key: str, text: str):
        if not key.startswith(("show:", "set:")):
            db.set_episode(key, synopsis=text)

    @Slot(str, str)
    def addTag(self, key: str, name: str):
        for u in db.uuids_for(key):
            db.add_tag(u, name)
        self._refresh_insights()

    @Slot(str, str)
    def removeTag(self, key: str, name: str):
        uids = db.uuids_for(key)
        db.remove_tag_many(uids, name)
        self._refresh_insights()
        shown = name.split(":", 1)[1] if name.startswith("auto:") else name
        self._offer_undo(f"Removed the tag {shown}", lambda: (db.add_tag_many(uids, name), self.boxArtChanged.emit(key)))

    @Slot(str, int)
    def setRating(self, key: str, stars: int):
        db.set_rating_many(db.uuids_for(key), stars)

    @Slot(str, str)
    def setNote(self, key: str, text: str):
        item = self._target(key)
        if item:
            db.set_note(item["uuid"], text)

    # -- thumbnail picker: 4 frames, in RAM only
    @Slot(str)
    def chooseThumbnail(self, key: str):
        item = self._target(key)
        if not item:
            return

        def work():
            try:
                frames = media_probe.grab_frames(item["file_path"], item["duration"] or 0)
            except Exception:
                log.exception("frame grab failed")
                frames = []
            self._thumbnailsDone.emit(key, frames)
        threading.Thread(target=work, daemon=True, name="frame-grab").start()

    def _store_thumbnails(self, key, frames):
        self._thumbs = list(frames)
        self.frames.clear()
        for i, f in enumerate(self._thumbs):
            self.frames.set_pil(f"thumb{i}", f)
        self.thumbnailsReady.emit(len(self._thumbs))

    @Slot(str, int)
    def useThumbnail(self, key: str, index: int):
        item = self._target(key)
        try:
            if item and 0 <= index < len(self._thumbs):
                img = self._thumbs[index]
                w, h = img.size
                tw = int(h * 2 / 3)
                left = (w - tw) // 2
                # kept as your own front cover, so re-downloading scraped covers never replaces it
                save_box_art(img.crop((left, 0, left + tw, h)), [item], "front")
                self.toast.emit("Box art updated")
        except Exception:
            log.exception("saving thumbnail failed")
            self.toast.emit("Could not save the thumbnail")
        finally:
            self.discardThumbnails()
        self.reload()

    @Slot()
    def discardThumbnails(self):
        self._thumbs = []  # the unused frames are dropped from memory here
        self.frames.clear()

    # -- custom DVD box art (for titles the scraper found nothing for, or art you prefer)
    def _media_folder(self, key: str) -> str:
        """Where a title's file is: the file picker for its art starts there."""
        item = self._target(key)
        return os.path.dirname(item["file_path"]) if item and item.get("file_path") else ""

    @Slot(str, str)
    def pickBoxArt(self, key: str, face: str):
        """face = front / back / spine / disc. A file dialog (starting in the title's own folder), then View More's
        crop editor (artPicked) to frame, zoom and turn it; saveCroppedArt writes it."""
        if face not in CUSTOM_ART and face != "wrap":
            return

        def run():
            path = pick_image(self._media_folder(key), "Choose a whole cover scan (back, spine and front)" if face == "wrap"
                              else f"Choose {face} art")
            if not path:
                return
            if face == "wrap" and self._apply_wrap(key, path, True):   # Front always opens the crop editor
                return
            # not a whole sleeve: the crop editor opens on it as the front
            self.artPicked.emit(key, "front" if face == "wrap" else face, file_url(path, bust=False), path)
        QTimer.singleShot(0, run)  # same reason as pickFolder: no modal dialog from inside a QML handler

    def _apply_wrap(self, key: str, path: str, asked: bool) -> bool:
        """A whole sleeve scan (back | spine | front): cut it into the three faces. Returns False when it is not
        one (then the crop editor opens on it, as the front)."""
        from utils import boxwrap
        try:
            img = Image.open(path)
            if not boxwrap.is_wrap(img):
                if asked:
                    self.toast.emit("That image is not a whole cover (it should be about 1.5 times wider than tall). Opening it as the front.")
                return False
            items = self._art_items(key)
            for face, part in boxwrap.split(img).items():
                save_box_art(part, items, face)
            self.toast.emit("Cover split into front, spine and back")
        except Exception as e:
            log.exception("cover wrap")
            self.toast.emit(f"Could not use that image: {e}")
        self.boxArtChanged.emit(key)
        return True

    @Slot(str, str, str, float, float, float, float, int)
    def saveCroppedArt(self, key: str, face: str, path: str, x: float, y: float, w: float, h: float, turns: int):
        """The crop editor's result: (x, y, w, h) as fractions of the image as it is shown (after EXIF rotation),
        then a quarter-turn count. Saved at the face's size for every file of the card (or the box set)."""
        if face not in CUSTOM_ART:
            return
        try:
            img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            W, H = img.size
            box = (max(0, int(x * W)), max(0, int(y * H)), min(W, int((x + w) * W)), min(H, int((y + h) * H)))
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                raise ValueError("the crop is too small")
            img = img.crop(box)
            if turns % 4:
                img = img.rotate(-90 * (turns % 4), expand=True)
            save_box_art(img, self._art_items(key), face)
            self.toast.emit(f"{face.capitalize()} art updated")
        except Exception as e:
            log.exception("box art")
            self.toast.emit(f"Could not use that image: {e}")
        self.boxArtChanged.emit(key)

    # -- Gallery: wide images for View More and the recommended carousel (scraped, or your own)
    @Slot(str)
    def addGalleryImages(self, key: str):
        def run():
            from . import pick_images
            paths = pick_images(self._media_folder(key))
            item = self._target(key)
            if not (paths and item):
                return
            d = scraper.gallery_dir(item)
            n = 0
            for p in paths:
                try:
                    scraper.save_webp(Image.open(p), d / f"c-{int(time.time() * 1000)}-{n}.webp", box=scraper.GALLERY_BOX)
                    n += 1
                except Exception:
                    log.warning("gallery image %s", p, exc_info=True)
            self.toast.emit(f"Added {n} image{'s' if n != 1 else ''} to the Gallery")
            self.boxArtChanged.emit(key)
        QTimer.singleShot(0, run)

    @Slot(str, str, bool)
    def importGalleryImages(self, key: str, link: str, replace: bool):
        """Gallery > Import from a link (TMDB episode / season / title images, MyAnimeList, or one image). They are
        kept as your own, so a later scrape does not swap them out; replace: drop the scraped ones first. A TMDB
        episode link also fills in the film's episode name and synopsis (when you have not written them)."""
        item = self._target(key)
        if not item or key.startswith("set:"):       # a box set's page has no Gallery of its own
            return
        tmdb = scraper.api_keys().get("tmdb") or ""

        def work():
            try:
                got = scraper.gallery_link(link, tmdb)
            except Exception as e:      # ScrapeError, offline, a 404
                self.toast.emit(f"Could not import: {e}")
                return
            if not got["urls"]:
                self.toast.emit("That page has no images to import")
                return
            from utils import progress
            d = scraper.gallery_dir(item)
            n, stamp = 0, int(time.time() * 1000)
            with progress.task("Importing Gallery images", total=len(got["urls"])) as t:
                for i, url in enumerate(got["urls"]):
                    try:
                        scraper.save_webp(scraper.fetch_image(url), d / f"c-{stamp}-{i:02d}.webp", box=scraper.GALLERY_BOX)
                        n += 1
                    except Exception:
                        log.warning("gallery import %s", url, exc_info=True)
                    t.step(detail=f"{n} saved")
            if n and replace:
                for p in d.glob("s-*.webp"):
                    p.unlink(missing_ok=True)
            ep = got.get("episode")
            if ep and item.get("media_type") == "movie":
                db.set_episode(item["uuid"], title=ep["name"] or None, synopsis=ep["overview"] or None, only_empty=True)
            self.toast.emit(f"Imported {n} image{'s' if n != 1 else ''} into the Gallery" if n else "None of those images could be downloaded")
            self.boxArtChanged.emit(key)
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, str, bool)
    def setBannerFromGallery(self, key: str, name: str, for_set: bool):
        """View More > Gallery > an image > "Set as banner": that image becomes the title's banner (for_set: the banner
        of the box set the film is in). It replaces the scraped one; a later scrape does not overwrite it."""
        item = self._target(key)
        if not item or not re.fullmatch(r"[cs]-[\w.-]+\.webp", name):
            return
        src = scraper.gallery_dir(item) / name
        if not src.is_file():
            return
        if for_set:
            if item.get("collection_id") is None:
                return
            owner, changed = scraper.collection_item(item["collection_id"], item.get("collection_name") or ""), f"set:{item['collection_id']}"
        else:
            owner, changed = item, key
        dest = scraper.banner_path(owner)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        except OSError as e:
            self.toast.emit(f"Could not set the banner: {e}")
            return
        self.toast.emit("Box set banner changed" if for_set else "Banner changed")
        self.boxArtChanged.emit(key)
        if changed != key:
            self.boxArtChanged.emit(changed)
        self.billboardChanged.emit()

    @Slot(str, str)
    def removeGalleryImage(self, key: str, name: str):
        item = self._target(key)
        if item and re.fullmatch(r"[cs]-[\w.-]+\.webp", name):
            src = scraper.gallery_dir(item) / name
            if not src.is_file():
                return
            # set aside, not deleted, until the next removal or the end of the session: Undo puts it back
            aside = db.data_dir() / "cache" / "undo.webp"
            aside.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(aside))
            self.boxArtChanged.emit(key)
            self._offer_undo("Removed the image", lambda: (shutil.move(str(aside), str(src)), self.boxArtChanged.emit(key)))

    @Slot(str, str)
    def resetBoxArt(self, key: str, face: str):
        if face not in CUSTOM_ART:
            return
        for item in self._art_items(key):
            CUSTOM_ART[face](item).unlink(missing_ok=True)
        self.boxArtChanged.emit(key)

    # -- settings, folders, backups, updates, file types
    @Slot(str, result=str)
    def setting(self, key: str) -> str:
        return db.get_setting(key, "") if key in SETTINGS else ""

    @Slot(str, str)
    def setSetting(self, key: str, value: str):
        if key not in SETTINGS:
            return
        if key.startswith("custom_") and value and not re.match(r"^#[0-9A-Fa-f]{6}$", value):   # "" = back to default
            return
        db.set_setting(key, value.strip() if key.endswith("_key") else value)
        engine = self.app.engine
        if key == "night_mode":
            engine.night = value == "1"
        elif key == "upscale_level":   # "auto" or "1".."3"
            engine.level = int(hw_accelerator.resolve(value, engine.hw.level))
        elif key == "core":            # "auto", "mpv" or "vlc"
            engine.core_pref = value
        elif key == "auto_credits":
            engine.auto_credits = value != "0"
        elif key == "gpu_high_performance":
            from utils import gpu_pref
            try:
                if gpu_pref.apply(value != "0") == "yours":
                    self.toast.emit("You chose a GPU for Media Vault in Windows' Graphics settings: change it there")
            except OSError:
                log.warning("GPU preference", exc_info=True)
        elif key in ("group_collections", "title_language"):
            self.reload()
        elif key.startswith("discord") and self.app.presence:
            self._discord_changed()
        elif key == "theme":
            self.app.set_theme(value)
        elif key.startswith("custom_"):   # picking a colour switches to the Custom theme
            self.app.set_theme("custom")

    @Slot(result="QVariantList")
    def directories(self):
        return [{"id": d["id"], "name": d["tab_name"], "path": d["folder_path"], "scrape": bool(d["should_scrape"]),
                 "parts": sorted(db.scrape_opts({**d, "should_scrape": 1})),
                 "anime": (d.get("source") or "tmdb") == "anilist",
                 "inAll": d["id"] not in set(db.hidden("all_dirs")),
                 "inInsights": d["id"] not in set(db.hidden("insights_dirs")),
                 "continueRow": d["id"] not in set(db.hidden("continue_dirs")),
                 "recentRow": d["id"] not in set(db.hidden("recent_dirs")),
                 "private": d["id"] in db.private_dirs()} for d in db.list_directories()]

    @Slot(result="QVariantList")
    def scrapeParts(self):
        return [{"id": k, "label": l} for k, l in db.SCRAPE_PARTS]

    @Slot(str, str, bool, str, bool)
    def addFolder(self, path: str, tab: str, scrape: bool, parts: str, anime: bool):
        """After the folder picker: the options sheet in QML sends the tab name, what to scrape, and whether it is anime."""
        try:
            self.app.add_directory(path, tab.strip() or None, scrape, [p for p in parts.split(",") if p],
                                   "anilist" if anime else "tmdb")
            self.toast.emit("Folder added. Scanning in the background.")
        except Exception as e:
            log.exception("add folder")
            self.toast.emit(f"Could not add folder: {e}")

    # -- keep folders / tags out of the All tab, or folders out of Insights
    @Slot(str, result="QVariantList")
    def hiddenFrom(self, kind: str):
        return db.hidden(kind) if kind in HIDDEN_KINDS else []

    @Slot(str, str)
    def toggleHidden(self, kind: str, value: str):
        if kind not in HIDDEN_KINDS:
            return
        if kind == "private_dirs":
            from utils import applock
            if not applock.enabled():
                self.toast.emit("Set a password or another sign-in first (Settings \u203A Privacy)")
                return
        v = int(value) if kind.endswith("dirs") else value
        now = set(db.hidden(kind))
        now.symmetric_difference_update({v})
        db.set_hidden(kind, now)
        if kind == "insights_dirs":
            self._refresh_insights()
        else:
            self.reload()

    @Slot(result="QVariantList")
    def tagNames(self):
        """Every tag in the library, for suggestions while typing: yours first, then genres, studios and the automatic
        ones, each most used first. name: what is added; label: what is shown and matched; kind: shown beside it.
        A genre or studio is added as that genre or studio; an automatic tag ("Rated PG") as your own tag of that name."""
        order = {"": 0, "genre:": 1, "studio:": 2, "auto:": 3}
        kinds = {"": "", "genre:": "Genre", "studio:": "Studio", "auto:": "Automatic"}
        out, seen = [], set()
        tags = sorted(db.tag_counts(), key=lambda t: next((order[p] for p in ("genre:", "studio:", "auto:") if t["name"].startswith(p)), 0))
        for t in tags:                       # yours first, so a name you typed wins over the same automatic one
            name = t["name"]
            prefix = next((p for p in ("genre:", "studio:", "auto:") if name.startswith(p)), "")
            label = name[len(prefix):]
            add = label if prefix == "auto:" else name
            if not label or add.casefold() in seen:
                continue
            seen.add(add.casefold())
            out.append({"name": add, "label": label, "kind": kinds[prefix], "rank": order[prefix], "n": t["n"]})
        out.sort(key=lambda r: (r["rank"], -r["n"], r["label"].casefold()))
        return [{k: r[k] for k in ("name", "label", "kind")} for r in out]

    @Slot(result="QVariantList")
    def allTags(self):
        """Your tags and the genres, for choosing what the All tab leaves out."""
        genres = sorted({g for info in db.search_index().values() for g in info["genres"]})
        return [{"name": t, "label": t[5:] if t.startswith("auto:") else t} for t in db.user_tags()] + \
               [{"name": "genre:" + g, "label": g} for g in genres] + \
               [{"name": t["name"], "label": "Studio: " + t["name"][7:]} for t in db.tag_counts() if t["name"].startswith("studio:")]

    @Slot(int, int)
    def moveTab(self, dir_id: int, to: int):
        """A folder tab dragged to position `to` among the folder tabs (All always stays first)."""
        ids = [d["id"] for d in db.list_directories() if d["id"] != dir_id]
        ids.insert(max(0, min(len(ids), to)), dir_id)
        db.set_directory_order(ids)
        self.tabs.reload()

    @Slot(int, bool)
    def setAnime(self, dir_id: int, anime: bool):
        """An anime folder gets its details from AniList (no key needed) instead of TMDB."""
        db.set_source(dir_id, "anilist" if anime else "tmdb")

    @Slot(int)
    def retag(self, dir_id: int):
        """Tags from folders and file names, again, for every title already in the folder (-1 = every folder)."""
        def work():
            from watcher import retag
            n = sum(retag(d) for d in db.list_directories() if dir_id < 0 or d["id"] == dir_id)
            self.toast.emit(f"Tagged {n} title{'s' if n != 1 else ''} from their folders and file names")
            self.libraryChanged.emit()
        threading.Thread(target=work, daemon=True, name="retag").start()

    @Slot(int, str)
    def setScrapeParts(self, dir_id: int, parts: str):
        db.set_scrape_opts(dir_id, [p for p in parts.split(",") if p])

    # -- Settings > Library > Storage: artwork nothing uses any more, or all of it (utils/cleanup.py)
    @Slot()
    def assetUsage(self):
        def work():
            from utils import cleanup
            try:
                self.assetsScanned.emit(cleanup.usage())
            except Exception:
                log.exception("artwork usage")
        threading.Thread(target=work, daemon=True, name="asset-usage").start()

    @Slot(str, bool)
    def cleanAssets(self, mode: str, keep_own: bool):
        """mode "unused": art for titles that are gone. "all": every piece of artwork (keep_own: not the art you added)."""
        if mode not in ("unused", "all"):
            return

        def work():
            from utils import cleanup, progress
            label = "Cleaning up unused artwork" if mode == "unused" else "Deleting artwork"
            with progress.task(label) as t:
                n, freed = cleanup.run(mode, keep_own, step=lambda i, total: t.update(done=i, total=total))
            mb = freed / 1048576
            self.toast.emit(f"Deleted {n} file{'s' if n != 1 else ''}, {mb:.1f} MB freed" if n else "Nothing to clean up")
            self.libraryChanged.emit()
            try:
                self.assetsScanned.emit(cleanup.usage())
            except Exception:
                log.exception("artwork usage")
        threading.Thread(target=work, daemon=True, name="asset-clean").start()

    @Slot()
    def redownloadImages(self):
        """Settings > Library > Image resolution: download every folder's scraped covers and Gallery again at the
        chosen resolution. Your own box art, Gallery images and banners are kept."""
        def work():
            from watcher import fetch_missing
            n = 0
            for d in db.list_directories():
                if not d["should_scrape"]:
                    continue
                try:
                    n += fetch_missing(d, redo_images=True)
                except Exception:
                    log.exception("re-download images %s", d["tab_name"])
            self.toast.emit(f"Downloaded images again for {n} title{'s' if n != 1 else ''}")
            self.libraryChanged.emit()
        self.toast.emit("Downloading covers and Gallery images again\u2026")
        threading.Thread(target=work, daemon=True, name="redownload-images").start()

    @Slot(int)
    def fetchMissing(self, dir_id: int):
        """Scrape what this folder's titles are missing (cast, photos, covers, discs, box sets, genres, synopses)
        without touching titles or anything you edited."""
        directory = db.get_directory(dir_id)
        if not directory:
            return

        def work():
            from watcher import fetch_missing
            try:
                n = fetch_missing(directory)
                self.toast.emit(f"Updated {n} title{'s' if n != 1 else ''} in {directory['tab_name']}" if n else
                                f"Nothing missing in {directory['tab_name']}")
            except Exception as e:
                log.exception("fetch missing")
                self.toast.emit(f"Could not update: {e}")
            self.libraryChanged.emit()
        self.toast.emit(f"Looking for missing details in {directory['tab_name']}\u2026")
        threading.Thread(target=work, daemon=True, name="fetch-missing").start()

    @Slot()
    def pickFolder(self):
        # Opened from the event loop, not from inside the QML click handler: a modal dialog started
        # there can fail to appear. Errors become a toast, never silence.
        def run():
            try:
                path = pick_folder()
                if path:
                    self.folderPicked.emit(path, Path(path).name or path)   # the options sheet opens in QML
            except Exception as e:
                log.exception("add folder")
                self.toast.emit(f"Could not add folder: {e}")
        QTimer.singleShot(0, run)

    @Slot(int)
    def removeFolder(self, dir_id: int):
        self.app.remove_directory(dir_id)

    @Slot(int, str, result=str)
    def renameTab(self, dir_id: int, name: str) -> str:
        """Blank = the folder's own name again. Returns the name now shown."""
        stored = db.rename_directory(dir_id, name)
        self.tabs.reload()
        return stored

    @Slot(int, bool)
    def setScrape(self, dir_id: int, on: bool):
        db.set_scrape(dir_id, on)

    @Slot(result="QVariantList")
    def backups(self):
        return [p.name for p in backup_manager.list_backups()]

    @Slot()
    def backupNow(self):
        self.toast.emit(f"Saved {backup_manager.run_backup().name}")

    @Slot()
    def exportPortable(self):
        """Portable backup: library, settings and all artwork in one .mvault file you can carry to another PC."""
        def run():
            from datetime import date
            from PySide6.QtWidgets import QFileDialog
            dest, _ = QFileDialog.getSaveFileName(None, "Save portable backup",
                                                  str(Path.home() / f"Media Vault backup {date.today()}.mvault"),
                                                  "Media Vault backup (*.mvault)")
            if not dest:
                return

            def work():
                try:
                    n = backup_manager.export_portable(dest)
                    self.toast.emit(f"Saved: {n['files']} artwork files, {n['bytes'] / 2 ** 20:.0f} MB")
                except Exception as e:
                    log.exception("portable export")
                    self.toast.emit(f"Could not save the backup: {e}")
            threading.Thread(target=work, daemon=True, name="portable-export").start()
        QTimer.singleShot(0, run)

    @Slot()
    def importPortable(self):
        def run():
            from PySide6.QtWidgets import QFileDialog
            src, _ = QFileDialog.getOpenFileName(None, "Restore portable backup", str(Path.home()),
                                                 "Media Vault backup (*.mvault *.zip)")
            if not src:
                return
            try:
                n = backup_manager.import_portable(src)
                self.toast.emit(f"Artwork restored ({n['art']} files). Restart Media Vault to finish restoring the library.")
            except Exception as e:
                log.exception("portable import")
                self.toast.emit(f"Could not restore: {e}")
        QTimer.singleShot(0, run)

    @Slot(str)
    def restoreBackup(self, name: str):
        try:
            path = backup_manager.backup_dir() / name
            if path.parent != backup_manager.backup_dir():
                return
            n = backup_manager.restore_backup(path)
            self.reload()
            self.toast.emit(f"Restored {n['items']} titles, {n['tags']} tags, {n['notes']} notes")
        except Exception as e:
            log.exception("restore failed")
            self.toast.emit(f"Could not restore: {e}")

    @Slot(bool)
    def setFileTypes(self, on: bool):
        self.app.set_file_types(on)

    @Slot(result=bool)
    def fileTypesOn(self):
        """Whether Media Vault is offered in "Open with" right now (read from Windows, not a saved guess)."""
        import setup
        return setup.file_types_command() is not None

    @Slot()
    def installRuntime(self):
        def work():
            import setup
            try:
                left = setup.repair(log.warning)
            except Exception as e:
                log.exception("repair")
                left = [str(e)]
            self.toast.emit("Everything is installed. Restart Media Vault." if not left
                            else "Still missing: " + ", ".join(left) + ". See setup.log.")
        threading.Thread(target=work, daemon=True, name="runtime").start()

    @Slot()
    def installShader(self):
        def work():
            try:
                import setup
                from utils import writable_bin
                setup.download_shader(writable_bin())
                self.toast.emit("Upscaling shader installed. It applies from the next video.")
            except Exception as e:
                log.exception("shader download")
                self.toast.emit(f"Could not download the shader: {e}")
        threading.Thread(target=work, daemon=True, name="shader").start()

    @Slot()
    def checkUpdates(self):
        self.app.check_updates(manual=True)

    # -- Settings > Components: the tools Media Vault uses, their versions, and updates (Media Vault's own from GitHub)
    @Slot(result="QVariantList")
    def components(self):
        from utils import components
        return components.inventory()

    @Slot(result="QVariantMap")
    def appInfo(self):
        import version
        from utils import components
        return {"version": version.VERSION, "repo": version.REPO, "page": version.RELEASES_PAGE, "installed": components.frozen()}

    @Slot()
    def checkComponents(self):
        def work():
            from utils import components
            try:
                rows = components.check(components.inventory(), log.warning)
            except Exception as e:
                log.exception("components check")
                self.toast.emit(f"Could not check for updates: {e}")
                rows = components.inventory()
            self.componentsChecked.emit(rows)
        threading.Thread(target=work, daemon=True, name="components-check").start()

    @Slot(str)
    def updateComponent(self, component: str):
        def work():
            from utils import components
            try:
                self.toast.emit(components.update(component, log.warning))
            except Exception as e:
                log.exception("component update")
                self.toast.emit(f"Could not update: {e}")
            self.componentsChecked.emit(components.check(components.inventory(), log.warning))
        self.toast.emit("Downloading\u2026")
        threading.Thread(target=work, daemon=True, name="component-update").start()

    @Slot(str, str)
    def installAppUpdate(self, url: str, name: str):
        """Download a Media Vault setup from GitHub and install it without the wizard: Media Vault closes, setup
        replaces it in the same folder and starts it again. Also used to roll back (an older release's setup)."""
        from utils import components
        if not components.frozen():
            self.openLink(url or self.appInfo()["page"])
            return

        def work():
            try:
                path = components.download_setup(url, name, lambda d, t: self.appUpdateProgress.emit(d / t if t else 0.0))
                self.appUpdateProgress.emit(1.0)
                components.run_setup(path)
                self._quitForUpdate.emit()
            except Exception as e:
                log.exception("app update")
                self.appUpdateProgress.emit(-1.0)
                self.toast.emit(f"Could not install the update: {e}")
        threading.Thread(target=work, daemon=True, name="app-update").start()

    @Slot()
    def updateAll(self):
        """Update everything that has an update: the video engines, shader and packages first, Media Vault last
        (installing it closes and reopens the app)."""
        def work():
            from utils import components
            rows = components.check(components.inventory(), log.warning)
            todo = [r for r in rows if r["status"] == "update" and r["kind"] not in ("bundled", "system", "app")]
            done, failed = [], []
            for i, r in enumerate(todo, 1):
                self.toast.emit(f"Updating {r['name']} ({i} of {len(todo)})\u2026")
                try:
                    components.update(r["id"], log.warning)
                    done.append(r["name"])
                except Exception as e:
                    log.exception("update %s", r["id"])
                    failed.append(f"{r['name']} ({e})")
            app = rows[0]
            self.componentsChecked.emit(components.check(components.inventory(), log.warning))
            if failed:
                self.toast.emit("Could not update " + ", ".join(failed))
            elif done:
                self.toast.emit("Updated " + ", ".join(done) + ". Restart Media Vault to use them.")
            if app.get("status") == "update" and app.get("setup") and components.frozen():
                self.installAppUpdate(app["setup"], app["setup"].split("/")[-1])
            elif not todo:
                self.toast.emit("Everything is up to date")
        self.toast.emit("Checking for updates\u2026")
        threading.Thread(target=work, daemon=True, name="update-all").start()

    @Slot(str)
    def rollbackComponent(self, component: str):
        def work():
            from utils import components
            try:
                self.toast.emit(components.rollback_component(component, log.warning))
            except Exception as e:
                log.exception("rollback")
                self.toast.emit(f"Could not roll back: {e}")
            self.componentsChecked.emit(components.check(components.inventory(), log.warning))
        threading.Thread(target=work, daemon=True, name="rollback").start()

    @Slot()
    def windowClosing(self):
        """The library window is closing: save its size and place, then end Media Vault."""
        self.app._main_closing()

    @Slot()
    def restartApp(self):
        self.app.restart()

    @Slot(str)
    def openLink(self, url: str):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if url.startswith("https://"):
            QDesktopServices.openUrl(QUrl(url))

    @Slot(str, result=str)
    def tintOf(self, url: str) -> str:
        """Animated themes: the colour of a poster / fanart (a file:// URL from the model)."""
        from PySide6.QtCore import QUrl
        path = QUrl(url).toLocalFile()
        return tint_of(path) if path else ""

    # -- Streaming: browsers on the Wi-Fi, Chromecast, AirPlay
    @Property(str, notify=streamChanged)
    def streamUrl(self):
        return self.stream.base_url()

    @Slot(bool)
    def setStreaming(self, on: bool):
        """Off by default and off again at every start; a new secret link each time it is switched on."""
        if on:
            try:
                self.stream.start()
            except Exception as e:
                log.exception("stream server")
                self.toast.emit(f"Could not start sharing: {e}")
        else:
            self.stream.stop()
        self.streamChanged.emit()

    @Slot(result="QVariantMap")
    def castSupport(self):
        return streaming.support()

    @Slot()
    def installCastSupport(self):
        if getattr(sys, "frozen", False):     # the installed app: they come built in (1.1.1 and later)
            self.toast.emit("AirPlay and Chromecast come built into Media Vault 1.1.1 and later: update it in Settings \u203A About & Updates")
            return

        def work():
            import setup
            try:
                setup.pip_install(["pychromecast", "pyatv"], log.info)
                self.toast.emit("AirPlay and Chromecast support installed")
            except Exception as e:
                log.exception("cast support install")
                self.toast.emit(f"Could not install: {e}")
            self.streamChanged.emit()
        self.toast.emit("Installing AirPlay and Chromecast support\u2026")
        threading.Thread(target=work, daemon=True, name="cast-install").start()

    @Slot()
    def findDevices(self):
        def work():
            found = streaming.discover()
            self._devices = found
            self.devicesFound.emit(found)
        threading.Thread(target=work, daemon=True, name="cast-discover").start()

    @Slot(str, str, str, result="QVariantMap")
    def discordPreview(self, details: str, state: str, paused: str):
        """What a movie and an episode look like on Discord with these lines (for the preview in Settings)."""
        from utils.discord_presence import DEFAULTS, fill
        movie = {"title": "Blade Runner 2049", "year": "2017", "kind": "movie", "episode": ""}
        show = {"title": "Severance", "year": "", "kind": "show", "episode": "S01E02"}
        d, st = details or DEFAULTS["discord_details"], state if state is not None else DEFAULTS["discord_state"]
        return {"movie": fill(d, movie), "movieState": fill(st, movie), "show": fill(d, show), "showState": fill(st, show),
                "placeholders": "{title}  {year}  {episode}  {type}"}

    @Slot(result="QVariantMap")
    def discordPrivacy(self):
        """Per-folder Discord modes and hidden tags, for Settings and each folder's Configure window."""
        try:
            modes = json.loads(db.get_setting("discord_folders", "{}") or "{}")
            tags = json.loads(db.get_setting("discord_hide_tags", "[]") or "[]")
        except ValueError:
            modes, tags = {}, []
        return {"folders": modes, "tags": tags, "hideAdult": db.get_setting("discord_hide_adult", "1") != "0"}

    @Slot(int, str)
    def setDiscordFolder(self, dir_id: int, mode: str):
        from utils.discord_presence import FOLDER_MODES
        if mode not in FOLDER_MODES:
            return
        modes = self.discordPrivacy()["folders"]
        if mode == "show":
            modes.pop(str(dir_id), None)
        else:
            modes[str(dir_id)] = mode
        db.set_setting("discord_folders", json.dumps(modes))
        self._discord_changed()

    @Slot(str, bool)
    def setDiscordHiddenTag(self, tag: str, hidden: bool):
        tags = [t for t in self.discordPrivacy()["tags"] if t != tag]
        if hidden and tag:
            tags.append(tag)
        db.set_setting("discord_hide_tags", json.dumps(tags))
        self._discord_changed()

    def _discord_changed(self):
        if self.app.presence:
            self.app._presence_privacy_for = None       # work out the playing title's privacy again
            self.app.presence.configure()

    @Slot(result=str)
    def discordStatus(self):
        return self.app.presence.status if self.app.presence else "Off"

    @Slot(result="QVariantList")
    def devices(self):
        return self._devices

    def _cast(self, device_id: str, item: dict, start: float = 0.0):
        if not any(d["id"] == device_id for d in self._devices):
            return
        ext = os.path.splitext(item["file_path"])[1].lower()
        if ext not in streaming.CASTABLE:
            self.toast.emit(f"{ext.upper()[1:]} files may not play on that device (MP4, MOV and WebM do)")
        if not self.stream.running:
            self.stream.start()
            self.streamChanged.emit()
        url = self.stream.file_url(item["uuid"])
        name = next(d["name"] for d in self._devices if d["id"] == device_id)

        def work():
            try:
                streaming.cast(device_id, url, item["title"], streaming.MIME.get(ext, "video/mp4"))
                self.toast.emit(f"Playing on {name}")
            except Exception as e:
                log.exception("cast")
                self.toast.emit(f"Could not play on {name}: {e}")
        threading.Thread(target=work, daemon=True, name="cast").start()

    @Slot(str, str)
    def castKey(self, device_id: str, key: str):
        item = self._target(key)
        if item:
            self._cast(device_id, item)

    @Slot(str)
    def castPlaying(self, device_id: str):
        """From the player: send what is playing to the device and stop playing it here."""
        s = self.app.engine.session
        item = db.get_media(s.uuid) if s and s.uuid else None
        if not item:
            self.toast.emit("Only titles in the library can be sent to another device")
            return
        self._cast(device_id, item)
        self.app.engine.stop()

    @Slot(str)
    def copyText(self, text: str):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(text)
        self.toast.emit("Link copied")

    @Slot()
    def openStream(self):
        if self.stream.running:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(self.stream.base_url()))

    # -- Library health
    @Slot(result="QVariantMap")
    def health(self):
        return health.report(quality_of, self._ignored_now)

    @Slot(str, str, bool)
    def ignoreIssue(self, kind: str, key: str, forever: bool):
        """kind: duplicate | missing_episode | missing_art. For now = until restart; forever = saved."""
        if kind not in ("duplicate", "missing_episode", "missing_art"):
            return
        if forever:
            db.ignore_issue(kind, key)
        else:
            self._ignored_now.setdefault(kind, set()).add(key)

    @Slot()
    def resetIgnored(self):
        db.unignore_all()
        self._ignored_now.clear()

    @Slot(str)
    def showInFolder(self, path: str):
        """Open Explorer with the file selected. Only for files the library knows (never an arbitrary path)."""
        known = conn_has_path(path)
        if not known:
            return
        if sys.platform == "win32":
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    @Slot(result="QVariantMap")
    def hardware(self):
        """What detect() found and what it recommends, for Settings > Playback."""
        h = self.app.engine.hw
        return {"gpus": list(h.gpus) or ["No display adapter reported"], "ram": h.ram_gb, "cores": h.cores,
                "core": h.backend, "level": h.level, "why": h.why, "rtx": h.rtx}

    @Slot(result="QVariantList")
    def themes(self):
        from . import THEMES
        out = [{"id": t[0], "name": t[1], "tagline": t[2], "page": t[3], "surface": t[4], "accent": t[5], "highlight": t[6]}
               for t in THEMES]
        from . import CUSTOM_COLOURS, custom_from
        mine = custom_from(db.get_setting)
        for t in out:  # the Custom swatches show the colours you picked
            if t["id"] == "custom":
                t.update(page=mine["custom_page"], surface=mine["custom_surface"], accent=mine["custom_accent"],
                         highlight=mine["custom_highlight"])
                t["colours"] = [{"key": k, "name": n, "role": r, "value": mine[k]} for k, n, r in CUSTOM_COLOURS]
        return out

    @Slot(result="QVariantList")
    def levelNames(self):
        return [hw_accelerator.LEVEL_NAMES[n] for n in (1, 2, 3)]
