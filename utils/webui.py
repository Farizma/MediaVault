"""The pages a phone (or any browser) sees: library, folders, a series or box set, the player. Liquid Glass styled:
frosted, see-through panels (the page's art shows through, blurred) with a bright rim, capsule controls.

Every value from the library is HTML-escaped; every address is built from library ids, never from a path.
Plain functions returning bytes; utils/streaming.py routes requests to them and checks who may ask.
"""
import html
import json
import os
import re
from urllib.parse import quote, urlencode

import database as db

CSS = """
:root{--glass:rgba(40,40,46,.42);--glass-hi:rgba(255,255,255,.16);--rim:rgba(255,255,255,.22);--txt:#F5F5F7;--dim:#9A9AA2}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{background:#000}
body{margin:0;color:var(--txt);font:15px/1.35 -apple-system,system-ui,'Segoe UI',sans-serif;-webkit-text-size-adjust:100%;
 min-height:100vh;padding-bottom:env(safe-area-inset-bottom)}
a{color:inherit;text-decoration:none}
/* the page's art, blurred, behind everything: what the glass has to show through */
.bg{position:fixed;inset:-40px;z-index:-1;background:#000 center/cover no-repeat;filter:blur(40px) saturate(1.4) brightness(.55);transform:translateZ(0)}
.bg.none{background:radial-gradient(120% 80% at 20% 0%,#1d2a4a 0%,#000 60%),radial-gradient(90% 70% at 100% 30%,#3a1d3f 0%,transparent 60%)}
/* Liquid Glass: frosted, a little see-through, a bright rim on top, a soft shadow under */
.glass{background:var(--glass);-webkit-backdrop-filter:blur(26px) saturate(180%);backdrop-filter:blur(26px) saturate(180%);
 border:1px solid var(--rim);box-shadow:inset 0 1px 0 var(--glass-hi),inset 0 -1px 0 rgba(0,0,0,.25),0 8px 30px rgba(0,0,0,.35)}
header{position:sticky;top:0;z-index:5;margin:0;padding:10px 14px;padding-top:max(10px,env(safe-area-inset-top));
 display:flex;gap:10px;align-items:center;border-width:0 0 1px;border-radius:0}
header .brand{font-weight:800;font-size:17px;letter-spacing:-.2px;white-space:nowrap}
header form{flex:1;display:flex}
header input{flex:1;min-width:0;font:inherit;font-size:15px;color:var(--txt);padding:9px 14px;border-radius:999px;outline:none;
 background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);box-shadow:inset 0 1px 0 rgba(255,255,255,.08)}
header input::placeholder{color:var(--dim)}
.back{font-size:15px;font-weight:600;padding:7px 13px;border-radius:999px}
.chips{display:flex;gap:8px;overflow-x:auto;padding:12px 14px 2px;scrollbar-width:none}
.chips::-webkit-scrollbar{display:none}
.chip{flex:none;padding:8px 15px;border-radius:999px;font-size:14px;font-weight:600;color:#E5E5EA}
.chip.on{background:rgba(255,255,255,.92);color:#000;border-color:rgba(255,255,255,.95)}
h2.sec{font-size:20px;font-weight:800;letter-spacing:-.3px;margin:20px 16px 10px}
.row{display:flex;gap:12px;overflow-x:auto;padding:0 16px 4px;scrollbar-width:none;scroll-snap-type:x mandatory}
.row::-webkit-scrollbar{display:none}
.wide{flex:none;width:250px;scroll-snap-align:start;border-radius:16px;overflow:hidden}
.wide .art{width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:#1C1C1E}
.wide .meta{padding:9px 12px}
.wide b{display:block;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar{height:4px;border-radius:2px;background:rgba(255,255,255,.18);margin-top:7px;overflow:hidden}
.bar i{display:block;height:100%;background:#30D158;border-radius:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(112px,1fr));gap:14px 12px;padding:12px 16px 30px}
.c{position:relative;display:block}
.c .p{width:100%;aspect-ratio:2/3;object-fit:cover;border-radius:12px;background:#1C1C1E;display:block;
 box-shadow:0 6px 18px rgba(0,0,0,.4)}
.c .t{position:absolute;inset:0;border-radius:12px;display:flex;align-items:flex-end;padding:10px;font-weight:700;font-size:13px}
.c p{margin:7px 2px 0;font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.c small{display:block;margin:1px 2px 0;color:var(--dim);font-size:12px}
.c .badge{position:absolute;top:7px;left:7px;font-size:10px;font-weight:800;letter-spacing:.4px;padding:4px 7px;border-radius:999px}
.c .tick{position:absolute;top:7px;right:7px;width:22px;height:22px;border-radius:50%;display:flex;align-items:center;
 justify-content:center;font-size:12px;font-weight:900;background:#30D158;color:#000}
.c .bar{position:absolute;left:8px;right:8px;bottom:8px;margin:0}
.folders .c .p{aspect-ratio:1}
.mosaic{display:grid;grid-template-columns:1fr 1fr;gap:2px;aspect-ratio:1;border-radius:14px;overflow:hidden;background:#1C1C1E}
.mosaic img{width:100%;height:100%;object-fit:cover;display:block}
.mosaic.one{grid-template-columns:1fr}
.empty{padding:60px 24px;text-align:center;color:var(--dim)}
/* the player */
.stage{padding:0 0 30px}
video{width:100%;max-height:70vh;background:#000;display:block}
.panel{margin:14px 14px 0;padding:16px;border-radius:22px}
.panel h1{font-size:22px;line-height:1.2;margin:0 0 4px;letter-spacing:-.4px}
.m{color:var(--dim);font-size:13px}
.panel>.m{display:block}
.seg{display:flex;gap:4px;padding:4px;border-radius:999px;margin-top:12px;width:max-content;max-width:100%;overflow-x:auto}
.seg a{padding:7px 13px;border-radius:999px;font-size:13px;font-weight:700;color:#E5E5EA;white-space:nowrap}
.seg a.on{background:rgba(255,255,255,.92);color:#000}
.syn{margin:12px 0 0;color:#D1D1D6;font-size:14px}
.btn{display:inline-flex;align-items:center;gap:8px;padding:11px 18px;border-radius:999px;font-weight:700;margin:12px 8px 0 0}
.btn.primary{background:#fff;color:#000;border-color:#fff}
.list{margin:14px;border-radius:22px;overflow:hidden}
.ep{display:flex;gap:12px;align-items:center;padding:12px 14px;border-top:1px solid rgba(255,255,255,.08)}
.ep:first-child{border-top:0}
.ep .n{width:34px;height:34px;flex:none;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;
 font-size:13px;background:rgba(255,255,255,.1)}
.ep.done .n{background:#30D158;color:#000}
.ep .x{flex:1;min-width:0}
.ep b{display:block;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
form.login{max-width:340px;margin:16vh auto 0;padding:28px 22px;border-radius:28px;display:flex;flex-direction:column;gap:12px}
form.login h1{font-size:28px;margin:0;text-align:center;letter-spacing:-.5px}
form.login input{font:inherit;padding:13px 16px;border-radius:999px;border:1px solid rgba(255,255,255,.16);
 background:rgba(255,255,255,.08);color:#fff;outline:none}
form.login button{font:inherit;font-weight:800;padding:13px;border:0;border-radius:999px;background:#fff;color:#000}
.err{color:#FF6961;font-size:13px;text-align:center}
@media (prefers-reduced-transparency:reduce){.glass{background:rgba(36,36,40,.96);-webkit-backdrop-filter:none;backdrop-filter:none}}
@media (min-width:700px){.grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}.panel,.list{max-width:900px;margin-left:auto;margin-right:auto}}
"""

