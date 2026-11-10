"""SQLite interface for Media Vault.

One connection per thread (SQLite connections are not shared across threads),
WAL mode so the UI can read while the watcher writes.
"""
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_NAME = "media_vault.db"
PROFILE = "default"

# The six tables are the spec schema. Additions: `intro_marks` (skip-intro bookmarks), `credit_marks`
# (where the credits start), `ignored_issues` (Library health items hidden for good), `settings`,
# `watch_log` (real watched seconds per day for analytics) and media_items.frame_rate (spec lists
# frame rate as a read-only field but its CREATE TABLE has no column).
SCHEMA = """
CREATE TABLE IF NOT EXISTS scanned_directories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_path TEXT UNIQUE NOT NULL,
    tab_name TEXT NOT NULL,
    should_scrape INTEGER DEFAULT 1,
    scrape_opts TEXT DEFAULT '',         -- what to scrape (comma list of SCRAPE_PARTS); '' = everything
    sort_order INTEGER DEFAULT 0,        -- tab order (drag the tabs, or Settings > Folders)
    source TEXT DEFAULT 'tmdb'           -- where details come from: 'tmdb' (films and series) or 'anilist' (anime)
);
CREATE TABLE IF NOT EXISTS media_items (
    uuid TEXT PRIMARY KEY,
    file_path TEXT UNIQUE NOT NULL,
    parent_directory_id INTEGER,
    title TEXT NOT NULL,
    media_type TEXT CHECK(media_type IN ('movie', 'show', 'clip')) NOT NULL,
    release_date TEXT,
    synopsis TEXT,
    duration INTEGER,
    resolution TEXT,
    codec TEXT,
    container TEXT,
    audio_layout TEXT,
    frame_rate REAL,
    added_at TEXT,                      -- when Media Vault first saw the file ("recently added")
    tmdb_id INTEGER,
    collection_id INTEGER,              -- TMDB collection (box set) the film belongs to
    collection_name TEXT,
    score REAL,                         -- scraped audience rating, 0-10 (TMDB vote average / IMDb / AniList)
    anilist_id INTEGER,
    FOREIGN KEY(parent_directory_id) REFERENCES scanned_directories(id)
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_uuid TEXT,
    tag_name TEXT NOT NULL,
    FOREIGN KEY(media_uuid) REFERENCES media_items(uuid) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS custom_notes (
    media_uuid TEXT PRIMARY KEY,
    notes_text TEXT,
    last_edited TEXT,
    FOREIGN KEY(media_uuid) REFERENCES media_items(uuid) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS watch_history (
    media_uuid TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    last_position INTEGER DEFAULT 0,
    last_watched TEXT NOT NULL,
    is_completed INTEGER DEFAULT 0,
    FOREIGN KEY(media_uuid) REFERENCES media_items(uuid) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS failed_scrapes (
    file_hash TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watch_log (
    media_uuid TEXT NOT NULL,
    day TEXT NOT NULL,
    seconds REAL NOT NULL,
    PRIMARY KEY (media_uuid, day),
    FOREIGN KEY(media_uuid) REFERENCES media_items(uuid) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS intro_marks (
    show_key TEXT PRIMARY KEY,
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS credit_marks (
    show_key TEXT PRIMARY KEY,          -- a series folder, or a single file
    left_sec REAL NOT NULL              -- credits start this many seconds before the end
);
CREATE TABLE IF NOT EXISTS ignored_issues (
    kind TEXT NOT NULL,                 -- duplicate | missing_episode | missing_art
    issue_key TEXT NOT NULL,
    PRIMARY KEY (kind, issue_key)
);
CREATE TABLE IF NOT EXISTS cast_members (
    owner TEXT NOT NULL,                -- a film's uuid, or 'show:<folder>' for a series
    ord INTEGER NOT NULL,
    person_id INTEGER,
    name TEXT NOT NULL,
    role TEXT,
    PRIMARY KEY (owner, ord)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_media_parent ON media_items(parent_directory_id);
CREATE INDEX IF NOT EXISTS idx_tags_media ON tags(media_uuid);
"""

# Columns of media_items that the user may edit. Everything else is read-only
# (taken from the container headers) and is never touched by update_media().
EDITABLE = ("title", "synopsis", "release_date")
_TECH = ("duration", "resolution", "codec", "container", "audio_layout", "frame_rate")
_COLS = ("uuid", "file_path", "parent_directory_id", "title", "media_type",
         "release_date", "synopsis", "tmdb_id", "collection_id", "collection_name", "score", "anilist_id") + _TECH

_local = threading.local()


# ---------------------------------------------------------------- paths / ids

def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    path = Path(base) / "MediaVault"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / DB_NAME


def db_exists() -> bool:
    return db_path().exists()


