"""Talk. R1 held = push-to-talk dictation through a Unix socket that takes
"start" and "stop" (iris-dictation)."""

from __future__ import annotations

import logging
import os
import socket

from ..core.config import CONFIG

log = logging.getLogger("iris-controller")

DICTATE_SOCK = os.path.expanduser(CONFIG.get("dictate", {}).get("socket", "")) or None


def dictate(verb: str) -> None:
    if not DICTATE_SOCK:
        return
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(DICTATE_SOCK)
        s.sendall(verb.encode())
        s.shutdown(socket.SHUT_WR)
        s.recv(64)
        s.close()
    except Exception as exc:
        log.warning("dictate %s failed: %s", verb, exc)


class Talk:
    def __init__(self, m) -> None:
        self.m = m
        self.active = False                     # R1 held, dictating

    def press(self) -> None:
        if DICTATE_SOCK and not self.active:
            self.active = True
            dictate("start")
            self.m.flash.show("R1", "Dictate", plain=True)

    def release(self) -> None:
        self.stop()

    def stop(self) -> None:
        if self.active:
            self.active = False
            dictate("stop")
