"""Window mode, R2 held: the left stick drags the window (Super + left button,
pressed once the stick moves), the right stick resizes it. Once dragging, the
right stick sideways takes the window to another workspace instead."""

from __future__ import annotations

import time

from evdev import ecodes as e

from ..core.sticks import WORKSPACE_DELAY, WORKSPACE_REPEAT
from ..keymap.bindings import SUPER
from ..output import hyprland

WINDOW_DRAG = [SUPER, e.BTN_LEFT]
RESIZE_SPEED = 900          # px/s the window grows at full R2 + right stick
RESIZE_EVERY = 0.03         # at most one resize dispatch per this many seconds


class WindowMode:
    def __init__(self, m) -> None:
        self.m = m
        self.resize_acc = [0.0, 0.0]            # px not yet sent
        self.dragged = False                    # this R2 hold has dragged: right stick = workspaces
        self.resized = False                    # this R2 hold has resized (flashed once)
        self.resize_next = 0.0                  # when the next resize may be sent

    def update(self, lx: float, ly: float, rx: float, ry: float, dt: float) -> bool:
        # False when R2 isn't held; letting go of R2 drops the window.
        m, out = self.m, self.m.out
        if not m.r2_held():
            out.unhold("drag")
            self.resize_acc = [0.0, 0.0]
            self.dragged = self.resized = False
            return False
        if (lx or ly) and not out.holding("drag"):
            out.hold("drag", WINDOW_DRAG)
            if not self.dragged:
                m.flash.show("R2 + L-stick", "Move window")
            self.dragged = True
        if self.dragged:
            m.sticks.step(rx, lambda: self.move_window(-1),
                          lambda: self.move_window(1), WORKSPACE_REPEAT,
                          WORKSPACE_DELAY)
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
            hyprland.dispatch(f"hl.dsp.window.resize({{ x = {dx}, y = {dy}, relative = true }})")
            if not self.resized:
                m.flash.show("R2 + R-stick", "Resize window")
            self.resized = True
        return True

    def move_window(self, way: int) -> None:
        # Let go of the Super-drag first: a window can't change workspace
        # mid-drag. The left stick picks it up again on the new workspace.
        self.m.out.unhold("drag")

        def go() -> None:
            ws = hyprland.next_workspace(way)
            if ws is not None:
                hyprland.dispatch_wait(f'hl.dsp.window.move({{ workspace = "{ws}" }})')
            self.m.flash.show("R2 + R-stick", f"Window to workspace {hyprland.workspace_name()}"
                              if ws is not None else "No more workspaces")
        hyprland.later(go)
