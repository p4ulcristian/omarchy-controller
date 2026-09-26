"""The virtual mouse + keyboard ("iris-controller") every key and click goes out through."""

from __future__ import annotations

import logging
import subprocess

from evdev import UInput, ecodes as e

from ..keymap.bindings import Bind

log = logging.getLogger("iris-controller")


class VirtualInput:
    def __init__(self, keys: list[int]) -> None:
        self.ui = UInput({
            e.EV_KEY: keys,
            e.EV_REL: [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL,
                       e.REL_WHEEL_HI_RES, e.REL_HWHEEL_HI_RES],
        }, name="iris-controller")
        self.down: set[int] = set()                 # output keys currently down
        self.owners: dict[object, list[int]] = {}   # input -> output keys held for it

    def key(self, code: int, down: bool) -> None:
        if down == (code in self.down):
            return
        self.ui.write(e.EV_KEY, code, 1 if down else 0)
        self.ui.syn()
        (self.down.add if down else self.down.discard)(code)

    def tap(self, combo: list[int]) -> None:
        for k in combo:
            self.ui.write(e.EV_KEY, k, 1)
            self.ui.syn()
        for k in reversed(combo):
            self.ui.write(e.EV_KEY, k, 0)
            self.ui.syn()

    def fire(self, bind: Bind) -> None:
        """A one-shot action: its keys, or its command (detached, output dropped)."""
        if bind.run:
            log.info("run: %s", bind.run)
            subprocess.Popen(["sh", "-c", bind.run], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        else:
            self.tap(bind.keys)

    def hold(self, owner, combo: list[int]) -> None:
        """Keys held down for an input until unhold(owner), so they autorepeat and drag."""
        self.owners[owner] = combo
        for k in combo:
            self.key(k, True)

    def unhold(self, owner) -> None:
        for k in reversed(self.owners.pop(owner, [])):
            self.key(k, False)

    def holding(self, owner) -> bool:
        return owner in self.owners

    def release_all(self) -> None:
        for owner in list(self.owners):
            self.unhold(owner)
        for k in list(self.down):
            self.key(k, False)

    def rel(self, code: int, n: int) -> None:
        """Pointer or wheel movement; syn() sends it."""
        self.ui.write(e.EV_REL, code, n)

    def syn(self) -> None:
        self.ui.syn()

    def close(self) -> None:
        self.ui.close()
