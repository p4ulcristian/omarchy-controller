"""The mapper: every button, trigger and D-pad event comes in here and goes to
the part that handles it. It keeps what they share: which buttons and
triggers are down, and whether the controller is grabbed."""

from __future__ import annotations

import logging
import os
import time

import evdev
from evdev import ecodes as e

from ..device import finder
from ..device.mic import Mic
from ..device.touchpad import Touchpad
from ..keymap.bindings import (BASE_HOLD, BASE_TAP, DOUBLE_TAP_WINDOW, DOUBLE_TRIGGERS, DPAD_ARROWS,
                               ENTER_BTN, ENTER_DOUBLE, FULLSCREEN, PS_COMBOS, L1_COMBOS, L2_COMBOS,
                               NAV_BACK, NAV_FORWARD, PARTS, REFRESH, RIGHT_CLICK, R2_DPAD, ARROWS,
                               VOLUME_DOWN, VOLUME_UP)
from ..modes.game import GameMode
from ..modes.talk import Talk
from ..modes.window import WindowMode
from ..output import hyprland
from ..output.virtual_input import VirtualInput
from ..screen.flash.flash import Flash
from ..screen.help.help import Help
from ..screen.keyboard.keyboard import OnScreenKeyboard
from ..screen.shell import Shell
from .sticks import Sticks

log = logging.getLogger("iris-controller")

TRIGGER_ON, TRIGGER_OFF = 0.5, 0.3
CHORD_WINDOW = 0.06         # L2 within this of R2 = fullscreen


