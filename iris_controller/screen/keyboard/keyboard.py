"""On-screen keyboard (R1 twice). The controller keeps the layout and the
highlight and types the keys; Keyboard.qml next to this file only draws them,
and reports the real pointer on its keys back over a socket."""

from __future__ import annotations

import json
import logging
import os
import selectors
import socket
import time

from evdev import ecodes as e

from ...core.config import CONFIG
from ...keymap.bindings import SHIFT
from ...keymap.user_binds import parse_keys

log = logging.getLogger("iris-controller")

PLUGIN = "p4ulcristian.iris-controller-keyboard"
DELAY = 0.35            # D-pad held this long: the highlight starts repeating
REPEAT = 0.08           # then one key every this many seconds
# The keyboard overlay reports the pointer here: "hover R C", "leave", "down R C", "up".
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "iris-controller", "keyboard.sock")


# US layout, top to bottom: symbols, numbers, letters, space. Each key is
# (label, shifted label, key code, width); a string key code = a snippet to
# type, a list = a shortcut to press. Shift is L1, held.
def _chars(base: str, shifted: str, codes: list[str]) -> list:
    return [(b, sh, getattr(e, "KEY_" + c), 1) for b, sh, c in zip(base, shifted, codes)]


ROWS = [
    _chars("`-=[]\\;',./", '~_+{}|:"<>?',
           ["GRAVE", "MINUS", "EQUAL", "LEFTBRACE", "RIGHTBRACE", "BACKSLASH",
            "SEMICOLON", "APOSTROPHE", "COMMA", "DOT", "SLASH"]),
    _chars("1234567890", "!@#$%^&*()", [*"1234567890"]),
    _chars("qwertyuiop", "QWERTYUIOP", [*"QWERTYUIOP"]),
    _chars("asdfghjkl", "ASDFGHJKL", [*"ASDFGHJKL"]),
    _chars("zxcvbnm", "ZXCVBNM", [*"ZXCVBNM"]),
    [("", "", e.KEY_SPACE, 1)],
]
KEYS = {k[2] for row in ROWS for k in row if k[2]}   # key codes it can send
# Characters the keyboard can type, for snippets: char -> (key code, shifted).
CHARS = {" ": (e.KEY_SPACE, False)}
for _row in ROWS:
    for _label, _shifted, _code, _w in _row:
        if len(_label) == 1:
            CHARS.setdefault(_label, (_code, False))
            CHARS.setdefault(_shifted, (_code, True))


def _extra(item) -> tuple | None:
    """A top-row entry from the config: "text" types the text,
    {keys = "CTRL + B", label = "^B"} presses the shortcut."""
    if isinstance(item, str):
        return (item, item, item, 1)
    try:
        combo = parse_keys(item["keys"])
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("keyboard extra %r skipped: %s", item, exc)
        return None
    label = item.get("label", "+".join(k.strip().title() for k in item["keys"].split("+")))
    return (label, label, combo, 1)


# A top row of extras: text snippets and shortcuts, picked with ✕.
# [keyboard] extras = [...] in the config replaces these; [] hides the row.
EXTRAS = CONFIG.get("keyboard", {}).get("extras", [
    "https://", ".com", "@", "~/", {"keys": "SHIFT + ENTER"}, {"keys": "CTRL + B"}])
EXTRAS = [k for k in map(_extra, EXTRAS) if k]
if EXTRAS:
    ROWS.insert(0, EXTRAS)
# Each row's keys share its 15 units evenly.
ROWS = [[(b, sh, code, 15 / len(row)) for b, sh, code, _ in row] for row in ROWS]

def center(row: list, col: int) -> float:
    """Middle of a key along its row, in units: to go up/down to the nearest key."""
    x = sum(k[3] for k in row[:col])
    return x + row[col][3] / 2


