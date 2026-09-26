"""Talking to Hyprland through hyprctl: workspaces, windows, what is open."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time

MOUSE_FOCUS = "misc:mouse_move_focuses_monitor"
MENU_LAYERS = ("omarchy-menu",)   # keyboard-driven overlays: the right stick sends arrows
MENU_CACHE = 0.25


def hyprctl_json(what: str):
    try:
        out = subprocess.run(["hyprctl", "-j", what], capture_output=True, text=True, timeout=1)
        return json.loads(out.stdout)
    except Exception:
        return None


def dispatch(arg: str) -> None:
    """Fire and forget."""
    subprocess.Popen(["hyprctl", "dispatch", arg],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def dispatch_wait(arg: str) -> None:
    """Returns once Hyprland has done it, e.g. to name the workspace we land on."""
    subprocess.run(["hyprctl", "dispatch", arg],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


_in_order: queue.SimpleQueue = queue.SimpleQueue()


def _run_in_order() -> None:
    while True:
        job = _in_order.get()
        try:
            job()
        except Exception:
            pass


threading.Thread(target=_run_in_order, daemon=True).start()


def later(job) -> None:
    """Runs job() on a thread of its own, in order with the other jobs:
    the caller never waits on hyprctl."""
    _in_order.put(job)


def next_workspace(way: int) -> int | None:
    """The workspace one step `way` (+1 / -1) from the focused one on its
    monitor: the next one with windows, or past the last of those one new
    empty workspace, and no further. None when there is nowhere to go."""
    here = hyprctl_json("activeworkspace") or {}
    cur, mon = here.get("id"), here.get("monitor")
    if cur is None:
        return None
    spaces = [w for w in hyprctl_json("workspaces") or [] if w["id"] > 0]
    busy = sorted(w["id"] for w in spaces if w["monitor"] == mon and w["windows"])
    ahead = [i for i in busy if (i - cur) * way > 0]
    if ahead:
        return ahead[0] if way > 0 else ahead[-1]
    if way < 0 or not here.get("windows"):
        return None
    # Past the last: the first number nobody uses and no rule keeps on another monitor.
    taken = {w["id"] for w in spaces}
    for rule in hyprctl_json("workspacerules") or []:
        if rule.get("monitor") not in (None, mon) and rule.get("workspaceString", "").isdigit():
            taken.add(int(rule["workspaceString"]))
    new = cur + 1
    while new in taken:
        new += 1
    return new


def workspace_name() -> str:
    return (hyprctl_json("activeworkspace") or {}).get("name", "?")


def active_window() -> dict:
    return hyprctl_json("activewindow") or {}


def mouse_focus_option() -> bool:
    return bool((hyprctl_json(f"getoption {MOUSE_FOCUS}") or {}).get("bool", True))


def set_mouse_focus(on: bool) -> None:
    """Whether moving the pointer onto another monitor focuses it. Without it,
    pointing at an empty monitor leaves focus behind, so the Omarchy menu and
    workspace swipes act on the old one. Some setups turn it off so games
    don't lose focus mid-match; the controller only turns it on while it is
    driving the desktop, and puts the user's value back in game mode."""
    subprocess.run(["hyprctl", "eval",
                    f"hl.config({{ misc = {{ mouse_move_focuses_monitor = {str(on).lower()} }} }})"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


_menu_checked = [0.0, False]    # (time, omarchy menu open?)


def menu_open() -> bool:
    at, is_open = _menu_checked
    now = time.monotonic()
    if now - at < MENU_CACHE:
        return is_open
    is_open = False
    for mon in (hyprctl_json("layers") or {}).values():
        for layers in mon.get("levels", {}).values():
            if any(l.get("namespace") in MENU_LAYERS for l in layers):
                is_open = True
    _menu_checked[:] = [now, is_open]
    return is_open
