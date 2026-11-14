"""Settings > Library > Storage: find and delete artwork Media Vault saved that nothing uses any more, or all of it.

Artwork lives in a hidden ".vault-assets" folder next to the videos (covers, banners, discs, Gallery images, your own
box art) and in the app cache (box sets, home videos, actor photos, the text cards drawn for the 3D box). Only those
places are ever touched: never a video, never anything else in your folders.

"Unused": art for a video that is no longer in the library (deleted, renamed, moved), a series folder with no
episodes left, a box set or home video that is gone, an actor in no title's cast, a card for a title that is gone.
Files Media Vault does not recognise are left alone. A folder whose drive is unplugged is skipped (its titles are
still in the library, so their art is not unused).

"All": every piece of artwork, so the next Fetch missing (or Download images again) downloads it fresh; the art you
added yourself (your box art and Gallery images) can be kept.
"""
import os
from pathlib import Path

import database as db
from utils import scraper

# what follows a video's name in an artwork file name (".vault-assets/<video>.<this>")
SUFFIXES = ("still.webp", "fanart.webp", "front.webp", "back.webp", "spine.webp", "discart.webp", "disc.webp", "banner.webp", "gallery", "webp")
YOURS = ("front.webp", "back.webp", "spine.webp", "disc.webp")          # box art you chose yourself
SERIES = "_series"


def _owners(name: str) -> list[tuple[str, str]]:
    """Every way to read an artwork name: "Movie.banner.webp" is the banner of "Movie", or the cover of a video
    called "Movie.banner". Art counts as used when any reading names a video in the library. [] for a name Media
    Vault never writes."""
    if name.endswith(".srt") and name.count(".") >= 2:        # a downloaded subtitle: "<video>.<language>.srt"
        return [(name.rsplit(".", 2)[0], "srt")]
    return [(name[: -len(s) - 1], s) for s in SUFFIXES if name.endswith("." + s) and len(name) > len(s) + 1]


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _entries(folder: Path):
    """Each artwork file in an asset folder (a Gallery folder file by file), with the videos it could belong to."""
    try:
        items = list(folder.iterdir())
    except OSError:
        return
    for p in items:
        owners = _owners(p.name)
        if not owners:
            continue
        stems, suffix = {o[0] for o in owners}, owners[0][1]
        if suffix == "gallery" and p.is_dir():
            try:
                for f in p.iterdir():
                    yield f, stems, f.name.startswith("c-")
            except OSError:
                pass
        else:
            yield p, stems, suffix in YOURS


def scan() -> list[tuple[Path, int, bool, bool]]:
    """Every piece of artwork, in one pass over the folders: [(path, bytes, used, yours)]."""
    out = []
    # 1. the .vault-assets folders next to your videos
    for d in db.list_directories():
        root = d["folder_path"]
        if not os.path.isdir(root):
            continue                         # unplugged: its titles are still in the library
        by_folder: dict[str, set] = {}
        series: set = set()
        for it in db.list_media(d["id"]):
            if it["media_type"] == "clip":
                continue
            folder = os.path.normcase(os.path.dirname(it["file_path"]))
            by_folder.setdefault(folder, set()).add(Path(it["file_path"]).stem)
            if it["media_type"] == "show":
                series.add(folder)
        for here, dirs, _files in os.walk(root):
            if scraper.ASSET_DIR not in dirs:
                continue
            dirs.remove(scraper.ASSET_DIR)    # never walk into it as a library folder
            live, is_series = by_folder.get(os.path.normcase(here), set()), os.path.normcase(here) in series
            for p, stems, own in _entries(Path(here) / scraper.ASSET_DIR):
                out.append((p, _size(p), bool(stems & live or (SERIES in stems and is_series)), own))
    # 2. the app cache: box sets, home videos, actor photos, 3D box cards
    cache = db.data_dir() / "cache"
    if cache.is_dir():
        media = db.list_media()
        uuids = {it["uuid"] for it in media}
        owners = {it["uuid"] for it in media if it["media_type"] == "clip"} | {f"set-{b['id']}" for b in db.box_sets()}
        people = {str(r[0]) for r in db.conn().execute("SELECT DISTINCT person_id FROM cast_members WHERE person_id IS NOT NULL")}
        for p, stems, own in _entries(cache):
            out.append((p, _size(p), bool(stems & owners), own))
        for p in (cache / "people").glob("*.webp") if (cache / "people").is_dir() else ():
            out.append((p, _size(p), p.stem in people, False))
        for p in (cache / "box").glob("*.png") if (cache / "box").is_dir() else ():
            out.append((p, _size(p), p.name.split("-front")[0].split("-back")[0] in uuids, False))
    return out


def plan(mode: str = "unused", keep_own: bool = True, found=None) -> list[tuple[Path, int]]:
    """What would be deleted: [(path, bytes)]. mode "unused" or "all"."""
    assert mode in ("unused", "all")
    found = scan() if found is None else found
    if mode == "unused":
        return [(p, size) for p, size, used, _own in found if not used]
    return [(p, size) for p, size, _used, own in found if not (keep_own and own)]


def _allowed(p: Path) -> bool:
    """Only ever inside a .vault-assets folder or Media Vault's own cache."""
    cache = (db.data_dir() / "cache").resolve()
    try:
        rp = p.resolve()
    except OSError:
        return False
    return scraper.ASSET_DIR in rp.parts or rp.is_relative_to(cache)


def run(mode: str = "unused", keep_own: bool = True, step=lambda n, total: None) -> tuple[int, int]:
    """Delete what plan() lists. Returns (items deleted, bytes freed). Empty Gallery and asset folders go too."""
    todo = plan(mode, keep_own)
    done = freed = 0
    parents = set()
    for i, (p, size) in enumerate(todo, 1):
        if not _allowed(p):
            continue
        try:
            p.unlink()
            done, freed = done + 1, freed + size
            parents.add(p.parent)
        except OSError:
            pass
        step(i, len(todo))
    for folder in sorted(parents, key=lambda x: len(x.parts), reverse=True):     # Gallery folders, then asset folders
        for f in (folder, folder.parent):
            try:
                if _allowed(f) and f.name != "cache" and f.is_dir() and not any(f.iterdir()):
                    f.rmdir()
            except OSError:
                pass
    return done, freed


def usage() -> dict:
    """Settings: how much artwork there is, how much of it is unused, how much is yours (one pass over the disk)."""
    found = scan()
    unused = [size for _p, size, used, _own in found if not used]
    return {"total": sum(f[1] for f in found), "unused": sum(unused), "unusedCount": len(unused),
            "yours": sum(size for _p, size, _used, own in found if own)}
