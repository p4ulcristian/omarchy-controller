#!/usr/bin/env python3
"""Drive Omarchy / Hyprland from a DualSense controller. Keymap: KEYMAP.md."""

from __future__ import annotations

import json
import logging
import os
import selectors
import signal
import socket
import subprocess
import sys
import time
import tomllib
from typing import NamedTuple

import evdev
from evdev import UInput, ecodes as e

log = logging.getLogger("iris-controller")

# The motion sensors are a separate device we leave alone; the touchpad is a
# separate device we use for swipes.
DUALSENSE_NAMES = ("DualSense Wireless Controller", "DualSense Edge Wireless Controller")
TOUCHPAD_SUFFIX = " Touchpad"   # grabbed like the pad: swipe pad, not a pointer
SWIPE_LOCK = 60                 # movement before a swipe commits to sideways or up/down
VOLUME_STEP = 100               # touchpad units (of 1080) per volume step
TOUCH_SIZE = (1920, 1080)       # DualSense touchpad resolution
CLICK_DEADZONE = 0.1            # taps/clicks this close to the centre have no direction: ignored
TAP_TIME = 0.25                 # a touch lifted within this, without sliding, is a tap
TICK = 0.008                 # seconds between pointer updates (~120 Hz)
DEADZONE = 0.15
POINTER_MAX = 1500.0         # px/s at full stick
SCROLL_MAX = 2400.0          # hi-res wheel units/s (120 = one notch)
TRIGGER_ON, TRIGGER_OFF = 0.5, 0.3
DOUBLE_TAP_WINDOW = 0.25    # second ✕ within this = Ctrl+Enter; a single ✕ waits this long
CHORD_WINDOW = 0.06         # L2 within this of R2 = fullscreen
ZOOM_THRESHOLD = 0.5         # right stick deflection that counts as a zoom step
ZOOM_REPEAT = 0.2           # seconds between zoom steps while the stick stays pushed
WORKSPACE_REPEAT = 0.4      # seconds between workspace steps while the stick stays pushed
RESIZE_SPEED = 900          # px/s the window grows at full RT + right stick
RESIZE_EVERY = 0.03         # at most one resize dispatch per this many seconds
GAME_TOGGLE_HOLD = 1.0      # hold the PS button this long to toggle game mode
GAME_POLL = 1.0
GAME_CLASSES = ("steam_app_", "gamescope")
MENU_LAYERS = ("omarchy-menu",)   # keyboard-driven overlays: the right stick sends arrows
MENU_CACHE = 0.25
HELP_PLUGIN = "p4ulcristian.iris-controller-help"   # Omarchy shell plugin in overlay/
MIC_BIT = 0x04     # DualSense mic button: third button byte of the raw HID report

CONFIG_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "iris-controller", "config.toml",
)


def load_config() -> dict:
    """Optional settings; see config.example.toml. Missing file = defaults."""
    try:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("config %s ignored: %s", CONFIG_PATH, exc)
        return {}


CONFIG = load_config()
# R1: push-to-talk dictation. A Unix socket that takes "start" and "stop".
DICTATE_SOCK = os.path.expanduser(CONFIG.get("dictate", {}).get("socket", "")) or None
# Rename actions in the cheat sheet, e.g. "Terminal" = "Claude in ~/Work".
LABELS: dict[str, str] = CONFIG.get("labels", {})
# A short popup naming each combo as it fires ("L2 + □ → Copy"), and each
# plain press ("□ → Enter").
COMBO_NOTIFY = CONFIG.get("notify", {}).get("combos", True)
BUTTON_NOTIFY = CONFIG.get("notify", {}).get("buttons", True)

# Right-hand Super/Alt, so layouts that swap the left ones
# (altwin:swap_lalt_lwin) still get the modifier they expect.
SUPER, SHIFT, CTRL, ALT = e.KEY_RIGHTMETA, e.KEY_LEFTSHIFT, e.KEY_LEFTCTRL, e.KEY_RIGHTALT

class Bind(NamedTuple):
    keys: list[int]
    label: str       # shown in the cheat sheet overlay and KEYMAP.md
    run: str | None = None   # a shell command instead of keys (user binds)


