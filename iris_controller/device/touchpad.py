"""The touchpad: a tap (touch and lift, no slide) or a click is an arrow key:
the side you touch is the arrow sent. Sliding does nothing."""

from __future__ import annotations

import time

from evdev import ecodes as e

from ..keymap.bindings import ARROWS

SLIDE = 60                      # movement that makes a touch a slide, not a tap
TOUCH_SIZE = (1920, 1080)       # DualSense touchpad resolution
CLICK_DEADZONE = 0.1            # taps/clicks this close to the centre have no direction: ignored
TAP_TIME = 0.25                 # a touch lifted within this, without sliding, is a tap


class Touchpad:
    def __init__(self, m) -> None:
        self.m = m
        self.pos = [None, None]                 # finger x, y
        self.touch_from: list[int] | None = None  # where the finger landed
        self.slid = False                       # moved too far (or clicked): not a tap
        self.click_pending = False              # pad pressed; zone decided at the end of the report
        self.since = 0.0                        # when the finger landed, for taps
        self.touching = False

    def handle(self, ev) -> None:
        if self.m.paused:
            return
        out = self.m.out
        if ev.type == e.EV_KEY and ev.code == e.BTN_TOUCH:
            if not ev.value and self.is_tap():
                zone = self.zone(*self.touch_from)
                if zone:
                    out.tap([ARROWS[zone]])
                    self.m.flash.show("Touchpad tap", zone.capitalize(), plain=True)
            self.touching = bool(ev.value)
            self.since = time.monotonic()
            self.pos, self.touch_from = [None, None], None
            self.slid = False
        elif ev.type == e.EV_KEY and ev.code == e.BTN_LEFT:
            if ev.value == 1:
                # The finger position may come later in the same report, so
                # the zone is picked at its end (EV_SYN).
                self.click_pending = True
            elif ev.value == 0:
                if self.click_pending:
                    self.on_click()
                out.unhold("touchclick")
        elif ev.type == e.EV_SYN and self.click_pending:
            self.on_click()
        elif ev.type == e.EV_ABS and ev.code in (e.ABS_X, e.ABS_Y) and self.touching:
            self.pos[0 if ev.code == e.ABS_X else 1] = ev.value
            if None not in self.pos:
                self.on_move(*self.pos)

    def is_tap(self) -> bool:
        # Short, never slid, and not a click (which already sent its arrow).
        return (self.touch_from is not None and not self.slid
                and time.monotonic() - self.since < TAP_TIME)

    @staticmethod
    def zone(x: int | None, y: int | None) -> str | None:
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

    def on_click(self) -> None:
        self.click_pending = False
        self.slid = True                        # pressing moves the finger: no tap as well
        zone = self.zone(*self.pos)
        # Held like a key, so holding the click autorepeats the arrow.
        if zone:
            self.m.out.hold("touchclick", [ARROWS[zone]])
            self.m.flash.show("Touchpad click", zone.capitalize(), plain=True)

    def on_move(self, x: int, y: int) -> None:
        if self.touch_from is None:
            self.touch_from = [x, y]             # first position after landing
        elif max(abs(x - self.touch_from[0]), abs(y - self.touch_from[1])) >= SLIDE:
            self.slid = True
