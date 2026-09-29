"""What differs between the pads we drive. Everything past the mapper's
input edge speaks DualSense: an Xbox pad's events are translated to the
DualSense codes for the same place on the pad (its top face button, Y, is
△), and only the names shown to you change.

Xbox pads, by driver:
  xpad (USB cable), xone (the Xbox Wireless adapter), xpadneo (Bluetooth):
      sticks ABS_X/Y and ABS_RX/RY, triggers ABS_Z/RZ.
  Bluetooth without xpadneo (hid-microsoft / hid-generic): right stick on
      ABS_Z/RZ, triggers on ABS_BRAKE/GAS. Told apart by having ABS_GAS.
  All of them: X is BTN_NORTH and Y is BTN_WEST (the codes' names, not
      where the buttons sit), so the two are swapped. Share (Series pads)
      comes as KEY_RECORD, or KEY_ONSCREEN_KEYBOARD from xpadneo, on a device
      of its own, and opens the cheat sheet, like the DualSense mic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import evdev
from evdev import ecodes as e

MICROSOFT = 0x045E


@dataclass(frozen=True)
class Profile:
    kind: str                           # "dualsense" or "xbox"
    title: str                          # the cheat sheet's heading
    names: dict[int, str]               # DualSense code -> the name printed on this pad
    keys: dict[int, int] = field(default_factory=dict)    # this pad's key -> DualSense key
    axes: dict[int, int] = field(default_factory=dict)    # this pad's axis -> DualSense axis
    sheet_keys: tuple[int, ...] = ()    # keys that open the cheat sheet (the DualSense's mic is raw HID)
    sheet_name: str = "Mic"
    streams: bool = False               # raw HID reports all the time: the mic and the watchdog read them
    touchpad: bool = False
    drawing: bool = False               # the cheat sheet has a drawing of it (dualsense.svg)
    colors: dict[str, str] = field(default_factory=dict)  # face button part id -> its color

    def key(self, code: int) -> int:
        return self.keys.get(code, code)

    def axis(self, code: int) -> int:
        return self.axes.get(code, code)

    def buttons(self) -> dict[str, str]:
        """DualSense name -> this pad's ("□" -> "X"), for the screens that spell them out."""
        out = {DUALSENSE.names[c]: n for c, n in self.names.items() if DUALSENSE.names.get(c) != n}
        if self.sheet_name != DUALSENSE.sheet_name:
            out[DUALSENSE.sheet_name] = self.sheet_name
        return out

    def rename(self, text: str) -> str:
        """"R2 + □" -> "RT + X": word by word, so "L1 hold" and "□ □" work too."""
        names = self.buttons()
        return " ".join(names.get(w, w) for w in text.split(" "))


DUALSENSE = Profile(
    kind="dualsense", title="DUALSENSE",
    names={
        e.BTN_SOUTH: "✕", e.BTN_EAST: "○", e.BTN_WEST: "□", e.BTN_NORTH: "△",
        e.BTN_TL: "L1", e.BTN_TR: "R1", e.ABS_Z: "L2", e.ABS_RZ: "R2",
        e.BTN_THUMBL: "Left stick", e.BTN_THUMBR: "Right stick",
        e.BTN_START: "Options", e.BTN_SELECT: "Create", e.BTN_MODE: "PS",
    },
    streams=True, touchpad=True, drawing=True,
    colors={"triangle": "#3fc8a8", "circle": "#e8616b", "cross": "#7b9fe8", "square": "#d58ad8"},
)

_XBOX_NAMES = {
    e.BTN_SOUTH: "A", e.BTN_EAST: "B", e.BTN_WEST: "X", e.BTN_NORTH: "Y",
    e.BTN_TL: "LB", e.BTN_TR: "RB", e.ABS_Z: "LT", e.ABS_RZ: "RT",
    e.BTN_THUMBL: "Left stick", e.BTN_THUMBR: "Right stick",
    e.BTN_START: "Menu", e.BTN_SELECT: "View", e.BTN_MODE: "Xbox",
}
_XBOX_KEYS = {
    e.BTN_NORTH: e.BTN_WEST, e.BTN_WEST: e.BTN_NORTH,   # X is on the left, Y on top
    e.KEY_HOMEPAGE: e.BTN_MODE,                          # the Xbox button, on some Bluetooth firmware
    e.KEY_BACK: e.BTN_SELECT,                            # View, likewise
}
_XBOX_COLORS = {"cross": "#5fbf4a", "circle": "#e0524a", "square": "#3f8fe0", "triangle": "#e8c23a"}


def xbox(axes: dict[int, int]) -> Profile:
    return Profile(kind="xbox", title="XBOX", names=_XBOX_NAMES, keys=_XBOX_KEYS, axes=axes,
                   sheet_keys=(e.KEY_RECORD, e.KEY_ONSCREEN_KEYBOARD), sheet_name="Share",
                   colors=_XBOX_COLORS)


XBOX = xbox({})
# Bluetooth without xpadneo: right stick on Z/RZ, triggers on brake/gas.
XBOX_BT = xbox({e.ABS_Z: e.ABS_RX, e.ABS_RZ: e.ABS_RY, e.ABS_BRAKE: e.ABS_Z, e.ABS_GAS: e.ABS_RZ})


def is_xbox(dev: evdev.InputDevice) -> bool:
    name = dev.name.lower()
    return dev.info.vendor == MICROSOFT or "xbox" in name or "x-box" in name


def for_pad(dev: evdev.InputDevice) -> Profile:
    if not is_xbox(dev):
        return DUALSENSE
    axes = {code for code, _ in dev.capabilities().get(e.EV_ABS, [])}
    return XBOX_BT if e.ABS_GAS in axes else XBOX


# The pad attached now; the mapper sets it (screens read it for names).
active = DUALSENSE
