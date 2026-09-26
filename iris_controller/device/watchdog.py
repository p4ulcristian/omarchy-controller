"""Notice a controller link that hangs without disconnecting, and restart the
USB host controller behind it.

A DualSense streams raw HID reports hundreds of times a second, even lying
untouched. When the USB host controller its Bluetooth adapter (or cable) sits
on wedges, e.g. after a flaky plug-in on a neighbouring port, the reports stop
but nothing reports a disconnect: the pad is still "connected", just silent.
Silence this long means the link is dead."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time

import evdev

log = logging.getLogger("iris-controller")

SILENCE = 3.0               # seconds without a raw report: the link is dead
RESET_EVERY = 60.0          # at most one host controller restart this often
RESET_HELPER = "/usr/local/bin/iris-controller-usb-reset"   # root, see setup/install.sh
PCI_ADDR = re.compile(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]")


def host_controller(dev: evdev.InputDevice) -> str | None:
    """PCI address of the USB host controller the device hangs off, e.g. 0000:02:00.0."""
    parts = os.path.realpath(f"/sys/class/input/{os.path.basename(dev.path)}/device").split("/")
    for prev, part in zip(parts, parts[1:]):
        if re.fullmatch(r"usb\d+", part) and PCI_ADDR.fullmatch(prev):
            return prev
    return None


class Watchdog:
    def __init__(self) -> None:
        self.host: str | None = None
        self.last_report = 0.0
        self.last_reset = -RESET_EVERY

    def attach(self, pad: evdev.InputDevice | None) -> None:
        self.host = host_controller(pad) if pad else None
        self.last_report = time.monotonic()

    def fed(self) -> None:
        self.last_report = time.monotonic()

    def dead(self, now: float) -> bool:
        return now - self.last_report > SILENCE

    def reset_host(self, now: float) -> bool:
        """Restart the USB host controller, if we know it and haven't just done so."""
        if self.host is None or now - self.last_reset < RESET_EVERY:
            return False
        self.last_reset = now
        log.warning("controller silent for %.0fs: restarting USB host controller %s",
                    SILENCE, self.host)
        try:
            subprocess.run(["sudo", "-n", RESET_HELPER, self.host], check=True, timeout=20,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            err = getattr(exc, "stderr", None) or exc
            log.warning("USB reset failed (%s); by hand: sudo %s %s", str(err).strip(),
                        RESET_HELPER, self.host)
            return False
