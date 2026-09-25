#!/usr/bin/env python3
"""Drive Omarchy / Hyprland from a DualSense controller. Keymap: KEYMAP.md."""

from __future__ import annotations

import json
import logging
import os
import selectors
import socket
import subprocess
import sys
import threading
import time
import tomllib
import urllib.request
from typing import NamedTuple

import evdev
from evdev import UInput, ecodes as e

log = logging.getLogger("omarchy-controller")

# The motion sensors are a separate device we leave alone; the touchpad is a
# separate device we use for swipes.
DUALSENSE_NAMES = ("DualSense Wireless Controller", "DualSense Edge Wireless Controller")
TOUCHPAD_SUFFIX = " Touchpad"   # grabbed like the pad: swipe pad, not a pointer
SWIPE_DISTANCE = 450            # touchpad units (of 1920) for a workspace swipe
TICK = 0.008                 # seconds between pointer updates (~120 Hz)
DEADZONE = 0.15
POINTER_MAX = 1800.0         # px/s at full stick
PRECISION = 0.3
SCROLL_MAX = 2400.0          # hi-res wheel units/s (120 = one notch)
TRIGGER_ON, TRIGGER_OFF = 0.5, 0.3
DOUBLE_TAP_WINDOW = 0.25    # second ✕ within this = Ctrl+Enter; a single ✕ waits this long
CHORD_WINDOW = 0.06         # both triggers within this = fullscreen, not clicks
ZOOM_THRESHOLD = 0.5         # right stick deflection that counts as a zoom step
ZOOM_REPEAT = 0.2           # seconds between zoom steps while the stick stays pushed
GAME_TOGGLE_HOLD = 1.0      # hold the PS button this long to toggle game mode
GAME_POLL = 1.0
GAME_CLASSES = ("steam_app_", "gamescope")
MENU_LAYERS = ("omarchy-menu",)   # keyboard-driven overlays: D-pad/right stick send arrows
MENU_CACHE = 0.25
HELP_PLUGIN = "p4ulcristian.controller-help"   # Omarchy shell plugin in overlay/
MIC_BIT = 0x04     # DualSense mic button: third button byte of the raw HID report

CONFIG_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "omarchy-controller", "config.toml",
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
# R2: dictate, then post the transcript to an Iris server. Needs the dictate
# socket to also take "stop-return" (stop and reply with the text).
IRIS = CONFIG.get("iris", {})
IRIS_URL = IRIS.get("url") if DICTATE_SOCK else None
# Rename actions in the cheat sheet, e.g. "Terminal" = "Claude in ~/Work".
LABELS: dict[str, str] = CONFIG.get("labels", {})

# Right-hand Super/Alt, so layouts that swap the left ones
# (altwin:swap_lalt_lwin) still get the modifier they expect.
SUPER, SHIFT, CTRL, ALT = e.KEY_RIGHTMETA, e.KEY_LEFTSHIFT, e.KEY_LEFTCTRL, e.KEY_RIGHTALT

class Bind(NamedTuple):
    keys: list[int]
    label: str       # shown in the cheat sheet overlay and KEYMAP.md