class Mapper:
    def __init__(self, out: VirtualInput) -> None:
        self.out = out
        self.shell = Shell()
        self.flash = Flash(self.shell)
        self.help = Help()
        self.keyboard = OnScreenKeyboard(self)
        self.touchpad = Touchpad(self)
        self.mic = Mic()
        self.sticks = Sticks(self)
        self.window = WindowMode(self)
        self.game = GameMode(self)
        self.talk = Talk(self)

        self.devs: list[evdev.InputDevice] = []
        self.pad: evdev.InputDevice | None = None
        self.touch: evdev.InputDevice | None = None
        self.hid_fd: int | None = None          # DualSense raw reports, for the mic button
        self.axes: dict[int, float] = {}
        self.ranges: dict[int, tuple[int, int]] = {}
        self.trig = {e.ABS_Z: False, e.ABS_RZ: False}
        self.trig_pending: dict[int, float] = {}  # trigger -> press time, action not sent yet
        self.trig_tapped: dict[int, float] = {}   # trigger -> when a quick tap ended (double tap)
        self.trig_consumed: set[int] = set()      # second press of a double tap: its release does nothing
        self.hat = {"x": 0, "y": 0}
        self.l1_held = False                  # L1 held: layer for user L1 combos
        self.enter_first: float | None = None   # first □ press, waiting for a second one
        self.grabbed = False
        self.mouse_focus_user = hyprland.mouse_focus_option()   # restored whenever we let go

    # --- device lifecycle -------------------------------------------------

    def attach(self, devs: list[evdev.InputDevice]) -> None:
        self.devs = devs
        self.pad, self.touch = finder.split(devs)
        if self.pad:
            for code, info in self.pad.capabilities()[e.EV_ABS]:
                self.ranges[code] = (info.min, info.max)
            self.hid_fd = finder.find_hidraw(self.pad)
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
            hyprland.set_mouse_focus(self.mouse_focus_user)
        self.devs, self.pad, self.touch, self.grabbed = [], None, None, False
        self.axes.clear()

    @property
    def paused(self) -> bool:
        return self.game.on

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
        hyprland.set_mouse_focus(True if want else self.mouse_focus_user)
        if not want:
            self.release_all()

    def release_all(self) -> None:
        self.enter_first = None
        if self.keyboard.open:
            self.keyboard.toggle(False)
        self.trig_pending.clear()
        self.mic.down = False
        if self.help.open:
            self.help.show(False)
        self.talk.stop()
        self.out.release_all()

    # --- input ------------------------------------------------------------

    def norm(self, code: int, value: int) -> float:
        lo, hi = self.ranges.get(code, (-32768, 32767))
        if code in (e.ABS_Z, e.ABS_RZ):
            return (value - lo) / (hi - lo) if hi > lo else 0.0
        mid = (lo + hi) / 2
        return max(-1.0, min(1.0, (value - mid) / ((hi - lo) / 2)))

    def handle(self, ev, dev=None) -> None:
        if dev is not None and dev is self.touch:
            self.touchpad.handle(ev)
            return
        if ev.type == e.EV_ABS:
            self.on_abs(ev.code, ev.value)
        elif ev.type == e.EV_KEY and ev.value in (0, 1):
            log.debug("key %s %s", e.KEY.get(ev.code) or e.BTN.get(ev.code) or ev.code, ev.value)
            self.on_button(ev.code, ev.value == 1)

    def on_hid(self, report: bytes) -> None:
        if not self.paused and self.mic.pressed(report):
            self.help.show(not self.help.open)

    def on_button(self, code, down: bool) -> None:
        if code == e.BTN_MODE:
            self.game.ps(down)
            return
        if self.paused:
            return
        out, flash = self.out, self.flash

        if down and code == e.BTN_EAST and self.r2_held():
            self.keyboard.toggle(not self.keyboard.open)   # R2 + ○: on-screen keyboard
            flash.show("R2 + ○", "Keyboard " + ("on" if self.keyboard.open else "off"))
            return
        if code == e.BTN_WEST and not down:
            out.unhold("r2_space")               # let go of an R2 + □ space, if it was one
        if down and code == e.BTN_WEST and self.r2_held():
            out.hold("r2_space", [e.KEY_SPACE])  # R2 + □: space, held so it repeats
            flash.show("R2 + □", "Space")
            return
        if down and code == e.BTN_NORTH and self.r2_held():
            out.tap(REFRESH.keys)                # R2 + △: refresh
            flash.show("R2 + △", REFRESH.label)
            return
        if self.keyboard.open and self.keyboard.button(code, down):
            return

        if down and self.game.ps_held:
            self.game.ps_used = True
            if code in PS_COMBOS:
                out.fire(PS_COMBOS[code])
                flash.show("PS + " + PARTS[code][1], PS_COMBOS[code].label)
                return
        if down and self.l1_held and code in L1_COMBOS:
            out.fire(L1_COMBOS[code])
            flash.show("L1 + " + PARTS[code][1], L1_COMBOS[code].label)
            return
        if down and self.trig[e.ABS_Z] and code in L2_COMBOS:
            out.fire(L2_COMBOS[code])
            flash.show("L2 + " + PARTS[code][1], L2_COMBOS[code].label)
            return
        # A layer held + a button with no combo on it: dropped, not the plain
        # action. L2 + ✕ (right click) and the stick clicks aren't combos.
        layer = ("PS" if self.game.ps_held else "L1" if self.l1_held and L1_COMBOS
                 else "L2" if self.trig[e.ABS_Z] and code != e.BTN_SOUTH else None)
        if down and layer and code in PARTS and \
                code not in (e.BTN_TL, e.BTN_THUMBL, e.BTN_THUMBR):
            flash.show(f"{layer} + {PARTS[code][1]}", "No such combo")
            return

        if code == ENTER_BTN:
            self.on_enter(down)
            return
        if code == e.BTN_TL:
            self.l1_held = down
            return

        if not down:
            if code == e.BTN_TR:
                self.talk.release()
            out.unhold(code)
            return

        if code == e.BTN_TR:
            self.talk.press()
        elif code == e.BTN_SOUTH and hyprland.menu_open():
            out.hold(code, [e.KEY_ENTER])   # ✕ confirms in the menu instead of clicking
            flash.show("✕", "Enter", plain=True)
        elif code == e.BTN_SOUTH and self.trig[e.ABS_Z]:
            out.hold(code, RIGHT_CLICK.keys)   # L2 held: ✕ is the right button (hold = drag)
            flash.show("L2 + ✕", RIGHT_CLICK.label)
        elif code in BASE_HOLD:
            out.hold(code, BASE_HOLD[code].keys)
            flash.show(PARTS[code][1], BASE_HOLD[code].label, plain=True)
        elif code in BASE_TAP:
            out.tap(BASE_TAP[code].keys)
            flash.show(PARTS[code][1], BASE_TAP[code].label, plain=True)

    def on_enter(self, down: bool) -> None:
        # □ is Enter, but a second press within DOUBLE_TAP_WINDOW makes it
        # Ctrl+Enter instead, so the first press is held back until then.
        if not down:
            self.out.unhold(ENTER_BTN)   # only held if the window already ran out
            return
        if self.enter_first is not None:
            self.enter_first = None
            self.out.tap(ENTER_DOUBLE.keys)
            self.flash.show("□ □", ENTER_DOUBLE.label)
        else:
            self.enter_first = time.monotonic()

    def check_enter(self) -> None:
        if self.enter_first is None or time.monotonic() - self.enter_first < DOUBLE_TAP_WINDOW:
            return
        self.enter_first = None
        # Still held: hold Enter so it autorepeats; already released: one Enter.
        if self.enter_held():
            self.out.hold(ENTER_BTN, BASE_HOLD[ENTER_BTN].keys)
        else:
            self.out.tap(BASE_HOLD[ENTER_BTN].keys)
        self.flash.show(PARTS[ENTER_BTN][1], BASE_HOLD[ENTER_BTN].label, plain=True)

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
            self.out.fire(DOUBLE_TRIGGERS[code])
            self.flash.show(f"{PARTS[code][1]} + {PARTS[code][1]}", DOUBLE_TRIGGERS[code].label)
            return
        if not now and code in self.trig_consumed:
            self.trig_consumed.discard(code)
            return
        # Both triggers together = fullscreen, in either order: an R2 press
        # stays pending for CHORD_WINDOW so L2 can still join it.
        if now and (self.trig[e.ABS_Z] if code == e.ABS_RZ
                    else self.trig_pending.pop(e.ABS_RZ, None) is not None):
            self.trig_consumed.add(e.ABS_RZ)
            self.out.tap(FULLSCREEN.keys)
            self.flash.show("L2 + R2", FULLSCREEN.label)
            return
        if code == e.ABS_Z and code not in DOUBLE_TRIGGERS:
            return                        # L2 is only a modifier (see on_button)
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

    def r2_held(self) -> bool:
        # R2 down as window mode: not still a possible fullscreen chord / double
        # tap, and not already used up by one.
        return (self.trig[e.ABS_RZ] and e.ABS_RZ not in self.trig_pending
                and e.ABS_RZ not in self.trig_consumed)

    def on_hat(self, axis: str, value: int) -> None:
        prev = self.hat[axis]
        self.hat[axis] = value
        if self.paused:
            return
        if self.keyboard.open:
            self.keyboard.dpad(axis, value, prev)
            return
        # D-pad = arrow keys, held while the direction is, so they autorepeat.
        names = ("left", "right") if axis == "x" else ("up", "down")
        if value != prev:
            self.out.unhold(("hat", axis))
            arrow = names[0] if value < 0 else names[1]
            if value and self.r2_held() and arrow in R2_DPAD:
                self.out.fire(R2_DPAD[arrow])        # R2 held: the D-pad runs user binds
                self.flash.show("R2 + D-pad " + DPAD_ARROWS[arrow], R2_DPAD[arrow].label)
            elif value and self.trig[e.ABS_Z] and axis == "x":
                nav = NAV_BACK if value < 0 else NAV_FORWARD   # L2 held: ←/→ = back / forward
                self.out.tap(nav.keys)
                self.flash.show("L2 + D-pad " + DPAD_ARROWS[arrow], nav.label)
            elif value and axis == "y" and self.trig[e.ABS_Z]:
                # L2 held: ↑/↓ = volume, held so Omarchy's binding repeats it.
                self.out.hold(("hat", axis), VOLUME_UP if value < 0 else VOLUME_DOWN)
                self.flash.show("L2 + D-pad", "Volume up" if value < 0 else "Volume down")
            elif value:
                self.out.hold(("hat", axis), [ARROWS[arrow]])
                self.flash.show("D-pad", arrow.capitalize(), plain=True)

    # --- every tick ---------------------------------------------------------

    def tick(self, dt: float) -> None:
        self.game.tick()
        if self.paused or not self.pad:
            return
        self.check_triggers()
        self.check_enter()
        self.keyboard.tick()
        self.sticks.update(dt)