class OnScreenKeyboard:
    def __init__(self, m) -> None:
        self.m = m
        self.open = False
        self.pos = [len(ROWS) - 3, 0]           # highlighted key: row, column (starts on "a")
        self.shift_held = False                 # L1 held on the keyboard: shift
        self.next = 0.0                         # when a held D-pad moves the highlight again
        self.aim = False                        # ✕ types the highlight (pointer on a key / D-pad used)
        self.x_typing = False                   # this ✕ press is typing, so its release is ours too

    def toggle(self, show: bool) -> None:
        self.open = show
        self.aim = show
        self.m.out.unhold("osk")
        if show:
            rows = [[{"label": k[0], "shift": k[1], "w": k[3]} for k in row] for row in ROWS]
            self.send(["summon", PLUGIN, json.dumps({"rows": rows, **self.state()})])
        else:
            self.send(["hide", PLUGIN])

    def state(self) -> dict:
        return {"row": self.pos[0], "col": self.pos[1], "mods": ["shift"] if self.shift_held else []}

    def update(self) -> None:
        self.send(["call", PLUGIN, "update", json.dumps(self.state())])

    def send(self, args: list[str]) -> None:
        self.m.shell.send(PLUGIN, args)

    def move(self, axis: str, value: int) -> None:
        r, c = self.pos
        if axis == "x":
            c = (c + value) % len(ROWS[r])
        else:
            x = center(ROWS[r], c)
            r = min(max(r + value, 0), len(ROWS) - 1)
            c = min(range(len(ROWS[r])), key=lambda i: abs(center(ROWS[r], i) - x))
        self.pos = [r, c]
        self.aim = True
        self.update()

    def dpad(self, axis: str, value: int, prev: int) -> None:
        # The D-pad moves the highlight; held, it keeps moving (see tick).
        if value and value != prev:
            self.move(axis, value)
            self.next = time.monotonic() + DELAY

    def button(self, code, down: bool) -> bool:
        # Buttons while the keyboard shows. True = handled here.
        if code == e.BTN_TL:
            self.shift_held = down               # L1 held = shift
            self.update()
            return True
        if code == e.BTN_EAST:
            if down:
                self.toggle(False)                # ○ closes the keyboard
            return True
        if code != e.BTN_SOUTH:
            return False                          # □ Enter, △ backspace and the rest, as usual
        # ✕ types the highlighted key while aiming at the keyboard; otherwise
        # it stays a click (and L2 + ✕ a right click), to reach a text field.
        if down:
            self.x_typing = self.aim and not self.m.trig[e.ABS_Z]
        if not self.x_typing:
            return False
        self.press(down)
        return True

    def press(self, down: bool) -> None:
        # The highlighted key goes down (held, so it autorepeats) or up.
        out = self.m.out
        out.unhold("osk")
        if not down:
            return
        _, _, key, _ = ROWS[self.pos[0]][self.pos[1]]
        if isinstance(key, str):                  # a snippet: type its text
            self.type(key)
        elif isinstance(key, list):               # a shortcut: press it once
            out.tap(key)
        else:                                     # held, so it autorepeats
            out.hold("osk", ([SHIFT] if self.shift_held else []) + [key])

    def line(self, line: str) -> None:
        # A report from the keyboard overlay: the pointer over a key, off it,
        # or a real mouse button on a key.
        parts = line.split()
        if not self.open or not parts:
            return
        if parts[0] in ("hover", "down") and len(parts) == 3:
            try:
                r, c = int(parts[1]), int(parts[2])
                ROWS[r][c]
            except (ValueError, IndexError):
                return
            self.aim = True
            if [r, c] != self.pos:
                self.pos = [r, c]
                self.update()
            if parts[0] == "down":
                self.press(True)
        elif parts[0] == "up":
            self.press(False)
        elif parts[0] == "leave":
            self.aim = False

    def type(self, text: str) -> None:
        for ch in text:
            if ch not in CHARS:
                log.warning("keyboard snippet: can't type %r", ch)
                continue
            code, shifted = CHARS[ch]
            self.m.out.tap([SHIFT, code] if shifted else [code])

    def tick(self) -> None:
        # A held D-pad keeps moving the highlight.
        if not self.open or time.monotonic() < self.next:
            return
        for axis in ("x", "y"):
            if self.m.hat[axis]:
                self.move(axis, self.m.hat[axis])
                self.next = time.monotonic() + REPEAT


class PointerReports:
    """The socket the keyboard overlay connects to, to report the pointer on its keys."""

    def __init__(self, sel: selectors.BaseSelector, on_line) -> None:
        self.sel, self.on_line = sel, on_line
        os.makedirs(os.path.dirname(SOCK), exist_ok=True)
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(SOCK)
        self.server.listen()
        self.server.setblocking(False)
        sel.register(self.server, selectors.EVENT_READ, "osk-server")
        self.buffers: dict[socket.socket, bytes] = {}

    def ready(self, key) -> bool:
        """Handle a selector event if it is ours. True = it was."""
        if key.data == "osk-server":
            try:
                conn, _ = self.server.accept()
            except OSError:
                return True
            conn.setblocking(False)
            self.sel.register(conn, selectors.EVENT_READ, "osk-conn")
            self.buffers[conn] = b""
            return True
        if key.data != "osk-conn":
            return False
        conn = key.fileobj
        try:
            data = conn.recv(4096)
        except BlockingIOError:
            return True
        except OSError:
            data = b""
        if not data:                              # the overlay went away (shell restart)
            self.sel.unregister(conn)
            conn.close()
            self.buffers.pop(conn, None)
            return True
        *lines, self.buffers[conn] = (self.buffers[conn] + data).split(b"\n")
        for line in lines:
            self.on_line(line.decode(errors="replace"))
        return True
