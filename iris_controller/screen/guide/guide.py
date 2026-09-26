"""The guide: hold L2 or R2 and what you can press next shows
at that side of the screen, until you let go. Built from keymap(), so your
[[bind]]s show up too. Drawn by Guide.qml next to this file."""

from __future__ import annotations

import json

from ...core.config import CONFIG
from ...keymap.docs import keymap

PLUGIN = "p4ulcristian.iris-controller-guide"

# [guide] enabled = false turns it off; delay = seconds of holding before it
# shows (0: at once).
_cfg = CONFIG.get("guide", {})
ENABLED = _cfg.get("enabled", True)
DELAY = _cfg.get("delay", 0.0)

PAIRS = (("←", "→"), ("↑", "↓"))
ORDER = ("✕", "○", "□", "△", "D-pad", "Left stick", "R-stick")   # rows sorted by the first input


def pair_label(a: str, b: str) -> str:
    """"Volume up" + "Volume down" = "Volume up / down"; "Previous workspace" +
    "Next workspace" = "Previous / next workspace"."""
    wa, wb = a.split(), b.split()
    if len(wa) > 1 and len(wb) > 1 and wa[0] == wb[0]:
        return f"{a} / {' '.join(wb[1:])}"
    if len(wa) > 1 and len(wb) > 1 and wa[-1] == wb[-1]:
        return f"{' '.join(wa[:-1])} / {' '.join(wb[:-1]).lower()} {wa[-1]}"
    return f"{a} / {b[:1].lower()}{b[1:]}"


def rows(trigger: str) -> list[dict]:
    """What can follow holding `trigger` ("L2" / "R2"), with ←/→ and ↑/↓
    pairs folded into one row."""
    found = [{"keys": c["keys"][1:], "action": c["action"].split(" (")[0]}
             for c in keymap()["combos"] if c["keys"][0] == "Hold " + trigger]
    out, used = [], set()
    for i, r in enumerate(found):
        if i in used:
            continue
        *head, last = r["keys"]
        for a, b in PAIRS:
            if not last.endswith(" " + a):
                continue
            twin = head + [last[:-1] + b]
            j = next((j for j, o in enumerate(found) if j not in used and o["keys"] == twin), None)
            if j is not None:
                used.add(j)
                r = {"keys": head + [f"{last}/{b}"], "action": pair_label(r["action"], found[j]["action"])}
                break
        out.append(r)
    rank = lambda r: next((n for n, p in enumerate(ORDER) if r["keys"][0].startswith(p)), len(ORDER))
    return sorted(out, key=rank)


class Guide:
    def __init__(self, shell) -> None:
        self.shell = shell
        self.side: str | None = None

    def update(self, side: str | None) -> None:
        """side: "left" (L2 held), "right" (R2 held) or None (hidden)."""
        if side == self.side or not ENABLED:
            return
        self.side = side
        if side:
            trigger = "L2" if side == "left" else "R2"
            payload = {"side": side, "trigger": trigger, "rows": rows(trigger)}
            self.shell.send(PLUGIN, ["summon", PLUGIN, json.dumps(payload)])
        else:
            self.shell.send(PLUGIN, ["hide", PLUGIN])
