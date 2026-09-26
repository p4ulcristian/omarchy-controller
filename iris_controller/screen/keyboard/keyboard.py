"""On-screen keyboard (R2 + ○). The controller keeps the layout and the
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
from ...keymap.bindings import ALT, CTRL, SHIFT

log = logging.getLogger("iris-controller")

PLUGIN = "p4ulcristian.iris-controller-keyboard"
DELAY = 0.35            # D-pad held this long: the highlight starts repeating
REPEAT = 0.08           # then one key every this many seconds
# The keyboard overlay reports the pointer here: "hover R C", "leave", "down R C", "up".
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "iris-controller", "keyboard.sock")


# US layout, 15 units per row. Each key is (label, shifted label, key code,
# width); key code None = a sticky modifier, a string = a snippet to type.
def _chars(base: str, shifted: str, codes: list[str]) -> list:
    return [(b, sh, getattr(e, "KEY_" + c), 1) for b, sh, c in zip(base, shifted, codes)]


MODS = {"shift": SHIFT, "ctrl": CTRL, "alt": ALT}
ROWS = [
    _chars("`1234567890-=", "~!@#$%^&*()_+",
           ["GRAVE", *"1234567890", "MINUS", "EQUAL"]) + [("⌫", "⌫", e.KEY_BACKSPACE, 2)],
    [("Tab", "Tab", e.KEY_TAB, 1.5)]
    + _chars("qwertyuiop[]", "QWERTYUIOP{}", [*"QWERTYUIOP", "LEFTBRACE", "RIGHTBRACE"])
    + [("\\", "|", e.KEY_BACKSLASH, 1.5)],
    [("Esc", "Esc", e.KEY_ESC, 1.75)]
    + _chars("asdfghjkl;'", 'ASDFGHJKL:"', [*"ASDFGHJKL", "SEMICOLON", "APOSTROPHE"])
    + [("⏎", "⏎", e.KEY_ENTER, 2.25)],
    [("⇧", "⇧", None, 2.25)]
    + _chars("zxcvbnm,./", "ZXCVBNM<>?", [*"ZXCVBNM", "COMMA", "DOT", "SLASH"])
    + [("⇧", "⇧", None, 2.75)],
    [("Ctrl", "Ctrl", None, 1.5), ("Alt", "Alt", None, 1.5), ("", "", e.KEY_SPACE, 8),
     ("←", "←", e.KEY_LEFT, 1), ("↓", "↓", e.KEY_DOWN, 1), ("↑", "↑", e.KEY_UP, 1),
     ("→", "→", e.KEY_RIGHT, 1)],
]
MOD_OF = {"⇧": "shift", "Ctrl": "ctrl", "Alt": "alt"}
KEYS = {k[2] for row in ROWS for k in row if k[2]}   # key codes it can send
# Characters the keyboard can type, for snippets: char -> (key code, shifted).
CHARS = {" ": (e.KEY_SPACE, False)}
for _row in ROWS:
    for _label, _shifted, _code, _w in _row:
        if _code and len(_label) == 1:
            CHARS.setdefault(_label, (_code, False))
            CHARS.setdefault(_shifted, (_code, True))
# A top row of text snippets: selected with ✕, the whole text is typed.
# [keyboard] snippets = [...] in the config replaces these.
SNIPPETS = CONFIG.get("keyboard", {}).get("snippets", ["https://", "www.", ".com", "@", "~/"])
if SNIPPETS:
    ROWS.insert(0, [(t, t, t, 15 / len(SNIPPETS)) for t in SNIPPETS])


def center(row: list, col: int) -> float:
    """Middle of a key along its row, in units: to go up/down to the nearest key."""
    x = sum(k[3] for k in row[:col])
    return x + row[col][3] / 2


class OnScreenKeyboard:
    def __init__(self, m) -> None:
        self.m = m
        self.open = False
        self.pos = [len(ROWS) - 3, 1]           # highlighted key: row, column (starts on "a")
        self.mods: set[str] = set()             # sticky modifiers armed for the next key
        self.shift_held = False                 # L1 held on the keyboard: shift
        self.next = 0.0                         # when a held D-pad moves the highlight again
        self.aim = False                        # ✕ types the highlight (pointer on a key / D-pad used)
        self.x_typing = False                   # this ✕ press is typing, so its release is ours too

    def toggle(self, show: bool) -> None:
        self.open = show
        self.aim = show
        self.mods.clear()
        self.m.out.unhold("osk")
        if show:
            rows = [[{"label": k[0], "shift": k[1], "w": k[3]} for k in row] for row in ROWS]
            self.send(["summon", PLUGIN, json.dumps({"rows": rows, **self.state()})])
        else:
            self.send(["hide", PLUGIN])

    def state(self) -> dict:
        mods = self.mods | ({"shift"} if self.shift_held else set())
        return {"row": self.pos[0], "col": self.pos[1], "mods": sorted(mods)}

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
        if code == e.BTN_WEST:
            self.m.out.unhold("osk")
            if down:
                self.m.out.hold("osk", [e.KEY_SPACE])   # □ = space
            return True
        if code != e.BTN_SOUTH:
            return False                          # △ backspace and the rest, as usual
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
        label, _, key, _ = ROWS[self.pos[0]][self.pos[1]]
        if key is None:                           # a modifier key: arm / disarm it
            self.mods ^= {MOD_OF[label]}
        elif isinstance(key, str):                # a snippet: type its text
            self.type(key)
            self.mods.clear()
        else:                                     # held, so it autorepeats; mods are one-shot
            mods = self.mods | ({"shift"} if self.shift_held else set())
            out.hold("osk", [MODS[m] for m in sorted(mods)] + [key])
            self.mods.clear()
        self.update()

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
