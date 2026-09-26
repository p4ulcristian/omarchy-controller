"""Start-up and the main loop: find the controller, read it, tick ~120 times a second."""

from __future__ import annotations

import logging
import os
import selectors
import signal
import sys
import time

from ..device.finder import find_controller
from ..keymap import bindings, user_binds
from ..keymap.docs import keymap_markdown
from ..modes.game import GAME_POLL
from ..output.virtual_input import VirtualInput
from ..screen.keyboard import keyboard
from .mapper import Mapper

log = logging.getLogger("iris-controller")

TICK = 0.008                 # seconds between pointer updates (~120 Hz)
SCAN_EVERY = 2.0             # seconds between looks for a controller while none is attached


def _raise_interrupt(*_) -> None:
    raise KeyboardInterrupt


def main() -> int:
    # systemctl stop sends SIGTERM: exit through the same cleanup as ctrl+c so
    # held keys are released and the user's Hyprland setting is put back.
    signal.signal(signal.SIGTERM, _raise_interrupt)
    user_binds.load_binds()
    if sys.argv[1:] == ["--keymap"]:
        print(keymap_markdown(), end="")
        return 0
    logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    out = VirtualInput(sorted(bindings.output_keys() | keyboard.KEYS))
    m = Mapper(out)
    sel = selectors.DefaultSelector()
    reports = keyboard.PointerReports(sel, m.keyboard.line)
    last_tick = time.monotonic()
    last_game = 0.0
    last_scan = 0.0

    try:
        while True:
            now = time.monotonic()
            if not m.devs and now - last_scan > SCAN_EVERY:
                last_scan = now
                devs = find_controller()
                if devs:
                    m.attach(devs)
                    for d in devs:
                        sel.register(d, selectors.EVENT_READ)
                    if m.hid_fd is not None:
                        sel.register(m.hid_fd, selectors.EVENT_READ)
            if m.devs and now - last_game > GAME_POLL:
                last_game = now
                m.game.poll()

            for key, _ in sel.select(timeout=TICK):
                if reports.ready(key):
                    continue
                dev = key.fileobj
                try:
                    if isinstance(dev, int):
                        m.on_hid(os.read(dev, 128))
                    else:
                        for ev in dev.read():
                            m.handle(ev, dev)
                except BlockingIOError:
                    pass
                except OSError:
                    log.info("controller disconnected")
                    for d in [*m.devs, m.hid_fd]:
                        try:
                            sel.unregister(d)
                        except Exception:
                            pass
                    m.detach()
                    break

            now = time.monotonic()
            m.tick(min(now - last_tick, 0.05))
            last_tick = now
    except KeyboardInterrupt:
        pass
    finally:
        m.release_all()
        m.detach()
        out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
