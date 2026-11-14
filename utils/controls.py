"""Keyboard and controller bindings: one list of actions, each with a key and a controller button. Saved in settings
(key_bindings, pad_bindings) as {action: [key, modifiers]} and {action: button}; anything not saved uses the default.

The controller does not need its own handling anywhere: a button press becomes a press of the key its action is bound
to (utils/gamepad.py), so every screen that answers the keyboard answers the controller too."""
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

import database as db

SHIFT, CTRL, ALT = int(Qt.ShiftModifier.value), int(Qt.ControlModifier.value), int(Qt.AltModifier.value)
MODS = SHIFT | CTRL | ALT
K = {n: int(getattr(Qt, f"Key_{n}").value) for n in ("Up", "Down", "Left", "Right", "Space", "Return", "Enter", "Tab",
                                                      "Backtab", "Escape")}

# id, label, default key [key, modifiers], default controller button
ACTIONS = (
    ("up", "Move up", [K["Up"], 0], "DPad Up"),
    ("down", "Move down", [K["Down"], 0], "DPad Down"),
    ("left", "Move left", [K["Left"], 0], "DPad Left"),
    ("right", "Move right", [K["Right"], 0], "DPad Right"),
    ("viewMore", "Open View More", [K["Space"], 0], "A"),
    ("play", "Play", [K["Return"], 0], "X"),
    ("nextTab", "Next tab", [K["Tab"], 0], "RB"),
    ("prevTab", "Previous tab", [K["Tab"], SHIFT], "LB"),
    ("back", "Back / close", [K["Escape"], 0], "B"),
)
IDS = [a[0] for a in ACTIONS]
# XInput buttons; the left stick always moves like the D-pad
BUTTONS = ("A", "B", "X", "Y", "LB", "RB", "LT", "RT", "Back", "Start", "LS", "RS",
           "DPad Up", "DPad Down", "DPad Left", "DPad Right")


def _load(name: str) -> dict:
    try:
        v = json.loads(db.get_setting(name, "") or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def normalize(key: int, mods: int) -> list:
    """The same key however it arrives: Shift+Tab comes as Backtab, the keypad's Enter as Enter."""
    mods = int(mods) & MODS
    if key == K["Backtab"]:
        key, mods = K["Tab"], mods | SHIFT
    if key == K["Enter"]:
        key = K["Return"]
    return [int(key), mods]


def keys() -> dict:
    saved = _load("key_bindings")
    out = {}
    for a, _, default, _ in ACTIONS:
        v = saved.get(a, default)
        out[a] = normalize(*v) if isinstance(v, list) and len(v) == 2 else None    # None: not bound
    return out


def pads() -> dict:
    saved = _load("pad_bindings")
    return {a: (saved.get(a, default) if saved.get(a, default) in BUTTONS else None) for a, _, _, default in ACTIONS}


def action_for_key(key: int, mods: int) -> str:
    want = normalize(key, mods)
    return next((a for a, k in keys().items() if k == want), "")


def action_for_button(button: str) -> str:
    return next((a for a, b in pads().items() if b == button), "")


def key_for(action: str) -> list | None:
    """What a controller press of this action types: its key, or its default key if you left it unbound."""
    k = keys().get(action)
    return k or next((normalize(*d) for a, _, d, _ in ACTIONS if a == action), None)


def set_key(action: str, key: int, mods: int) -> None:
    """Bind a key to an action. An action that had that key takes this action's old key (a swap)."""
    if action not in IDS:
        return
    now = keys()
    new = normalize(key, mods)
    for other, k in now.items():
        if other != action and k == new:
            now[other] = now[action]
    now[action] = new
    db.set_setting("key_bindings", json.dumps(now))


def set_pad(action: str, button: str) -> None:
    if action not in IDS or button not in BUTTONS:
        return
    now = pads()
    for other, b in now.items():
        if other != action and b == button:
            now[other] = now[action]
    now[action] = button
    db.set_setting("pad_bindings", json.dumps(now))


def reset() -> None:
    db.set_setting("key_bindings", "")
    db.set_setting("pad_bindings", "")


def key_label(k) -> str:
    if not k:
        return "None"
    names = {K["Return"]: "Enter", K["Escape"]: "Esc", K["Space"]: "Space", K["Tab"]: "Tab",
             K["Up"]: "↑", K["Down"]: "↓", K["Left"]: "←", K["Right"]: "→"}
    key, mods = k
    base = names.get(key) or QKeySequence(key).toString(QKeySequence.NativeText) or "?"
    prefix = "".join(p for bit, p in ((CTRL, "Ctrl+"), (ALT, "Alt+"), (SHIFT, "Shift+")) if mods & bit)
    return prefix + base


def rows() -> list[dict]:
    """For Settings > Controls."""
    k, p = keys(), pads()
    return [{"id": a, "label": label, "key": key_label(k[a]), "button": p[a] or "None"} for a, label, _, _ in ACTIONS]