# Buttons mirrored as held keys (so autorepeat and drag work).
BASE_HOLD = {
    e.BTN_SOUTH: Bind([e.KEY_ENTER], "Enter"),
    e.BTN_EAST: Bind([e.KEY_ESC], "Escape"),
    e.BTN_WEST: Bind([e.BTN_LEFT], "Left click (hold = drag)"),   # physical X / Square
    e.BTN_NORTH: Bind([e.KEY_BACKSPACE], "Backspace"),            # physical Y / Triangle
    e.BTN_THUMBL: Bind([e.BTN_MIDDLE], "Middle click"),
}
# One-shot chords on press.
BASE_TAP = {
    e.BTN_START: Bind([SUPER, e.KEY_SPACE], "Omarchy menu"),
    e.BTN_SELECT: Bind([SUPER, e.KEY_W], "Close window"),
}
CROSS_DOUBLE = Bind([CTRL, e.KEY_ENTER], "Ctrl + Enter (double tap)")       # ✕ twice
FULLSCREEN = Bind([SUPER, e.KEY_F], "Fullscreen")               # LT + RT together
# RT is push-to-talk to Iris if configured (see talk_to_iris); LT holds these keys.
TRIGGER_ACTION = {e.ABS_Z: Bind([SUPER, e.BTN_LEFT], "move window (left stick)")}
IRIS_TALK = "talk to Iris (release to send)"
ZOOM_IN = Bind([CTRL, e.KEY_EQUAL], "Bigger text")              # LB + right stick
ZOOM_OUT = Bind([CTRL, e.KEY_MINUS], "Smaller text")
# Touchpad swipes: next/previous workspace on the focused monitor (empty ones too).
NEXT_WS = 'hl.dsp.focus({ workspace = "r+1" })'
PREV_WS = 'hl.dsp.focus({ workspace = "r-1" })'
# PS button held + another button: one-shot chord (cancels the tap and hold).
GUIDE_COMBOS = {
    e.BTN_SOUTH: Bind([SUPER, e.KEY_ENTER], "Terminal"),
}
# LB held + another button: one-shot chord.
LB_COMBOS = {
    e.BTN_NORTH: Bind([SUPER, e.KEY_W], "Close window"),          # physical Y / Triangle
}
ARROWS = {"left": e.KEY_LEFT, "right": e.KEY_RIGHT, "up": e.KEY_UP, "down": e.KEY_DOWN}

