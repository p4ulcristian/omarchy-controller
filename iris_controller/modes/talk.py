"""R1: talk. Held = push-to-talk dictation through a Unix socket that takes
"start" and "stop" (omarchy-dictation). Tap, then hold = dictate, and on
release post the transcript to an Iris server instead of typing it; that
needs the socket to also take "stop-return"."""

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
        self.active: str | None = None          # "dictate" or "iris" while R1 is held
        self.r1_down = 0.0                      # when R1 went down
        self.r1_tapped = -1.0                   # when a quick R1 tap ended: a press soon after talks to Iris

    def press(self) -> None:
        now = time.monotonic()
        self.r1_down = now
        if IRIS_URL and now - self.r1_tapped < DOUBLE_TAP_WINDOW:
            self.r1_tapped = -1.0
            self.active = "iris"                 # sent to Iris on release
            dictate("start")
            self.m.flash.show("R1 + R1", "Talk to Iris")
        elif DICTATE_SOCK:
            self.active = "dictate"
            dictate("start")
            self.m.flash.show("R1", "Dictate", plain=True)

    def release(self) -> None:
        active, self.active = self.active, None
        if active == "iris":
            threading.Thread(target=self.send_to_iris, daemon=True).start()
        elif active == "dictate":
            dictate("stop")   # a quick tap is shorter than dictation's minimum: ignored
            if time.monotonic() - self.r1_down < DOUBLE_TAP_WINDOW:
                self.r1_tapped = time.monotonic()

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
