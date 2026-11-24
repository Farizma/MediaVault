"""Card pictures, ready before you get to them.

A cover saved at High quality is up to 1200 x 1800; a card draws it at 400 x 600. Shrinking it each time a card
scrolls into view is what made big libraries load as you browsed. Now:

- `image://card/<id>` serves a picture at the size the card asks for (its sourceSize);
- the first time, it is shrunk once (smoothly) and a small copy is kept in cache/cards (about 25 KB);
- the pictures drawn most recently stay decoded in memory (up to RAM_BYTES), so going back is instant;
- at startup, `warm()` makes the small copies for the whole library in the background and loads the first
  screen of every tab into memory.

A request with no size, or a big one (View More, the DVD box), is served from the original without a copy.
"""
import base64
import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtQml import QQmlImageProviderBase
from PySide6.QtQuick import QQuickImageProvider

import database as db

log = logging.getLogger(__name__)

PREFIX = "image://card/"
MAX_SIDE = 1100             # larger requests are not cards: no small copy is kept (a card is 400 x 600 times display scaling)
RAM_BYTES = 1024 << 20      # decoded pictures kept in memory (about 1,000 cards)
FIRST_SCREEN = 48           # cards per tab loaded into memory at startup


def url(path, mtime=None) -> str:
    """image://card/ address for a picture file (mtime: from a listing, so a changed picture gets a new address)."""
    if not path:
        return ""
    p = os.fspath(path)
    if mtime is None:
        try:
            mtime = os.stat(p).st_mtime_ns
        except OSError:
            mtime = 0
    return PREFIX + base64.urlsafe_b64encode(f"{p}|{mtime}".encode("utf-8")).decode("ascii")


def parse(ident: str) -> tuple[str, int]:
    """(path, mtime) from what follows image://card/ (anything after '?' is ignored)."""
    raw = ident.split("?")[0].split("/")[-1]
    try:
        path, _, mtime = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8").rpartition("|")
        return path, int(mtime or 0)
    except (ValueError, UnicodeDecodeError):
        return "", 0


def local_path(u: str) -> str:
    """The file behind a card address or a file:// URL."""
    if u.startswith(PREFIX):
        return parse(u[len(PREFIX):])[0]
    from PySide6.QtCore import QUrl
    return QUrl(u).toLocalFile()


def folder() -> Path:
    return db.data_dir() / "cache" / "cards"


def fit(w: int, h: int, want_w: int, want_h: int) -> QSize:
    """The size that covers want_w x want_h keeping the picture's shape (a card crops what is left over);
    one side 0 or less: that side follows the other."""
    if want_w <= 0 and want_h <= 0:
        return QSize(w, h)
    if want_w <= 0:
        s = want_h / h
    elif want_h <= 0:
        s = want_w / w
    else:
        s = max(want_w / w, want_h / h)
    s = min(1.0, s)                           # never enlarged
    return QSize(max(1, round(w * s)), max(1, round(h * s)))


def _small(path: str, mtime: int, w: int, h: int) -> Path:
    tag = hashlib.sha1(f"{os.path.normcase(path)}|{mtime}|{w}x{h}".encode("utf-8")).hexdigest()[:24]
    return folder() / tag[:2] / f"{tag}.webp"


def decode(path: str, w: int, h: int) -> QImage:
    """The picture shrunk smoothly to cover w x h (0 x 0: as it is)."""
    r = QImageReader(path)
    r.setAutoTransform(True)
    img = r.read()
    if img.isNull():
        return img
    size = fit(img.width(), img.height(), w, h)
    if size != img.size():
        img = img.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return img


class Cache:
    def __init__(self, budget: int = RAM_BYTES):
        self.budget = budget
        self._ram: OrderedDict = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, path: str, mtime: int, w: int, h: int, keep: bool = True) -> QImage:
        key = (path, mtime, w, h)
        with self._lock:
            img = self._ram.get(key)
            if img is not None:
                self._ram.move_to_end(key)
                return img
        img = self._load(path, mtime, w, h)
        if keep and not img.isNull():
            self._keep(key, img)
        return img

    def has_copy(self, path: str, mtime: int, w: int, h: int) -> bool:
        return _small(path, mtime, w, h).exists()

    def _load(self, path: str, mtime: int, w: int, h: int) -> QImage:
        if not (0 < max(w, h) <= MAX_SIDE):
            return decode(path, w, h)
        small = _small(path, mtime, w, h)
        if small.exists():
            img = QImage(str(small))
            if not img.isNull():
                return img
        img = decode(path, w, h)
        if not img.isNull():
            try:
                small.parent.mkdir(parents=True, exist_ok=True)
                tmp = small.with_name(f"{small.stem}.{threading.get_ident()}.tmp.webp")
                if img.save(str(tmp), "WEBP", 88):
                    os.replace(tmp, small)         # whole or not at all (two threads may make the same one)
                else:
                    tmp.unlink(missing_ok=True)
            except OSError:
                log.debug("card copy %s", small, exc_info=True)
        return img

    def _keep(self, key, img: QImage) -> None:
        cost = img.sizeInBytes()
        with self._lock:
            if key in self._ram:
                return
            self._ram[key] = img
            self._bytes += cost
            while self._bytes > self.budget and len(self._ram) > 1:
                _, old = self._ram.popitem(last=False)
                self._bytes -= old.sizeInBytes()

    def clear(self) -> None:
        with self._lock:
            self._ram.clear()
            self._bytes = 0


CACHE = Cache()


class CardProvider(QQuickImageProvider):
    """image://card/<id>: on Qt's image threads (never the interface's)."""

    def __init__(self, cache: Cache = CACHE):
        super().__init__(QQmlImageProviderBase.ImageType.Image, QQmlImageProviderBase.Flag.ForceAsynchronousImageLoading)
        self.cache = cache

    def requestImage(self, ident, size, requested):
        path, mtime = parse(ident)
        img = QImage()
        if path:
            try:
                img = self.cache.get(path, mtime, max(0, requested.width()), max(0, requested.height()))
            except Exception:
                log.warning("card picture %s", path, exc_info=True)
        if img.isNull():
            img = QImage(1, 1, QImage.Format.Format_ARGB32)
            img.fill(0)
        return img


# ---------------------------------------------------------------- startup: get everything ready
def warm(jobs: list[tuple[str, int, int, int, bool]], progress_task=None, workers: int = 0) -> dict:
    """jobs: (path, mtime, w, h, into_memory). Makes each missing small copy, and loads into memory the ones
    marked (the first screen of each tab). Runs on worker threads; returns counts for the log."""
    workers = workers or max(2, min(6, (os.cpu_count() or 4) // 2))
    made = loaded = 0
    lock = threading.Lock()
    t0 = time.monotonic()

    def one(job):
        nonlocal made, loaded
        path, mtime, w, h, keep = job
        fresh = not CACHE.has_copy(path, mtime, w, h)
        if fresh or keep:
            CACHE.get(path, mtime, w, h, keep=keep)
        with lock:
            made += fresh
            loaded += keep
        if progress_task:
            progress_task.step()

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="cards") as pool:
        list(pool.map(one, jobs))
    return {"pictures": len(jobs), "made": made, "in_memory": loaded, "seconds": round(time.monotonic() - t0, 1)}
