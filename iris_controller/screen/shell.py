"""Calls to the Omarchy shell, one at a time on a thread of their own, so the
controller never waits on them and each plugin sees its calls in order."""

from __future__ import annotations

import subprocess
import threading


class Shell:
    def __init__(self) -> None:
        self.calls = threading.Condition()
        self.pending: dict[str, list[str]] = {}   # per plugin, the call still to send
        threading.Thread(target=self.sender, daemon=True).start()

    def send(self, plugin: str, args: list[str]) -> None:
        # Per plugin only the newest pending call matters, except that a state
        # update never replaces a summon / hide.
        with self.calls:
            old = self.pending.get(plugin)
            if args[0] != "call" or not old or old[0] == "call":
                self.pending[plugin] = args
            self.calls.notify()

    def sender(self) -> None:
        while True:
            with self.calls:
                while not self.pending:
                    self.calls.wait()
                plugin = next(iter(self.pending))
                args = self.pending.pop(plugin)
            subprocess.run(["omarchy-shell", "-q", "shell", *args],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
