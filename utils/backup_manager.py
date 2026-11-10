"""Weekly JSON export of titles, tags, notes and history (keeps the newest 8) and restore from one."""
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import database as db

log = logging.getLogger(__name__)
INTERVAL = timedelta(days=7)
KEEP = 8


def backup_dir() -> Path:
    return db.data_dir() / "backups"


def run_backup() -> Path:
    folder = backup_dir()
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"vault-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(db.export_user_data(), indent=1), encoding="utf-8")
    db.set_setting("last_backup", datetime.now(timezone.utc).isoformat())
    for old in sorted(folder.glob("vault-*.json"))[:-KEEP]:
        old.unlink()
    return out


def list_backups() -> list[Path]:
    return sorted(backup_dir().glob("vault-*.json"), reverse=True)


def restore_backup(path) -> dict:
    """Merge a backup into the library. Returns how many titles, tags, notes and history rows were applied."""
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("backup file is unexpectedly large")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not a Media Vault backup")
    return db.import_user_data(data)


def is_due() -> bool:
    last = db.get_setting("last_backup")
    if not last:
        return True
    return datetime.now(timezone.utc) - datetime.fromisoformat(last) >= INTERVAL


def start() -> threading.Thread:
    """Daemon thread: checks every 6 hours, so a backup lands within a week even if the app stays open."""
    def loop():
        stop = threading.Event()
        while True:
            try:
                if is_due():
                    run_backup()
            except Exception:
                log.exception("backup failed")
            stop.wait(6 * 3600)

    t = threading.Thread(target=loop, daemon=True, name="backup")
    t.start()
    return t


# ------------------------------------------------------------ portable backups (move to another PC, or keep safe)
# A .mvault file is a zip: manifest.json, the database (settings included), and every artwork folder
# (.vault-assets next to the media, plus the app's own cache). Restoring swaps the database at the next start,
# so nothing has to be swapped under a running library.

import os
import shutil
import sqlite3
import tempfile
import zipfile

PORTABLE_VERSION = 1
MAX_PORTABLE = 8 * 2 ** 30       # refuse anything bigger than 8 GB
_ART_EXT = (".webp", ".png", ".jpg", ".jpeg")


def pending_restore_path() -> Path:
    return db.data_dir() / "restore-pending.db"


def _art_folders() -> list[Path]:
    from utils import scraper
    folders = {scraper._assets(it) for it in db.list_media(None)}
    folders.add(db.data_dir() / "cache")
    return sorted(f for f in folders if f.is_dir())


def export_portable(dest) -> dict:
    """Write a portable backup to `dest`. Returns counts."""
    dest = Path(dest)
    art = _art_folders()
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "media_vault.db"
        src = sqlite3.connect(db.db_path())
        out = sqlite3.connect(copy)
        with out:
            src.backup(out)          # a consistent copy, even while the library is in use
        src.close()
        out.close()
        manifest = {"app": "Media Vault", "version": PORTABLE_VERSION, "exported": datetime.now(timezone.utc).isoformat(),
                    "art": []}
        files = 0
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(copy, "media_vault.db")
            for i, folder in enumerate(art):
                names = [p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _ART_EXT]
                manifest["art"].append({"index": i, "folder": str(folder), "files": names})
                for n in names:
                    z.write(folder / n, f"art/{i}/{n}")
                    files += 1
            z.writestr("manifest.json", json.dumps(manifest, indent=1))
    return {"folders": len(art), "files": files, "bytes": dest.stat().st_size}


def import_portable(src) -> dict:
    """Check a portable backup, put its artwork back where those folders exist on this PC, and stage its
    database to replace the current one at the next start (the current one is kept in backups/)."""
    src = Path(src)
    if src.stat().st_size > MAX_PORTABLE:
        raise ValueError("file is too large to be a Media Vault backup")
    with zipfile.ZipFile(src) as z:
        names = set(z.namelist())
        if "manifest.json" not in names or "media_vault.db" not in names:
            raise ValueError("not a Media Vault portable backup")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("app") != "Media Vault" or int(manifest.get("version", 0)) > PORTABLE_VERSION:
            raise ValueError("backup is from an unknown or newer version")
        # the database must open and look like ours before anything is written
        with tempfile.TemporaryDirectory() as tmp:
            z.extract("media_vault.db", tmp)
            probe = sqlite3.connect(Path(tmp) / "media_vault.db")
            try:
                tables = {r[0] for r in probe.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"media_items", "scanned_directories", "settings"} <= tables:
                    raise ValueError("backup database is not a Media Vault library")
                roots = [os.path.normcase(os.path.normpath(r[0])) for r in probe.execute("SELECT folder_path FROM scanned_directories")]
            finally:
                probe.close()
            shutil.copy2(Path(tmp) / "media_vault.db", pending_restore_path())
        restored, skipped = 0, 0
        for entry in manifest.get("art", []):
            folder = Path(str(entry.get("folder", "")))
            # only into the app's own cache, or the artwork folder of a library folder that exists on this PC
            if folder.name == "cache":
                folder = db.data_dir() / "cache"
                target_ok = True
            else:
                parent = os.path.normcase(os.path.normpath(str(folder.parent)))
                target_ok = folder.name == ".vault-assets" and folder.parent.is_dir() and any(
                    parent == r or parent.startswith(r + os.sep) for r in roots)
            for n in entry.get("files", []):
                arc = f"art/{int(entry.get('index', -1))}/{n}"
                if not target_ok or "/" in n or "\\" in n or n.startswith(".") or Path(n).suffix.lower() not in _ART_EXT \
                        or arc not in names:
                    skipped += 1
                    continue
                folder.mkdir(exist_ok=True)
                with z.open(arc) as fin, open(folder / n, "wb") as fout:
                    shutil.copyfileobj(fin, fout)
                restored += 1
    return {"art": restored, "skipped": skipped}


def apply_pending_restore() -> bool:
    """At start-up, before the database is opened: swap in a staged portable backup. The old database is kept."""
    staged = pending_restore_path()
    if not staged.exists():
        return False
    current = Path(db.db_path())
    if current.exists():
        backup_dir().mkdir(parents=True, exist_ok=True)
        shutil.copy2(current, backup_dir() / f"before-restore-{datetime.now():%Y%m%d-%H%M%S}.db")
    for extra in ("-wal", "-shm"):
        Path(str(current) + extra).unlink(missing_ok=True)
    os.replace(staged, current)
    return True