def norm(path) -> str:
    return os.path.normpath(os.path.abspath(path))


def file_id(path) -> str:
    # uuid5, not uuid4: the id must be the same after every rescan so tags,
    # notes and history stay attached to the file.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, os.path.normcase(norm(path))))


def file_hash(path) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return hashlib.sha1(f"{os.path.normcase(norm(path))}|{size}".encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- connection

def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        c = sqlite3.connect(db_path(), timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL;")
        c.execute("PRAGMA foreign_keys=ON;")
        c.execute("PRAGMA busy_timeout=5000;")
        _local.conn = c
    return c


def close_thread_connection() -> None:
    c = getattr(_local, "conn", None)
    if c is not None:
        c.close()
        _local.conn = None


@contextmanager
def _tx():
    c = conn()
    with c:  # commit on success, rollback on error
        yield c


def init_db() -> None:
    c = conn()
    c.executescript(SCHEMA)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(media_items)")}
    if "frame_rate" not in cols:
        c.execute("ALTER TABLE media_items ADD COLUMN frame_rate REAL")  # database from an older build
    if "added_at" not in cols:
        c.execute("ALTER TABLE media_items ADD COLUMN added_at TEXT")    # older rows: left empty (sort last)
    dir_cols = {r["name"] for r in c.execute("PRAGMA table_info(scanned_directories)")}
    if "scrape_opts" not in dir_cols:
        c.execute("ALTER TABLE scanned_directories ADD COLUMN scrape_opts TEXT DEFAULT ''")
    if "source" not in dir_cols:
        c.execute("ALTER TABLE scanned_directories ADD COLUMN source TEXT DEFAULT 'tmdb'")
    if "sort_order" not in dir_cols:
        c.execute("ALTER TABLE scanned_directories ADD COLUMN sort_order INTEGER DEFAULT 0")
        c.execute("UPDATE scanned_directories SET sort_order = id")   # keep the order they were added in
    for col, kind in (("tmdb_id", "INTEGER"), ("collection_id", "INTEGER"), ("collection_name", "TEXT"), ("score", "REAL"), ("anilist_id", "INTEGER")):
        if col not in cols:
            c.execute(f"ALTER TABLE media_items ADD COLUMN {col} {kind}")
    c.commit()


def _rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]


def _one(cursor) -> dict | None:
    r = cursor.fetchone()
    return dict(r) if r else None


# ---------------------------------------------------------------- directories

# what a folder can scrape; a folder with scraping on gets all of them unless the user unticked some
SCRAPE_PARTS = (("titles", "Titles and years"), ("synopsis", "Synopsis"), ("genres", "Genres"), ("score", "Star rating"),
                ("poster", "Box art (front cover)"), ("disc", "Disc art"), ("sets", "Box sets"),
                ("cast", "Actors"), ("photos", "Actor photos"), ("gallery", "Gallery images"))


def scrape_opts(directory: dict | None) -> set[str]:
    """The parts a folder scrapes. Empty when scraping is off."""
    if not directory or not directory.get("should_scrape"):
        return set()
    raw = directory.get("scrape_opts") or ""
    allowed = {k for k, _ in SCRAPE_PARTS}
    return allowed if not raw else {p for p in raw.split(",") if p in allowed}


def set_scrape_opts(dir_id: int, parts) -> None:
    allowed = [k for k, _ in SCRAPE_PARTS]
    chosen = [p for p in allowed if p in set(parts)]
    with _tx() as c:
        c.execute("UPDATE scanned_directories SET scrape_opts=? WHERE id=?",
                  ("" if len(chosen) == len(allowed) else ",".join(chosen) or "none", dir_id))


def set_source(dir_id: int, source: str) -> None:
    with _tx() as c:
        c.execute("UPDATE scanned_directories SET source=? WHERE id=?", ("anilist" if source == "anilist" else "tmdb", dir_id))


def add_directory(folder_path: str, tab_name: str, should_scrape: bool = True, parts=None, source: str = "tmdb") -> int:
    folder_path = norm(folder_path)
    allowed = [k for k, _ in SCRAPE_PARTS]
    opts = "" if parts is None or set(allowed) <= set(parts) else ",".join(p for p in allowed if p in set(parts)) or "none"
    with _tx() as c:
        c.execute("INSERT OR IGNORE INTO scanned_directories (folder_path, tab_name, should_scrape, scrape_opts, sort_order, source) "
                  "VALUES (?,?,?,?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM scanned_directories), ?)",
                  (folder_path, tab_name, int(should_scrape), opts, "anilist" if source == "anilist" else "tmdb"))
        return c.execute("SELECT id FROM scanned_directories WHERE folder_path=?",
                         (folder_path,)).fetchone()["id"]


def list_directories() -> list[dict]:
    return _rows(conn().execute("SELECT * FROM scanned_directories ORDER BY sort_order, id"))


def set_directory_order(ids) -> None:
    """Tabs in this order (folder ids); folders not named keep their place after them."""
    rest = [d["id"] for d in list_directories() if d["id"] not in set(ids)]
    with _tx() as c:
        c.executemany("UPDATE scanned_directories SET sort_order=? WHERE id=?", [(i, d) for i, d in enumerate([*ids, *rest])])


def get_directory(dir_id: int) -> dict | None:
    return _one(conn().execute("SELECT * FROM scanned_directories WHERE id=?", (dir_id,)))


def set_scrape(dir_id: int, should_scrape: bool) -> None:
    with _tx() as c:
        c.execute("UPDATE scanned_directories SET should_scrape=? WHERE id=?", (int(should_scrape), dir_id))


def rename_directory(dir_id: int, tab_name: str) -> str:
    """Rename a folder's tab. A blank name goes back to the folder's own name. Returns the name stored."""
    d = get_directory(dir_id)
    if not d:
        return ""
    name = " ".join(tab_name.split())[:60] or os.path.basename(d["folder_path"].rstrip("\\/")) or d["folder_path"]
    with _tx() as c:
        c.execute("UPDATE scanned_directories SET tab_name=? WHERE id=?", (name, dir_id))
    return name


def remove_directory(dir_id: int) -> None:
    # Removes library entries only. Files on disk are never touched.
    with _tx() as c:
        c.execute("DELETE FROM media_items WHERE parent_directory_id=?", (dir_id,))
        c.execute("DELETE FROM scanned_directories WHERE id=?", (dir_id,))


# ---------------------------------------------------------------- media items

def add_items(rows: list[dict], tags=()) -> None:
    """Insert new files and their tags in ONE transaction (the delta-queue write).

    A rescan of a known file refreshes only the read-only technical columns;
    title, synopsis and release date the user may have edited are kept.
    """
    if not rows and not tags:
        return
    cols = ",".join(_COLS)
    marks = ",".join("?" * len(_COLS))
    update = ",".join(f"{c}=excluded.{c}" for c in _TECH)
    with _tx() as c:
        c.executemany(f"INSERT INTO media_items ({cols}, added_at) VALUES ({marks}, ?) "
                      f"ON CONFLICT(uuid) DO UPDATE SET {update}",
                      [tuple(r.get(k) for k in _COLS) + (_now(),) for r in rows])
        c.executemany("INSERT INTO tags (media_uuid, tag_name) SELECT ?,? "
                      "WHERE NOT EXISTS (SELECT 1 FROM tags WHERE media_uuid=? AND tag_name=?)",
                      [(u, t, u, t) for u, t in tags])


def known_paths(dir_id: int) -> set[str]:
    return {r["file_path"] for r in conn().execute(
        "SELECT file_path FROM media_items WHERE parent_directory_id=?", (dir_id,))}


def remove_under(paths) -> None:
    """Remove items whose path is one of `paths` or lies inside one (folder deleted)."""
    with _tx() as c:
        for p in paths:
            p = norm(p)
            prefix = p + os.sep
            c.execute("DELETE FROM media_items WHERE file_path=? OR substr(file_path,1,?)=?",
                      (p, len(prefix), prefix))


_SELECT = ("SELECT m.*, COALESCE(w.last_position,0) AS last_position, "
           "COALESCE(w.is_completed,0) AS is_completed, w.last_watched AS last_watched "
           "FROM media_items m LEFT JOIN watch_history w ON w.media_uuid=m.uuid ")


def list_media(dir_id: int | None = None) -> list[dict]:
    where, args = ("WHERE m.parent_directory_id=? ", (dir_id,)) if dir_id is not None else ("", ())
    return _rows(conn().execute(_SELECT + where + "ORDER BY m.title COLLATE NOCASE, m.file_path", args))


def get_media(uid: str) -> dict | None:
    return _one(conn().execute(_SELECT + "WHERE m.uuid=?", (uid,)))


def get_media_by_path(path: str) -> dict | None:
    return get_media(file_id(path))


def update_media(uid: str, **fields) -> None:
    """Write user-editable fields. Anything else (resolution, codec...) is rejected."""
    bad = set(fields) - set(EDITABLE)
    if bad:
        raise ValueError(f"read-only or unknown field(s): {', '.join(sorted(bad))}")
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    with _tx() as c:
        c.execute(f"UPDATE media_items SET {sets} WHERE uuid=?", (*fields.values(), uid))


def random_unwatched() -> dict | None:
    return _one(conn().execute(
        _SELECT + "WHERE m.media_type='movie' AND COALESCE(w.is_completed,0)=0 "
                  "AND COALESCE(w.last_position,0)=0 ORDER BY RANDOM() LIMIT 1"))


def _natkey(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def next_episode(uid: str) -> dict | None:
    cur = get_media(uid)
    if not cur or cur["media_type"] != "show":
        return None
    folder = os.path.dirname(cur["file_path"])
    rows = [r for r in _rows(conn().execute(
        "SELECT * FROM media_items WHERE media_type='show' AND parent_directory_id IS ?",
        (cur["parent_directory_id"],))) if os.path.dirname(r["file_path"]) == folder]
    rows.sort(key=lambda r: _natkey(os.path.basename(r["file_path"])))
    ids = [r["uuid"] for r in rows]
    i = ids.index(uid) + 1 if uid in ids else len(ids)
    return rows[i] if i < len(rows) else None



# ---------------------------------------------------------------- shows: one card per series

_EPISODE = re.compile(r"\s+S\d{1,2}E\d{1,3}\s*$", re.I)


def series_title(title: str) -> str:
    return _EPISODE.sub("", title)


def episode_suffix(title: str) -> str:
    m = _EPISODE.search(title)
    return m.group(0) if m else ""


def next_up(episodes: list[dict]) -> dict:
    """The episode to play for a series card: the one in progress, else the first unwatched, else the first."""
    started = [e for e in episodes if e["last_position"] and not e["is_completed"]]
    if started:
        return max(started, key=lambda e: e["last_watched"] or "")
    return next((e for e in episodes if not e["is_completed"]), episodes[0])


def episodes_in(folder: str) -> list[dict]:
    prefix = folder + os.sep
    rows = [r for r in _rows(conn().execute(_SELECT + "WHERE m.media_type='show' AND substr(m.file_path,1,?)=?",
                                            (len(prefix), prefix))) if os.path.dirname(r["file_path"]) == folder]
    return sorted(rows, key=lambda r: _natkey(os.path.basename(r["file_path"])))


def _by_release(films: list[dict]) -> list[dict]:
    return sorted(films, key=lambda f: (f["release_date"] or "9999", f["title"].lower()))


def list_library(dir_id: int | None = None, sets: bool | None = None) -> list[dict]:
    """Movies and clips one card each; every show folder collapses into ONE card; films of the same TMDB
    collection (two or more in this tab) collapse into ONE box-set card (unless turned off in Settings).

    Series cards carry key 'show:<folder>', box sets 'set:<collection id>'. Both play their next-up item.
    """
    if sets is None:
        sets = get_setting("group_collections", "1") == "1"
    cards, shows, boxes = [], {}, {}
    for r in list_media(dir_id):
        if r["media_type"] == "show":
            shows.setdefault(os.path.dirname(r["file_path"]), []).append(r)
        elif sets and r["media_type"] == "movie" and r.get("collection_id"):
            boxes.setdefault(r["collection_id"], []).append(r)
        else:
            cards.append({**r, "key": r["uuid"], "episodes": 0, "watched": 0, "films": 0})
    for folder, eps in shows.items():
        eps.sort(key=lambda r: _natkey(os.path.basename(r["file_path"])))
        cards.append({**next_up(eps), "key": "show:" + folder, "title": series_title(eps[0]["title"]),
                      "episodes": len(eps), "watched": sum(1 for e in eps if e["is_completed"]),
                      "is_completed": all(e["is_completed"] for e in eps), "films": 0})
    for cid, films in boxes.items():
        if len(films) < 2 and cid > 0:   # a lone film of a TMDB collection stays a normal card; your own sets always show
            cards.append({**films[0], "key": films[0]["uuid"], "episodes": 0, "watched": 0, "films": 0})
            continue
        films = _by_release(films)
        cards.append({**next_up(films), "key": f"set:{cid}", "title": films[0]["collection_name"] or films[0]["title"],
                      "episodes": 0, "films": len(films), "watched": sum(1 for f in films if f["is_completed"]),
                      "is_completed": all(f["is_completed"] for f in films),
                      "release_date": films[0]["release_date"], "added_at": max(f["added_at"] or "" for f in films)})
    return sorted(cards, key=lambda c: c["title"].lower())


def films_in_set(cid) -> list[dict]:
    return _by_release(_rows(conn().execute(_SELECT + "WHERE m.collection_id=? AND m.media_type='movie'", (int(cid),))))


def uuids_for(key: str) -> list[str]:
    if key.startswith("show:"):
        return [e["uuid"] for e in episodes_in(key[5:])]
    if key.startswith("set:"):
        return [f["uuid"] for f in films_in_set(key[4:])]
    return [key]


def box_sets() -> list[dict]:
    """Every box set in the library (from TMDB or made by you), with how many films it holds."""
    return _rows(conn().execute(
        "SELECT collection_id AS id, MAX(collection_name) AS name, COUNT(*) AS films FROM media_items "
        "WHERE collection_id IS NOT NULL AND media_type='movie' GROUP BY collection_id ORDER BY name COLLATE NOCASE"))


def new_set_id() -> int:
    """Sets you make get negative ids, so they never collide with TMDB collection ids."""
    low = conn().execute("SELECT MIN(collection_id) FROM media_items").fetchone()[0]
    return min(int(low or 0), 0) - 1


def add_to_set(uids, cid: int, name: str) -> None:
    with _tx() as c:
        c.executemany("UPDATE media_items SET collection_id=?, collection_name=? WHERE uuid=? AND media_type='movie'",
                      [(int(cid), name, u) for u in uids])


def remove_from_set(uids) -> None:
    with _tx() as c:
        c.executemany("UPDATE media_items SET collection_id=NULL, collection_name=NULL WHERE uuid=?", [(u,) for u in uids])


def set_cast(owner: str, people: list[dict]) -> None:
    """people: [{"id", "name", "role"}] in billing order (replaces what was there)."""
    with _tx() as c:
        c.execute("DELETE FROM cast_members WHERE owner=?", (owner,))
        c.executemany("INSERT INTO cast_members (owner, ord, person_id, name, role) VALUES (?,?,?,?,?)",
                      [(owner, i, p.get("id"), p["name"], p.get("role") or "") for i, p in enumerate(people) if p.get("name")])


def get_cast(owner: str) -> list[dict]:
    return _rows(conn().execute("SELECT person_id, name, role FROM cast_members WHERE owner=? ORDER BY ord", (owner,)))


def cast_owner(item: dict) -> str:
    """Where a title's cast is kept: per series (all episodes share it), else per file."""
    return "show:" + os.path.dirname(item["file_path"]) if item["media_type"] == "show" else item["uuid"]


def rename_collection(cid, name: str) -> None:
    with _tx() as c:
        c.execute("UPDATE media_items SET collection_name=? WHERE collection_id=?", (name, int(cid)))


def set_score(uids, score) -> None:
    with _tx() as c:
        c.executemany("UPDATE media_items SET score=? WHERE uuid=?", [(score, u) for u in uids])


# View More: the sections in the right pane, in the order shown (Settings > Appearance > View More layout)
DETAIL_SECTIONS = (("title", "Title"), ("rating", "Star ratings"), ("meta", "File details"), ("synopsis", "Synopsis"),
                   ("cast", "Actors"), ("gallery", "Gallery"), ("tags", "Tags"), ("boxset", "Box set"), ("notes", "Private notes"),
                   ("list", "Episodes / films"))


def detail_order() -> list[str]:
    """The saved order, with any section it does not mention (added in a later version) kept at its default place."""
    ids = [k for k, _ in DETAIL_SECTIONS]
    saved = [k for k in (get_setting("detail_order", "") or "").split(",") if k in ids]
    for i, k in enumerate(ids):
        if k not in saved:   # goes right after the section it follows by default
            before = next((p for p in reversed(ids[:i]) if p in saved), None)
            saved.insert(saved.index(before) + 1 if before else 0, k)
    return saved


def set_match(uids, release_date: str | None, synopsis: str | None, tmdb_id, collection_id, collection_name,
              genres=()) -> None:
    """Fix match: write what TMDB says about the chosen title onto these items (titles are set by the caller,
    so series keep their SxxEyy) and replace their genre tags. Your own tags, rating and notes stay."""
    uids = list(uids)
    with _tx() as c:
        c.executemany("UPDATE media_items SET release_date=?, synopsis=?, tmdb_id=?, collection_id=?, collection_name=? "
                      "WHERE uuid=?", [(release_date, synopsis, tmdb_id, collection_id, collection_name, u) for u in uids])
        c.executemany("DELETE FROM tags WHERE media_uuid=? AND tag_name LIKE 'genre:%'", [(u,) for u in uids])
        c.executemany("INSERT INTO tags (media_uuid, tag_name) VALUES (?,?)", [(u, f"genre:{g}") for u in uids for g in genres])


def rename_series(folder: str, name: str) -> None:
    """Rename a series: every episode keeps its own SxxEyy suffix."""
    with _tx() as c:
        for e in episodes_in(folder):
            c.execute("UPDATE media_items SET title=? WHERE uuid=?", (name + episode_suffix(e["title"]), e["uuid"]))


def set_synopsis_many(uids, text: str) -> None:
    with _tx() as c:
        c.executemany("UPDATE media_items SET synopsis=? WHERE uuid=?", [(text, u) for u in uids])


def remove_tag_many(uids, name: str) -> None:
    with _tx() as c:
        c.executemany("DELETE FROM tags WHERE media_uuid=? AND tag_name=?", [(u, name) for u in uids])


def set_rating_many(uids, stars: int) -> None:
    for u in uids:
        set_rating(u, stars)


# ---------------------------------------------------------------- tags / rating / notes

def search_index() -> dict[str, dict]:
    """uuid -> {"genres": [...], "tags": [...], "rating": n, "note": "..."} in three queries, for search and filters."""
    out: dict[str, dict] = {}
    def get(u):
        return out.setdefault(u, {"genres": [], "tags": [], "rating": 0, "note": ""})
    for r in conn().execute("SELECT media_uuid, tag_name FROM tags"):
        t = r["tag_name"]
        if t.startswith("genre:"):
            get(r["media_uuid"])["genres"].append(t[6:])
        elif t.startswith("rating:"):
            get(r["media_uuid"])["rating"] = int(t[7:] or 0)
        else:
            get(r["media_uuid"])["tags"].append(t)
    for r in conn().execute("SELECT media_uuid, notes_text FROM custom_notes"):
        get(r["media_uuid"])["note"] = r["notes_text"] or ""
    return out


def tags_for(uid: str) -> list[str]:
    return [r["tag_name"] for r in conn().execute(
        "SELECT tag_name FROM tags WHERE media_uuid=? ORDER BY tag_name COLLATE NOCASE", (uid,))]


def add_tag(uid: str, name: str) -> None:
    name = name.strip()
    if name:
        add_items([], [(uid, name)])


def remove_tag(uid: str, name: str) -> None:
    with _tx() as c:
        c.execute("DELETE FROM tags WHERE media_uuid=? AND tag_name=?", (uid, name))


def user_tags() -> list[str]:
    """Tags a person typed. `genre:` and `rating:` tags are written by the app."""
    return [r["t"] for r in conn().execute(
        "SELECT DISTINCT tag_name t FROM tags WHERE tag_name NOT LIKE 'genre:%' "
        "AND tag_name NOT LIKE 'rating:%' ORDER BY t COLLATE NOCASE")]


def set_rating(uid: str, stars: int) -> None:
    with _tx() as c:
        c.execute("DELETE FROM tags WHERE media_uuid=? AND tag_name LIKE 'rating:%'", (uid,))
        if stars:
            c.execute("INSERT INTO tags (media_uuid, tag_name) VALUES (?,?)", (uid, f"rating:{int(stars)}"))


def get_rating(uid: str) -> int:
    r = conn().execute("SELECT tag_name FROM tags WHERE media_uuid=? AND tag_name LIKE 'rating:%'",
                       (uid,)).fetchone()
    return int(r["tag_name"].split(":")[1]) if r else 0


def get_note(uid: str) -> str:
    r = conn().execute("SELECT notes_text FROM custom_notes WHERE media_uuid=?", (uid,)).fetchone()
    return r["notes_text"] or "" if r else ""


def set_note(uid: str, text: str) -> None:
    with _tx() as c:
        c.execute("INSERT INTO custom_notes (media_uuid, notes_text, last_edited) VALUES (?,?,?) "
                  "ON CONFLICT(media_uuid) DO UPDATE SET notes_text=excluded.notes_text, "
                  "last_edited=excluded.last_edited", (uid, text, _now()))


# ---------------------------------------------------------------- watch history / intro marks

def save_progress(uid: str, position: float, completed: bool) -> None:
    with _tx() as c:
        c.execute("INSERT INTO watch_history (media_uuid, profile_id, last_position, last_watched, is_completed) "
                  "VALUES (?,?,?,?,?) ON CONFLICT(media_uuid) DO UPDATE SET "
                  "last_position=excluded.last_position, last_watched=excluded.last_watched, "
                  "is_completed=excluded.is_completed",
                  (uid, PROFILE, int(position), _now(), int(completed)))


def get_intro(show_key: str) -> tuple[float, float] | None:
    r = conn().execute("SELECT start_sec, end_sec FROM intro_marks WHERE show_key=?", (show_key,)).fetchone()
    return (r["start_sec"], r["end_sec"]) if r else None


def set_intro(show_key: str, start: float, end: float) -> None:
    with _tx() as c:
        c.execute("INSERT INTO intro_marks (show_key, start_sec, end_sec) VALUES (?,?,?) "
                  "ON CONFLICT(show_key) DO UPDATE SET start_sec=excluded.start_sec, end_sec=excluded.end_sec",
                  (show_key, start, end))


def get_credits(key: str) -> float | None:
    r = conn().execute("SELECT left_sec FROM credit_marks WHERE show_key=?", (key,)).fetchone()
    return r["left_sec"] if r else None


def set_credits(key: str, left_sec: float) -> None:
    with _tx() as c:
        c.execute("INSERT INTO credit_marks (show_key, left_sec) VALUES (?,?) "
                  "ON CONFLICT(show_key) DO UPDATE SET left_sec=excluded.left_sec", (key, float(left_sec)))


def ignored(kind: str) -> set[str]:
    return {r["issue_key"] for r in conn().execute("SELECT issue_key FROM ignored_issues WHERE kind=?", (kind,))}


def ignore_issue(kind: str, key: str) -> None:
    with _tx() as c:
        c.execute("INSERT OR IGNORE INTO ignored_issues (kind, issue_key) VALUES (?,?)", (kind, key))


def unignore_all() -> None:
    with _tx() as c:
        c.execute("DELETE FROM ignored_issues")


# ---------------------------------------------------------------- failed scrapes

def is_failed(h: str) -> bool:
    return conn().execute("SELECT 1 FROM failed_scrapes WHERE file_hash=?", (h,)).fetchone() is not None


def clear_failed(hashes) -> None:
    with _tx() as c:
        c.executemany("DELETE FROM failed_scrapes WHERE file_hash=?", [(h,) for h in hashes])


def mark_failed(hashes) -> None:
    with _tx() as c:
        c.executemany("INSERT OR IGNORE INTO failed_scrapes (file_hash, timestamp) VALUES (?,?)",
                      [(h, _now()) for h in hashes])


# ---------------------------------------------------------------- settings

def get_setting(key: str, default=None):
    r = conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(key: str, value) -> None:
    with _tx() as c:
        c.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def excluded_tags() -> list[str]:
    try:
        return list(json.loads(get_setting("analytics_excluded_tags", "[]")))
    except (ValueError, TypeError):
        return []


def set_excluded_tags(tags) -> None:
    set_setting("analytics_excluded_tags", json.dumps(sorted(set(tags))))


# ---------------------------------------------------------------- analytics / export / restore

def log_watch(uid: str, seconds: float) -> None:
    """Add really-watched seconds (time spent playing, not the furthest point reached) to today's total."""
    if seconds < 1:
        return
    with _tx() as c:
        c.execute("INSERT INTO watch_log (media_uuid, day, seconds) VALUES (?,?,?) "
                  "ON CONFLICT(media_uuid, day) DO UPDATE SET seconds=seconds+excluded.seconds",
                  (uid, datetime.now(timezone.utc).date().isoformat(), seconds))


def analytics(excluded=(), days: int = 7, excluded_dirs=()) -> dict:
    """Minutes watched per day, and top genres: rated genres first (average stars), then by watch time.
    Items carrying an excluded tag, or in an excluded folder, are left out of everything."""
    ex = list(excluded)
    skip = ""
    if ex:
        skip = ("AND NOT EXISTS (SELECT 1 FROM tags x WHERE x.media_uuid=l.media_uuid "
                f"AND x.tag_name IN ({','.join('?' * len(ex))})) ")
    dirs = [int(d) for d in excluded_dirs]
    if dirs:
        skip += ("AND NOT EXISTS (SELECT 1 FROM media_items mx WHERE mx.uuid=l.media_uuid "
                 f"AND mx.parent_directory_id IN ({','.join(str(d) for d in dirs)})) ")
    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=days - 1)).isoformat()
    per_day = {r["d"]: r["s"] for r in conn().execute(
        f"SELECT l.day d, SUM(l.seconds) s FROM watch_log l WHERE l.day >= ? {skip}GROUP BY d", (since, *ex))}
    series = [((today - timedelta(days=days - 1 - i)).isoformat(),
               round(per_day.get((today - timedelta(days=days - 1 - i)).isoformat(), 0) / 60)) for i in range(days)]
    genres = [(r["name"], round(r["secs"] / 60), round(r["rating"], 1) if r["rating"] else None)
              for r in conn().execute(
        f"SELECT substr(g.tag_name,7) name, SUM(l.seconds) secs, AVG(CAST(substr(r.tag_name,8) AS REAL)) rating "
        f"FROM watch_log l JOIN tags g ON g.media_uuid=l.media_uuid AND g.tag_name LIKE 'genre:%' "
        f"LEFT JOIN tags r ON r.media_uuid=l.media_uuid AND r.tag_name LIKE 'rating:%' "
        f"WHERE 1=1 {skip}GROUP BY name ORDER BY rating IS NULL, rating DESC, secs DESC LIMIT 5", ex)]
    total = conn().execute(f"SELECT COALESCE(SUM(l.seconds),0) s FROM watch_log l WHERE 1=1 {skip}", ex).fetchone()["s"]
    return {"days": series, "genres": genres, "total_minutes": round(total / 60)}


