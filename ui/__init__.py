"""QML front end. Python side: theme tokens, paths, small helpers.

The QML files in this folder are loaded by main.py. They talk to Python through context properties:
Theme, Backend (ui/dashboard.py), Library, Tabs, Onboarding (ui/wizard.py), Player (player/player_engine.py).
"""
import ctypes
import re
import sys
from pathlib import Path

from PySide6.QtCore import QUrl

QML_DIR = Path(__file__).resolve().parent
PLAYER_DIR = QML_DIR.parent / "player"

THEME = {  # matches the web app (media-vault-googleAI): Tailwind white/NN overlays on pure black
    "black": "#000000", "graphite": "#121212", "slate": "#1C1C1E",   # page / modal panels / cards and inputs
    "chrome": "#BF1C1C1E",                                            # glass header (rgba 28,28,30,.75)
    "hud": "#D9121212",                                               # player glass (rgba 18,18,18,.85)
    "scrim": "#BF000000",                                             # behind modals (black/75)
    "line": "#1AFFFFFF", "lineStrong": "#26FFFFFF",                   # borders: white/10, white/15
    "fill": "#0DFFFFFF", "fillHover": "#1AFFFFFF",                    # quiet surfaces: white/5, white/10
    "green": "#34C759", "blue": "#007AFF", "amber": "#FCD34D", "red": "#FF453A",
    "text": "#F5F5F7", "muted": "#8E8E93", "faint": "#80FFFFFF",      # faint = white/50
    "font": "Plus Jakarta Sans", "mono": "JetBrains Mono",            # bundled in ui/fonts
    "motion": 1,  # multiplier for every animation duration; 0 = reduced motion
    "panel": "#F2121212", "theme": "midnight",                        # modal sheets; current colourway id
    "onBlue": "#FFFFFF", "onGreen": "#000000",                        # text on highlight / accent fills
    "soft": "#CCF5F5F7", "dim": "#B3F5F5F7", "edge": "#33F5F5F7",     # text at 80% / 70%, edges at 20% (player HUD)
}


# Dark colourways. The first five are the web app's; the last three are new. "custom" takes its two colours
# from Settings (colour wheel); the values here are its defaults.
# accent fills progress bars, switches and "watched" marks; highlight is focus and selection.
THEMES = [  # id, name, tagline, page, surface, accent, highlight
    ("midnight", "Midnight Obsidian", "Pure OLED black with emerald and deep blue", "#000000", "#121214", "#34C759", "#007AFF"),
    ("cyberpunk", "Cyberpunk Neon", "Indigo night with electric cyan and hot magenta", "#09090F", "#13131F", "#00F0FF", "#FF007F"),
    ("tokyo", "Tokyo Slate", "Twilight slate with sky blue and indigo", "#0B0F19", "#141D2E", "#38BDF8", "#818CF8"),
    ("titanium", "OLED Titanium", "Warm graphite with amber gold", "#101012", "#1C1C20", "#F59E0B", "#E2E8F0"),
    ("matrix", "Emerald Matrix", "Carbon black with terminal emerald and lime", "#070B07", "#0E170E", "#10B981", "#84CC16"),
    ("crimson", "Crimson Noir", "Cinema black with marquee amber and red", "#0C0607", "#1A0E10", "#FF9F0A", "#FF453A"),
    ("nebula", "Nebula", "Deep violet with purple and teal", "#0A0814", "#16122A", "#64D2FF", "#BF5AF2"),
    ("custom", "Custom", "Graphite grey with your own two colours", "#161618", "#232326", "#30D158", "#0A84FF"),
]


def _mix(a: str, b: str, t: float) -> str:
    ca, cb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


def _ink(bg: str) -> str:
    """Black or white text, whichever reads better on bg (WCAG relative luminance)."""
    lin = [(c / 255 / 12.92) if c <= 10 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in (int(bg[i:i + 2], 16) for i in (1, 3, 5))]
    return "#000000" if 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] > 0.4 else "#FFFFFF"


HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


# Every colour of the Custom theme can be chosen (Settings > Appearance). Setting key, name, what it paints.
CUSTOM_COLOURS = [
    ("custom_page", "Background", "Behind everything"),
    ("custom_surface", "Panels", "Sheets, menus, the player bar"),
    ("custom_card", "Cards", "Cards, fields, rows"),
    ("custom_text", "Text", "Titles and body text"),
    ("custom_muted", "Secondary text", "Labels, hints, counts"),
    ("custom_accent", "Accent", "Progress bars, switches, watched marks"),
    ("custom_highlight", "Highlight", "Selection and focus"),
    ("custom_amber", "Warning", "Box sets, notices, audience stars"),
    ("custom_red", "Danger", "Missing files, errors"),
]


def custom_defaults() -> dict:
    """What each Custom colour is when you have not chosen it (the Custom row of THEMES, plus the usual text)."""
    t = next(t for t in THEMES if t[0] == "custom")
    return {"custom_page": t[3], "custom_surface": t[4], "custom_card": _mix(t[4], "#FFFFFF", 0.05),
            "custom_text": "#F5F5F7", "custom_muted": "#8E8E93", "custom_accent": t[5], "custom_highlight": t[6],
            "custom_amber": "#FCD34D", "custom_red": "#FF453A"}


