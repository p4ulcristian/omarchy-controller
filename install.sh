#!/usr/bin/env bash
# Install iris-controller for the current user. Safe to run again.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
SRC=$PWD
PLUGIN=p4ulcristian.iris-controller-help
KEYBOARD=p4ulcristian.iris-controller-keyboard
HUD=p4ulcristian.iris-controller-hud

python3 -c "import evdev" 2>/dev/null || {
  echo "python-evdev is missing: sudo pacman -S python-evdev" >&2; exit 1; }
[ -e /usr/lib/udev/rules.d/60-steam-input.rules ] || {
  echo "Controller permissions missing: sudo pacman -S steam-devices, then replug the pad" >&2; exit 1; }

chmod +x iris_controller.py
mkdir -p ~/.local/bin ~/.config/omarchy/plugins ~/.config/systemd/user
ln -sfn "$SRC/iris_controller.py" ~/.local/bin/iris-controller
ln -sfn "$SRC/overlay" ~/.config/omarchy/plugins/$PLUGIN
ln -sfn "$SRC/keyboard" ~/.config/omarchy/plugins/$KEYBOARD
ln -sfn "$SRC/hud" ~/.config/omarchy/plugins/$HUD

# Enable the cheat sheet, keyboard and combo HUD plugins in the Omarchy shell.
SHELL_JSON=~/.config/omarchy/shell.json
if [ -f "$SHELL_JSON" ]; then
  python3 - "$SHELL_JSON" "$PLUGIN" "$KEYBOARD" "$HUD" <<'PY'
import json, sys
path, *wanted = sys.argv[1:]
with open(path) as f:
    cfg = json.load(f)
plugins = cfg.setdefault("plugins", [])
added = [w for w in wanted if not any(p.get("id") == w for p in plugins)]
if added:
    plugins.extend({"id": w} for w in added)
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print("enabled", ", ".join(added), "in", path)
PY
  # Make the running shell pick up the plugin now, not at next login.
  command -v omarchy-shell >/dev/null && omarchy-shell -q shell rescanPlugins || true
fi

cp systemd/iris-controller.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now iris-controller
systemctl --user restart iris-controller
echo "Installed. Logs: journalctl --user -u iris-controller -f"
