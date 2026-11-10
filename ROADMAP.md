# Media Vault — Roadmap (PySide6 + QML)

Flet is gone. The UI is QML, the player HUD is a second QML window, the backend is Python.
Written on Linux with no Windows, no PySide6, no libmpv and no network. So there are three levels of "done":

- ✅ **Tested** — ran here. 31 logic tests pass (`python -m unittest discover -s tests`), plus a static check that
  every QML call matches a real Python slot, argument count, signal and Theme key. I broke QML on purpose to
  confirm that check fails when it should.
- 🟡 **Written, never run** — needs Windows + PySide6 + libmpv. Python compiles. The QML has *not* been through Qt.
- ⚠️ **Different from the spec, on purpose** — reason given.
- ⬜ **Not done.**

## Build order

| # | Step | Status |
|---|------|--------|
| 1 | `database.py` | ✅ |
| 2 | `utils/` (hw_accelerator, scraper, backup_manager, media_probe) | ✅ logic · 🟡 libmpv, network, GPU lookup |
| 3 | `watcher.py` | ✅ |
| 4 | `player/` (vr_detector, player_engine, Hud.qml) | ✅ VR · 🟡 engine and HUD |
| 5 | `ui/` (`.py` controllers + `.qml` screens) | 🟡 |
| 6 | `setup.py`, `build_installer.py`, `installer.iss` | 🟡 |
| 7 | `main.py` | 🟡 |

## What the move to Qt fixed

| Was "different" or "not done" | Now |
|---|---|
| Video could not sit under a HUD | mpv/VLC render into a native fullscreen window; the HUD is a transparent QML window over it. 🟡 |
| No glass HUD, no subtitle/audio toggles | HUD with play/seek, subtitle and audio pickers, Reduce Loud Sounds, 3 upscaling levels, VR view, snapshot, skip-intro badge. 🟡 |
| Blackout used raw Win32 | One click-through black window per other monitor (`QScreen`). 🟡 |
| Text-only countdown at episode end | The picture shrinks into the corner, with a circular countdown ring and Enter to skip (MPV core). 🟡 |
| Hover preview was a frame slideshow | Real silent video, one shared `MediaPlayer`, 500 ms debounce, 15 s loop. 🟡 |
| Box was a width-squeeze | 3D box drawn with its own perspective maths on plain 2D layers (no GPU needed), spine + custom art, drag 360°, coasts after release, idle spin. ✅ rendered |
| No live crop canvas | Snapshot opens a crop canvas (2:3 box art or 16:9 fanart, drag + size slider). 🟡 |
| Grid did not recycle | `GridView` with `reuseItems`; refreshes in place so scroll position survives. 🟡 |
| Hover only scaled | Scale 1.05 + 6° turn, 220 ms ease-out-cubic. 🟡 |
| Watch time = furthest point reached | `watch_log` counts seconds actually played. ✅ |
| "Top-rated genres" ranked by time | Rated genres first (average stars), then by time. ✅ |
| One card per episode | One card per show folder; detail view lists episodes; edits apply to the whole series. ✅ |
| Frame rate missing | `frame_rate` column (old databases migrate), read-only chip. ✅ |
| No auto skip-intro | Chapters named Intro/Opening/Recap become the folder's skip bookmark; `I` marks one by hand. 🟡 |
| VR: left eye only | `V` toggles left eye (flat) and both eyes side by side (top-bottom is converted). 🟡 |
| VLC night mode next start only | Re-opens at the same position with the filter on. 🟡 |
| Downloads unverified | libmpv (GitHub digest) and VLC (`.sha256`) are checked and refused on mismatch. 🟡 |
| No update daemon | Weekly check; tells you, never installs on its own. Settings → Check for updates installs. 🟡 |
| No un-register / restore | `unregister_file_types()`, backup list + Restore in Settings. ✅ restore · 🟡 registry |
| No shader download | Settings → Install upscaling shader. 🟡 |
| No icon / installer / signing | Icon drawn by Pillow, `installer.iss` (Inno Setup), optional `signtool` step. 🟡 |
| Dependencies | PySide6, python-mpv, python-vlc, watchdog, pillow. **pywin32 and Flet removed**: GPU lookup and sleep lock use ctypes, the single-instance pipe is Qt's `QLocalServer` (a Windows named pipe). |
| Windows-side tests | `tests/test_windows.py` (registry, GPU, libmpv probe) and `tests/test_qt.py` (compiles every QML file, model checks) written. Not run. |

