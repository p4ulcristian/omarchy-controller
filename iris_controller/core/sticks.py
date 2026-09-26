"""The sticks, every tick: left moves the pointer, right scrolls. With
L2 held the right stick switches workspaces (sideways) or changes the text
size (up/down); in the Omarchy menu it moves through the list; with R2 held
it belongs to window mode. While the app launcher shows, the left stick
steps through its tiles."""

from __future__ import annotations

import time

from evdev import ecodes as e

from ..keymap.bindings import ZOOM_IN, ZOOM_OUT, Bind
from ..output import hyprland
from ..screen.flash import flash

DEADZONE = 0.15
POINTER_MAX = 1500.0         # px/s at full stick
SCROLL_MAX = 2400.0          # hi-res wheel units/s (120 = one notch)
ZOOM_THRESHOLD = 0.5         # right stick deflection that counts as a step
ZOOM_REPEAT = 0.2            # seconds between zoom steps while the stick stays pushed
WORKSPACE_DELAY = 0.3        # seconds from the first workspace step to the second while held
WORKSPACE_REPEAT = 0.12      # seconds between workspace steps after that


def curve(x: float, y: float) -> tuple[float, float]:
    mag = (x * x + y * y) ** 0.5
    if mag < DEADZONE:
        return 0.0, 0.0
    scaled = min(1.0, (mag - DEADZONE) / (1 - DEADZONE))
    f = scaled * scaled / mag
    return x * f, y * f


class Sticks:
    def __init__(self, m) -> None:
        self.m = m
        self.acc = [0.0, 0.0, 0.0, 0.0]         # dx, dy, wheel_v, wheel_h not yet sent
        self.next_step = 0.0                    # when the next zoom/arrow/workspace step may fire
        self.step_dir = 0                       # which way the stick is pushed for steps, 0 = not

    def update(self, dt: float) -> None:
        m = self.m
        lx, ly = curve(m.axes.get(e.ABS_X, 0.0), m.axes.get(e.ABS_Y, 0.0))
        rx, ry = curve(m.axes.get(e.ABS_RX, 0.0), m.axes.get(e.ABS_RY, 0.0))

        if m.launcher.open:
            # The app grid: the left stick steps through the tiles, the
            # further-pushed direction wins; the pointer stays put.
            axis, v = ("x", lx) if abs(lx) > abs(ly) else ("y", ly)
            self.step(v, lambda: m.launcher.move(axis, -1), lambda: m.launcher.move(axis, 1),
                      WORKSPACE_REPEAT, WORKSPACE_DELAY)
            return
        speed = POINTER_MAX * dt
        self.acc[0] += lx * speed
        self.acc[1] += ly * speed
        if m.window.update(lx, ly, rx, ry, dt):
            pass                                # R2 held: right stick resizes
        elif m.trig[e.ABS_Z]:
            # L2 + right stick: sideways = workspaces, up/down = text size.
            # The further-pushed direction wins, so a slightly diagonal push is one.
            layer = "L2 + R-stick"
            if abs(rx) > abs(ry):
                self.step(rx, lambda: self.to_workspace(layer, -1),
                          lambda: self.to_workspace(layer, 1), WORKSPACE_REPEAT, WORKSPACE_DELAY)
            else:
                self.step(ry, lambda: self.zoom(ZOOM_IN, layer), lambda: self.zoom(ZOOM_OUT, layer))
        elif abs(ry) >= ZOOM_THRESHOLD and hyprland.menu_open():
            self.step(ry, lambda: m.out.tap([e.KEY_UP]), lambda: m.out.tap([e.KEY_DOWN]))
        else:
            self.step_dir = 0
            self.acc[2] += ry * SCROLL_MAX * dt     # natural: stick up moves the content up
            self.acc[3] += rx * SCROLL_MAX * dt
        wrote = False
        for i, code in enumerate((e.REL_X, e.REL_Y, e.REL_WHEEL_HI_RES, e.REL_HWHEEL_HI_RES)):
            n = int(self.acc[i])
            if n:
                self.acc[i] -= n
                m.out.rel(code, n)
                wrote = True
        if wrote:
            m.out.syn()

    def step(self, v: float, negative, positive, repeat: float = ZOOM_REPEAT,
             delay: float | None = None) -> None:
        # One action per push (up/left = negative), like a held key: after
        # `delay` seconds it repeats every `repeat` seconds while the stick
        # stays pushed. Pushing the other way starts over at once.
        if abs(v) < ZOOM_THRESHOLD:
            self.step_dir = 0
            return
        now = time.monotonic()
        way = -1 if v < 0 else 1
        if way != self.step_dir:
            self.step_dir = way
            self.next_step = now + (repeat if delay is None else delay)
        elif now >= self.next_step:
            self.next_step = now + repeat
        else:
            return
        (negative if way < 0 else positive)()

    def zoom(self, bind: Bind, inputs: str) -> None:
        self.m.out.tap(bind.keys)
        self.m.flash.show(inputs, bind.label)

    def to_workspace(self, inputs: str, way: int) -> None:
        # Workspaces with windows on this monitor, then one new empty one.
        # Worked out and switched on hyprland's thread, which answers with
        # the flash: the stick never waits on hyprctl.
        def go() -> None:
            ws = hyprland.next_workspace(way)
            if ws is not None:
                hyprland.dispatch_wait(f'hl.dsp.focus({{ workspace = "{ws}" }})')
            if flash.COMBOS:
                self.m.flash.show(inputs, f"Workspace {hyprland.workspace_name()}"
                                  if ws is not None else "No more workspaces")
        hyprland.later(go)