PLAYER_JS = b"""(function () {
  var v = document.querySelector('video[data-src]');
  if (!v) return;
  var src = v.getAttribute('data-src'), offset = +v.getAttribute('data-offset') || 0;
  var resume = +v.getAttribute('data-resume') || 0, report = v.getAttribute('data-report');
  if (!/\\.m3u8$/.test(src) || v.canPlayType('application/vnd.apple.mpegurl')) v.src = src;
  else if (window.Hls && Hls.isSupported()) { var h = new Hls({ enableWorker: false }); h.loadSource(src); h.attachMedia(v); }
  else v.src = src;
  if (resume > 0) v.addEventListener('loadedmetadata', function () { try { v.currentTime = resume; } catch (e) {} }, { once: true });
  // where you are, every 10 seconds and when you stop: Media Vault's progress and Continue Watching follow
  var last = -1, total = +v.getAttribute('data-duration') || 0;
  function send(force) {
    if (!report) return;
    var pos = Math.floor(offset + (v.currentTime || 0));
    if (!force && Math.abs(pos - last) < 10) return;
    last = pos;
    var dur = total || Math.floor(offset + (isFinite(v.duration) ? v.duration : 0));
    var body = JSON.stringify({ pos: pos, dur: dur });
    if (force && navigator.sendBeacon) navigator.sendBeacon(report, new Blob([body], { type: 'application/json' }));
    else fetch(report, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true, credentials: 'same-origin' });
  }
  v.addEventListener('timeupdate', function () { send(false); });
  v.addEventListener('pause', function () { send(true); });
  v.addEventListener('ended', function () { send(true); var n = document.querySelector('a[data-next]'); if (n) location.href = n.href; });
  document.addEventListener('visibilitychange', function () { if (document.hidden) send(true); });
  window.addEventListener('pagehide', function () { send(true); });
})();"""