# ---------------------------------------------------------------- what the All tab and Insights leave out

def hidden(kind: str) -> list:
    """kind: all_dirs / all_tags (kept out of the All tab), insights_dirs (out of Insights). Insights' tags use
    excluded_tags() as before."""
    try:
        return list(json.loads(get_setting(f"hidden_{kind}", "[]")))
    except (TypeError, ValueError):
        return []


def set_hidden(kind: str, values) -> None:
    set_setting(f"hidden_{kind}", json.dumps(sorted(set(values), key=str)))


def visible_in_all(cards: list[dict], index: dict) -> list[dict]:
    """The All tab without the folders and tags you chose to keep out of it (each folder's own tab still shows them)."""
    dirs, tags = set(hidden("all_dirs")), set(hidden("all_tags"))
    if not (dirs or tags):
        return cards
    def shown(c):
        if c["parent_directory_id"] in dirs:
            return False
        info = index.get(c["uuid"], {})
        return not (tags & (set(info.get("tags", ())) | {"genre:" + g for g in info.get("genres", ())}))
    return [c for c in cards if shown(c)]


def export_user_data() -> dict:
    """Everything a person typed or produced: titles, tags, notes, history."""
    c = conn()
    return {
        "exported": _now(),
        "items": _rows(c.execute("SELECT uuid, file_path, title, synopsis, release_date FROM media_items")),
        "tags": _rows(c.execute("SELECT media_uuid, tag_name FROM tags")),
        "notes": _rows(c.execute("SELECT media_uuid, notes_text, last_edited FROM custom_notes")),
        "history": _rows(c.execute("SELECT * FROM watch_history")),
        "watch_log": _rows(c.execute("SELECT * FROM watch_log")),
        "intro_marks": _rows(c.execute("SELECT * FROM intro_marks")),
    }


