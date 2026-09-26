"""Optional settings from ~/.config/iris-controller/config.toml; see
setup/config.example.toml. Each part reads its own section from CONFIG."""

from __future__ import annotations

import logging
import os
import tomllib

log = logging.getLogger("iris-controller")

CONFIG_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "iris-controller", "config.toml",
)


def load_config() -> dict:
    """Missing file = defaults."""
    try:
        with open(CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("config %s ignored: %s", CONFIG_PATH, exc)
        return {}


CONFIG = load_config()
# Rename actions in the cheat sheet and the flash, e.g. "Close window" = "Quit".
LABELS: dict[str, str] = CONFIG.get("labels", {})