OUT_KEYS = sorted(
    {k for m in (BASE_HOLD, BASE_TAP, GUIDE_COMBOS, LB_COMBOS, TRIGGER_ACTION)
     for b in m.values() for k in b.keys}
    | {k for b in (CROSS_DOUBLE, FULLSCREEN, ZOOM_IN, ZOOM_OUT) for k in b.keys}
    | set(ARROWS.values())
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
        add(code, "Press: " + b.label.lower() if code == e.BTN_THUMBL else b.label)
    for code, b in BASE_TAP.items():
        add(code, b.label)
    add(e.BTN_THUMBR, "Click & hold: precise pointer")
    if DICTATE_SOCK:
        add(e.BTN_TR, "Hold: dictate")
    add(e.BTN_TL, "Hold: combo layer")
    add(e.BTN_MODE, "Hold 1 s: game mode on/off")
    if IRIS_URL:
        add(e.ABS_RZ, "Hold: " + IRIS_TALK)
    add(e.ABS_Z, "Hold: " + TRIGGER_ACTION[e.ABS_Z].label)
    add("dpad", "Focus window that way")
    add("touchpad", "Swipe ←/→: prev / next workspace")
    add("touchpad", "Click: left click")
    add("mic", "Show / hide this cheat sheet")

    combos = [{"keys": [name(e.BTN_SOUTH), name(e.BTN_SOUTH)], "action": CROSS_DOUBLE.label},
              {"keys": [name(e.ABS_Z), name(e.ABS_RZ)], "action": FULLSCREEN.label}]
    combos += [{"keys": ["Hold " + name(e.BTN_MODE), name(c)], "action": b.label}
               for c, b in GUIDE_COMBOS.items()]
    combos += [{"keys": ["Hold " + name(e.BTN_TL), "R-stick ↑"], "action": ZOOM_IN.label},
               {"keys": ["Hold " + name(e.BTN_TL), "R-stick ↓"], "action": ZOOM_OUT.label}]
    combos += [{"keys": ["Hold " + name(e.BTN_TL), name(c)], "action": b.label}
               for c, b in LB_COMBOS.items()]
    menu = [{"keys": ["D-pad", "R-stick"], "action": "Move through the list"},
            {"keys": [name(e.BTN_SOUTH)], "action": "Open"},
            {"keys": [name(e.BTN_EAST)], "action": "Close"}]
    for c in combos:
        c["action"] = LABELS.get(c["action"], c["action"])
    return {"parts": parts, "combos": combos, "menu": menu}


def keymap_markdown() -> str:
    km = keymap()
    out = ["# omarchy-controller keymap", "",
           "Generated by `python3 omarchy_controller.py --keymap > KEYMAP.md`; "
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


def hypr_dispatch(arg: str) -> None:
    subprocess.Popen(["hyprctl", "dispatch", arg],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def iris_secret() -> str:
    """The shared secret, read from a KEY=value file so it never sits in the config."""
    path = IRIS.get("secret_file")
    if not path:
        return ""
    name = IRIS.get("secret_key", "IRIS_INTERNAL_SECRET")
    try:
        with open(os.path.expanduser(path)) as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key == name:
                    return value.strip().strip("'\"")
    except OSError as exc:
        log.warning("iris secret: %s", exc)
    return ""


def talk_to_iris() -> None:
    """Runs in a thread: stop dictation, get the transcript, post it to Iris."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(65)
        s.connect(DICTATE_SOCK)
        s.sendall(b"stop-return")
        s.shutdown(socket.SHUT_WR)
        text = s.recv(65536).decode().strip()
        s.close()
    except Exception as exc:
        log.warning("dictate stop-return failed: %s", exc)
        return
    if not text:
        return
    req = urllib.request.Request(
        IRIS_URL, data=json.dumps({"message": text, "source": "desktop"}).encode(),
        headers={"Content-Type": "application/json", "X-Iris-Secret": iris_secret()})
    try:
        urllib.request.urlopen(req, timeout=10).read()
        notify(f"To Iris: {text}")
    except Exception as exc:
        log.warning("iris send failed: %s", exc)
        subprocess.run(["wl-copy", text], check=False)
        notify(f"Iris didn't answer; message is on the clipboard: {text}")


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


def notify(msg: str) -> None:
    subprocess.Popen(["notify-send", "-t", "1500", "Controller", msg],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
        self.swipe_x: int | None = None         # ABS_X where the finger landed
        self.swipe_fired = False
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
        self.trig_chord = False                   # both fired together; ignore until both up
        self.hat = {"x": 0, "y": 0}
        self.precision = False
        self.zoom_mode = False                  # LB held: right stick zooms
        self.cross_first: float | None = None   # first ✕ press, waiting for a second one
        self.zoom_next = 0.0                    # when the next zoom/arrow step may fire
        self.menu_checked = (0.0, False)        # (time, omarchy menu open?)
        self.acc = [0.0, 0.0, 0.0, 0.0]         # dx, dy, wheel_v, wheel_h
        self.manual_pause = False
        self.auto_pause = False
        self.grabbed = False

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

    def hold(self, owner, combo: list[int]) -> None:
        self.btn_owner[owner] = combo
        for k in combo:
            self.key(k, True)

    def unhold(self, owner) -> None:
        for k in reversed(self.btn_owner.pop(owner, [])):
            self.key(k, False)

    def release_all(self) -> None:
        self.cross_first = None
        if self.btn_owner.pop("iris", None) is not None:
            dictate("stop")
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
        # One finger sliding sideways = workspace swipe: right goes to the next
        # workspace, left to the previous. Clicking the pad = left click.
        if self.paused:
            return
        if ev.type == e.EV_KEY and ev.code == e.BTN_TOUCH:
            self.touching, self.swipe_x, self.swipe_fired = bool(ev.value), None, False
        elif ev.type == e.EV_KEY and ev.code == e.BTN_LEFT:
            if ev.value == 1:
                self.hold("touchclick", [e.BTN_LEFT])
            elif ev.value == 0:
                self.unhold("touchclick")
        elif ev.type == e.EV_ABS and ev.code == e.ABS_X and self.touching:
            if self.swipe_x is None:
                self.swipe_x = ev.value          # first position after landing
            elif not self.swipe_fired and abs(ev.value - self.swipe_x) >= SWIPE_DISTANCE:
                self.swipe_fired = True
                hypr_dispatch(NEXT_WS if ev.value > self.swipe_x else PREV_WS)

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
                self.tap(GUIDE_COMBOS[code].keys)
                return
        if down and self.zoom_mode and code in LB_COMBOS:
            self.tap(LB_COMBOS[code].keys)
            return

        if code == e.BTN_SOUTH:
            self.on_cross(down)
            return
        if code == e.BTN_THUMBR:
            self.precision = down        # slow pointer only while held
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
        elif code in BASE_HOLD:
            self.hold(code, BASE_HOLD[code].keys)
        elif code in BASE_TAP:
            self.tap(BASE_TAP[code].keys)

    def on_cross(self, down: bool) -> None:
        # ✕ is Enter, but a second press within DOUBLE_TAP_WINDOW makes it
        # Ctrl+Enter instead, so the first press is held back until then.
        if not down:
            self.unhold(e.BTN_SOUTH)     # only held if the window already ran out
            return
        if self.cross_first is not None:
            self.cross_first = None
            self.tap(CROSS_DOUBLE.keys)
        else:
            self.cross_first = time.monotonic()

    def check_cross(self) -> None:
        if self.cross_first is None or time.monotonic() - self.cross_first < DOUBLE_TAP_WINDOW:
            return
        self.cross_first = None
        # Still held: hold Enter so it autorepeats; already released: one Enter.
        if self.cross_held():
            self.hold(e.BTN_SOUTH, BASE_HOLD[e.BTN_SOUTH].keys)
        else:
            self.tap(BASE_HOLD[e.BTN_SOUTH].keys)

    def cross_held(self) -> bool:
        try:
            return e.BTN_SOUTH in self.pad.active_keys()
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
        other = e.ABS_Z if code == e.ABS_RZ else e.ABS_RZ
        if now:
            # Hold the action back for CHORD_WINDOW so both triggers can become fullscreen.
            if self.trig_pending.pop(other, None) is not None:
                self.trig_chord = True
                self.tap(FULLSCREEN.keys)
            elif not self.trig_chord:
                self.trig_pending[code] = time.monotonic()
            return
        if self.trig_pending.pop(code, None) is not None:
            if code in TRIGGER_ACTION:
                self.tap(TRIGGER_ACTION[code].keys)   # released before the window: plain click
        elif code == e.ABS_RZ:
            if self.btn_owner.pop("iris", None) is not None:
                threading.Thread(target=talk_to_iris, daemon=True).start()
        else:
            self.unhold(("trig", code))
        if not any(self.trig.values()):
            self.trig_chord = False

    def check_triggers(self) -> None:
        now = time.monotonic()
        for code, since in list(self.trig_pending.items()):
            if now - since >= CHORD_WINDOW:
                del self.trig_pending[code]
                if code == e.ABS_RZ:
                    if IRIS_URL:
                        self.btn_owner["iris"] = []   # released in on_abs
                        dictate("start")
                else:
                    self.hold(("trig", code), TRIGGER_ACTION[code].keys)

    def on_hat(self, axis: str, value: int) -> None:
        prev = self.hat[axis]
        self.hat[axis] = value
        if self.paused:
            return
        # D-pad = SUPER + arrow: focus the window in that direction.
        # With the Omarchy menu open it sends plain arrows to move through it.
        names = ("left", "right") if axis == "x" else ("up", "down")
        if value and not prev:
            arrow = ARROWS[names[0] if value < 0 else names[1]]
            self.tap([arrow] if self.menu_open() else [SUPER, arrow])

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
        self.check_cross()
        lx, ly = self.curve(self.axes.get(e.ABS_X, 0.0), self.axes.get(e.ABS_Y, 0.0))
        rx, ry = self.curve(self.axes.get(e.ABS_RX, 0.0), self.axes.get(e.ABS_RY, 0.0))


        speed = POINTER_MAX * (PRECISION if self.precision else 1.0) * dt
        self.acc[0] += lx * speed
        self.acc[1] += ly * speed
        if self.zoom_mode:
            self.step(ry, ZOOM_IN.keys, ZOOM_OUT.keys)
        elif abs(ry) >= ZOOM_THRESHOLD and self.menu_open():
            self.step(ry, [e.KEY_UP], [e.KEY_DOWN])
        else:
            self.acc[2] += -ry * SCROLL_MAX * dt
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

    def step(self, ry: float, up: list[int], down: list[int]) -> None:
        # One tap per push, repeating every ZOOM_REPEAT while held.
        if abs(ry) < ZOOM_THRESHOLD:
            self.zoom_next = 0.0
            return
        now = time.monotonic()
        if now >= self.zoom_next:
            self.tap(up if ry < 0 else down)
            self.zoom_next = now + ZOOM_REPEAT

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


def main() -> int:
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
    ui = UInput(caps, name="omarchy-controller")
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