def import_user_data(data: dict) -> dict:
    """Restore a backup. Only touches files that are in the library now; nothing is deleted."""
    known = {r["uuid"] for r in conn().execute("SELECT uuid FROM media_items")}
    count = {"items": 0, "tags": 0, "notes": 0, "history": 0}
    with _tx() as c:
        for i in data.get("items", []):
            if i.get("uuid") in known:
                c.execute("UPDATE media_items SET title=?, synopsis=?, release_date=? WHERE uuid=?",
                          (str(i.get("title") or ""), i.get("synopsis"), i.get("release_date"), i["uuid"]))
                count["items"] += 1
        for t in data.get("tags", []):
            if t.get("media_uuid") in known and isinstance(t.get("tag_name"), str):
                c.execute("INSERT INTO tags (media_uuid, tag_name) SELECT ?,? WHERE NOT EXISTS "
                          "(SELECT 1 FROM tags WHERE media_uuid=? AND tag_name=?)",
                          (t["media_uuid"], t["tag_name"], t["media_uuid"], t["tag_name"]))
                count["tags"] += 1
        for n in data.get("notes", []):
            if n.get("media_uuid") in known:
                c.execute("INSERT INTO custom_notes (media_uuid, notes_text, last_edited) VALUES (?,?,?) "
                          "ON CONFLICT(media_uuid) DO UPDATE SET notes_text=excluded.notes_text, "
                          "last_edited=excluded.last_edited", (n["media_uuid"], n.get("notes_text"), n.get("last_edited")))
                count["notes"] += 1
        for h in data.get("history", []):
            if h.get("media_uuid") in known:
                c.execute("INSERT INTO watch_history (media_uuid, profile_id, last_position, last_watched, is_completed) "
                          "VALUES (?,?,?,?,?) ON CONFLICT(media_uuid) DO UPDATE SET last_position=excluded.last_position, "
                          "last_watched=excluded.last_watched, is_completed=excluded.is_completed",
                          (h["media_uuid"], h.get("profile_id") or PROFILE, int(h.get("last_position") or 0),
                           h.get("last_watched") or _now(), int(h.get("is_completed") or 0)))
                count["history"] += 1
        for w in data.get("watch_log", []):
            if w.get("media_uuid") in known:
                c.execute("INSERT INTO watch_log (media_uuid, day, seconds) VALUES (?,?,?) "
                          "ON CONFLICT(media_uuid, day) DO UPDATE SET seconds=excluded.seconds",
                          (w["media_uuid"], w["day"], float(w["seconds"])))
        for m in data.get("intro_marks", []):
            c.execute("INSERT INTO intro_marks (show_key, start_sec, end_sec) VALUES (?,?,?) "
                      "ON CONFLICT(show_key) DO UPDATE SET start_sec=excluded.start_sec, end_sec=excluded.end_sec",
                      (m["show_key"], float(m["start_sec"]), float(m["end_sec"])))
    return count
