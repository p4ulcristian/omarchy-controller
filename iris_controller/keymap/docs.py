"""The keymap as data, for the cheat sheet, and as docs/KEYMAP.md:
    XDG_CONFIG_HOME=/nonexistent python3 -m iris_controller.core.main --keymap > docs/KEYMAP.md"""

from __future__ import annotations

from evdev import ecodes as e

from ..core.config import LABELS
from ..modes.talk import DICTATE_SOCK, IRIS_URL
from .bindings import (DOUBLE_TRIGGERS, KEYBOARD, ENTER_BTN, ENTER_DOUBLE, FULLSCREEN, PS_COMBOS, L1_COMBOS,
                       L2_COMBOS, NAV_BACK, NAV_FORWARD, PARTS, REFRESH, RIGHT_CLICK, R2_DPAD, ZOOM_IN,
                       ZOOM_OUT, BASE_HOLD, BASE_TAP, DPAD_ARROWS)


def keymap() -> dict:
    """Every mapping, from the tables, for the cheat sheet and KEYMAP.md:
    parts: {id: {name, actions}} labels on the drawing; combos: [{keys, action}]."""
    parts = {pid: {"name": name, "actions": []} for pid, name in PARTS.values()}
    parts |= {"dpad": {"name": "D-pad", "actions": []},
              "touchpad": {"name": "Touchpad", "actions": []},
              "mic": {"name": "Mic", "actions": []}}

    def add(code_or_id, action):
        action = LABELS.get(action, action)
        parts[PARTS[code_or_id][0] if code_or_id in PARTS else code_or_id]["actions"].append(action)

    def name(code):
        return PARTS[code][1]

    add("lstick", "Move pointer")
    add("rstick", "Scroll")
    for code, b in BASE_HOLD.items():
        add(code, b.label)
    for code, b in BASE_TAP.items():
        add(code, b.label)
    if DICTATE_SOCK:
        add(e.BTN_TR, "Hold: dictate")
    if IRIS_URL:
        add(e.BTN_TR, "Tap, then hold: talk to Iris (release to send)")
    if L1_COMBOS:
        add(e.BTN_TL, "Hold: combo layer")
    add(e.BTN_MODE, "Hold 1 s: game mode on/off")
    add(e.ABS_Z, "Hold + ✕: right click")
    add("dpad", "Arrow keys (hold to repeat)")
    add(e.ABS_Z, "Hold + right stick ←/→: previous / next workspace")
    add(e.ABS_Z, "Hold + right stick ↑/↓: bigger / smaller text")
    add(e.ABS_Z, "Hold + D-pad ↑/↓: volume up / down")
    add(e.ABS_Z, "Hold + D-pad ←/→: back / forward")
    add(e.ABS_RZ, "Hold + left stick: move window")
    add(e.ABS_RZ, "Hold + right stick: resize window")
    add(e.ABS_RZ, "Twice: on-screen keyboard")
    add(e.ABS_RZ, "Hold + □: space")
    add(e.ABS_RZ, "Hold + △: refresh")
    add(e.ABS_RZ, "Dragging + right stick ←/→: take window to prev / next workspace")
    add("touchpad", "Tap: arrow key toward that side")
    add("touchpad", "Click & hold: arrow key, repeating")
    add("mic", "Show this cheat sheet (any button closes it)")

    combos = [{"keys": [name(ENTER_BTN), name(ENTER_BTN)], "action": ENTER_DOUBLE.label},
              *({"keys": [name(c), name(c)], "action": b.label} for c, b in DOUBLE_TRIGGERS.items()),
              {"keys": [name(e.ABS_Z), name(e.ABS_RZ)], "action": FULLSCREEN.label},
              {"keys": ["Hold " + name(e.ABS_Z), name(e.BTN_SOUTH)], "action": RIGHT_CLICK.label},
              {"keys": ["Hold " + name(e.ABS_Z), "R-stick ←"], "action": "Previous workspace"},
              {"keys": ["Hold " + name(e.ABS_Z), "R-stick →"], "action": "Next workspace"},
              {"keys": ["Hold " + name(e.ABS_Z), "R-stick ↑"], "action": ZOOM_IN.label},
              {"keys": ["Hold " + name(e.ABS_Z), "R-stick ↓"], "action": ZOOM_OUT.label},
              {"keys": ["Hold " + name(e.ABS_Z), "D-pad ↑"], "action": "Volume up"},
              {"keys": ["Hold " + name(e.ABS_Z), "D-pad ↓"], "action": "Volume down"},
              {"keys": ["Hold " + name(e.ABS_Z), "D-pad ←"], "action": NAV_BACK.label},
              {"keys": ["Hold " + name(e.ABS_Z), "D-pad →"], "action": NAV_FORWARD.label},
              {"keys": ["Hold " + name(e.ABS_RZ), "Left stick"], "action": "Move window"},
              {"keys": ["Hold " + name(e.ABS_RZ), "R-stick"], "action": "Resize window (→/↓ bigger)"},
              {"keys": ["Hold " + name(e.ABS_RZ), "Left stick", "R-stick ←/→"],
               "action": "Take window to prev / next workspace"}]
    combos.append({"keys": ["Hold " + name(e.ABS_RZ), name(ENTER_BTN)], "action": "Space"})
    combos.append({"keys": ["Hold " + name(e.ABS_RZ), name(e.BTN_NORTH)], "action": REFRESH.label})
    combos += [{"keys": ["Hold " + name(e.ABS_RZ), "D-pad " + DPAD_ARROWS[d]], "action": b.label}
               for d, b in R2_DPAD.items()]
    combos += [{"keys": ["Hold " + name(e.ABS_Z), name(c)], "action": b.label}
               for c, b in L2_COMBOS.items()]
    combos += [{"keys": ["Hold " + name(e.BTN_MODE), name(c)], "action": b.label}
               for c, b in PS_COMBOS.items()]
    combos += [{"keys": ["Hold " + name(e.BTN_TL), name(c)], "action": b.label}
               for c, b in L1_COMBOS.items()]
    menu = [{"keys": ["D-pad", "R-stick"], "action": "Move through the list"},
            {"keys": [name(e.BTN_SOUTH) + " / " + name(ENTER_BTN)], "action": "Open"},
            {"keys": [name(e.BTN_EAST)], "action": "Close"}]
    for c in combos:
        c["action"] = LABELS.get(c["action"], c["action"])
    return {"parts": parts, "combos": combos, "menu": menu}


