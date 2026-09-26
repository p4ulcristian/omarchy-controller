"""Talking to Hyprland through hyprctl: workspaces, windows, what is open."""

from __future__ import annotations

import json
import subprocess
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
