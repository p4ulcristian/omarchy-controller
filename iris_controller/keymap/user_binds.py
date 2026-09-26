"""Your own buttons: the config's [[bind]] entries, added to the binding tables."""

from __future__ import annotations

import logging

from evdev import ecodes as e

from ..core.config import CONFIG
from .bindings import ALT, CTRL, DOUBLE_TRIGGERS, PS_COMBOS, L1_COMBOS, R2_DPAD, SHIFT, SUPER, Bind

log = logging.getLogger("iris-controller")

# Names a [[bind]] input may use for a button.
BUTTON_NAMES = {
    "✕": e.BTN_SOUTH, "x": e.BTN_SOUTH, "cross": e.BTN_SOUTH,
    "○": e.BTN_EAST, "o": e.BTN_EAST, "circle": e.BTN_EAST,
    "□": e.BTN_WEST, "square": e.BTN_WEST,
    "△": e.BTN_NORTH, "triangle": e.BTN_NORTH,
    "l1": e.BTN_TL, "r1": e.BTN_TR, "l2": e.ABS_Z, "r2": e.ABS_RZ,
    "l3": e.BTN_THUMBL, "r3": e.BTN_THUMBR,
    "options": e.BTN_START, "create": e.BTN_SELECT, "ps": e.BTN_MODE,
}
DPAD_NAMES = {"↑": "up", "→": "right", "↓": "down", "←": "left",
              "up": "up", "right": "right", "down": "down", "left": "left"}
MODIFIERS = {"super": SUPER, "ctrl": CTRL, "shift": SHIFT, "alt": ALT}


def parse_keys(spec: str) -> list[int]:
    """"SUPER + W" -> [SUPER, KEY_W]."""
    keys = []
    for part in (p.strip().lower() for p in spec.split("+")):
        code = MODIFIERS.get(part) or getattr(e, "KEY_" + part.upper(), None)
        if code is None:
            raise ValueError(f"unknown key {part!r}")
        keys.append(code)
    return keys


def load_binds() -> None:
    """Add the config's [[bind]] entries to the tables:
         input = "L1 + ○" | "PS + ✕" | "R2 + ↑" (D-pad) | "R2 double" | "L2 double"
         run = "a shell command"  or  keys = "SUPER + W"
         label = "shown in the cheat sheet"
    A bad entry is logged and skipped; the rest still load."""
    for entry in CONFIG.get("bind", []):
        try:
            spec = entry["input"].strip().lower()
            if entry.get("run"):
                action = Bind([], entry.get("label", entry["run"]), entry["run"])
            else:
                action = Bind(parse_keys(entry["keys"]), entry.get("label", entry["keys"]))
            if spec.endswith(" double"):
                code = BUTTON_NAMES[spec.removesuffix(" double").strip()]
                if code not in (e.ABS_Z, e.ABS_RZ):
                    raise ValueError("double tap works on L2 and R2")
                DOUBLE_TRIGGERS[code] = action
            else:
                layer, _, button = (x.strip() for x in spec.partition("+"))
                if layer == "r2":
                    R2_DPAD[DPAD_NAMES[button.removeprefix("d-pad").strip()]] = action
                else:
                    table = {"l1": L1_COMBOS, "ps": PS_COMBOS}[layer]
                    table[BUTTON_NAMES[button]] = action
        except (KeyError, ValueError) as exc:
            log.warning("config bind %r skipped: %s", entry, exc)
