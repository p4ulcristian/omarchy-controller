"""Talk. R1 held = push-to-talk dictation through a Unix socket that takes
"start" and "stop" (iris-dictation). L1 held (or R1 tapped, then held) = the
same, but on release the transcript goes to an Iris server instead of being
typed (the socket must also take "stop-return"). Those recordings are tagged
"iris" ("start iris"), so Iris's card on the desktop (the p4ulcristian.iris-desk
shell plugin, if it's there) shows them instead of the dictation pill. L1
tapped opens or closes her card."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
import time
import urllib.request

from ..core.config import CONFIG
from ..keymap.bindings import DOUBLE_TAP_WINDOW

log = logging.getLogger("iris-controller")

DICTATE_SOCK = os.path.expanduser(CONFIG.get("dictate", {}).get("socket", "")) or None
IRIS = CONFIG.get("iris", {})
IRIS_URL = IRIS.get("url") if DICTATE_SOCK else None


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


def stop_return() -> str:
    """Stop dictation and get the transcript back instead of it being typed.
    Blocks while it transcribes. Empty = nothing heard, or it failed."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(65)
        s.connect(DICTATE_SOCK)
        s.sendall(b"stop-return")
        s.shutdown(socket.SHUT_WR)
        text = s.recv(65536).decode().strip()
        s.close()
        return text
    except Exception as exc:
        log.warning("dictate stop-return failed: %s", exc)
        return ""


def iris_secret() -> str:
    """The shared secret, read from a KEY=value file so it never sits in the config."""
    path = IRIS.get("secret_file")
    if not path:
        return ""
    name = IRIS.get("secret_key", "IRIS_INTERNAL_SECRET")
    try:
        with open(os.path.expanduser(path)) as f:
            for line in f:
                key, _, value = line.strip().partition("=")
                if key.strip() == name:
                    return value.strip().strip("'\"")
    except OSError as exc:
        log.warning("iris secret: %s", exc)
    return ""


IRIS_CARD = "p4ulcristian.iris-desk"


class Talk:
    def __init__(self, m) -> None:
        self.m = m
        self.active: str | None = None   # "dictate" or "iris" while R1 is held, "l1" while L1 is
        self.tapped = -1.0               # when a quick R1 tap ended: a press soon after talks to Iris
        self.down = 0.0

    def l1(self, down: bool) -> None:
        """L1 held: talk to Iris. A quick tap is shorter than dictation's minimum,
        so its stop types nothing: it opens or closes her card instead."""
        if not IRIS_URL:
            return
        if down:
            if self.active or self.m.compose.recording:
                return
            self.down = time.monotonic()
            self.active = "l1"
            dictate("start iris")               # tagged: her card listens, not the dictation pill
            return
        if self.active != "l1":
            return
        self.active = None
        if time.monotonic() - self.down < DOUBLE_TAP_WINDOW:
            dictate("stop")
            self.m.shell.send(IRIS_CARD, ["call", IRIS_CARD, "tapped", ""])
        else:
            threading.Thread(target=self.send_to_iris, daemon=True).start()

    def press(self) -> None:
        if not DICTATE_SOCK or self.active or self.m.compose.recording:
            return
        self.down = time.monotonic()
        if IRIS_URL and self.down - self.tapped < DOUBLE_TAP_WINDOW:
            self.active = "iris"
        else:
            self.active = "dictate"
            self.m.flash.show("R1", "Dictate", plain=True)
        self.tapped = -1.0
        dictate("start iris" if self.active == "iris" else "start")

    def release(self) -> None:
        if self.active in (None, "l1"):    # an L1 talk ends on L1
            return
        quick = time.monotonic() - self.down < DOUBLE_TAP_WINDOW
        was, self.active = self.active, None
        # A quick tap is shorter than dictation's minimum, so its stop types nothing.
        if was == "iris" and not quick:
            threading.Thread(target=self.send_to_iris, daemon=True).start()
        else:
            dictate("stop")
        # Only a quick plain tap can start the tap-then-hold.
        self.tapped = time.monotonic() if was == "dictate" and quick else -1.0

    def stop(self) -> None:
        if self.active:
            self.active = None
            dictate("stop")

    def send_to_iris(self) -> None:
        """Runs in a thread: stop dictation, get the transcript, post it to Iris."""
        text = stop_return()
        if not text:
            return
        req = urllib.request.Request(
            IRIS_URL, data=json.dumps({"message": text, "source": "desktop"}).encode(),
            headers={"Content-Type": "application/json", "X-Iris-Secret": iris_secret()})
        try:
            urllib.request.urlopen(req, timeout=10).read()   # her card shows it
        except Exception as exc:
            log.warning("iris send failed: %s", exc)
            subprocess.run(["wl-copy", text], check=False)
            self.m.flash.message("Iris didn't answer: message copied")
