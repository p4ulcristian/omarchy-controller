#!/usr/bin/env bash
# Install omarchy-controller for the current user. Safe to run again.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
SRC=$PWD
PLUGIN=p4ulcristian.controller-help

python3 -c "import evdev" 2>/dev/null || {
  echo "python-evdev is missing: sudo pacman -S python-evdev" >&2; exit 1; }
[ -e /usr/lib/udev/rules.d/60-steam-input.rules ] || {
  echo "Controller permissions missing: sudo pacman -S steam-devices, then replug the pad" >&2; exit 1; }

chmod +x omarchy_controller.py
mkdir -p ~/.local/bin ~/.config/omarchy/plugins ~/.config/systemd/user
ln -sfn "$SRC/omarchy_controller.py" ~/.local/bin/omarchy-controller
ln -sfn "$SRC/overlay" ~/.config/omarchy/plugins/$PLUGIN

# Enable the cheat sheet plugin in the Omarchy shell.
SHELL_JSON=~/.config/omarchy/shell.json
if [ -f "$SHELL_JSON" ]; then
  python3 - "$SHELL_JSON" "$PLUGIN" <<'PY'
import json, sys
path, plugin = sys.argv[1:]
with open(path) as f:
    cfg = json.load(f)
plugins = cfg.setdefault("plugins", [])
if not any(p.get("id") == plugin for p in plugins):
    plugins.append({"id": plugin})
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print("enabled the cheat sheet in", path)
PY
  # Make the running shell pick up the plugin now, not at next login.
  command -v omarchy-shell >/dev/null && omarchy-shell -q shell rescanPlugins || true
fi

cp systemd/omarchy-controller.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now omarchy-controller
systemctl --user restart omarchy-controller
echo "Installed. Logs: journalctl --user -u omarchy-controller -f"
