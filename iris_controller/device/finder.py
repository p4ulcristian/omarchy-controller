"""Find the DualSense: its gamepad and touchpad devices, and the raw HID node
the mic button is read from."""

from __future__ import annotations

import logging
import os

import evdev
from evdev import ecodes as e

log = logging.getLogger("iris-controller")

# The motion sensors are a separate device we leave alone; the touchpad is a
# separate device we use for taps and clicks.
DUALSENSE_NAMES = ("DualSense Wireless Controller", "DualSense Edge Wireless Controller")
TOUCHPAD_SUFFIX = " Touchpad"   # grabbed like the pad: tap pad, not a pointer


def find_controller() -> list[evdev.InputDevice]:
    devs = []
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except OSError:
            continue
        if d.name.removesuffix(TOUCHPAD_SUFFIX) in DUALSENSE_NAMES:
            devs.append(d)
        else:
            d.close()
    return devs


def split(devs: list[evdev.InputDevice]) -> tuple[evdev.InputDevice | None, evdev.InputDevice | None]:
    """(gamepad, touchpad) among the devices find_controller returned."""
    touch = next((d for d in devs if d.name.endswith(TOUCHPAD_SUFFIX)), None)
    pad = next((d for d in devs if d is not touch and e.EV_ABS in d.capabilities()), None)
    return pad, touch


def find_hidraw(dev: evdev.InputDevice) -> int | None:
    """Open the raw HID node behind an evdev device (non-blocking), if we may read it."""
    hid = os.path.realpath(f"/sys/class/input/{os.path.basename(dev.path)}/device/device")
    try:
        name = os.listdir(os.path.join(hid, "hidraw"))[0]
        return os.open(f"/dev/{name}", os.O_RDONLY | os.O_NONBLOCK)
    except (OSError, IndexError) as exc:
        log.warning("no raw HID access for %s: %s", dev.name, exc)
        return None
