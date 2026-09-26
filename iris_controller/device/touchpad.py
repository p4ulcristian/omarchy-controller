"""The touchpad: one finger sliding up/down = volume, one step per VOLUME_STEP
travelled; sideways does nothing. A tap (touch and lift, no slide) or a click
is an arrow key: the side you touch is the arrow sent."""

from __future__ import annotations

import time

from evdev import ecodes as e

from ..keymap.bindings import ARROWS, VOLUME_DOWN, VOLUME_UP

SWIPE_LOCK = 60                 # movement before a swipe commits to sideways or up/down
VOLUME_STEP = 100               # touchpad units (of 1080) per volume step
TOUCH_SIZE = (1920, 1080)       # DualSense touchpad resolution
CLICK_DEADZONE = 0.1            # taps/clicks this close to the centre have no direction: ignored
TAP_TIME = 0.25                 # a touch lifted within this, without sliding, is a tap


class Touchpad:
    def __init__(self, m) -> None:
        self.m = m
        self.pos = [None, None]                 # finger x, y
        self.swipe_from: list[int] | None = None  # where the swipe started (or last volume step)
        self.swipe_axis: str | None = None      # "x"/"y" once the swipe has a direction, "click" if clicked
        self.click_pending = False              # pad pressed; zone decided at the end of the report
        self.since = 0.0                        # when the finger landed, for taps
        self.touching = False

    def handle(self, ev) -> None:
        if self.m.paused:
            return
        out = self.m.out
        if ev.type == e.EV_KEY and ev.code == e.BTN_TOUCH:
            if not ev.value and self.is_tap():
                zone = self.zone(*self.swipe_from)
                if zone:
                    out.tap([ARROWS[zone]])
                    self.m.flash.show("Touchpad tap", zone.capitalize(), plain=True)
            self.touching = bool(ev.value)
            self.since = time.monotonic()
            self.pos, self.swipe_from = [None, None], None
            self.swipe_axis = None
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
                self.on_swipe(*self.pos)

    def is_tap(self) -> bool:
        # Short, never slid far enough to count as a swipe, and not a click
        # (which already sent its arrow).
        return (self.swipe_from is not None and self.swipe_axis is None
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
        self.swipe_axis = "click"               # pressing moves the finger: no volume, no tap
        zone = self.zone(*self.pos)
        # Held like a key, so holding the click autorepeats the arrow.
        if zone:
            self.m.out.hold("touchclick", [ARROWS[zone]])
            self.m.flash.show("Touchpad click", zone.capitalize(), plain=True)

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
            self.m.out.tap(VOLUME_UP if dy < 0 else VOLUME_DOWN)   # touchpad y grows downward
            self.m.flash.show("Touchpad swipe", "Volume up" if dy < 0 else "Volume down", plain=True)
            self.swipe_from[1] += VOLUME_STEP if dy > 0 else -VOLUME_STEP
