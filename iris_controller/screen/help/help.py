"""The cheat sheet: the mic button opens it, any button (or the mic again)
closes it. Help.qml next to this file draws the controller and every
binding, grouped, from cheatsheet()."""

from __future__ import annotations

import json
import subprocess

from ...keymap.docs import cheatsheet

PLUGIN = "p4ulcristian.iris-controller-help"


class Help:
    def __init__(self) -> None:
        self.open = False
        self.proc: subprocess.Popen | None = None

    def show(self, show: bool) -> None:
        self.open = show
        if show:
            cmd = ["omarchy-shell", "-q", "shell", "summon", PLUGIN, json.dumps(cheatsheet())]
        else:
            cmd = ["omarchy-shell", "-q", "shell", "hide", PLUGIN]
            if self.proc:
                try:
                    self.proc.wait(timeout=1)   # a quick tap: summon lands first
                except subprocess.TimeoutExpired:
                    pass
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
