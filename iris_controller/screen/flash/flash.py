"""The flash: what just happened, mid-screen. The buttons pop in, then what
they did ("L2 + □ ▸ Copy", "□ ▸ Enter"). Drawn by Flash.qml next to this file."""

from __future__ import annotations

import json

from ...core.config import CONFIG, LABELS
from ...device import profiles

PLUGIN = "p4ulcristian.iris-controller-flash"

# [flash] combos / buttons = false turns them off. [notify] is the old name.
_switches = CONFIG.get("flash", CONFIG.get("notify", {}))
COMBOS = _switches.get("combos", True)
BUTTONS = _switches.get("buttons", True)


class Flash:
    def __init__(self, shell) -> None:
        self.shell = shell

    def show(self, inputs: str, action: str, plain: bool = False) -> None:
        """A press that did something: inputs like "L2 + □", plain = a single
        button. The cheat sheet's notes ("(hold = drag)") are dropped."""
        if not (BUTTONS if plain else COMBOS):
            return
        action = LABELS.get(action, action.split(" (")[0])
        self.message(action, [k.removeprefix("Hold ") for k in inputs.split(" + ")])

    def message(self, text: str, keys: list[str] = ()) -> None:
        """Always shown: game mode, Iris."""
        keys = [profiles.active.rename(k) for k in keys]   # written as on a DualSense
        self.shell.send(PLUGIN, ["summon", PLUGIN, json.dumps({"keys": keys, "action": text})])
