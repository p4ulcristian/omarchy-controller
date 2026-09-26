"""Talk. R1 held = push-to-talk dictation through a Unix socket that takes
"start" and "stop" (iris-dictation). R1 tapped, then held = the same, but on
release the transcript goes to an Iris server instead of being typed (the
socket must also take "stop-return")."""

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


def short(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


class Talk:
    def __init__(self, m) -> None:
        self.m = m
        self.active: str | None = None   # "dictate" or "iris" while R1 is held
        self.tapped = -1.0               # when a quick R1 tap ended: a press soon after talks to Iris
        self.down = 0.0

    def press(self) -> None:
        if not DICTATE_SOCK or self.active:
            return
        self.down = time.monotonic()
        if IRIS_URL and self.down - self.tapped < DOUBLE_TAP_WINDOW:
            self.active = "iris"
            self.m.flash.show("R1 + R1", "Talk to Iris", plain=True)
        else:
            self.active = "dictate"
            self.m.flash.show("R1", "Dictate", plain=True)
        self.tapped = -1.0
        dictate("start")

    def release(self) -> None:
        if not self.active:
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
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(65)
            s.connect(DICTATE_SOCK)
            s.sendall(b"stop-return")
            s.shutdown(socket.SHUT_WR)
            text = s.recv(65536).decode().strip()
            s.close()
        except Exception as exc:
            log.warning("dictate stop-return failed: %s", exc)
            return
        if not text:
            return
        req = urllib.request.Request(
            IRIS_URL, data=json.dumps({"message": text, "source": "desktop"}).encode(),
            headers={"Content-Type": "application/json", "X-Iris-Secret": iris_secret()})
        try:
            urllib.request.urlopen(req, timeout=10).read()
            self.m.flash.message(f"To Iris: {short(text)}")
        except Exception as exc:
            log.warning("iris send failed: %s", exc)
            subprocess.run(["wl-copy", text], check=False)
            self.m.flash.message("Iris didn't answer: message copied")
