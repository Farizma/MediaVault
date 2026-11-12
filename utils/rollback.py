"""Roll back an update. Before libmpv, libVLC or the shader is updated, the version on this PC is copied to
bin/.previous/<id>/. Rolling back swaps the two (so rolling back again undoes it). The swap happens at the next
start, before any video engine is loaded: Windows will not replace a DLL that is in use.

Python packages (source installs only) keep just their previous version number; pip puts it back.
Media Vault itself rolls back by installing the previous release from GitHub (see utils.components).
"""
import json
import shutil
from pathlib import Path

# id -> files and folders in bin/ that make up that component
PARTS = {
    "libmpv": ["libmpv-2.dll", "mpv-2.dll", "mpv.version"],
    "libvlc": ["vlc"],
    "shader": ["shaders/FSRCNNX_x2_8-0-4-1.glsl"],
}


def _bin() -> Path:
    from utils import bin_dir
    return bin_dir()


def _write_bin() -> Path:
    from utils import writable_bin
    return writable_bin()


def _root() -> Path:
    return _bin() / ".previous"


def _meta(component: str) -> Path:
    return _root() / component / "previous.json"


def previous(component: str) -> str:
    """The version a rollback would bring back ("" when there is none)."""
    if component in PARTS:
        try:
            return json.loads(_meta(component).read_text(encoding="utf-8")).get("version") or "previous version"
        except (OSError, ValueError):
            return ""
    return _pip_versions().get(component, "")


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


def snapshot(component: str, installed: str) -> None:
    """Keep what is on this PC now, before it is replaced. Only the one previous version is kept."""
    if component not in PARTS:
        return
    _write_bin()             # Program Files: work in your own copy of bin/ from here on
    present = [p for p in PARTS[component] if (_bin() / p).exists()]
    if not present:
        return
    keep = _root() / component
    shutil.rmtree(keep, ignore_errors=True)
    for p in present:
        _copy(_bin() / p, keep / "files" / p)
    _meta(component).write_text(json.dumps({"version": installed}), encoding="utf-8")


def request(component: str, installed_now: str) -> None:
    """Ask for the swap at the next start (installed_now: the version being rolled back, kept for an undo)."""
    _write_bin()
    want = _pending_map()
    want[component] = installed_now
    _root().mkdir(parents=True, exist_ok=True)
    (_root() / "pending.json").write_text(json.dumps(want), encoding="utf-8")


def _pending_map() -> dict:
    try:
        v = json.loads((_root() / "pending.json").read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def pending() -> list[str]:
    return sorted(_pending_map())


def apply_pending() -> list[str]:
    """At start-up: swap each requested component with its kept copy. Returns the components rolled back."""
    done, busy = [], {}
    for component, current_version in _pending_map().items():
        keep = _root() / component
        if component not in PARTS or not (keep / "files").is_dir():
            continue
        swap = _root() / (component + ".swap")
        shutil.rmtree(swap, ignore_errors=True)
        try:
            for p in PARTS[component]:      # the current files go aside ...
                if (_bin() / p).exists():
                    (swap / "files" / p).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(_bin() / p), str(swap / "files" / p))
        except OSError:                     # still in use (another copy running): put them back, try next start
            for p in PARTS[component]:
                if (swap / "files" / p).exists() and not (_bin() / p).exists():
                    shutil.move(str(swap / "files" / p), str(_bin() / p))
            busy[component] = current_version
            continue
        for p in PARTS[component]:          # ... the kept ones come back ...
            if (keep / "files" / p).exists():
                (_bin() / p).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(keep / "files" / p), str(_bin() / p))
        shutil.rmtree(keep, ignore_errors=True)
        if (swap / "files").is_dir():       # ... and the ones taken out are the new "previous" (roll back again = undo)
            swap.rename(keep)
            _meta(component).write_text(json.dumps({"version": current_version or "newer version"}), encoding="utf-8")
        done.append(component)
    if busy:
        (_root() / "pending.json").write_text(json.dumps(busy), encoding="utf-8")
    else:
        (_root() / "pending.json").unlink(missing_ok=True)
    return done


# -- Python packages (running from source): only the version number is needed, pip fetches it again
def _pip_file() -> Path:
    return _root() / "pip.json"


def _pip_versions() -> dict:
    try:
        return json.loads(_pip_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember_pip(component: str, installed: str) -> None:
    if not installed:
        return
    v = _pip_versions()
    v[component] = installed.split(" ")[0]
    _pip_file().parent.mkdir(parents=True, exist_ok=True)
    _pip_file().write_text(json.dumps(v), encoding="utf-8")


def forget_pip(component: str) -> None:
    v = _pip_versions()
    v.pop(component, None)
    if _pip_file().parent.exists():
        _pip_file().write_text(json.dumps(v), encoding="utf-8")
