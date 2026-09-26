"""The mic button. The kernel driver drops it, so it is read from the raw HID report."""

from __future__ import annotations

MIC_BIT = 0x04     # third button byte of the raw HID report


class Mic:
    def __init__(self) -> None:
        self.down = False

    def pressed(self, report: bytes) -> bool:
        """True when this report is the mic button going down.
        Bluetooth report 0x31 has it in byte 11, USB report 0x01 in byte 10."""
        if len(report) < 12 or report[0] not in (0x01, 0x31):
            return False
        down = bool(report[11 if report[0] == 0x31 else 10] & MIC_BIT)
        if down == self.down:
            return False
        self.down = down
        return down
