"""Find subtitles online (the player's Audio & Subtitles panel > "Find subtitles online"): OpenSubtitles' REST API,
with your own free API key (Settings > Integrations & APIs). One request to search, one to get the download link.
The file is saved in the hidden .vault-assets folder next to the video, never over anything of yours."""
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import version

API = "https://api.opensubtitles.com/api/v1"
MAX_SUB = 5 * 1024 * 1024


class SubtitleError(Exception):
    pass


def _call(path: str, key: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(f"{API}/{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Api-Key": key, "User-Agent": f"MediaVault v{version.VERSION}",
                                          "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read(2 << 20))
    except urllib.error.HTTPError as e:
        why = {401: "OpenSubtitles rejected the API key", 403: "OpenSubtitles rejected the API key",
               406: "OpenSubtitles' download limit for today is used up", 429: "OpenSubtitles is busy: try again in a moment"}
        raise SubtitleError(why.get(e.code, f"OpenSubtitles answered {e.code}")) from None
    except Exception as e:
        raise SubtitleError(f"OpenSubtitles could not be reached ({type(e).__name__})") from None


def search(key: str, title: str, language: str = "en", tmdb_id=None, season=None, episode=None, show: bool = False) -> list[dict]:
    """Best first: [{file_id, release, downloads}]. By TMDB id when the title is matched, else by name."""
    q = {"languages": language, "order_by": "download_count", "order_direction": "desc"}
    if tmdb_id:
        q["parent_tmdb_id" if show else "tmdb_id"] = int(tmdb_id)
    else:
        q["query"] = title
    if season is not None and episode is not None:
        q["season_number"], q["episode_number"] = int(season), int(episode)
    data = _call("subtitles?" + urllib.parse.urlencode(sorted(q.items())), key).get("data") or []
    out = []
    for d in data:
        at = d.get("attributes") or {}
        files = at.get("files") or []
        if files and files[0].get("file_id"):
            out.append({"file_id": files[0]["file_id"], "release": at.get("release") or files[0].get("file_name") or "",
                        "downloads": at.get("download_count") or 0})
    return out


def download(key: str, file_id: int, dest: Path) -> Path:
    link = _call("download", key, {"file_id": int(file_id)}).get("link") or ""
    if not link.startswith("https://"):
        raise SubtitleError("OpenSubtitles gave no download link")
    req = urllib.request.Request(link, headers={"User-Agent": f"MediaVault v{version.VERSION}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(MAX_SUB + 1)
    if len(data) > MAX_SUB:
        raise SubtitleError("that subtitle file is far too large")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest
