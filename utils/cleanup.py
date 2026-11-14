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
SUFFIXES = ("fanart.webp", "front.webp", "back.webp", "spine.webp", "discart.webp", "disc.webp", "banner.webp", "gallery", "webp")
YOURS = ("front.webp", "back.webp", "spine.webp", "disc.webp")          # box art you chose yourself
SERIES = "_series"


def _owners(name: str) -> list[tuple[str, str]]:
    """Every way to read an artwork name: "Movie.banner.webp" is the banner of "Movie", or the cover of a video
    called "Movie.banner". Art counts as used when any reading names a video in the library. [] for a name Media
    Vault never writes."""
    return [(name[: -len(s) - 1], s) for s in SUFFIXES if name.endswith("." + s) and len(name) > len(s) + 1]


def _size(p: Path) -> int:
    try:
        if p.is_dir():
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        return p.stat().st_size
    except OSError:
        return 0


def _yours(p: Path, suffix: str) -> bool:
    return suffix in YOURS


def _entries(folder: Path, keep_own: bool):
    """Each artwork file (or Gallery folder) in an asset folder, with what it belongs to. With keep_own, a Gallery
    folder is split into its files so your own images (c-*) can stay."""
    try:
        items = list(folder.iterdir())
    except OSError:
        return
    for p in items:
        owners = _owners(p.name)
        if not owners:
            continue
        stems, suffix = {o[0] for o in owners}, owners[0][1]
        if suffix == "gallery" and p.is_dir() and keep_own:
            for f in p.iterdir():
                yield f, stems, "gallery-c" if f.name.startswith("c-") else "gallery"
        else:
            yield p, stems, suffix


def plan(mode: str = "unused", keep_own: bool = True) -> list[tuple[Path, int]]:
    """What would be deleted: [(path, bytes)]. mode "unused" or "all"."""
    assert mode in ("unused", "all")
    out: list[tuple[Path, int]] = []

    def take(p: Path):
        out.append((p, _size(p)))

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
            folder = Path(here) / scraper.ASSET_DIR
            live, is_series = by_folder.get(os.path.normcase(here), set()), os.path.normcase(here) in series
            for p, stems, suffix in _entries(folder, keep_own):
                own = suffix == "gallery-c" or _yours(p, suffix)
                if mode == "all":
                    if not (keep_own and own):
                        take(p)
                elif not (stems & live or (SERIES in stems and is_series)):
                    take(p)

    # 2. the app cache: box sets, home videos, actor photos, 3D box cards
    cache = db.data_dir() / "cache"
    if cache.is_dir():
        uuids = {it["uuid"] for it in db.list_media()}
        clips = {it["uuid"] for it in db.list_media() if it["media_type"] == "clip"}
        sets = {f"set-{b['id']}" for b in db.box_sets()}
        people = {str(r[0]) for r in db.conn().execute("SELECT DISTINCT person_id FROM cast_members WHERE person_id IS NOT NULL")}
        for p, stems, suffix in _entries(cache, keep_own):
            own = suffix == "gallery-c" or _yours(p, suffix)
            if mode == "all":
                if not (keep_own and own):
                    take(p)
            elif not stems & (sets | clips):
                take(p)
        for p in (cache / "people").glob("*.webp") if (cache / "people").is_dir() else ():
            if mode == "all" or p.stem not in people:
                take(p)
        for p in (cache / "box").glob("*.png") if (cache / "box").is_dir() else ():
            owner = p.name.split("-front")[0].split("-back")[0]
            if mode == "all" or owner not in uuids:
                take(p)
    return out


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
    import shutil
    todo = plan(mode, keep_own)
    done = freed = 0
    parents = set()
    for i, (p, size) in enumerate(todo, 1):
        if not _allowed(p):
            continue
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
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
    """Settings: how much artwork there is, how much of it is unused, how much is yours."""
    every, unused, others = plan("all", keep_own=False), plan("unused"), plan("all", keep_own=True)
    total = sum(s for _, s in every)
    return {"total": total, "unused": sum(s for _, s in unused), "unusedCount": len(unused),
            "yours": total - sum(s for _, s in others)}
