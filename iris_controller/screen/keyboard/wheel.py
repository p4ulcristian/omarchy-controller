"""The petal keyboard: the left stick picks one of 8 petals around a wheel,
a face button (right thumb) one of that petal's 4 characters. With the stick at rest the
face buttons edit: ✕ space, △ backspace, □ Enter, ○ closes. L2 / R2 step
through the layers, the D-pad sets sticky modifiers (↑ Ctrl, ← Alt,
→ Super; tap once = next key only, twice = locked, three times = off) and
↓ is Tab. The right stick moves the text cursor."""

from __future__ import annotations

import math

from evdev import ecodes as e

from ...keymap.bindings import ALT, CTRL, SHIFT, SUPER

# A petal's characters go to the face buttons clockwise from the top.
FACE = [e.BTN_NORTH, e.BTN_EAST, e.BTN_SOUTH, e.BTN_WEST]   # △ ○ ✕ □
PICK = 0.55              # left stick pushed this far: a petal
LET_GO = 0.35            # back under this: the center again
STICKY = 8               # degrees past a petal's edge before the next one takes over


def _key(label: str, name: str) -> tuple[str, int]:
    return (label, getattr(e, "KEY_" + name))


# Each layer: its name, then 8 petals clockwise from ↑. A petal is 4
# characters (a string) or 4 (label, key code) keys, in FACE order.
LAYERS = [
    ("abc", ["abcd", "efgh", "ijkl", "mnop", "qrst", "uvwx", "yz.,", "?!'-"]),
    ("123", ["1234", "5678", "90=+", "@#$%", "&*_/", "()[]", "{}<>", '\\:;"']),
    ("keys", [
        [_key("Esc", "ESC"), _key("Del", "DELETE"), _key("Home", "HOME"), _key("End", "END")],
        [_key("PgUp", "PAGEUP"), _key("PgDn", "PAGEDOWN"), _key("Tab", "TAB"), _key("Ins", "INSERT")],
        [_key("↑", "UP"), _key("→", "RIGHT"), _key("↓", "DOWN"), _key("←", "LEFT")],
        [_key(f"F{n}", f"F{n}") for n in range(1, 5)],
        [_key(f"F{n}", f"F{n}") for n in range(5, 9)],
        [_key(f"F{n}", f"F{n}") for n in range(9, 13)],
        "`~^|",
        [_key("Menu", "COMPOSE"), _key("PrtSc", "SYSRQ"), _key("Caps", "CAPSLOCK"), _key("Space", "SPACE")],
    ]),
]
CENTER = {e.BTN_SOUTH: e.KEY_SPACE, e.BTN_NORTH: e.KEY_BACKSPACE, e.BTN_WEST: e.KEY_ENTER}
MODS = {"up": ("ctrl", CTRL), "left": ("alt", ALT), "right": ("super", SUPER)}
ARROWS = {"left": e.KEY_LEFT, "right": e.KEY_RIGHT, "up": e.KEY_UP, "down": e.KEY_DOWN}
# Key codes only the wheel sends (the characters are the grid's keys too).
KEYS = ({code for _, petals in LAYERS for petal in petals if not isinstance(petal, str)
         for _, code in petal}
        | {e.KEY_TAB, e.KEY_SPACE, e.KEY_BACKSPACE, e.KEY_ENTER, CTRL, ALT, SUPER, SHIFT}
        | set(ARROWS.values()))


class Wheel:
    def __init__(self, kb, chars: dict[str, tuple[int, bool]]) -> None:
        self.kb, self.m = kb, kb.m
        # Every slot as (label, shifted label, keys): a character types with
        # Shift if the US layout needs it, and R1 upper-cases letters.
        self.layers = []
        for _, petals in LAYERS:
            layer = []
            for petal in petals:
                slots = []
                for item in petal:
                    if isinstance(item, str):
                        code, shifted = chars[item]
                        slots.append((item, item.upper(), [SHIFT, code] if shifted else [code]))
                    else:
                        slots.append((item[0], item[0], [item[1]]))
                layer.append(slots)
            self.layers.append(layer)
        self.reset()

    def reset(self) -> None:
        self.layer = 0
        self.petal: int | None = None
        self.mods: dict[str, str] = {}          # "ctrl" -> "once" (next key) | "lock"

    def payload(self) -> dict:
        return {"layers": [{"name": name, "petals": [[{"label": l, "shift": s} for l, s, _ in p]
                                                     for p in layer]}
                           for (name, _), layer in zip(LAYERS, self.layers)]}

    def state(self) -> dict:
        return {"layer": self.layer, "petal": -1 if self.petal is None else self.petal,
                "mods": list(self.mods), "locked": [n for n, how in self.mods.items() if how == "lock"]}

    # --- input ------------------------------------------------------------

    def aim(self, x: float, y: float) -> None:
        # The left stick, every tick: which petal it points at, if any.
        mag = math.hypot(x, y)
        petal = self.petal
        if mag < LET_GO or (petal is None and mag < PICK):
            petal = None
        else:
            angle = math.degrees(math.atan2(x, -y)) % 360     # 0 = up, clockwise
            off = abs((angle - 45 * (petal or 0) + 180) % 360 - 180)
            if petal is None or off > 22.5 + STICKY:
                petal = round(angle / 45) % 8
        if petal != self.petal:
            self.petal = petal
            self.kb.update()

    def button(self, code, down: bool) -> bool:
        if code not in FACE:
            return False
        out = self.m.out
        out.unhold("osk")
        if not down:
            return True
        if self.petal is None:
            if code == e.BTN_EAST:
                self.kb.toggle(False)             # ○ closes
            else:
                self.send(CENTER[code], held=True)
            return True
        _, _, keys = self.layers[self.layer][self.petal][FACE.index(code)]
        if self.kb.shift_held and SHIFT not in keys:
            keys = [SHIFT] + keys
        self.send(keys, held=True)
        return True

    def dpad(self, axis: str, value: int, prev: int) -> None:
        if not value or value == prev:
            return
        way = ("left" if value < 0 else "right") if axis == "x" else ("up" if value < 0 else "down")
        if way == "down":
            self.send([e.KEY_TAB])
            return
        name = MODS[way][0]
        # Tap: next key only -> locked -> off.
        how = {None: "once", "once": "lock"}.get(self.mods.get(name))
        if how:
            self.mods[name] = how
        else:
            self.mods.pop(name, None)
        self.kb.update()

    def trigger(self, code) -> None:
        # R2 next layer, L2 the one before.
        self.layer = (self.layer + (1 if code == e.ABS_RZ else -1)) % len(self.layers)
        self.kb.update()

    def arrow(self, way: str) -> None:
        # The right stick: the text cursor (R1 held selects).
        self.send(([SHIFT] if self.kb.shift_held else []) + [ARROWS[way]])

    # --- output -----------------------------------------------------------

    def send(self, keys, held: bool = False) -> None:
        # With the modifiers that are on; a "once" modifier is used up.
        if isinstance(keys, int):
            keys = [keys]
        keys = [MODS[w][1] for w in ("up", "left", "right") if MODS[w][0] in self.mods] + keys
        if held:
            self.m.out.hold("osk", keys)        # held with its button, so it autorepeats
        else:
            self.m.out.tap(keys)
        once = [n for n, how in self.mods.items() if how == "once"]
        for n in once:
            del self.mods[n]
        if once:
            self.kb.update()
