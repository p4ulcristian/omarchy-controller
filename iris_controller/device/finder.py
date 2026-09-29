"""Find the controller: a DualSense (its gamepad and touchpad devices, and the
raw HID node the mic button is read from), or else an Xbox pad."""

from __future__ import annotations

import logging
import os

import evdev
from evdev import ecodes as e

from .profiles import is_xbox

log = logging.getLogger("iris-controller")

# The motion sensors are a separate device we leave alone; the touchpad is a
# separate device we use for taps and clicks.
DUALSENSE_NAMES = ("DualSense Wireless Controller", "DualSense Edge Wireless Controller")
TOUCHPAD_SUFFIX = " Touchpad"   # grabbed like the pad: we move the pointer from it ourselves


def is_gamepad(d: evdev.InputDevice) -> bool:
    caps = d.capabilities()
    return e.EV_ABS in caps and e.BTN_SOUTH in caps.get(e.EV_KEY, [])


def same_pad(a: evdev.InputDevice, b: evdev.InputDevice) -> bool:
    """Two devices of one pad (Bluetooth firmware can put Share on a device of its own)."""
    if a.uniq and a.uniq == b.uniq:
        return True
    return bool(a.phys) and a.phys.rsplit("/", 1)[0] == b.phys.rsplit("/", 1)[0]


def find_controller() -> list[evdev.InputDevice]:
    """A DualSense's devices; with none, the first Xbox pad's."""
    found = []
    for path in evdev.list_devices():
        try:
            found.append(evdev.InputDevice(path))
        except OSError:
            continue
    devs = [d for d in found if d.name.removesuffix(TOUCHPAD_SUFFIX) in DUALSENSE_NAMES]
    if not devs:
        pad = next((d for d in found if is_gamepad(d) and is_xbox(d)), None)
        devs = [d for d in found if pad and (d is pad or is_xbox(d) and same_pad(pad, d))]
    for d in found:
        if d not in devs:
            d.close()
    return devs


def split(devs: list[evdev.InputDevice]) -> tuple[evdev.InputDevice | None, evdev.InputDevice | None]:
    """(gamepad, touchpad) among the devices find_controller returned."""
    touch = next((d for d in devs if d.name.endswith(TOUCHPAD_SUFFIX)), None)
    pad = next((d for d in devs if d is not touch and is_gamepad(d)), None)
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
