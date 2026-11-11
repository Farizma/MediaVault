"""Alternate titles, grouped the way View More lists them: English, Romanized, Native, then Other languages.

TMDB says which language each translation is in, so its titles go straight to their group. AniList's synonyms
carry no language, so they are sorted by their letters: the title's own script is Native, romaji-looking Latin
is Romanized, Latin with English words is English, and everything else (French, Spanish, Russian, Thai, ...) is
Other languages.
"""
import json
import re

GROUPS = ("english", "romanized", "native", "other")
LIMITS = {"english": 6, "romanized": 6, "native": 4, "other": 30}

_KANA = re.compile(r"[぀-ヿㇰ-ㇿｦ-ﾟ]")
_HAN = re.compile(r"[㐀-鿿豈-﫿]")
_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
_LATIN_ONLY = re.compile(r"^[\x00-\x7fÀ-ɏḀ-ỿ -⁯←-⇿☀-➿]+$")
_LETTER = re.compile(r"[^\W\d_]")
# a romaji syllable: optional consonant(s) then vowels, or a syllable-final n (long vowels and doubled consonants too)
_ROMAJI_WORD = re.compile(r"^(?:(?:[kgsztdnhbpmyrwjf]|sh|ch|ts|[kgnhbpmr]y)?[aeiouāēīōū]+|n|(?<=[aeiou])[kstpgc](?=[kstpgc]))+$")
_ENGLISH = {"the", "of", "and", "a", "an", "to", "in", "on", "for", "with", "my", "your", "is", "are", "from", "at",
            "by", "into", "who", "what", "when", "how", "i", "me", "you", "our", "his", "her", "this", "that", "be",
            "it", "as", "not", "no", "one", "all", "love", "girl", "boy", "world", "story", "animation", "life"}
_NOT_ENGLISH = {"le", "la", "les", "de", "del", "des", "du", "el", "los", "las", "il", "di", "der", "die", "das",
                "und", "et", "och", "og", "och", "y", "e", "una", "uno", "ein", "eine", "het", "een", "na", "do", "da"}


def _words(t: str) -> list[str]:
    return [w for w in re.split(r"[\s\-:;,.!?~/()\[\]\"']+", t.lower()) if w]


def _romaji(t: str) -> bool:
    words = [w for w in _words(t) if _LETTER.search(w)]
    if len(words) < 2 or not t.isascii():
        return False
    hits = sum(1 for w in words if _ROMAJI_WORD.match(w))
    return hits / len(words) >= 0.8


def _english(t: str) -> bool:
    words = set(_words(t))
    return t.isascii() and bool(words & _ENGLISH) and not (words & _NOT_ENGLISH) and not _romaji(t)


def classify(title: str, native: str = "", japanese: bool = False) -> str:
    """Which group an unlabelled title belongs to, given the title in its own language (native). japanese: the
    source is Japanese (AniList), so kana is always Native, even when AniList's native title is in Latin letters."""
    if _KANA.search(title) or _HANGUL.search(title):
        same = (_KANA.search(title) and (japanese or _KANA.search(native))) or (_HANGUL.search(native) and _HANGUL.search(title))
        return "native" if same else "other"
    if _HAN.search(title):              # Chinese characters alone: Native for a Chinese title, else (for a Japanese
        return "native" if native and not _KANA.search(native) and _HAN.search(native) else "other"   # one) Chinese
    if not _LATIN_ONLY.match(title):
        return "other"                  # Cyrillic, Greek, Hebrew, Arabic, Thai, ...
    if _romaji(title):
        return "romanized"
    if _english(title):
        return "english"
    return "other"


def _add(groups: dict, group: str, title: str) -> None:
    title = " ".join((title or "").split())
    if len(title) < 2 or (len(title) <= 3 and title.isupper()):      # "OP", "SAO": a nickname, not a title
        return
    seen = {t.casefold() for g in GROUPS for t in groups[g]}
    if title.casefold() not in seen and len(groups[group]) < LIMITS[group]:
        groups[group].append(title)


def empty() -> dict:
    return {g: [] for g in GROUPS}


def from_anilist(title: dict, synonyms) -> dict:
    """AniList: its English, romaji and native titles, then every synonym sorted into a group."""
    title = title or {}
    groups = empty()
    native = title.get("native") or ""
    _add(groups, "english", title.get("english") or "")
    _add(groups, "romanized", title.get("romaji") or "")
    _add(groups, "native", native)
    for s in synonyms or []:
        _add(groups, classify(s, native, japanese=not _HANGUL.search(native) and not (_HAN.search(native) and not _KANA.search(native))), s)
    return groups


_ENGLISH_COUNTRIES = {"US", "GB", "CA", "AU", "NZ", "IE"}


def from_tmdb(r: dict) -> dict:
    """TMDB: the original title (Native), translations by language, and alternative titles (Romaji ones by type)."""
    groups = empty()
    orig_lang = r.get("original_language") or ""
    original = r.get("original_title") or r.get("original_name") or ""
    _add(groups, "english" if orig_lang == "en" else "native", original)
    if orig_lang != "en":
        _add(groups, "english", r.get("title") or r.get("name") or "")
    for t in ((r.get("translations") or {}).get("translations") or []):
        name = (t.get("data") or {}).get("title") or (t.get("data") or {}).get("name") or ""
        lang = t.get("iso_639_1")
        _add(groups, "english" if lang == "en" else "native" if lang == orig_lang else "other", name)
    alts = r.get("alternative_titles") or {}
    for a in alts.get("titles") or alts.get("results") or []:
        kind = (a.get("type") or "").lower()
        name = a.get("title") or ""
        if "roma" in kind:
            _add(groups, "romanized", name)
        elif a.get("iso_3166_1") in _ENGLISH_COUNTRIES and name.isascii():
            _add(groups, "english", name)
        else:
            _add(groups, classify(name, original), name)
    return groups


def dumps(groups: dict | None) -> str | None:
    if not groups or not any(groups.get(g) for g in GROUPS):
        return None
    return json.dumps({g: groups.get(g) or [] for g in GROUPS}, ensure_ascii=False)


def loads(text: str | None) -> dict:
    try:
        v = json.loads(text or "{}")
        return {g: [str(t) for t in v.get(g) or []] for g in GROUPS}
    except (TypeError, ValueError, AttributeError):
        return empty()


def for_display(text: str | None, shown: tuple = ()) -> list[dict]:
    """[{"group", "label", "titles"}] for View More, leaving out the titles already shown above it."""
    hide = {s.casefold() for s in shown if s}
    labels = {"english": "English", "romanized": "Romanized", "native": "Native", "other": "Other languages"}
    out = []
    for g in GROUPS:
        titles = [t for t in loads(text)[g] if t.casefold() not in hide]
        if titles:
            out.append({"group": g, "label": labels[g], "titles": titles})
    return out


def haystack(text: str | None) -> str:
    return " ".join(t for g in loads(text).values() for t in g)