QUALITY_NAMES = {"orig": "Original", "1080": "1080p", "720": "720p", "480": "480p"}
DONE_AT = 0.92            # this far through counts as watched


def esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def clock(sec) -> str:
    sec = int(sec or 0)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def page(title: str, body: str, header: str = "", bg: str = "", script: bool = False) -> bytes:
    bg_div = f'<div class="bg" style="background-image:url(\'{bg}\')"></div>' if bg else '<div class="bg none"></div>'
    return (f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="Media Vault">
<meta name="theme-color" content="#000000"><link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon.png"><link rel="icon" href="/icon.png">
<title>{esc(title)}</title><link rel="stylesheet" href="/style.css">"""
            + ('<script src="/hls.min.js" defer></script><script src="/player.js" defer></script>' if script else "")
            + f"</head><body>{bg_div}"
            + (f'<header class="glass">{header}</header>' if header else "") + body + "</body></html>").encode("utf-8")


def login(error: str = "") -> bytes:
    body = ('<form class="login glass" method="post" action="/login"><h1>Media Vault</h1>'
            '<p class="m" style="text-align:center;margin:0">Enter the password you set in Settings › Streaming.</p>'
            '<input type="password" name="password" autocomplete="current-password" placeholder="Password" autofocus required>'
            '<button type="submit">Open library</button>' + (f'<p class="err">{esc(error)}</p>' if error else "") + "</form>")
    return page("Media Vault", body)


class Pages:
    """One request's pages. t: the secret at the start of every address."""

    def __init__(self, token: str):
        self.t = token
        self.hidden = set(db.private_dirs())                 # private tabs never show here
        self.quiet = set(db.hidden("nowatch_dirs"))          # tabs that do not track watched

    # -- addresses
    def u(self, *parts, **q) -> str:
        path = "/" + "/".join([self.t] + [quote(str(p), safe="") for p in parts]) + ("/" if not parts else "")
        q = {k: v for k, v in q.items() if v not in (None, "")}
        return esc(path + ("?" + urlencode(q) if q else ""))            # ready to go in an attribute

    def poster(self, uid: str) -> str:
        return self.u("poster", uid)

    def header(self, back: str = "", q: str = "", tab="") -> str:
        left = f'<a class="back glass" href="{back}">‹</a>' if back else '<a class="brand" href="' + self.u() + '">Media Vault</a>'
        hidden_tab = f'<input type="hidden" name="tab" value="{esc(tab)}">' if tab != "" else ""
        return (left + f'<form action="{self.u()}" method="get">{hidden_tab}'
                f'<input type="search" name="q" value="{esc(q)}" placeholder="Search" enterkeyhint="search" autocomplete="off"></form>')

    def dirs(self) -> list[dict]:
        return [d for d in db.list_directories() if d["id"] not in self.hidden]

    # -- cards
    def card(self, c: dict) -> str:
        key, uid = c["key"], c["uuid"]
        if key.startswith("show:"):
            href, badge = self.u("series", uid), f'{c["episodes"]} EP'
        elif key.startswith("set:"):
            href, badge = self.u("set", key[4:]), f'{c["films"]} FILMS'
        else:
            href, badge = self.u("watch", uid), ""
        track = c.get("parent_directory_id") not in self.quiet
        done = track and bool(c.get("is_completed"))
        prog = 0.0
        if track and not done and c.get("duration") and (c.get("last_position") or 0) > 10 and not (c["episodes"] or c.get("films")):
            prog = min(1.0, c["last_position"] / c["duration"])
        year = (c.get("release_date") or "")[:4]
        return (f'<a class="c" href="{href}"><img class="p" loading="lazy" alt="" src="{self.poster(uid)}">'
                + (f'<span class="badge glass">{badge}</span>' if badge else "")
                + ('<span class="tick">✓</span>' if done else "")
                + (f'<span class="bar"><i style="width:{prog * 100:.0f}%"></i></span>' if prog else "")
                + f'<p>{esc(c["title"])}</p>' + (f"<small>{year}</small>" if year else "") + "</a>")

    # -- the library: Continue Watching, tabs, search, the cards (or a folder-cards tab's folders)
    def library(self, tab: str = "", q: str = "", folder: str = "") -> bytes:
        dirs = self.dirs()
        tab_id = int(tab) if tab.isdigit() and any(d["id"] == int(tab) for d in dirs) else None
        d = next((x for x in dirs if x["id"] == tab_id), None)
        chips = [f'<a class="chip glass{" on" if tab_id is None else ""}" href="{self.u()}">All</a>'] + [
            f'<a class="chip glass{" on" if x["id"] == tab_id else ""}" href="{self.u(tab=x["id"])}">{esc(x["tab_name"])}</a>'
            for x in dirs]
        out = [f'<nav class="chips">{"".join(chips)}</nav>']
        cards = [c for c in db.list_library(tab_id) if c.get("parent_directory_id") not in self.hidden]
        if tab_id is None:
            cards = db.visible_in_all(cards, db.search_index())
        if q:
            words = q.lower().split()
            index = db.search_index()
            cards = [c for c in cards if all(w in (c["title"] + " " + " ".join(index.get(c["uuid"], {}).get("tags", []))
                                                   + " " + (c.get("release_date") or "")).lower() for w in words)]
        root = d["folder_path"] if d else ""
        folder_mode = bool(d) and tab_id in set(db.hidden("folders_dirs"))
        if folder_mode and folder:
            if folder == "~":
                cards = [c for c in cards if os.path.dirname(c["file_path"]) == root]
            elif folder != "*":
                pre = db.norm(os.path.join(root, folder)) + os.sep
                cards = [c for c in cards if c["file_path"].startswith(pre)]
        if not q and not folder:
            cont = self.continuing(cards)
            if cont:
                out.append('<h2 class="sec">Continue Watching</h2><div class="row">' + "".join(cont) + "</div>")
        if folder_mode and not folder and not q:
            out.append('<h2 class="sec">' + esc(d["tab_name"]) + "</h2>" + self.folder_cards(tab_id, root, cards))
        else:
            title = f'Results for “{esc(q)}”' if q else (esc(folder if folder not in ("*", "~") else
                                                                       "All videos" if folder == "*" else "Unsorted")
                                                                    if folder else esc(d["tab_name"]) if d else "Library")
            out.append(f'<h2 class="sec">{title}</h2>')
            out.append('<div class="grid">' + "".join(self.card(c) for c in cards) + "</div>" if cards else
                       '<p class="empty">Nothing here.</p>')
        back = self.u(tab=tab_id) if folder else ""
        return page("Media Vault", "".join(out), self.header(back, q, tab_id if tab_id is not None else ""))

    def continuing(self, cards: list[dict]) -> list[str]:
        started = [c for c in cards if c.get("parent_directory_id") not in self.quiet and not c["is_completed"]
                   and (c.get("last_position") or 0) > 10 and c.get("duration")]
        started.sort(key=lambda c: c.get("last_watched") or "", reverse=True)
        out = []
        for c in started[:12]:
            prog = min(1.0, c["last_position"] / c["duration"])
            left = clock(max(0, c["duration"] - c["last_position"]))
            out.append(f'<a class="wide glass" href="{self.u("watch", c["uuid"])}"><img class="art" loading="lazy" alt="" '
                       f'src="{self.u("wide", c["uuid"])}"><div class="meta"><b>{esc(c["title"])}</b>'
                       f'<span class="m">{left} left</span><div class="bar"><i style="width:{prog * 100:.0f}%"></i></div></div></a>')
        return out

    def folder_cards(self, tab_id: int, root: str, cards: list[dict]) -> str:
        by_top: dict[str, list] = {}
        for c in cards:
            rel = os.path.relpath(c["file_path"], root)
            by_top.setdefault(rel.split(os.sep, 1)[0] if os.sep in rel else "~", []).append(c)
        names = sorted((k for k in by_top if k != "~"), key=str.casefold)
        favs = set(_folder_favs().get(str(tab_id), []))
        names.sort(key=lambda k: k not in favs)

        def tile(rel, name, items):
            from ui.dashboard import folder_picture_path
            pic = folder_picture_path(tab_id, rel) if rel not in ("*", "~") else None
            if pic is not None and pic.exists():
                art = f'<img class="p" loading="lazy" alt="" src="{self.u("folderpic", tab_id, rel)}">'
            else:
                shots = items[:4]
                art = (f'<div class="mosaic{" one" if len(shots) < 4 else ""}">'
                       + "".join(f'<img loading="lazy" alt="" src="{self.poster(i["uuid"])}">' for i in shots[:4 if len(shots) >= 4 else 1])
                       + "</div>")
            n = len(items)
            return (f'<a class="c" href="{self.u(tab=tab_id, folder=rel)}">{art}<p>{esc(name)}</p>'
                    f'<small>{n} video{"s" if n != 1 else ""}</small></a>')
        tiles = [tile("*", "All videos", cards)]
        if by_top.get("~"):
            tiles.append(tile("~", "Unsorted", by_top["~"]))
        tiles += [tile(k, k, by_top[k]) for k in names]
        return '<div class="grid folders">' + "".join(tiles) + "</div>"

    # -- a series or a box set: its episodes / films, ticked when watched, to pick from
    def series(self, item: dict) -> bytes:
        eps = db.episodes_in(os.path.dirname(item["file_path"]))
        name = db.series_title(eps[0]["title"]) if eps else item["title"]
        return self._list(name, eps, item, numbered=True)

    def box_set(self, cid: int) -> bytes:
        films = [f for f in db.films_in_set(cid) if f.get("parent_directory_id") not in self.hidden]
        if not films:
            return b""
        return self._list(films[0].get("collection_name") or films[0]["title"], films, films[0], numbered=False)

    def _list(self, name: str, items: list[dict], art: dict, numbered: bool) -> bytes:
        quiet = art.get("parent_directory_id") in self.quiet
        nxt = db.next_up(items) if items else None
        rows = []
        for i, e in enumerate(items, 1):
            done = not quiet and bool(e["is_completed"])
            label = db.episode_suffix(e["title"]).strip() if numbered else ""
            se = re.match(r"S(\d+)E(\d+)", label or "")
            num = (str(int(se[2])) if se else str(i)) if numbered else str(i)
            sub = (e.get("episode_title") or "") if numbered else (e.get("release_date") or "")[:4]
            prog = ""
            if not quiet and not done and e.get("duration") and (e.get("last_position") or 0) > 10:
                prog = f'<div class="bar"><i style="width:{min(1.0, e["last_position"] / e["duration"]) * 100:.0f}%"></i></div>'
            rows.append(f'<a class="ep{" done" if done else ""}" href="{self.u("watch", e["uuid"])}">'
                        f'<span class="n">{"✓" if done else num}</span><span class="x"><b>{esc(label or e["title"])}</b>'
                        + (f'<span class="m">{esc(sub)}</span>' if sub else "") + prog + "</span></a>")
        play = (f'<a class="btn primary" href="{self.u("watch", nxt["uuid"])}">▶ '
                f'{"Resume" if (nxt.get("last_position") or 0) > 10 and not quiet else "Play"}</a>') if nxt else ""
        body = (f'<div class="panel glass"><h1>{esc(name)}</h1><span class="m">{len(items)} '
                f'{"episodes" if numbered else "films"}</span>'
                + (f'<p class="syn">{esc(art.get("synopsis") or "")}</p>' if art.get("synopsis") else "") + play + "</div>"
                f'<div class="list glass">{"".join(rows)}</div>')
        return page(name, body, self.header(self.u()), bg=self.u("wide", art["uuid"]))

    # -- the player
    def watch(self, item: dict, quality: str, start: str, remote: bool, can_convert: bool, subs: list[dict]) -> bytes:
        from utils import transcode
        uid, quiet = item["uuid"], item.get("parent_directory_id") in self.quiet
        direct = transcode.plays_directly(item)
        if quality not in QUALITY_NAMES or (quality != "orig" and not can_convert):
            quality = ("720" if remote else "orig" if direct else "1080") if can_convert else "orig"
        dur = int(item.get("duration") or 0)
        saved = 0 if quiet or item.get("is_completed") else int(item.get("last_position") or 0)
        at = int(start) if start.isdigit() else (saved if saved > 10 and (not dur or saved < dur * DONE_AT) else 0)
        at = max(0, min(at, max(0, dur - 5))) if dur else at
        if quality == "orig":
            src, offset, resume = self.u("v", uid), 0, at          # the file itself: seek in the browser
        else:
            src, offset, resume = self.u("hls", uid, quality, at, "index.m3u8"), at, 0     # converted from there on
        qs = "".join(f'<a class="{"on" if k == quality else ""}" href="{self.u("watch", uid, q=k, t=at or None)}">{v}</a>'
                     for k, v in QUALITY_NAMES.items() if k == "orig" or can_convert)
        tracks = "".join(f'<track kind="subtitles" src="{self.u("sub", uid, s["n"])}" srclang="{esc(s["lang"])}" '
                         f'label="{esc(s["label"])}"{" default" if i == 0 else ""}>' for i, s in enumerate(subs))
        nxt = self.next_of(item)
        resume_links = ""
        if saved > 10 and (not dur or saved < dur * DONE_AT):
            resume_links = (f'<div class="seg glass"><a class="{"on" if at == saved else ""}" href="{self.u("watch", uid, q=quality, t=saved)}">'
                            f'Resume {clock(saved)}</a><a class="{"on" if at == 0 else ""}" href="{self.u("watch", uid, q=quality, t=0)}">'
                            f"Start over</a></div>")
        note = ""
        if quality == "orig" and not direct:
            note = ('<p class="m">This file may not play in this browser. '
                    + ("Pick 1080p or 720p to convert it as it plays." if can_convert else
                       "Install ffmpeg in Media Vault (Settings › Streaming) to convert it as it plays.") + "</p>")
        report = "" if quiet else self.u("progress", uid)
        back = self.u("series", uid) if item["media_type"] == "show" else (
            self.u("set", item["collection_id"]) if item.get("collection_id") is not None and item["media_type"] == "movie" else self.u())
        body = (f'<div class="stage"><video controls autoplay playsinline preload="metadata" crossorigin="use-credentials" '
                f'data-src="{src}" data-offset="{offset}" data-resume="{resume}" data-duration="{dur}" data-report="{report}" '
                f'poster="{self.u("wide", uid)}">{tracks}</video>'
                f'<div class="panel glass"><h1>{esc(item["title"])}</h1>'
                f'<span class="m">{" · ".join(x for x in ((item.get("release_date") or "")[:4], clock(dur) if dur else "", item.get("resolution") or "") if x)}</span>'
                f'{resume_links}<div class="seg glass">{qs}</div>{note}'
                + (f'<p class="syn">{esc(item.get("synopsis") or "")}</p>' if item.get("synopsis") else "")
                + (f'<a class="btn glass" data-next href="{self.u("watch", nxt["uuid"])}">Next: {esc(nxt["title"])} ›</a>' if nxt else "")
                + "</div></div>")
        return page(item["title"], body, self.header(back), bg=self.u("wide", uid), script=True)

    @staticmethod
    def next_of(item: dict) -> dict | None:
        """The episode after this one, or the next film of its box set."""
        if item["media_type"] == "show":
            eps = db.episodes_in(os.path.dirname(item["file_path"]))
        elif item.get("collection_id") is not None:
            eps = db.films_in_set(item["collection_id"])
        else:
            return None
        ids = [e["uuid"] for e in eps]
        i = ids.index(item["uuid"]) if item["uuid"] in ids else -1
        return eps[i + 1] if 0 <= i < len(eps) - 1 else None


def _folder_favs() -> dict:
    try:
        return dict(json.loads(db.get_setting("folder_favs", "{}") or "{}"))
    except (TypeError, ValueError):
        return {}


# ------------------------------------------------------------ subtitles for the phone (WebVTT)

SUB_EXTS = (".srt", ".vtt")
TEXT_CODECS = ("subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text")


def subtitles(item: dict) -> list[dict]:
    """Subtitles a browser can show: .srt / .vtt files beside the video (or downloaded into its art folder), then the
    file's own text subtitles (read out by ffmpeg). [{n, lang, label, kind: file|stream, path|index}]"""
    from utils import scraper
    video = item["file_path"]
    stem = os.path.splitext(os.path.basename(video))[0].lower()
    out = []
    for folder in (os.path.dirname(video), os.path.join(os.path.dirname(video), scraper.ASSET_DIR)):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            low = name.lower()
            if low.endswith(SUB_EXTS) and low.startswith(stem):
                lang = low[len(stem):].strip(". _-").rsplit(".", 1)[0] or "und"
                out.append({"lang": lang[:8], "label": lang.upper() if lang != "und" else "Subtitles",
                            "kind": "file", "path": os.path.join(folder, name)})
    for s in embedded_subtitles(video):
        out.append({"lang": s["lang"], "label": s["label"], "kind": "stream", "index": s["index"]})
    for i, s in enumerate(out):
        s["n"] = i
    return out


_STREAM = re.compile(r"Stream #0:(\d+)(?:\[\w+\])?(?:\((\w+)\))?: Subtitle: (\w+)")


def embedded_subtitles(video: str) -> list[dict]:
    """The video's own text subtitle tracks (picture subtitles such as PGS cannot become WebVTT)."""
    from utils import transcode
    import subprocess
    ffmpeg = transcode.ffmpeg_path()
    if not ffmpeg:
        return []
    try:
        err = subprocess.run([str(ffmpeg), "-hide_banner", "-i", video], capture_output=True, text=True, timeout=15,
                             creationflags=transcode.NO_WINDOW).stderr
    except Exception:
        return []
    out = []
    for m in _STREAM.finditer(err):
        if m[3].lower() in TEXT_CODECS:
            lang = (m[2] or "und").lower()
            out.append({"index": int(m[1]), "lang": lang, "label": (lang.upper() if lang != "und" else "Subtitles") + " (in file)"})
    return out


def srt_to_vtt(text: str) -> str:
    """SubRip to WebVTT: a header, and full stops instead of commas in the times."""
    text = text.lstrip("﻿").replace("\r\n", "\n")
    if text.startswith("WEBVTT"):
        return text
    return "WEBVTT\n\n" + re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text)


def subtitle_vtt(sub: dict, video: str) -> bytes | None:
    if sub["kind"] == "file":
        try:
            with open(sub["path"], "rb") as f:
                raw = f.read(8 << 20)
        except OSError:
            return None
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return srt_to_vtt(raw.decode(enc)).encode("utf-8")
            except UnicodeDecodeError:
                continue
        return None
    from utils import transcode
    import subprocess
    ffmpeg = transcode.ffmpeg_path()
    if not ffmpeg:
        return None
    try:
        r = subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-i", video, "-map", f"0:{sub['index']}",
                            "-f", "webvtt", "-"], capture_output=True, timeout=120, creationflags=transcode.NO_WINDOW)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 and r.stdout.startswith(b"WEBVTT") else None
