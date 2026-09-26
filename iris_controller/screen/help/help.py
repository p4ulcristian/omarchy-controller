"""The cheat sheet, toggled by the mic button. Help.qml next to this file
draws the controller with every binding from keymap()."""

from __future__ import annotations

import json
import subprocess

from ...keymap.docs import keymap

PLUGIN = "p4ulcristian.iris-controller-help"


class Help:
    def __init__(self) -> None:
        self.open = False
        self.proc: subprocess.Popen | None = None

    def show(self, show: bool) -> None:
        self.open = show
        if show:
            cmd = ["omarchy-shell", "-q", "shell", "summon", PLUGIN, json.dumps(keymap())]
        else:
            cmd = ["omarchy-shell", "-q", "shell", "hide", PLUGIN]
            if self.proc:
                try:
                    self.proc.wait(timeout=1)   # a quick tap: summon lands first
                except subprocess.TimeoutExpired:
                    pass
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