# Buttons mirrored as held keys (so autorepeat and drag work).
BASE_HOLD = {
    e.BTN_SOUTH: Bind([e.BTN_LEFT], "Left click (hold = drag)"),  # physical A / Cross
    e.BTN_EAST: Bind([e.KEY_ESC], "Escape"),
    e.BTN_WEST: Bind([e.KEY_ENTER], "Enter"),                     # physical X / Square
    e.BTN_NORTH: Bind([e.KEY_BACKSPACE], "Backspace"),            # physical Y / Triangle
}
# One-shot chords on press.
BASE_TAP = {
    e.BTN_START: Bind([SUPER, e.KEY_SPACE], "Omarchy menu"),
    e.BTN_SELECT: Bind([SUPER, e.KEY_W], "Close window"),
}
ENTER_BTN = e.BTN_WEST      # □: Enter, double tap = Ctrl+Enter
ENTER_DOUBLE = Bind([CTRL, e.KEY_ENTER], "Ctrl + Enter (double tap)")       # □ twice
# LT is a modifier for the combos below; LT + RT together is fullscreen.
# RT held is window mode: the left stick drags the window (Super + left
# button, pressed once the stick moves), the right stick resizes it.
WINDOW_DRAG = [SUPER, e.BTN_LEFT]
# RT + right stick sideways once a drag has started: take the window along
# to the previous/next workspace.
MOVE_NEXT_WS = 'hl.dsp.window.move({ workspace = "r+1" })'
MOVE_PREV_WS = 'hl.dsp.window.move({ workspace = "r-1" })'
RIGHT_CLICK = Bind([e.BTN_RIGHT], "Right click")                # LT + ✕
FULLSCREEN = Bind([SUPER, e.KEY_F], "Fullscreen")               # LT + RT together
# LT held + another button: one-shot chord. Copy/paste are Omarchy's universal
# ones, so they work in terminals too.
LT_COMBOS = {
    e.BTN_NORTH: Bind([SUPER, e.KEY_W], "Close window"),          # physical Y / Triangle
    e.BTN_WEST: Bind([SUPER, e.KEY_C], "Copy"),                   # physical X / Square
    e.BTN_EAST: Bind([SUPER, e.KEY_V], "Paste"),                  # physical B / Circle
}
ZOOM_IN = Bind([CTRL, e.KEY_EQUAL], "Bigger text")              # LB + right stick
ZOOM_OUT = Bind([CTRL, e.KEY_MINUS], "Smaller text")
# LB or LT + right stick sideways: next/previous workspace on the focused
# monitor (empty ones too).
NEXT_WS = 'hl.dsp.focus({ workspace = "r+1" })'
PREV_WS = 'hl.dsp.focus({ workspace = "r-1" })'
# PS button held + another button: one-shot chord (cancels the tap and hold).
# Empty: combos live on L1, the PS button only toggles game mode.
GUIDE_COMBOS: dict[int, Bind] = {}
# LB held + another button: one-shot chord.
LB_COMBOS = {
    e.BTN_SOUTH: Bind([SUPER, e.KEY_ENTER], "Terminal"),
    e.BTN_NORTH: Bind([SUPER, e.KEY_W], "Close window"),          # physical Y / Triangle
}
# Touchpad swipe up/down: the media keys, so Omarchy's volume binding and OSD apply.
VOLUME_UP, VOLUME_DOWN = [e.KEY_VOLUMEUP], [e.KEY_VOLUMEDOWN]
ARROWS = {"left": e.KEY_LEFT, "right": e.KEY_RIGHT, "up": e.KEY_UP, "down": e.KEY_DOWN}

# L2/R2 double tap: user binds only (see [[bind]] in config.example.toml).
DOUBLE_TRIGGERS: dict[int, Bind] = {}
# RT held + D-pad direction: user binds only ("R2 + ↑" in [[bind]]).
RT_DPAD: dict[str, Bind] = {}
DPAD_NAMES = {"↑": "up", "→": "right", "↓": "down", "←": "left",
              "up": "up", "right": "right", "down": "down", "left": "left"}
DPAD_ARROWS = {"up": "↑", "right": "→", "down": "↓", "left": "←"}

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
                    RT_DPAD[DPAD_NAMES[button.removeprefix("d-pad").strip()]] = action
                else:
                    table = {"l1": LB_COMBOS, "ps": GUIDE_COMBOS}[layer]
                    table[BUTTON_NAMES[button]] = action
        except (KeyError, ValueError) as exc:
            log.warning("config bind %r skipped: %s", entry, exc)


load_binds()

OUT_KEYS = sorted(
    {k for m in (BASE_HOLD, BASE_TAP, GUIDE_COMBOS, LB_COMBOS, LT_COMBOS, DOUBLE_TRIGGERS, RT_DPAD)
     for b in m.values() for k in b.keys}
    | {k for b in (ENTER_DOUBLE, RIGHT_CLICK, FULLSCREEN, ZOOM_IN, ZOOM_OUT) for k in b.keys}
    | set(ARROWS.values())
    | {e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN}
    | {SUPER, SHIFT, CTRL, ALT, e.KEY_A, e.KEY_Z}
    | {e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE}
)

# Where each input sits on the pad: an id the overlay drawing knows, and the name
# printed in text.
PARTS = {
    e.BTN_SOUTH: ("cross", "✕"), e.BTN_EAST: ("circle", "○"), e.BTN_WEST: ("square", "□"),
    e.BTN_NORTH: ("triangle", "△"), e.BTN_TL: ("l1", "L1"), e.BTN_TR: ("r1", "R1"),
    e.BTN_THUMBL: ("lstick", "Left stick"), e.BTN_THUMBR: ("rstick", "Right stick"),
    e.BTN_START: ("options", "Options"), e.BTN_SELECT: ("create", "Create"),
    e.BTN_MODE: ("ps", "PS"), e.ABS_Z: ("l2", "L2"), e.ABS_RZ: ("r2", "R2"),
}


