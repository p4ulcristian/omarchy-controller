"""App launcher (tap PS): the apps of the Omarchy launcher as a grid of
tiles. Launcher.qml next to this file reads the apps and launches them; the
controller only counts D-pad steps and ✕ presses and sends the totals, so a
call the shell queue drops for a newer one loses nothing."""

from __future__ import annotations

import json
import time

from evdev import ecodes as e

PLUGIN = "p4ulcristian.iris-controller-launcher"
DELAY = 0.35            # D-pad held this long: the highlight starts repeating
REPEAT = 0.1            # then one tile every this many seconds


class Launcher:
    def __init__(self, m) -> None:
        self.m = m
        self.open = False
        self.dx = self.dy = self.picks = 0      # running totals, never reset
        self.next = 0.0                         # when a held D-pad moves the highlight again

    def totals(self) -> str:
        return json.dumps({"dx": self.dx, "dy": self.dy, "picks": self.picks})

    def toggle(self, show: bool) -> None:
        self.open = show
        if show:
            if self.m.keyboard.open:
                self.m.keyboard.toggle(False)
            self.m.shell.send(PLUGIN, ["summon", PLUGIN, self.totals()])
        else:
            self.m.shell.send(PLUGIN, ["hide", PLUGIN])

    def steer(self) -> None:
        self.m.shell.send(PLUGIN, ["call", PLUGIN, "steer", self.totals()])

    def move(self, axis: str, value: int) -> None:
        if axis == "x":
            self.dx += value
        else:
            self.dy += value
        self.steer()

    def dpad(self, axis: str, value: int, prev: int) -> None:
        # The D-pad moves the highlight; held, it keeps moving (see tick).
        if value and value != prev:
            self.move(axis, value)
            self.next = time.monotonic() + DELAY

    def button(self, code, down: bool) -> bool:
        # Buttons while the grid shows: ✕ launches, ○ closes, the rest do
        # nothing. Releases go on as usual, so nothing held gets stuck.
        if not down:
            return False
        if code == e.BTN_SOUTH:
            self.picks += 1
            self.steer()
            self.open = False                   # the grid closes itself as it launches
        elif code == e.BTN_EAST:
            self.toggle(False)
        return True

    def tick(self) -> None:
        # A held D-pad keeps moving the highlight.
        if not self.open or time.monotonic() < self.next:
            return
        for axis in ("x", "y"):
            if self.m.hat[axis]:
                self.move(axis, self.m.hat[axis])
                self.next = time.monotonic() + REPEAT
