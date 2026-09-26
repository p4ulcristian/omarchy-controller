"""Game mode: let go of the controller so games see it. Automatic while a
Steam game or gamescope is fullscreen; holding the PS button toggles it by hand.
A tap on PS opens the app launcher instead."""

from __future__ import annotations

import logging
import time

from ..output import hyprland

log = logging.getLogger("iris-controller")

GAME_TOGGLE_HOLD = 1.0      # hold the PS button this long to toggle game mode
GAME_POLL = 1.0             # seconds between checks of the focused window
GAME_CLASSES = ("steam_app_", "gamescope")


class GameMode:
    def __init__(self, m) -> None:
        self.m = m
        self.manual = False                     # toggled with the PS button
        self.auto = False                       # a game is fullscreen
        self.ps_since: float | None = None      # PS button press time
        self.ps_used = False                    # this PS hold already did something

    @property
    def on(self) -> bool:
        return self.manual or self.auto

    def ps(self, down: bool) -> None:
        # The PS button is a layer for PS_COMBOS; held alone it toggles game
        # mode (see tick). A tap on its own opens / closes the app launcher,
        # on release, once it can't be a hold any more.
        if down:
            self.ps_since, self.ps_used = time.monotonic(), False
            return
        tapped = self.ps_since is not None and not self.ps_used
        self.ps_since = None
        if tapped and not self.on:
            self.m.launcher.toggle(not self.m.launcher.open)

    @property
    def ps_held(self) -> bool:
        return self.ps_since is not None

    def tick(self) -> None:
        if self.ps_since is None or self.ps_used:
            return
        if time.monotonic() - self.ps_since < GAME_TOGGLE_HOLD:
            return
        self.ps_used = True
        self.manual = not self.manual
        if not self.manual:
            self.auto = False
        self.m.flash.message("Game mode: controller released" if self.manual else "Desktop mode",
                             ["PS"])
        self.m.update_grab()

    def poll(self) -> None:
        if self.manual:
            return
        w = hyprland.active_window()
        cls = (w.get("class") or "").lower()
        is_game = bool(w.get("fullscreen")) and cls.startswith(GAME_CLASSES)
        if is_game != self.auto:
            self.auto = is_game
            log.info("auto game mode %s (%s)", "on" if is_game else "off", cls)
            self.m.flash.message("Game detected: controller released" if is_game else "Desktop mode")
            self.m.update_grab()