def keymap() -> dict:
    """Every mapping, from the tables above, for the overlay and KEYMAP.md:
    parts: {id: {name, actions}} labels on the drawing; combos: [{keys, action}]."""
    parts = {pid: {"name": name, "actions": []} for pid, name in PARTS.values()}
    parts |= {"dpad": {"name": "D-pad", "actions": []},
              "touchpad": {"name": "Touchpad", "actions": []},
              "mic": {"name": "Mic", "actions": []}}

    def add(code_or_id, action):
        action = LABELS.get(action, action)
        parts[PARTS[code_or_id][0] if code_or_id in PARTS else code_or_id]["actions"].append(action)

    def name(code):
        return PARTS[code][1]

    add("lstick", "Move pointer")
    add("rstick", "Scroll")
    for code, b in BASE_HOLD.items():
        add(code, b.label)
    for code, b in BASE_TAP.items():
        add(code, b.label)
    if DICTATE_SOCK:
        add(e.BTN_TR, "Hold: dictate")
    add(e.BTN_TL, "Hold: combo layer")
    add(e.BTN_MODE, "Hold 1 s: game mode on/off")
    add(e.ABS_Z, "Hold + ✕: right click")
    add("dpad", "Arrow keys (hold to repeat)")
    add(e.ABS_Z, "Hold + right stick ←/→: previous / next workspace")
    add(e.ABS_Z, "Hold + D-pad ↑/↓: volume up / down")
    add(e.ABS_RZ, "Hold + left stick: move window")
    add(e.ABS_RZ, "Hold + right stick: resize window")
    add(e.ABS_RZ, "Dragging + right stick ←/→: take window to prev / next workspace")
    add("touchpad", "Swipe ↑/↓: volume up / down")
    add("touchpad", "Tap: arrow key toward that side")
    add("touchpad", "Click & hold: arrow key, repeating")
    add("mic", "Show / hide this cheat sheet")

    combos = [{"keys": [name(ENTER_BTN), name(ENTER_BTN)], "action": ENTER_DOUBLE.label},
              *({"keys": [name(c), name(c)], "action": b.label} for c, b in DOUBLE_TRIGGERS.items()),
              {"keys": [name(e.ABS_Z), name(e.ABS_RZ)], "action": FULLSCREEN.label},
              {"keys": ["Hold " + name(e.ABS_Z), name(e.BTN_SOUTH)], "action": RIGHT_CLICK.label},
              {"keys": ["Hold " + name(e.ABS_Z), "R-stick ←"], "action": "Previous workspace"},
              {"keys": ["Hold " + name(e.ABS_Z), "R-stick →"], "action": "Next workspace"},
              {"keys": ["Hold " + name(e.ABS_Z), "D-pad ↑"], "action": "Volume up"},
              {"keys": ["Hold " + name(e.ABS_Z), "D-pad ↓"], "action": "Volume down"},
              {"keys": ["Hold " + name(e.ABS_RZ), "Left stick"], "action": "Move window"},
              {"keys": ["Hold " + name(e.ABS_RZ), "R-stick"], "action": "Resize window (→/↓ bigger)"},
              {"keys": ["Hold " + name(e.ABS_RZ), "Left stick", "R-stick ←/→"],
               "action": "Take window to prev / next workspace"}]
    combos += [{"keys": ["Hold " + name(e.ABS_RZ), "D-pad " + DPAD_ARROWS[d]], "action": b.label}
               for d, b in RT_DPAD.items()]
    combos += [{"keys": ["Hold " + name(e.ABS_Z), name(c)], "action": b.label}
               for c, b in LT_COMBOS.items()]
    combos += [{"keys": ["Hold " + name(e.BTN_MODE), name(c)], "action": b.label}
               for c, b in GUIDE_COMBOS.items()]
    combos += [{"keys": ["Hold " + name(e.BTN_TL), "R-stick ←"], "action": "Previous workspace"},
               {"keys": ["Hold " + name(e.BTN_TL), "R-stick →"], "action": "Next workspace"},
               {"keys": ["Hold " + name(e.BTN_TL), "R-stick ↑"], "action": ZOOM_IN.label},
               {"keys": ["Hold " + name(e.BTN_TL), "R-stick ↓"], "action": ZOOM_OUT.label}]
    combos += [{"keys": ["Hold " + name(e.BTN_TL), name(c)], "action": b.label}
               for c, b in LB_COMBOS.items()]
    menu = [{"keys": ["D-pad", "R-stick"], "action": "Move through the list"},
            {"keys": [name(e.BTN_SOUTH) + " / " + name(ENTER_BTN)], "action": "Open"},
            {"keys": [name(e.BTN_EAST)], "action": "Close"}]
    for c in combos:
        c["action"] = LABELS.get(c["action"], c["action"])
    return {"parts": parts, "combos": combos, "menu": menu}


def keymap_markdown() -> str:
    km = keymap()
    out = ["# iris-controller keymap", "",
           "Generated by `python3 iris_controller.py --keymap > KEYMAP.md`; "
           "edit the tables in the script, not this file.",
           "Press the mic button to toggle it as an overlay.", "",
           "## Buttons", "", "| Input | Action |", "|---|---|"]
    for part in km["parts"].values():
        out += [f"| {part['name']} | {a} |" for a in part["actions"]]
    for title, rows in (("Combos", km["combos"]), ("In the Omarchy menu", km["menu"])):
        out += ["", f"## {title}", "", "| Input | Action |", "|---|---|"]
        out += [f"| {' + '.join(r['keys'])} | {r['action']} |" for r in rows]
    out += ["", "## Game mode", "",
            "The mapper grabs the controller while it runs, so games would see nothing.",
            "- Hold the PS button for 1 second to release/retake the controller.",
            "- Auto: pause when the focused window is fullscreen and belongs to Steam "
            "(`steam_app_*` class) or gamescope.", ""]
    return "\n".join(out)


def hyprctl_json(what: str):
    try:
        out = subprocess.run(["hyprctl", "-j", what], capture_output=True, text=True, timeout=1)
        return json.loads(out.stdout)
    except Exception:
        return None


MOUSE_FOCUS = "misc:mouse_move_focuses_monitor"


def workspace_name() -> str:
    return (hyprctl_json("activeworkspace") or {}).get("name", "?")


def mouse_focus_option() -> bool:
    return bool((hyprctl_json(f"getoption {MOUSE_FOCUS}") or {}).get("bool", True))


