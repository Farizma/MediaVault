# Media Vault

A Windows media library and player. It watches your movie and TV folders, scrapes covers and details, and plays
everything in a full-screen player with a glass HUD. PySide6 + QML front end, Python back end, mpv or VLC for playback.

## Download

Get the latest **MediaVault_v…_setup.exe** from [Releases](https://github.com/Farizma/MediaVault/releases/latest) and run it.
The setup wizard installs wherever you choose: your user folder needs no administrator rights, while Program Files
or "Install for all users" asks Windows for permission. Updates: Settings › About & Updates checks GitHub and installs
new versions inside Media Vault, with no wizard: it closes, updates and opens again.

## Run from source

```
python main.py
```

On first start a setup window installs anything missing (PySide6, mpv/VLC, watchdog, Pillow) with live progress.

Tests: `python -m unittest discover -s tests` (Qt tests need `QT_QPA_PLATFORM=offscreen` on a machine without a display).
Installer: `python build_installer.py` on Windows (PyInstaller, then Inno Setup 6) makes
`dist/MediaVault_v<version>_setup.exe`. Releases are built by `.github/workflows/release.yml`: raise `VERSION`
in `version.py` and push to `main`; the workflow tests, builds the setup on Windows, and publishes release
`v<version>` (pushing a tag `v<version>` works too).

## What it does

- **Library:** tabs per watched folder (renamable), search across title, synopsis, tags, genres, year and codec,
  six sort orders, genre / quality / unwatched filters, a recommended carousel, and a Grid or Spine Shelf view.
  Films of the same series (TMDB collections) share one box-set card; make your own sets, move films between
  sets, or ungroup one. In View More the films are pulled out of the set into a floating 3D carousel (a gentle
  wave while idle); the title is a dropdown of the set's films, and each film shows its full page.
- **View More:** reorder its sections (Settings › Appearance › View More layout); audience star rating from
  TMDB / IMDb beside your own score; file type shown as the extension; Resume and From start for part-watched titles.
- **Cast:** actors with their part and a round photo in View More (TMDB), shared across titles.
- **Per-folder scraping:** when you add a folder, pick what to scrape (titles, synopsis, genres, box art, disc
  art, box sets, actors, actor photos); change it later in Settings › Library › Configure. "Fetch missing" fills gaps for
  titles already there without touching your edits.
- **Fix Scraped Data:** search TMDB, AniList and OMDb at once by hand from View More when a title was scraped wrong; title, details, genres,
  cover, disc and box set are pulled again. Your own tags, rating, notes and art stay.
- **3D DVD box:** posters fly into a spinning, draggable box (no GPU needed) with front, spine, back and disc art.
  Scraped art first; your own art always wins.
- **Player:** mpv or VLC chosen from your hardware (override in Settings), Audio and Video panel with track,
  audio delay (lip sync), subtitle, timing, style, speed (0.5×–3×), upscaling, HDR and VR options, skip intro, skip credits into the next-episode
  countdown, picture in picture, snapshot to box art or fanart.
- **Library Status:** duplicates (best copy marked), missing episodes, missing artwork and offline folders, each
  ignorable for now or forever.
- **Streaming:** a private link any browser on your Wi-Fi can open, plus AirPlay and Chromecast with optional add-ons.
- **HDR:** HDR10 / HLG detected; tone mapping for normal screens with per-scene adaptation and a brightness
  target, or HDR passed straight through to an HDR screen (MPV engine).
- **Discord status:** optional "Watching …" status with three detail levels; home videos never show their name.
- **Themes:** eight dark themes including a custom one with a colour wheel, optional animated glow.
- **Backups:** automatic database backups, plus portable `.mvault` files with the whole library and its artwork.
- **About & Updates:** Settings › About & Updates lists every tool Media Vault uses with its version, and updates them
  one at a time or all at once; a badge on Settings shows when something is waiting. Every update can be rolled back
  (Media Vault itself to the previous release, the video engines and shader to the version they replaced).
- **Help:** shortcut sheet in Settings › Help; hover any button for a hint.

Build history and what is tested vs. written-but-unrun: [ROADMAP.md](ROADMAP.md).

## Roadmap

Status: 🟢 planned (decided, not built) · 💡 proposed (not decided yet) · ✅ shipped (moved to "What it does").

### Planned

_Nothing decided yet. Ideas move here once we choose to build them._

### Shipped

| Idea | Version |
|---|---|
| Fix match, audio delay, box sets (collections), Discord status, better HDR | Round 9 |
| Box set carousel, editable box sets, cast and photos, per-folder scrape choices | Round 10 |
| Box set title dropdown, pull-out carousel with wave, reorderable View More, audience rating, Resume / From start | Round 11 |
| v1.0.0: Windows setup, Components and GitHub update checks | 1.0.0 |
| View More fix, setup elevation fix, smooth wheel scrolling, smoother parallax, Black Out button, Insights window | 1.0.1 |
| Anime (AniList), crop editor, Gallery, auto tags, hide from All / Insights, tab and layout dragging, full Custom theme, player window and PiP fixes | 1.0.2 |
| Age ratings, original / romaji titles, Tag Manager, tag rules, folder Configure window, themed player | 1.0.3 |
| Fix Scraped Data across TMDB, AniList and OMDb, AniList % scores, adult / OVA file names | 1.0.4 |
| Updates inside Media Vault (no wizard), Update all, update badge, rollbacks | 1.0.5 |
| Tag suggestions, adult OVAs as box sets, AniList tags as genres, studio tags, whole-cover scans, DVD-shaped box, close and libmpv update fixes | 1.0.6 |

### Proposed

| Idea | What it adds | Size |
|---|---|---|
| Continue Watching row + Up Next queue | Half-watched titles first on the dashboard; queue titles to play back to back | S |
| Seek-bar previews | Thumbnail of the frame under the cursor when hovering the progress bar | M |
| Trailers | Play the TMDB trailer from View More | S |
| Profiles | Separate watch progress and ratings per person; a kids profile limited by rating | M |
| Subtitle download | Fetch missing subtitles from OpenSubtitles, with auto-sync to the audio | M |
| Phone remote | Control playback from a phone using the existing streaming server | M |
| Watch together | Synced playback across PCs on the same network | L |
| Trakt / Letterboxd sync | Two-way watch history and ratings | M |
| Kodi / Jellyfin NFO | Read and write `.nfo` files so metadata travels with the files | S |
| Year in review | A yearly "wrapped" page from the watch log: hours, top genres, most rewatched | S |
| Match display refresh rate | Switch the monitor to the film's frame rate (24p) while playing | M |
| Physical collection | Scan a disc barcode to log DVDs and Blu-rays you own; "owned on disc" badge | M |
