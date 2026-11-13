"""Long jobs report here (scraping, downloading artwork, component downloads); the dashboard shows each one as a
progress pill under the top bar. Plain Python, no Qt: watcher, scraper and setup call it from any thread.

    with progress.task("Scraping TV Shows", total=len(files)) as t:
        for f in files:
            ...
            t.step(detail=f.name)

total 0 = indeterminate (a moving bar). Updates are throttled so a fast loop does not flood the interface.
"""
import itertools
import threading
import time
from contextlib import contextmanager

_ids = itertools.count(1)
_listeners: list = []
_lock = threading.Lock()
THROTTLE = 0.08        # seconds between updates of one job (start, phase changes and the end always go out)


def subscribe(fn) -> None:
    """fn(event: dict) is called (on the reporting thread) with {id, label, detail, done, total, unit, state}."""
    with _lock:
        _listeners.append(fn)


def unsubscribe(fn) -> None:
    with _lock:
        if fn in _listeners:
            _listeners.remove(fn)


def _emit(event: dict) -> None:
    with _lock:
        targets = list(_listeners)
    for fn in targets:
        try:
            fn(dict(event))
        except Exception:
            pass


class Task:
    def __init__(self, label: str, total: int = 0, unit: str = ""):
        self.id, self.label, self.total, self.unit = next(_ids), label, int(total or 0), unit
        self.done, self.detail, self.state = 0, "", "running"
        self._sent = 0.0

    def _event(self) -> dict:
        return {"id": self.id, "label": self.label, "detail": self.detail, "done": self.done, "total": self.total,
                "unit": self.unit, "state": self.state}

    def _send(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._sent >= THROTTLE:
            self._sent = now
            _emit(self._event())

    def step(self, n: int = 1, detail: str | None = None) -> None:
        self.done = min(self.done + n, self.total) if self.total else self.done + n
        if detail is not None:
            self.detail = detail
        self._send(force=bool(self.total) and self.done >= self.total)

    def update(self, done: int | None = None, total: int | None = None, detail: str | None = None,
               label: str | None = None) -> None:
        """A new phase (label), or an absolute position (bytes downloaded)."""
        phase = label is not None and label != self.label
        if label is not None:
            self.label = label
        if total is not None:
            self.total = int(total)
        if done is not None:
            self.done = int(done)
        if detail is not None:
            self.detail = detail
        self._send(force=phase)

    def finish(self, ok: bool = True, detail: str | None = None) -> None:
        if self.state != "running":
            return
        self.state = "done" if ok else "failed"
        if self.total and ok:
            self.done = self.total
        if detail is not None:
            self.detail = detail
        self._send(force=True)


@contextmanager
def task(label: str, total: int = 0, unit: str = ""):
    """A job from start to end. An exception marks it failed (and still propagates)."""
    t = Task(label, total, unit)
    t._send(force=True)
    try:
        yield t
    except BaseException:
        t.finish(ok=False)
        raise
    t.finish()
