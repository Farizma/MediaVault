"""Folder watcher: queues file events, waits for a quiet second, then does ONE batch write.

Also holds the indexer (probe -> clean name -> scrape -> single DB write), because the
watcher and the first scan of a new folder must run the exact same pipeline.
"""
import asyncio
import logging
import os
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import database as db
from utils import autotag, media_probe, scraper, tagrules

log = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".webm"}
QUIET = 1.0  # seconds without events before a batch is processed


def is_video(path) -> bool:
    p = Path(path)
    return p.suffix.lower() in VIDEO_EXTS and scraper.ASSET_DIR not in p.parts


def scan_paths(root):
    for folder, subdirs, files in os.walk(root):
        subdirs[:] = [d for d in subdirs if d != scraper.ASSET_DIR]
        for f in files:
            if is_video(f):
                yield os.path.join(folder, f)


# ------------------------------------------------------------------ indexer

def _headless():
    try:
        return media_probe.HeadlessPlayer()
    except Exception:
        log.warning("libmpv unavailable: files are indexed without resolution/codec/duration")
        return None


def index_paths(directory: dict, paths) -> int:
    """Add files not yet in the library. Returns how many were new."""
    known = db.known_paths(directory["id"])
    new = sorted({db.norm(p) for p in paths if os.path.isfile(p)} - known)
    if not new:
        return 0
    scrape = bool(directory["should_scrape"])
    auto = db.get_setting("auto_tags", "1") != "0"     # tags from folders and file names (Settings > Library)
    hp = _headless()
    rows, tags = [], []
    try:
        for p in new:
            parsed = scraper.clean_name(p, fallback=Path(p).parent.name)
            kind = "clip" if not scrape else "show" if parsed.episode is not None else "movie"
            title = parsed.title
            if kind == "show":
                title += f" S{parsed.season or 1:02d}E{parsed.episode:02d}"
            row = {"uuid": db.file_id(p), "file_path": p, "parent_directory_id": directory["id"],
                   "title": title, "media_type": kind, "release_date": parsed.year}
            row.update(media_probe.probe(p, hp) if hp else {"container": Path(p).suffix.lower()})
            rows.append((row, parsed))
            if kind == "clip":
                tags.append((row["uuid"], "Personal"))  # lets analytics hide home video with one tag toggle
    finally:
        if hp:
            hp.close()
    if scrape:
        _scrape_into(rows, tags, db.scrape_opts(directory), directory.get("source") or "tmdb")
    # computed tags (folder and file names, age rating, your rules) once the scrape has filled in what it found
    rules = tagrules.load()
    for row, _ in rows:
        info = {"genres": [t[6:] for u, t in tags if u == row["uuid"] and t.startswith("genre:")],
                "tags": [t for u, t in tags if u == row["uuid"] and ":" not in t]}
        tags.extend((row["uuid"], autotag.PREFIX + t)
                    for t in tagrules.computed_tags(row, info, directory["folder_path"], rules, auto))
    db.add_items([r for r, _ in rows], tags)  # the one collective write
    return len(rows)


def _scrape_into(rows, tags, opts=None, source: str = "tmdb") -> None:
    """Fill rows from TMDB / OMDb, or AniList for an anime folder. opts: which parts this folder wants
    (database.SCRAPE_PARTS); None = all."""
    opts = {k for k, _ in db.SCRAPE_PARTS} if opts is None else opts
    keys = scraper.api_keys()
    if not opts or (source != "anilist" and not (keys["tmdb"] or keys["omdb"])):
        return  # nothing to ask; do not mark files as failed
    todo = [(r, p) for r, p in rows if not db.is_failed(db.file_hash(r["file_path"]))]
    if not todo:
        return
    answers = asyncio.run(scraper.scrape_many([(r["media_type"], p) for r, p in todo], keys, source))
    gallery_done = set()
    images, missed, cast_done = {}, [], set()
    for (row, parsed), hit in zip(todo, answers):
        if isinstance(hit, Exception):
            log.warning("scrape skipped for %s: %s", parsed.title, hit)
        elif hit is None:
            missed.append(db.file_hash(row["file_path"]))
        else:
            if "titles" in opts:
                row["title"] = hit["title"] + (f" S{parsed.season or 1:02d}E{parsed.episode:02d}"
                                               if row["media_type"] == "show" else "")
                row["release_date"] = hit["release_date"] or row["release_date"]
            if "titles" in opts:
                row["original_title"], row["romaji_title"] = hit.get("original_title"), hit.get("romaji_title")
            if "certification" in opts:
                row["certification"] = hit.get("certification")
            if "synopsis" in opts:
                row["synopsis"] = hit["synopsis"]
            row["tmdb_id"] = hit.get("tmdb_id")
            row["anilist_id"] = hit.get("anilist_id")
            if "gallery" in opts and hit.get("gallery_urls"):
                owner = db.cast_owner(row)
                if owner not in gallery_done:            # a series' episodes share one Gallery
                    gallery_done.add(owner)
                    scraper.save_gallery(row, hit["gallery_urls"])
            if "score" in opts:
                row["score"] = hit.get("score")
            if "sets" in opts:
                row["collection_id"], row["collection_name"] = hit.get("collection_id"), hit.get("collection_name")
                if hit.get("collection_id") and hit.get("collection_poster_url") and "poster" in opts:
                    scraper.save_collection_poster(hit["collection_id"], hit["collection_poster_url"], images)
            if "genres" in opts:
                tags.extend((row["uuid"], f"genre:{g}") for g in hit["genres"])
            if "cast" in opts and hit.get("cast"):
                owner = db.cast_owner(row)
                if owner not in cast_done:      # a series' episodes share one cast list
                    cast_done.add(owner)
                    db.set_cast(owner, hit["cast"])
                    if "photos" in opts:
                        scraper.save_person_photos(hit["cast"])
            if hit["poster_url"] and "poster" in opts:
                try:
                    img = images.get(hit["poster_url"]) or images.setdefault(
                        hit["poster_url"], scraper.fetch_image(hit["poster_url"]))
                    scraper.save_webp(img, scraper.poster_path(row))
                except Exception:
                    log.warning("poster failed for %s", row["title"], exc_info=True)
            if hit.get("disc_url") and "disc" in opts:
                try:
                    scraper.save_webp(scraper.fetch_image(hit["disc_url"]), scraper.disc_path(row), box=(500, 500))
                except Exception:
                    log.warning("disc art failed for %s", row["title"], exc_info=True)
    if missed:
        db.mark_failed(missed)