def keymap_markdown() -> str:
    km = keymap()
    out = ["# iris-controller keymap", "",
           "Generated by `python3 -m iris_controller.core.main --keymap > docs/KEYMAP.md`; "
           "edit the tables in `iris_controller/keymap/bindings.py`, not this file.",
           "Press the mic button to toggle it as an overlay.", "",
           "## Buttons", "", "| Input | Action |", "|---|---|"]
    for part in km["parts"].values():
        out += [f"| {part['name']} | {a} |" for a in part["actions"]]
    for title, rows in (("Combos", km["combos"]), ("In the Omarchy menu", km["menu"])):
        out += ["", f"## {title}", "", "| Input | Action |", "|---|---|"]
        out += [f"| {' + '.join(r['keys'])} | {r['action']} |" for r in rows]
    out += ["", "## Game mode", "",
            "The mapper grabs the controller while it runs, so games would see nothing.",
            "- Hold the PS button for 1 second to release/retake the controller.",
            "- Auto: pause when the focused window is fullscreen and belongs to Steam "
            "(`steam_app_*` class) or gamescope.", ""]
    return "\n".join(out)


def cheatsheet() -> dict:
    """The mic-button overlay: one short label per part of the drawing, and
    every action once, grouped by what you want to do.
    parts: {id: {name, actions: [label]}}; categories: [{title, rows: [{keys, action}]}]."""
    parts = keymap()["parts"]
    short = {"cross": "Click", "circle": "Escape", "square": "Enter", "triangle": "Backspace",
             "lstick": "Pointer", "rstick": "Scroll", "options": "Omarchy menu", "ps": "Game mode",
             "l2": "Shortcuts", "r2": "Window mode", "dpad": "Arrow keys", "touchpad": "Arrow keys",
             "mic": "This sheet"}
    if DICTATE_SOCK or IRIS_URL:
        short["r1"] = "Voice"
    if L1_COMBOS:
        short["l1"] = "Your combos"
    for pid, part in parts.items():
        part["actions"] = [short[pid]] if pid in short else []

    def name(code):
        return PARTS[code][1]

    def row(keys, action):
        return {"keys": keys, "action": LABELS.get(action, action).split(" (")[0]}

    L2, R2 = name(e.ABS_Z), name(e.ABS_RZ)
    sq, ci, tr, cr = name(e.BTN_WEST), name(e.BTN_EAST), name(e.BTN_NORTH), name(e.BTN_SOUTH)
    voice = []
    if DICTATE_SOCK:
        voice.append(row(["R1 hold"], "Dictate"))
    if IRIS_URL:
        voice.append(row(["R1 tap, hold"], "Talk to Iris"))
    categories = [
        {"title": "Pointer", "rows": [
            row(["L-stick"], "Move pointer"),
            row([cr], "Click (hold = drag)"),
            row([L2, cr], RIGHT_CLICK.label),
            row(["R-stick"], "Scroll")]},
        {"title": "Typing", "rows": [
            row([sq], "Enter"), row([ci], "Escape"), row([tr], "Backspace"),
            row([sq, sq], ENTER_DOUBLE.label),
            row([R2, sq], "Space"),
            row([R2, R2], "On-screen keyboard")]},
        {"title": "Edit & browse", "rows": [
            row([L2, sq], L2_COMBOS[e.BTN_WEST].label),
            row([L2, ci], L2_COMBOS[e.BTN_EAST].label),
            row(["D-pad"], "Arrow keys"),
            row(["Touchpad"], "Arrow key toward that side"),
            row([L2, "D-pad ←/→"], f"{NAV_BACK.label} / {NAV_FORWARD.label.lower()}"),
            row([R2, tr], REFRESH.label)]},
        {"title": "Windows", "rows": [
            row([R2, "L-stick"], "Move"),
            row([R2, "R-stick"], "Resize"),
            row([R2, "L-stick", "R-stick ←/→"], "To workspace"),
            row([L2, tr], L2_COMBOS[e.BTN_NORTH].label),
            row([L2, R2], FULLSCREEN.label)]},
        {"title": "Desktop", "rows": [
            row([L2, "R-stick ←/→"], "Workspaces"),
            row([L2, "R-stick ↑/↓"], "Text size"),
            row([L2, "D-pad ↑/↓"], "Volume"),
            row([name(e.BTN_START)], BASE_TAP[e.BTN_START].label)]},
        {"title": "Voice & system", "rows": voice + [
            row([name(e.BTN_MODE) + " hold 1 s"], "Game mode on/off"),
            row(["Mic"], "This sheet")]},
    ]
    own = ([row([R2, "D-pad " + DPAD_ARROWS[d]], b.label) for d, b in R2_DPAD.items()]
           + [row([name(c), name(c)], b.label) for c, b in DOUBLE_TRIGGERS.items() if b is not KEYBOARD]
           + [row([name(e.BTN_TL), name(c)], b.label) for c, b in L1_COMBOS.items()]
           + [row([name(e.BTN_MODE), name(c)], b.label) for c, b in PS_COMBOS.items()])
    if own:
        categories.append({"title": "Your shortcuts", "rows": own})
    categories.append({"title": "In the Omarchy menu", "rows": keymap()["menu"]})
    return {"parts": parts, "categories": categories}
