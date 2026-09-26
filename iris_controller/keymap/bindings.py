"""The binding tables: which button sends which keys. Change a binding here,
then regenerate KEYMAP.md (see keymap/docs.py)."""

from __future__ import annotations

from typing import NamedTuple

from evdev import ecodes as e

# Right-hand Super/Alt, so layouts that swap the left ones
# (altwin:swap_lalt_lwin) still get the modifier they expect.
SUPER, SHIFT, CTRL, ALT = e.KEY_RIGHTMETA, e.KEY_LEFTSHIFT, e.KEY_LEFTCTRL, e.KEY_RIGHTALT

DOUBLE_TAP_WINDOW = 0.25    # a second press within this = a double tap; a single one waits this long


class Bind(NamedTuple):
    keys: list[int]
    label: str       # shown in the cheat sheet overlay and KEYMAP.md
    run: str | None = None   # a shell command instead of keys (user binds)


# Buttons mirrored as held keys (so autorepeat and drag work).
BASE_HOLD = {
    e.BTN_SOUTH: Bind([e.BTN_LEFT], "Left click (hold = drag)"),  # ✕
    e.BTN_EAST: Bind([e.KEY_ESC], "Escape"),                      # ○
    e.BTN_WEST: Bind([e.KEY_ENTER], "Enter"),                     # □
    e.BTN_NORTH: Bind([e.KEY_BACKSPACE], "Backspace"),            # △
}
# One-shot chords on press. Create is free.
BASE_TAP = {
    e.BTN_START: Bind([SUPER, e.KEY_SPACE], "Omarchy menu"),      # Options
}
ENTER_BTN = e.BTN_WEST      # □: Enter, double tap = Ctrl+Enter
ENTER_DOUBLE = Bind([CTRL, e.KEY_ENTER], "Ctrl + Enter (double tap)")       # □ twice
# L2 is a modifier for the combos below; L2 + R2 together is fullscreen.
# R2 held is window mode (modes/window.py).
RIGHT_CLICK = Bind([e.BTN_RIGHT], "Right click")                # L2 + ✕
FULLSCREEN = Bind([SUPER, e.KEY_F], "Fullscreen")               # L2 + R2 together
REFRESH = Bind([CTRL, e.KEY_R], "Refresh")                      # R2 + △
# L2 + D-pad ←/→: back / forward, as in browsers and file managers.
NAV_BACK = Bind([ALT, e.KEY_LEFT], "Back")
NAV_FORWARD = Bind([ALT, e.KEY_RIGHT], "Forward")
# L2 held + another button: one-shot chord. Copy/paste are Omarchy's universal
# ones, so they work in terminals too.
L2_COMBOS = {
    e.BTN_NORTH: Bind([SUPER, e.KEY_W], "Close window"),          # △
    e.BTN_WEST: Bind([SUPER, e.KEY_C], "Copy"),                   # □
    e.BTN_EAST: Bind([SUPER, e.KEY_V], "Paste"),                  # ○
}
ZOOM_IN = Bind([CTRL, e.KEY_EQUAL], "Bigger text")              # L2 + right stick
ZOOM_OUT = Bind([CTRL, e.KEY_MINUS], "Smaller text")
# L2 + right stick sideways: next/previous workspace on the focused
# monitor (empty ones too).
NEXT_WS = 'hl.dsp.focus({ workspace = "r+1" })'
PREV_WS = 'hl.dsp.focus({ workspace = "r-1" })'
# PS button held + another button: one-shot chord (cancels the tap and hold).
# Empty: the PS button only toggles game mode.
PS_COMBOS: dict[int, Bind] = {}
# L1 held + another button: one-shot chord. Empty: user binds only
# ("L1 + ○" in [[bind]]); until then L1 isn't a layer.
L1_COMBOS: dict[int, Bind] = {}
# Touchpad swipe up/down: the media keys, so Omarchy's volume binding and OSD apply.
VOLUME_UP, VOLUME_DOWN = [e.KEY_VOLUMEUP], [e.KEY_VOLUMEDOWN]
ARROWS = {"left": e.KEY_LEFT, "right": e.KEY_RIGHT, "up": e.KEY_UP, "down": e.KEY_DOWN}

# L2/R2 double tap: user binds only ("R2 double" / "L2 double" in [[bind]]).
# An R2 double tap makes every R2 hold wait DOUBLE_TAP_WINDOW before it counts.
DOUBLE_TRIGGERS: dict[int, Bind] = {}
# R2 held + D-pad direction: user binds only ("R2 + ↑" in [[bind]]).
R2_DPAD: dict[str, Bind] = {}
DPAD_ARROWS = {"up": "↑", "right": "→", "down": "↓", "left": "←"}

# Where each input sits on the pad: an id the cheat sheet drawing knows, and
# the name printed in text.
PARTS = {
    e.BTN_SOUTH: ("cross", "✕"), e.BTN_EAST: ("circle", "○"), e.BTN_WEST: ("square", "□"),
    e.BTN_NORTH: ("triangle", "△"), e.BTN_TL: ("l1", "L1"), e.BTN_TR: ("r1", "R1"),
    e.BTN_THUMBL: ("lstick", "Left stick"), e.BTN_THUMBR: ("rstick", "Right stick"),
    e.BTN_START: ("options", "Options"), e.BTN_SELECT: ("create", "Create"),
    e.BTN_MODE: ("ps", "PS"), e.ABS_Z: ("l2", "L2"), e.ABS_RZ: ("r2", "R2"),
}


def output_keys() -> set[int]:
    """Every key and mouse button the bindings can send."""
    return (
        {k for m in (BASE_HOLD, BASE_TAP, PS_COMBOS, L1_COMBOS, L2_COMBOS, DOUBLE_TRIGGERS, R2_DPAD)
         for b in m.values() for k in b.keys}
        | {k for b in (ENTER_DOUBLE, RIGHT_CLICK, FULLSCREEN, REFRESH, NAV_BACK, NAV_FORWARD, ZOOM_IN, ZOOM_OUT)
           for k in b.keys}
        | set(ARROWS.values())
        | {e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN}
        | {SUPER, SHIFT, CTRL, ALT, e.KEY_A, e.KEY_Z}
        | {e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE}
    )