def set_mouse_focus(on: bool) -> None:
    """Whether moving the pointer onto another monitor focuses it. Without it,
    pointing at an empty monitor leaves focus behind, so the Omarchy menu and
    workspace swipes act on the old one. Some setups turn it off so games
    don't lose focus mid-match; the controller only turns it on while it is
    driving the desktop, and puts the user's value back in game mode."""
    subprocess.run(["hyprctl", "eval",
                    f"hl.config({{ misc = {{ mouse_move_focuses_monitor = {str(on).lower()} }} }})"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def hypr_dispatch(arg: str) -> None:
    subprocess.Popen(["hyprctl", "dispatch", arg],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def dictate(verb: str) -> None:
    if not DICTATE_SOCK:
        return
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(DICTATE_SOCK)
        s.sendall(verb.encode())
        s.shutdown(socket.SHUT_WR)
        s.recv(64)
        s.close()
    except Exception as exc:
        log.warning("dictate %s failed: %s", verb, exc)


_note: list = [None, "0"]    # the last notify-send, and the notification id it got


def notify(msg: str) -> None:
    # Replaces the previous popup instead of stacking. The daemon picks the id
    # (notify-send -p prints it), so it is read back from the last call once
    # that has finished; waiting for it would stall the pointer.
    proc = _note[0]
    if proc and proc.poll() is not None:
        _note[1] = proc.stdout.read().strip() or _note[1]
        proc.stdout.close()
    _note[0] = subprocess.Popen(["notify-send", "-p", "-r", _note[1], "-t", "1500",
                                 "Controller", msg],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)


def find_hidraw(dev: evdev.InputDevice) -> int | None:
    """Open the raw HID node behind an evdev device (non-blocking), if we may read it."""
    hid = os.path.realpath(f"/sys/class/input/{os.path.basename(dev.path)}/device/device")
    try:
        name = os.listdir(os.path.join(hid, "hidraw"))[0]
        return os.open(f"/dev/{name}", os.O_RDONLY | os.O_NONBLOCK)
    except (OSError, IndexError) as exc:
        log.warning("no raw HID access for %s: %s", dev.name, exc)
        return None


def find_controller() -> list[evdev.InputDevice]:
    devs = []
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except OSError:
            continue
        if d.name.removesuffix(TOUCHPAD_SUFFIX) in DUALSENSE_NAMES:
            devs.append(d)
        else:
            d.close()
    return devs


class Mapper:
    def __init__(self, ui: UInput) -> None:
        self.ui = ui
        self.devs: list[evdev.InputDevice] = []
        self.pad: evdev.InputDevice | None = None
        self.touch: evdev.InputDevice | None = None
        self.touch_pos = [None, None]           # finger x, y on the touchpad
        self.swipe_from: list[int] | None = None  # where the swipe started (or last volume step)
        self.swipe_axis: str | None = None      # "x"/"y" once the swipe has a direction, "click" if clicked
        self.click_pending = False              # pad pressed; zone decided at the end of the report
        self.touch_since = 0.0                  # when the finger landed, for taps
        self.touching = False
        self.hid_fd: int | None = None          # DualSense raw reports, for the mic button
        self.mic_down = False
        self.help_open = False                  # cheat sheet showing (mic toggles it)
        self.help_proc: subprocess.Popen | None = None
        self.axes: dict[int, float] = {}
        self.ranges: dict[int, tuple[int, int]] = {}
        self.guide_since: float | None = None   # PS button press time
        self.guide_fired = False
        self.held_out: set[int] = set()         # output keys currently down
        self.btn_owner: dict[object, list[int]] = {}  # input -> output keys held for it
        self.trig = {e.ABS_Z: False, e.ABS_RZ: False}
        self.trig_pending: dict[int, float] = {}  # trigger -> press time, action not sent yet
        self.trig_tapped: dict[int, float] = {}   # trigger -> when a quick tap ended (double tap)
        self.trig_consumed: set[int] = set()      # second press of a double tap: its release does nothing
        self.hat = {"x": 0, "y": 0}
        self.zoom_mode = False                  # LB held: right stick zooms
        self.enter_first: float | None = None   # first □ press, waiting for a second one
        self.zoom_next = 0.0                    # when the next zoom/arrow step may fire
        self.resize_acc = [0.0, 0.0]            # RT + right stick: px not yet sent
        self.dragged = False                    # this RT hold has dragged: right stick = workspaces
        self.resized = False                    # this RT hold has resized (announced once)
        self.resize_next = 0.0                  # when the next resize may be sent
        self.menu_checked = (0.0, False)        # (time, omarchy menu open?)
        self.acc = [0.0, 0.0, 0.0, 0.0]         # dx, dy, wheel_v, wheel_h
        self.manual_pause = False
        self.auto_pause = False
        self.grabbed = False
        self.mouse_focus_user = mouse_focus_option()   # restored whenever we let go

    # --- device lifecycle -------------------------------------------------

    def attach(self, devs: list[evdev.InputDevice]) -> None:
        self.devs = devs
        self.touch = next((d for d in devs if d.name.endswith(TOUCHPAD_SUFFIX)), None)
        self.pad = next((d for d in devs
                         if d is not self.touch and e.EV_ABS in d.capabilities()), None)
        if self.pad:
            for code, info in self.pad.capabilities()[e.EV_ABS]:
                self.ranges[code] = (info.min, info.max)
            self.hid_fd = find_hidraw(self.pad)
        log.info("attached: %s", ", ".join(f"{d.name} ({d.path})" for d in devs))
        self.update_grab()

    def detach(self) -> None:
        self.release_all()
        if self.hid_fd is not None:
            os.close(self.hid_fd)
            self.hid_fd = None
        for d in self.devs:
            try:
                d.close()
            except Exception:
                pass
        if self.grabbed:
            set_mouse_focus(self.mouse_focus_user)
        self.devs, self.pad, self.touch, self.grabbed = [], None, None, False
        self.axes.clear()

    @property
    def paused(self) -> bool:
        return self.manual_pause or self.auto_pause

    def update_grab(self) -> None:
        want = not self.paused
        if want == self.grabbed:
            return
        for d in self.devs:
            try:
                d.grab() if want else d.ungrab()
            except OSError as exc:
                log.warning("grab %s: %s", d.path, exc)
        self.grabbed = want
        set_mouse_focus(True if want else self.mouse_focus_user)
        if not want:
            self.release_all()

    # --- output helpers ---------------------------------------------------

    def key(self, code: int, down: bool) -> None:
        if down == (code in self.held_out):
            return
        self.ui.write(e.EV_KEY, code, 1 if down else 0)
        self.ui.syn()
        (self.held_out.add if down else self.held_out.discard)(code)

    def tap(self, combo: list[int]) -> None:
        for k in combo:
            self.ui.write(e.EV_KEY, k, 1)
            self.ui.syn()
        for k in reversed(combo):
            self.ui.write(e.EV_KEY, k, 0)
            self.ui.syn()

    def fire(self, bind: Bind) -> None:
        """A one-shot action: its keys, or its command (detached, output dropped)."""
        if bind.run:
            log.info("run: %s", bind.run)
            subprocess.Popen(["sh", "-c", bind.run], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        else:
            self.tap(bind.keys)

    def announce(self, inputs: str, action: str, plain: bool = False) -> None:
        # Names what just fired. The cheat sheet's notes ("(hold = drag)") are dropped.
        if BUTTON_NOTIFY if plain else COMBO_NOTIFY:
            notify(f"{inputs} → {LABELS.get(action, action.split(' (')[0])}")

    def hold(self, owner, combo: list[int]) -> None:
        self.btn_owner[owner] = combo
        for k in combo:
            self.key(k, True)

    def unhold(self, owner) -> None:
        for k in reversed(self.btn_owner.pop(owner, [])):
            self.key(k, False)

    def release_all(self) -> None:
        self.enter_first = None
        self.trig_pending.clear()
        self.mic_down = False
        if self.help_open:
            self.show_help(False)
        if self.btn_owner.pop("dictate", None) is not None:
            dictate("stop")
        for owner in list(self.btn_owner):
            self.unhold(owner)
        for k in list(self.held_out):
            self.key(k, False)

    # --- input ------------------------------------------------------------

    def norm(self, code: int, value: int) -> float:
        lo, hi = self.ranges.get(code, (-32768, 32767))
        if code in (e.ABS_Z, e.ABS_RZ):
            return (value - lo) / (hi - lo) if hi > lo else 0.0
        mid = (lo + hi) / 2
        return max(-1.0, min(1.0, (value - mid) / ((hi - lo) / 2)))

    def handle(self, ev, dev=None) -> None:
        if dev is not None and dev is self.touch:
            self.on_touch(ev)
            return
        if ev.type == e.EV_ABS:
            self.on_abs(ev.code, ev.value)
        elif ev.type == e.EV_KEY and ev.value in (0, 1):
            log.debug("key %s %s", e.KEY.get(ev.code) or e.BTN.get(ev.code) or ev.code, ev.value)
            self.on_button(ev.code, ev.value == 1)

    def on_touch(self, ev) -> None:
        # One finger sliding up/down = volume, one step per VOLUME_STEP
        # travelled; sideways does nothing. A tap (touch and lift, no slide)
        # or a click is an arrow key: the side you touch is the arrow sent.
        if self.paused:
            return
        if ev.type == e.EV_KEY and ev.code == e.BTN_TOUCH:
            if not ev.value and self.is_tap():
                zone = self.pad_zone(*self.swipe_from)
                if zone:
                    self.tap([ARROWS[zone]])
                    self.announce("Touchpad tap", zone.capitalize(), plain=True)
            self.touching = bool(ev.value)
            self.touch_since = time.monotonic()
            self.touch_pos, self.swipe_from = [None, None], None
            self.swipe_axis = None
        elif ev.type == e.EV_KEY and ev.code == e.BTN_LEFT:
            if ev.value == 1:
                # The finger position may come later in the same report, so
                # the zone is picked at its end (EV_SYN).
                self.click_pending = True
            elif ev.value == 0:
                if self.click_pending:
                    self.on_pad_click()
                self.unhold("touchclick")
        elif ev.type == e.EV_SYN and self.click_pending:
            self.on_pad_click()
        elif ev.type == e.EV_ABS and ev.code in (e.ABS_X, e.ABS_Y) and self.touching:
            self.touch_pos[0 if ev.code == e.ABS_X else 1] = ev.value
            if None not in self.touch_pos:
                self.on_swipe(*self.touch_pos)

    def is_tap(self) -> bool:
        # Short, never slid far enough to count as a swipe, and not a click
        # (which already sent its arrow).
        return (self.swipe_from is not None and self.swipe_axis is None
                and time.monotonic() - self.touch_since < TAP_TIME)

    @staticmethod
    def pad_zone(x: int | None, y: int | None) -> str | None:
        """Which arrow a touch at (x, y) means. -1..1 from the centre; the axis
        pushed further wins, so the pad splits into four triangles and a
        corner belongs to one arrow."""
        if x is None or y is None:
            return None
        dx = x / TOUCH_SIZE[0] * 2 - 1
        dy = y / TOUCH_SIZE[1] * 2 - 1
        if max(abs(dx), abs(dy)) <= CLICK_DEADZONE:
            return None
        if abs(dx) >= abs(dy):
            return "left" if dx < 0 else "right"
        return "up" if dy < 0 else "down"

    def on_pad_click(self) -> None:
        self.click_pending = False
        self.swipe_axis = "click"               # pressing moves the finger: no volume, no tap
        zone = self.pad_zone(*self.touch_pos)
        # Held like a key, so holding the click autorepeats the arrow.
        if zone:
            self.hold("touchclick", [ARROWS[zone]])
            self.announce("Touchpad click", zone.capitalize(), plain=True)

    def on_swipe(self, x: int, y: int) -> None:
        if self.swipe_from is None:
            self.swipe_from = [x, y]             # first position after landing
            return
        dx, dy = x - self.swipe_from[0], y - self.swipe_from[1]
        if self.swipe_axis is None:
            if max(abs(dx), abs(dy)) < SWIPE_LOCK:
                return
            self.swipe_axis = "x" if abs(dx) >= abs(dy) else "y"
        # A sideways swipe is locked out, so drifting while clicking or
        # resting a thumb never changes the volume.
        if self.swipe_axis == "y" and abs(dy) >= VOLUME_STEP:
            self.tap(VOLUME_UP if dy < 0 else VOLUME_DOWN)   # touchpad y grows downward
            self.announce("Touchpad swipe", "Volume up" if dy < 0 else "Volume down", plain=True)
            self.swipe_from[1] += VOLUME_STEP if dy > 0 else -VOLUME_STEP

    def on_hid(self, report: bytes) -> None:
        # The kernel driver drops the mic button, so read it from the raw report:
        # Bluetooth report 0x31 has it in byte 11, USB report 0x01 in byte 10.
        if self.paused or len(report) < 12 or report[0] not in (0x01, 0x31):
            return
        down = bool(report[11 if report[0] == 0x31 else 10] & MIC_BIT)
        if down != self.mic_down:
            self.mic_down = down
            if down:
                self.show_help(not self.help_open)

    def show_help(self, show: bool) -> None:
        # Cheat sheet toggled by the mic button: the Omarchy shell plugin renders keymap().
        self.help_open = show
        if show:
            payload = json.dumps(keymap())
            cmd = ["omarchy-shell", "-q", "shell", "summon", HELP_PLUGIN, payload]
        else:
            cmd = ["omarchy-shell", "-q", "shell", "hide", HELP_PLUGIN]
            if self.help_proc:
                try:
                    self.help_proc.wait(timeout=1)   # a quick tap: summon lands first
                except subprocess.TimeoutExpired:
                    pass
        self.help_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)

    def on_button(self, code, down: bool) -> None:
        # PS button: a layer for GUIDE_COMBOS; held alone it toggles game mode
        # (see check_guide). A tap on its own does nothing.
        if code == e.BTN_MODE:
            if down:
                self.guide_since, self.guide_fired = time.monotonic(), False
            else:
                self.guide_since = None
            return
        if self.paused:
            return

        if down and self.guide_since is not None:
            self.guide_fired = True
            if code in GUIDE_COMBOS:
                self.fire(GUIDE_COMBOS[code])
                self.announce("PS + " + PARTS[code][1], GUIDE_COMBOS[code].label)
                return
        if down and self.zoom_mode and code in LB_COMBOS:
            self.fire(LB_COMBOS[code])
            self.announce("L1 + " + PARTS[code][1], LB_COMBOS[code].label)
            return
        if down and self.trig[e.ABS_Z] and code in LT_COMBOS:
            self.fire(LT_COMBOS[code])
            self.announce("L2 + " + PARTS[code][1], LT_COMBOS[code].label)
            return
        # A layer held + a button with no combo on it: dropped, not the plain
        # action. L2 + ✕ (right click) and the stick clicks aren't combos.
        layer = ("PS" if self.guide_since is not None else "L1" if self.zoom_mode
                 else "L2" if self.trig[e.ABS_Z] and code != e.BTN_SOUTH else None)
        if down and layer and code in PARTS and \
                code not in (e.BTN_TL, e.BTN_THUMBL, e.BTN_THUMBR):
            self.announce(f"{layer} + {PARTS[code][1]}", "No such combo")
            return

        if code == ENTER_BTN:
            self.on_enter(down)
            return
        if code == e.BTN_TL:
            self.zoom_mode = down        # right stick zooms instead of scrolling
            self.zoom_next = 0.0
            return

        if not down:
            if code == e.BTN_TR and self.btn_owner.pop("dictate", None) is not None:
                dictate("stop")
            self.unhold(code)
            return

        if code == e.BTN_TR:
            if DICTATE_SOCK:
                self.btn_owner["dictate"] = []
                dictate("start")
                self.announce("R1", "Dictate", plain=True)
        elif code == e.BTN_SOUTH and self.menu_open():
            self.hold(code, [e.KEY_ENTER])   # ✕ confirms in the menu instead of clicking
            self.announce("✕", "Enter", plain=True)
        elif code == e.BTN_SOUTH and self.trig[e.ABS_Z]:
            self.hold(code, RIGHT_CLICK.keys)   # LT held: ✕ is the right button (hold = drag)
            self.announce("L2 + ✕", RIGHT_CLICK.label)
        elif code in BASE_HOLD:
            self.hold(code, BASE_HOLD[code].keys)
            self.announce(PARTS[code][1], BASE_HOLD[code].label, plain=True)
        elif code in BASE_TAP:
            self.tap(BASE_TAP[code].keys)
            self.announce(PARTS[code][1], BASE_TAP[code].label, plain=True)

    def on_enter(self, down: bool) -> None:
        # □ is Enter, but a second press within DOUBLE_TAP_WINDOW makes it
        # Ctrl+Enter instead, so the first press is held back until then.
        if not down:
            self.unhold(ENTER_BTN)       # only held if the window already ran out
            return
        if self.enter_first is not None:
            self.enter_first = None
            self.tap(ENTER_DOUBLE.keys)
            self.announce("□ □", ENTER_DOUBLE.label)
        else:
            self.enter_first = time.monotonic()

    def check_enter(self) -> None:
        if self.enter_first is None or time.monotonic() - self.enter_first < DOUBLE_TAP_WINDOW:
            return
        self.enter_first = None
        # Still held: hold Enter so it autorepeats; already released: one Enter.
        if self.enter_held():
            self.hold(ENTER_BTN, BASE_HOLD[ENTER_BTN].keys)
        else:
            self.tap(BASE_HOLD[ENTER_BTN].keys)
        self.announce(PARTS[ENTER_BTN][1], BASE_HOLD[ENTER_BTN].label, plain=True)

    def enter_held(self) -> bool:
        try:
            return ENTER_BTN in self.pad.active_keys()
        except (OSError, AttributeError):
            return False

    def on_abs(self, code: int, value: int) -> None:
        if code in (e.ABS_HAT0X, e.ABS_HAT0Y):
            self.on_hat("x" if code == e.ABS_HAT0X else "y", value)
            return
        v = self.norm(code, value)
        self.axes[code] = v
        if self.paused or code not in self.trig:
            return
        was = self.trig[code]
        now = v > TRIGGER_ON if not was else v > TRIGGER_OFF
        if now == was:
            return
        self.trig[code] = now
        if now and code in DOUBLE_TRIGGERS and \
                time.monotonic() - self.trig_tapped.pop(code, -1.0) < DOUBLE_TAP_WINDOW:
            self.trig_consumed.add(code)
            self.fire(DOUBLE_TRIGGERS[code])
            self.announce(f"{PARTS[code][1]} {PARTS[code][1]}", DOUBLE_TRIGGERS[code].label)
            return
        if not now and code in self.trig_consumed:
            self.trig_consumed.discard(code)
            return
        # Both triggers together = fullscreen, in either order: an RT press
        # stays pending for CHORD_WINDOW so LT can still join it.
        if now and (self.trig[e.ABS_Z] if code == e.ABS_RZ
                    else self.trig_pending.pop(e.ABS_RZ, None) is not None):
            self.trig_consumed.add(e.ABS_RZ)
            self.tap(FULLSCREEN.keys)
            self.announce("L2 + R2", FULLSCREEN.label)
            return
        if code == e.ABS_Z and code not in DOUBLE_TRIGGERS:
            return                        # LT is only a modifier (see on_button)
        if now:
            self.trig_pending[code] = time.monotonic()   # started in check_triggers
            return
        if self.trig_pending.pop(code, None) is not None:
            self.trig_tapped[code] = time.monotonic()   # a quick tap: maybe half a double tap

    def check_triggers(self) -> None:
        now = time.monotonic()
        for code, since in list(self.trig_pending.items()):
            # A press stays a possible chord / double-tap start for this long.
            if now - since >= (DOUBLE_TAP_WINDOW if code in DOUBLE_TRIGGERS else CHORD_WINDOW):
                del self.trig_pending[code]

    def on_hat(self, axis: str, value: int) -> None:
        prev = self.hat[axis]
        self.hat[axis] = value
        if self.paused:
            return
        # D-pad = arrow keys, held while the direction is, so they autorepeat.
        names = ("left", "right") if axis == "x" else ("up", "down")
        if value != prev:
            self.unhold(("hat", axis))
            arrow = names[0] if value < 0 else names[1]
            if value and self.rt_held() and arrow in RT_DPAD:
                self.fire(RT_DPAD[arrow])        # RT held: the D-pad runs user binds
                self.announce("R2 + D-pad " + DPAD_ARROWS[arrow], RT_DPAD[arrow].label)
            elif value and axis == "y" and self.trig[e.ABS_Z]:
                # LT held: ↑/↓ = volume, held so Omarchy's binding repeats it.
                self.hold(("hat", axis), VOLUME_UP if value < 0 else VOLUME_DOWN)
                self.announce("L2 + D-pad", "Volume up" if value < 0 else "Volume down")
            elif value:
                self.hold(("hat", axis), [ARROWS[arrow]])
                self.announce("D-pad", arrow.capitalize(), plain=True)

    def rt_held(self) -> bool:
        # RT down as window mode: not still a possible fullscreen chord / double
        # tap, and not already used up by one.
        return (self.trig[e.ABS_RZ] and e.ABS_RZ not in self.trig_pending
                and e.ABS_RZ not in self.trig_consumed)

    def window_mode(self, lx: float, ly: float, rx: float, ry: float, dt: float) -> bool:
        # RT held: the left stick drags the window (Super-drag, started once the
        # stick moves) and the right stick resizes it. False when RT isn't held;
        # letting go of RT drops the window.
        if not self.rt_held():
            self.unhold("drag")
            self.resize_acc = [0.0, 0.0]
            self.dragged = self.resized = False
            return False
        if (lx or ly) and "drag" not in self.btn_owner:
            self.hold("drag", WINDOW_DRAG)
            if not self.dragged:
                self.announce("R2 + L-stick", "Move window")
            self.dragged = True
        if self.dragged:
            # Once dragging, the right stick sideways takes the window to
            # another workspace instead of resizing it.
            self.step(rx, lambda: self.move_window(MOVE_PREV_WS),
                      lambda: self.move_window(MOVE_NEXT_WS), WORKSPACE_REPEAT)
            return True
        # Right/down grow the window, left/up shrink it. Batched so a held
        # stick is a few hyprctl calls a second, not one per tick.
        self.resize_acc[0] += rx * RESIZE_SPEED * dt
        self.resize_acc[1] += ry * RESIZE_SPEED * dt
        now = time.monotonic()
        dx, dy = int(self.resize_acc[0]), int(self.resize_acc[1])
        if (dx or dy) and now >= self.resize_next:
            self.resize_acc[0] -= dx
            self.resize_acc[1] -= dy
            self.resize_next = now + RESIZE_EVERY
            hypr_dispatch(f"hl.dsp.window.resize({{ x = {dx}, y = {dy}, relative = true }})")
            if not self.resized:
                self.announce("R2 + R-stick", "Resize window")
            self.resized = True
        return True

    def move_window(self, dispatch: str) -> None:
        # Let go of the Super-drag first: a window can't change workspace
        # mid-drag. The left stick picks it up again on the new workspace.
        self.unhold("drag")
        subprocess.run(["hyprctl", "dispatch", dispatch],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        self.announce("R2 + R-stick", f"Window to workspace {workspace_name()}")

    def to_workspace(self, inputs: str, dispatch: str) -> None:
        # The popup names the workspace we land on, so wait for the switch.
        if not COMBO_NOTIFY:
            hypr_dispatch(dispatch)
            return
        subprocess.run(["hyprctl", "dispatch", dispatch],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        self.announce(inputs, f"Workspace {workspace_name()}")

    def menu_open(self) -> bool:
        at, is_open = self.menu_checked
        now = time.monotonic()
        if now - at < MENU_CACHE:
            return is_open
        is_open = False
        for mon in (hyprctl_json("layers") or {}).values():
            for layers in mon.get("levels", {}).values():
                if any(l.get("namespace") in MENU_LAYERS for l in layers):
                    is_open = True
        self.menu_checked = (now, is_open)
        return is_open

    def check_guide(self) -> None:
        if self.guide_since is None or self.guide_fired:
            return
        if time.monotonic() - self.guide_since < GAME_TOGGLE_HOLD:
            return
        self.guide_fired = True
        self.manual_pause = not self.manual_pause
        if not self.manual_pause:
            self.auto_pause = False
        notify("Game mode ON (controller released)" if self.manual_pause
               else "Desktop mode ON")
        self.update_grab()

    # --- per-tick continuous output ---------------------------------------

    @staticmethod
    def curve(x: float, y: float) -> tuple[float, float]:
        mag = (x * x + y * y) ** 0.5
        if mag < DEADZONE:
            return 0.0, 0.0
        scaled = min(1.0, (mag - DEADZONE) / (1 - DEADZONE))
        f = scaled * scaled / mag
        return x * f, y * f

    def tick(self, dt: float) -> None:
        self.check_guide()
        if self.paused or not self.pad:
            return
        self.check_triggers()
        self.check_enter()
        lx, ly = self.curve(self.axes.get(e.ABS_X, 0.0), self.axes.get(e.ABS_Y, 0.0))
        rx, ry = self.curve(self.axes.get(e.ABS_RX, 0.0), self.axes.get(e.ABS_RY, 0.0))


        speed = POINTER_MAX * dt
        self.acc[0] += lx * speed
        self.acc[1] += ly * speed
        if self.window_mode(lx, ly, rx, ry, dt):
            pass                                # RT held: right stick resizes
        elif self.trig[e.ABS_Z]:
            # LT held: right stick sideways = workspaces.
            self.step(rx, lambda: self.to_workspace("L2 + R-stick", PREV_WS),
                      lambda: self.to_workspace("L2 + R-stick", NEXT_WS), WORKSPACE_REPEAT)
        elif self.zoom_mode:
            # LB + right stick: sideways = workspaces, up/down = zoom. The
            # further-pushed direction wins, so a slightly diagonal push is one.
            if abs(rx) > abs(ry):
                self.step(rx, lambda: self.to_workspace("L1 + R-stick", PREV_WS),
                          lambda: self.to_workspace("L1 + R-stick", NEXT_WS), WORKSPACE_REPEAT)
            else:
                self.step(ry, lambda: self.zoom(ZOOM_IN), lambda: self.zoom(ZOOM_OUT))
        elif abs(ry) >= ZOOM_THRESHOLD and self.menu_open():
            self.step(ry, lambda: self.tap([e.KEY_UP]), lambda: self.tap([e.KEY_DOWN]))
        else:
            self.acc[2] += ry * SCROLL_MAX * dt     # natural: stick up moves the content up
            self.acc[3] += rx * SCROLL_MAX * dt
        wrote = False
        for i, (code, unit) in enumerate(((e.REL_X, 1), (e.REL_Y, 1),
                                          (e.REL_WHEEL_HI_RES, 1), (e.REL_HWHEEL_HI_RES, 1))):
            n = int(self.acc[i] / unit)
            if n:
                self.acc[i] -= n * unit
                self.ui.write(e.EV_REL, code, n)
                wrote = True
        if wrote:
            self.ui.syn()

    def zoom(self, bind: Bind) -> None:
        self.tap(bind.keys)
        self.announce("L1 + R-stick", bind.label)

    def step(self, v: float, negative, positive, repeat: float = ZOOM_REPEAT) -> None:
        # One action per push (up/left = negative), repeating every `repeat`
        # seconds while the stick stays pushed.
        if abs(v) < ZOOM_THRESHOLD:
            self.zoom_next = 0.0
            return
        now = time.monotonic()
        if now >= self.zoom_next:
            (negative if v < 0 else positive)()
            self.zoom_next = now + repeat

    def poll_game(self) -> None:
        if self.manual_pause:
            return
        w = hyprctl_json("activewindow") or {}
        cls = (w.get("class") or "").lower()
        is_game = bool(w.get("fullscreen")) and cls.startswith(GAME_CLASSES)
        if is_game != self.auto_pause:
            self.auto_pause = is_game
            log.info("auto game mode %s (%s)", "on" if is_game else "off", cls)
            notify("Game detected, controller released" if is_game else "Desktop mode ON")
            self.update_grab()


def _raise_interrupt(*_) -> None:
    raise KeyboardInterrupt


def main() -> int:
    # systemctl stop sends SIGTERM: exit through the same cleanup as ctrl+c so
    # held keys are released and the user's Hyprland setting is put back.
    signal.signal(signal.SIGTERM, _raise_interrupt)
    if sys.argv[1:] == ["--keymap"]:
        print(keymap_markdown(), end="")
        return 0
    logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    caps = {
        e.EV_KEY: OUT_KEYS,
        e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL,
                   e.REL_WHEEL_HI_RES, e.REL_HWHEEL_HI_RES],
    }
    ui = UInput(caps, name="iris-controller")
    m = Mapper(ui)
    sel = selectors.DefaultSelector()
    last_tick = time.monotonic()
    last_game = 0.0
    last_scan = 0.0

    try:
        while True:
            now = time.monotonic()
            if not m.devs and now - last_scan > 2.0:
                last_scan = now
                devs = find_controller()
                if devs:
                    m.attach(devs)
                    for d in devs:
                        sel.register(d, selectors.EVENT_READ)
                    if m.hid_fd is not None:
                        sel.register(m.hid_fd, selectors.EVENT_READ)
            if m.devs and now - last_game > GAME_POLL:
                last_game = now
                m.poll_game()

            for keyobj, _ in sel.select(timeout=TICK):
                dev = keyobj.fileobj
                try:
                    if isinstance(dev, int):
                        m.on_hid(os.read(dev, 128))
                    else:
                        for ev in dev.read():
                            m.handle(ev, dev)
                except BlockingIOError:
                    pass
                except OSError:
                    log.info("controller disconnected")
                    for d in [*m.devs, m.hid_fd]:
                        try:
                            sel.unregister(d)
                        except Exception:
                            pass
                    m.detach()
                    break

            now = time.monotonic()
            m.tick(min(now - last_tick, 0.05))
            last_tick = now
    except KeyboardInterrupt:
        pass
    finally:
        m.release_all()
        m.detach()
        ui.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
