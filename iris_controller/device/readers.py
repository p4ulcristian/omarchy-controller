"""Notice other programs reading the controller.

The grab keeps apps off the controller's evdev devices, but not off its raw
HID node: anything using SDL or a browser's gamepad API can open that and see
every press, and some act on them even unfocused (Jellyfin toggled its
fullscreen on L1 and stole focus that way). Nothing can be blocked from here,
since access is per user, so every few seconds a thread looks through /proc
for other processes holding the node open and flashes each new one once.
[readers] ignore = ["steam"] in the config skips programs by name."""

from __future__ import annotations

import logging
import os
import threading
import time

from ..core.config import CONFIG

log = logging.getLogger("iris-controller")

EVERY = 5.0                 # seconds between looks
IGNORE = set(CONFIG.get("readers", {}).get("ignore", []))


def holders(node: str) -> dict[int, str]:
    """Other processes with `node` open: pid -> program name."""
    found = {}
    me = os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
        except OSError:
            continue                            # gone, or not ours to look at
        for fd in fds:
            try:
                if os.readlink(f"/proc/{pid}/fd/{fd}") == node:
                    with open(f"/proc/{pid}/comm") as f:
                        found[int(pid)] = f.read().strip()
                    break
            except OSError:
                continue
    return found


class Readers:
    def __init__(self, m) -> None:
        self.m = m
        self.seen: set[int] = set()             # pids already reported
        threading.Thread(target=self.run, daemon=True, name="readers").start()

    def run(self) -> None:
        while True:
            time.sleep(EVERY)
            try:
                self.look()
            except Exception:
                log.exception("looking for other controller readers")

    def look(self) -> None:
        m = self.m
        fd = m.hid_fd
        if fd is None or not m.grabbed:         # game mode: games may read it
            return
        try:
            node = os.readlink(f"/proc/self/fd/{fd}")
        except OSError:
            return
        found = holders(node)
        self.seen &= set(found)                 # a pid that let go may be reused
        for pid, name in found.items():
            if pid in self.seen or name in IGNORE:
                continue
            self.seen.add(pid)
            log.warning("%s (pid %d) is reading the controller", name, pid)
            m.flash.message(f"{name} is reading the controller")