def retag(directory: dict) -> int:
    """Computed tags (folder and file names, age rating, your rules) worked out again for every title in a folder.
    Only "auto:" tags change; yours stay. Returns titles tagged."""
    return tagrules.retag_all([directory])


def fetch_missing(directory: dict) -> int:
    """Fill gaps for titles already in a folder, by what the folder scrapes: cast and photos, cover, disc art,
    box set, genres, synopsis. Titles, and anything you set yourself, are never touched. Returns titles updated."""
    opts = db.scrape_opts(directory)
    keys = scraper.api_keys()
    anime = (directory.get("source") or "tmdb") == "anilist"
    if not opts or (not anime and not keys["tmdb"]):
        return 0
    groups: dict[str, list[dict]] = {}          # one lookup per film, and per series
    for it in db.list_media(directory["id"]):
        if it["media_type"] != "clip":
            groups.setdefault(db.cast_owner(it), []).append(it)
    updated = 0
    for owner, items in groups.items():
        first = items[0]
        kind = first["media_type"]
        tags = set(db.tags_for(first["uuid"]))
        need = {
            "cast": "cast" in opts and not db.get_cast(owner),
            "photos": "photos" in opts and any(p["person_id"] and not scraper.person_photo_path(p["person_id"]).exists()
                                               for p in db.get_cast(owner)),
            "poster": "poster" in opts and not all(scraper.cover_path(i).exists() for i in items),
            "disc": "disc" in opts and kind == "movie" and not scraper.disc_art(first),
            "sets": "sets" in opts and kind == "movie" and first.get("collection_id") is None,
            "genres": "genres" in opts and not any(t.startswith("genre:") for t in tags),
            "synopsis": "synopsis" in opts and not first.get("synopsis"),
            "score": "score" in opts and first.get("score") is None,
            "certification": "certification" in opts and not first.get("certification"),
            "gallery": "gallery" in opts and not scraper.gallery_images(first),
        }
        if "photos" in opts and need["cast"]:
            need["photos"] = True
        if not any(need.values()):
            continue
        title = db.series_title(first["title"]) if kind == "show" else first["title"]
        year = (first.get("release_date") or "")[:4] or None
        try:
            if anime:
                from utils import anilist
                hit = anilist.details(first["anilist_id"]) if first.get("anilist_id") else anilist.lookup(title, year)
                if not hit:
                    continue
                tid = None
            else:
                tid = first.get("tmdb_id")
                if not tid:
                    hit = scraper._tmdb(kind, scraper.Parsed(title, year, None, None), keys["tmdb"])
                    tid = hit and hit.get("tmdb_id")
                if not tid:
                    continue
                hit = scraper.tmdb_details(kind, tid, keys["tmdb"])
        except Exception as e:   # ScrapeError, AniListError, offline
            log.warning("fetch missing skipped %s: %s", first["title"], e)
            continue
        uids = [i["uuid"] for i in items]
        with db._tx() as c:
            if tid:
                c.executemany("UPDATE media_items SET tmdb_id=? WHERE uuid=? AND tmdb_id IS NULL", [(tid, u) for u in uids])
            if hit.get("anilist_id"):
                c.executemany("UPDATE media_items SET anilist_id=? WHERE uuid=? AND anilist_id IS NULL", [(hit["anilist_id"], u) for u in uids])
            if need["synopsis"] and hit.get("synopsis"):
                c.executemany("UPDATE media_items SET synopsis=? WHERE uuid=? AND (synopsis IS NULL OR synopsis='')",
                              [(hit["synopsis"], u) for u in uids])
            if need["genres"]:
                c.executemany("INSERT INTO tags (media_uuid, tag_name) VALUES (?,?)", [(u, f"genre:{g}") for u in uids for g in hit["genres"]])
        if need["score"] and hit.get("score") is not None:
            db.set_score(uids, hit["score"])
        db.set_scraped(uids, certification=hit.get("certification") if "certification" in opts else None,
                       original_title=hit.get("original_title") if "titles" in opts else None,
                       romaji_title=hit.get("romaji_title") if "titles" in opts else None)
        if need["sets"] and hit.get("collection_id"):
            db.add_to_set(uids, hit["collection_id"], hit["collection_name"])
            if hit.get("collection_poster_url"):
                scraper.save_collection_poster(hit["collection_id"], hit["collection_poster_url"])
        cast = hit.get("cast") or []
        if need["cast"] and cast:
            db.set_cast(owner, cast)
        if need["photos"] and cast:
            scraper.save_person_photos(cast)
        if need["poster"] and hit.get("poster_url"):
            try:
                img = scraper.fetch_image(hit["poster_url"])
                for i in items:
                    if not scraper.cover_path(i).exists():
                        scraper.save_webp(img, scraper.poster_path(i))
            except Exception:
                log.warning("poster failed for %s", first["title"], exc_info=True)
        if need["gallery"] and hit.get("gallery_urls"):
            scraper.save_gallery(first, hit["gallery_urls"])
        if need["disc"] and tid:
            url = scraper.disc_url(tid, keys.get("fanart", ""))
            if url:
                try:
                    scraper.save_webp(scraper.fetch_image(url), scraper.disc_path(first), box=(500, 500))
                except Exception:
                    log.warning("disc art failed for %s", first["title"], exc_info=True)
        updated += 1
    if updated:
        tagrules.retag_all([directory])     # new age ratings and titles can change computed tags
    return updated