## Still different from the spec, on purpose

| Spec | What exists | Why |
|---|---|---|
| Player inside the app window | A separate borderless fullscreen window | A native video surface cannot sit inside a QML scene without the HUD vanishing behind it |
| Glass HUD | Translucent, **not blurred** | The video is in another window, so Qt cannot blur it |
| Hardware-accelerated poster downscale | Pillow resizes on the CPU once at import; the GPU only draws the small WebP | Pillow has no GPU path |
| Shrinking picture + spinner on VLC | Countdown ring only, no shrink | libvlc cannot align a scaled picture |
| Upscaling levels, VR filters, auto intro from chapters on VLC | MPV only | libvlc has no such filters or chapter API |
| `HKEY_CLASSES_ROOT` | `HKCU\Software\Classes` + "Open with" | Needs no admin. Windows lets only *you* choose the default app |
| `uuid4` ids | `uuid5` of the path | The id must survive a rescan |
| Schema | + `intro_marks`, `settings`, `watch_log`, `frame_rate` | The spec needs them and lists no table |
| Skip intro "automated" | Chapters, plus a bookmark you set once per folder | Nothing detects intros from audio or video |
| FSRCNNX shader download | HTTPS only, **no checksum** | The author publishes none |

## Not done

- ⬜ **Profiles.** The spec's `watch_history` key is `media_uuid` alone, so two people cannot have separate resume points.
  Doing it means changing that key. Your call.
- ⬜ Headset-native VR output (OpenXR). The side-by-side view is for a 3D/VR display, not a headset runtime.
- ⬜ Intro detection from the audio.
- ⬜ Running any of the 🟡 items on Windows.

## Verify first on Windows (these are the real unknowns)

1. `pip install PySide6 python-mpv python-vlc watchdog pillow`, then `python -m unittest discover -s tests`.
   `tests/test_qt.py` compiles every QML file with Qt's own compiler. Fix whatever it prints before anything else.
2. `python main.py` → wizard → add a folder → does the grid fill and do posters load?
3. Play a file. The riskiest part: **transparent HUD window over mpv's native window.** If the HUD does not
   appear, or stops getting keys, the fix is in `Hud.qml` window flags and `PlayerEngine._start`.
4. 3D box (`DvdBox.qml`): check feel of drag + idle spin on real hardware. Qt 6.5+ needed for `MultiEffect`.
5. Card hover preview: `MediaPlayer.videoOutput` re-pointing between cards.
6. mpv: `screenshot_raw()` with a real window, `d3d11vpp=scaling-mode=nvidia` (mpv ≥ 0.38, RTX), `video-zoom` shrink.
7. `setup.py` downloads (GitHub asset name, VLC index page), then `python build_installer.py`.
   PyInstaller may need `--collect-all PySide6` if a QML module is missing from the packaged app.

## Run

```
python main.py                        # installs missing packages on first launch
python -m unittest discover -s tests  # 31 logic tests + static QML check; Qt/Windows tests run when possible
python build_installer.py             # icon, EXE, signing (optional), installer
```

## Update: setup rewrite and Add folder

- `setup.run_setup()` runs first on every launch. It checks Python 3.10+/64-bit, PySide6, python-mpv, python-vlc, watchdog, pillow, py7zr, libmpv and libvlc. Everything present: no window, instant start.
- Anything missing is installed in one window (pip, then downloads into `bin/`) with Retry and Quit. There is no "No" and no skip. The app starts only when all packages are present and at least one video engine loads. If only the second engine fails, "Continue anyway" appears. Log: `%LOCALAPPDATA%\MediaVault\setup.log`.
- Settings > "Install missing components" re-runs the same check.
- Add folder: dialog now opens from the event loop (not inside the QML click), as an always-on-top dialog, and errors show as a toast and go to `media_vault.log`. Root cause of the "does nothing" is unconfirmed: untested on Windows/Qt. Check the log if it still fails.
- Unverified: live GitHub/VideoLAN download layouts, tkinter window (no display here). libmpv is accepted over HTTPS alone if the release lists no checksum.

