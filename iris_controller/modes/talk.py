"""Talk. R1 held = push-to-talk dictation through a Unix socket that takes
"start" and "stop" (omarchy-dictation); R1 tapped twice = the on-screen
keyboard opens / closes. L1 held = dictate, and on release post the
transcript to an Iris server instead of typing it (the socket must also take
"stop-return"); L1 tapped twice = open Iris ([iris] open)."""

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
from evdev import ecodes as e

from ..keymap.bindings import DOUBLE_TAP_WINDOW, Bind

log = logging.getLogger("iris-controller")

DICTATE_SOCK = os.path.expanduser(CONFIG.get("dictate", {}).get("socket", "")) or None
IRIS = CONFIG.get("iris", {})
IRIS_URL = IRIS.get("url") if DICTATE_SOCK else None
IRIS_OPEN = IRIS.get("open")          # shell command that opens Iris (L1 twice)


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


class Taps:
    """One button's presses: is this release the end of a quick double tap?"""

    def __init__(self) -> None:
        self.down = 0.0          # when it went down
        self.tapped = -1.0       # when a quick tap ended: a press soon after is a second tap
        self.second = False      # this press is that second tap

    def press(self) -> None:
        self.down = time.monotonic()
        self.second = self.down - self.tapped < DOUBLE_TAP_WINDOW

    def release(self) -> tuple[bool, bool]:
        """(quick, double): a short press, and a short second one of a pair."""
        now = time.monotonic()
        quick = now - self.down < DOUBLE_TAP_WINDOW
        second, self.second = self.second, False
        # A quick tap may start a double tap; the second one never starts another.
        self.tapped = now if quick and not second else -1.0
        return quick, quick and second


class Talk:
    def __init__(self, m) -> None:
        self.m = m
        self.active: str | None = None          # "dictate" (R1) or "iris" (L1) while held
        self.taps = {e.BTN_TR: Taps(), e.BTN_TL: Taps()}

    def press(self, code) -> None:
        self.taps[code].press()
        if self.active:
            return
        if code == e.BTN_TR and DICTATE_SOCK:
            self.active = "dictate"
            dictate("start")
            self.m.flash.show("R1", "Dictate", plain=True)
        elif code == e.BTN_TL and IRIS_URL:
            self.active = "iris"                 # sent to Iris on release
            dictate("start")
            self.m.flash.show("L1", "Talk to Iris", plain=True)

    def release(self, code) -> None:
        quick, double = self.taps[code].release()
        mine = self.active == ("dictate" if code == e.BTN_TR else "iris")
        if mine:
            self.active = None
            if quick or code == e.BTN_TR:
                dictate("stop")   # a quick tap is shorter than dictation's minimum: ignored
            else:
                threading.Thread(target=self.send_to_iris, daemon=True).start()
        if double and code == e.BTN_TR:
            kb = self.m.keyboard
            kb.toggle(not kb.open)
            self.m.flash.show("R1 + R1", "Keyboard " + ("on" if kb.open else "off"))
        elif double and IRIS_OPEN:
            self.m.out.fire(Bind([], "Open Iris", IRIS_OPEN))
            self.m.flash.show("L1 + L1", "Open Iris")

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
