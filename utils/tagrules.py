"""Tag rules: "if <field> <test> <value>, tag with <tag>". Yours, made in the Tag Manager (Settings > Library).

Rules, the tags worked out from folder and file names (autotag.py) and the age rating ("Rated PG-13") are all
"computed" tags, stored as "auto:<tag>". They are worked out again whenever the rules change or a folder is
re-tagged, so a rule you delete takes its tags with it. Tags you add by hand are never touched.

A rule: {"field": "file", "test": "contains", "value": "remux", "tag": "Remux", "on": true, "folders": []}
  field   one of FIELDS        test  one of TESTS        folders: library folder ids it applies to ([] = all)
"""
import json
import os
import re

import database as db
from utils import autotag

FIELDS = [  # id, label, kind ("text" or "number")
    ("file", "File name", "text"), ("folder", "Folder path", "text"), ("title", "Title", "text"),
    ("original", "Original title", "text"), ("genre", "Genre", "text"), ("tag", "Your tags", "text"),
    ("rating", "Age rating", "text"), ("resolution", "Resolution", "text"), ("codec", "Video codec", "text"),
    ("audio", "Audio", "text"), ("type", "Type (movie / show / clip)", "text"),
    ("year", "Year", "number"), ("minutes", "Length (minutes)", "number"), ("score", "Audience score (0-10)", "number"),
]
TESTS = [  # id, label, kinds it applies to
    ("contains", "contains", "text"), ("not_contains", "does not contain", "text"), ("is", "is", "text number"),
    ("is_not", "is not", "text number"), ("starts", "starts with", "text"), ("ends", "ends with", "text"),
    ("regex", "matches pattern", "text"), ("gt", "is more than", "number"), ("lt", "is less than", "number"),
]
_FIELD_IDS = {f for f, _, _ in FIELDS}
_TEST_IDS = {t for t, _, _ in TESTS}
SETTING = "tag_rules"


def load() -> list[dict]:
    try:
        rules = json.loads(db.get_setting(SETTING, "[]") or "[]")
    except (TypeError, ValueError):
        return []
    return [r for r in (clean(x) for x in rules if isinstance(x, dict)) if r]


def clean(r: dict) -> dict | None:
    """A rule as stored, or None when it cannot work (unknown field or test, no tag)."""
    field, test = r.get("field"), r.get("test")
    tag = str(r.get("tag") or "").strip().removeprefix(autotag.PREFIX)[:60]
    if field not in _FIELD_IDS or test not in _TEST_IDS or not tag:
        return None
    if test == "regex":
        try:
            re.compile(str(r.get("value") or ""))
        except re.error:
            return None
    return {"field": field, "test": test, "value": str(r.get("value") or "")[:200], "tag": tag,
            "on": r.get("on", True) is not False, "folders": [int(f) for f in r.get("folders") or [] if str(f).isdigit()]}


def save(rules: list[dict]) -> list[dict]:
    kept = [r for r in (clean(x) for x in rules) if r]
    db.set_setting(SETTING, json.dumps(kept))
    return kept


def _values(field: str, item: dict, info: dict) -> list:
    """What a rule tests, for one title. Lists (genres, tags) match when any element matches."""
    if field == "file":
        return [os.path.basename(item["file_path"])]
    if field == "folder":
        return [os.path.dirname(item["file_path"])]
    if field == "title":
        return [db.series_title(item["title"]) if item["media_type"] == "show" else item["title"]]
    if field == "original":
        return [t for t in (item.get("original_title"), item.get("romaji_title")) if t]
    if field == "genre":
        return list(info.get("genres", ()))
    if field == "tag":
        return [t for t in info.get("tags", ()) if not t.startswith(autotag.PREFIX)]
    if field == "rating":
        return [item.get("certification") or ""]
    if field == "resolution":
        return [item.get("resolution") or ""]
    if field == "codec":
        return [item.get("codec") or ""]
    if field == "audio":
        return [item.get("audio_layout") or ""]
    if field == "type":
        return [item["media_type"]]
    if field == "year":
        y = (item.get("release_date") or "")[:4]
        return [int(y)] if y.isdigit() else []
    if field == "minutes":
        return [round((item.get("duration") or 0) / 60)] if item.get("duration") else []
    if field == "score":
        return [item["score"]] if item.get("score") is not None else []
    return []


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def matches(rule: dict, item: dict, info: dict) -> bool:
    if not rule.get("on", True):
        return False
    if rule.get("folders") and item.get("parent_directory_id") not in rule["folders"]:
        return False
    want, test = rule["value"], rule["test"]
    values = _values(rule["field"], item, info)
    if test == "not_contains":
        return not any(want.casefold() in str(v).casefold() for v in values)
    if test == "is_not":
        return not any(str(v).casefold() == want.casefold() or (_num(v) is not None and _num(v) == _num(want)) for v in values)
    for v in values:
        if test in ("gt", "lt"):
            a, b = _num(v), _num(want)
            if a is not None and b is not None and (a > b if test == "gt" else a < b):
                return True
            continue
        s, w = str(v).casefold(), want.casefold()
        if (test == "contains" and w in s) or (test == "is" and (s == w or (_num(v) is not None and _num(v) == _num(want)))) \
                or (test == "starts" and s.startswith(w)) or (test == "ends" and s.endswith(w)) \
                or (test == "regex" and re.search(want, str(v), re.I)):
            return True
    return False


def computed_tags(item: dict, info: dict, root: str, rules: list[dict], names: bool = True) -> list[str]:
    """Every computed tag for one title, without the prefix: from names (optional), the age rating, then your rules."""
    out = autotag.tags_for(item["file_path"], root, item["media_type"] == "show") if names else []
    if item.get("certification"):
        out.append(f"Rated {item['certification']}")
    out += [r["tag"] for r in rules if matches(r, item, info)]
    seen, unique = set(), []
    for t in out:
        if t.casefold() not in seen:
            seen.add(t.casefold())
            unique.append(t)
    return unique


def preview(rule: dict) -> int:
    """How many titles a rule would tag now (a series counts once per episode file)."""
    r = clean(rule)
    if not r:
        return 0
    index = db.search_index()
    return sum(1 for it in db.list_media(None) if matches(r, it, index.get(it["uuid"], {})))


def retag_all(directories=None) -> int:
    """Work out every computed tag again (names, age rating, rules) for these folders (default: all). Returns
    titles with at least one computed tag."""
    rules = load()
    names = db.get_setting("auto_tags", "1") != "0"
    index = db.search_index()
    dirs = directories if directories is not None else db.list_directories()
    pairs, uids = [], []
    for d in dirs:
        for it in db.list_media(d["id"]):
            uids.append(it["uuid"])
            pairs += [(it["uuid"], autotag.PREFIX + t) for t in computed_tags(it, index.get(it["uuid"], {}), d["folder_path"], rules, names)]
    with db._tx() as c:
        c.executemany("DELETE FROM tags WHERE media_uuid=? AND tag_name LIKE 'auto:%'", [(u,) for u in uids])
        c.executemany("INSERT INTO tags (media_uuid, tag_name) VALUES (?,?)", pairs)
    return len({u for u, _ in pairs})