def scan_directory(directory: dict) -> int:
    root = directory["folder_path"]
    if not os.path.isdir(root):
        return 0  # drive unplugged: keep the library entries
    found = {db.norm(p) for p in scan_paths(root)}
    # Prune only when something was found: an empty result usually means a share that did not mount.
    gone = db.known_paths(directory["id"]) - found if found else set()
    if gone:
        db.remove_under(gone)
    return index_paths(directory, found)


# ------------------------------------------------------------------ watcher

class _Handler(FileSystemEventHandler):
    def __init__(self, watcher, dir_id):
        self.w, self.dir_id = watcher, dir_id

    def _add(self, path, is_dir):
        if scraper.ASSET_DIR in Path(path).parts:  # our own poster writes must not trigger a rescan
            return
        if is_dir:
            self.w.queue(self.dir_id, scan=[path])
        elif is_video(path):
            self.w.queue(self.dir_id, add=[path])

    def on_created(self, e):
        self._add(e.src_path, e.is_directory)

    def on_modified(self, e):  # a file that is still being copied keeps firing this, which resets the timer
        if not e.is_directory:
            self._add(e.src_path, False)

    def on_moved(self, e):
        if scraper.ASSET_DIR not in Path(e.src_path).parts:
            self.w.queue(self.dir_id, delete=[e.src_path])
        self._add(e.dest_path, e.is_directory)

    def on_deleted(self, e):
        if scraper.ASSET_DIR not in Path(e.src_path).parts:
            self.w.queue(self.dir_id, delete=[e.src_path])


class Watcher:
    """on_change(set_of_directory_ids) runs after each batch; the UI uses it to refresh tabs."""

    def __init__(self, on_change, quiet: float = QUIET):
        self.on_change, self.quiet = on_change, quiet
        self._obs = Observer()
        self._watches = {}
        self._pending = {}
        self._lock = threading.Lock()
        self._run = threading.Lock()
        self._timer = None

    def start(self):
        self._obs.start()

    def stop(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
        self._obs.stop()

    def watch(self, directory: dict):
        if directory["id"] in self._watches or not os.path.isdir(directory["folder_path"]):
            return
        self._watches[directory["id"]] = self._obs.schedule(
            _Handler(self, directory["id"]), directory["folder_path"], recursive=True)

    def unwatch(self, dir_id: int):
        if w := self._watches.pop(dir_id, None):
            self._obs.unschedule(w)

    def queue(self, dir_id, add=(), delete=(), scan=()):
        with self._lock:
            q = self._pending.setdefault(dir_id, {"add": set(), "delete": set(), "scan": set()})
            q["add"].update(add)
            q["delete"].update(delete)
            q["scan"].update(scan)
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.quiet, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self):
        with self._run:  # a second flush waits for the first; events keep queueing meanwhile
            with self._lock:
                batch, self._pending = self._pending, {}
            changed = set()
            for dir_id, q in batch.items():
                try:
                    directory = db.get_directory(dir_id)
                    if not directory:
                        continue
                    if q["delete"]:
                        db.remove_under(q["delete"])
                    paths = set(q["add"])
                    for folder in q["scan"]:
                        paths.update(scan_paths(folder))
                    index_paths(directory, paths)
                    changed.add(dir_id)
                except Exception:
                    log.exception("batch failed for directory %s", dir_id)
            if changed:
                self.on_change(changed)