def custom_from(get_setting) -> dict:
    """The Custom theme's colours from settings (a bad or missing value falls back to its default)."""
    out = custom_defaults()
    for key, _, _ in CUSTOM_COLOURS:
        v = (get_setting(key) or "").strip()
        if HEX.match(v):
            out[key] = v.upper()
    return out


def apply_theme(theme_id: str, accent: str = "", highlight: str = "", custom: dict | None = None) -> str:
    """Rewrite THEME's colours for a colourway (unknown ids fall back to the first). Returns the id used.
    The Custom theme takes all its colours from `custom` (see custom_from); accent / highlight alone still work."""
    theme_id = "custom" if theme_id == "graphite" else theme_id  # Graphite became the customisable theme
    t = next((t for t in THEMES if t[0] == theme_id), THEMES[0])
    page, surface, accent0, highlight0 = t[3:]
    accent = accent.upper() if HEX.match(accent or "") else accent0
    highlight = highlight.upper() if HEX.match(highlight or "") else highlight0
    card = _mix(surface, "#FFFFFF", 0.05)
    extra = {"text": "#F5F5F7", "muted": "#8E8E93", "amber": "#FCD34D", "red": "#FF453A"}
    if t[0] == "custom" and custom:
        page, surface, card = custom["custom_page"], custom["custom_surface"], custom["custom_card"]
        accent, highlight = custom["custom_accent"], custom["custom_highlight"]
        extra = {"text": custom["custom_text"], "muted": custom["custom_muted"],
                 "amber": custom["custom_amber"], "red": custom["custom_red"]}
    # faint text: the text colour at half strength, so light themes made with Custom still read
    THEME.update({"black": page, "graphite": surface, "slate": card, "chrome": "#BF" + card[1:],
                  "panel": "#F2" + surface[1:], "scrim": "#BF" + page[1:], "green": accent, "blue": highlight,
                  "onBlue": _ink(highlight), "onGreen": _ink(accent), "theme": t[0],
                  **extra, "faint": "#80" + extra["text"][1:], "soft": "#CC" + extra["text"][1:],
                  "dim": "#B3" + extra["text"][1:], "edge": "#33" + extra["text"][1:],
                  "line": "#1A" + extra["text"][1:], "lineStrong": "#26" + extra["text"][1:],
                  "fill": "#0D" + extra["text"][1:], "fillHover": "#1A" + extra["text"][1:]})
    return t[0]


def load_fonts(app) -> None:
    """Register the bundled fonts and make Plus Jakarta Sans the default for every QML Text."""
    from PySide6.QtGui import QFont, QFontDatabase
    for f in sorted((QML_DIR / "fonts").glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(f))
    font = QFont(THEME["font"])
    font.setHintingPreference(QFont.PreferNoHinting)  # keeps the geometric shapes on Windows' ClearType
    app.setFont(font)


def detect_reduced_motion() -> bool:
    """Windows 'Show animations in Windows' switch (Accessibility > Visual effects)."""
    if sys.platform != "win32":
        return False
    on = ctypes.c_int(1)
    ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)  # SPI_GETCLIENTAREAANIMATION
    return not on.value


def pick_folder() -> str:
    """Folder chooser. Returns "" when cancelled. Errors are logged, then raised so the caller can show them."""
    import logging
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QFileDialog
        if QApplication.instance() is None:
            raise RuntimeError("no QApplication (QtWidgets missing?)")
        dialog = QFileDialog(None, "Choose a media folder", str(Path.home()))
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)  # the HUD window is always-on-top
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() and dialog.selectedFiles():
            return str(Path(dialog.selectedFiles()[0]))
    except Exception:
        logging.getLogger("ui").exception("folder dialog failed")
        raise
    return ""


IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"


def _image_dialog(start_dir: str, title: str, many: bool):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFileDialog
    start = start_dir if start_dir and Path(start_dir).is_dir() else str(Path.home() / "Pictures")
    dialog = QFileDialog(None, title, start, IMAGE_FILTER)     # starts in the title's own folder
    dialog.setFileMode(QFileDialog.FileMode.ExistingFiles if many else QFileDialog.FileMode.ExistingFile)
    dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    return dialog.selectedFiles() if dialog.exec() else []


def pick_image(start_dir: str = "", title: str = "Choose box art") -> str:
    """Image chooser for custom box art, opening in `start_dir` (the media file's folder). "" when cancelled."""
    files = _image_dialog(start_dir, title, False)
    return files[0] if files else ""


def pick_images(start_dir: str = "") -> list[str]:
    """Several images at once, for a title's Gallery."""
    return _image_dialog(start_dir, "Add images to the Gallery", True)


def file_url(path, bust: bool = True) -> str:
    """file:/// URL for QML. `?v=<mtime>` makes Qt reload an image that was replaced in place."""
    p = Path(path)
    url = QUrl.fromLocalFile(str(p)).toString()
    if bust:
        try:
            url += f"?v={p.stat().st_mtime_ns}"
        except OSError:
            pass
    return url
