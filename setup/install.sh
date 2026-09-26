#!/usr/bin/env bash
# Install iris-controller for the current user. Safe to run again.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
SRC=$PWD
SCREEN=$SRC/iris_controller/screen
PLUGIN=p4ulcristian.iris-controller-help
KEYBOARD=p4ulcristian.iris-controller-keyboard
LAUNCHER=p4ulcristian.iris-controller-launcher
FLASH=p4ulcristian.iris-controller-flash
GUIDE=p4ulcristian.iris-controller-guide
OLD=p4ulcristian.iris-controller-hud   # the flash's old name

python3 -c "import evdev" 2>/dev/null || {
  echo "python-evdev is missing: sudo pacman -S python-evdev" >&2; exit 1; }
[ -e /usr/lib/udev/rules.d/60-steam-input.rules ] || {
  echo "Controller permissions missing: sudo pacman -S steam-devices, then replug the pad" >&2; exit 1; }

mkdir -p ~/.local/bin ~/.config/omarchy/plugins ~/.config/systemd/user
BIN=~/.local/bin/iris-controller
rm -f "$BIN"   # was a symlink to the old single script
cat > "$BIN" <<EOF
#!/bin/sh
PYTHONPATH="$SRC" exec python3 -m iris_controller.core.main "\$@"
EOF
chmod +x "$BIN"
ln -sfn "$SCREEN/help" ~/.config/omarchy/plugins/$PLUGIN
ln -sfn "$SCREEN/keyboard" ~/.config/omarchy/plugins/$KEYBOARD
ln -sfn "$SCREEN/launcher" ~/.config/omarchy/plugins/$LAUNCHER
ln -sfn "$SCREEN/flash" ~/.config/omarchy/plugins/$FLASH
ln -sfn "$SCREEN/guide" ~/.config/omarchy/plugins/$GUIDE
rm -f ~/.config/omarchy/plugins/$OLD

# Enable the cheat sheet, keyboard, launcher, flash and guide plugins in the Omarchy shell.
SHELL_JSON=~/.config/omarchy/shell.json
if [ -f "$SHELL_JSON" ]; then
  python3 - "$SHELL_JSON" "$OLD" "$PLUGIN" "$KEYBOARD" "$LAUNCHER" "$FLASH" "$GUIDE" <<'PY'
import json, sys
path, old, *wanted = sys.argv[1:]
with open(path) as f:
    cfg = json.load(f)
plugins = cfg.setdefault("plugins", [])
kept = [p for p in plugins if p.get("id") != old]
added = [w for w in wanted if not any(p.get("id") == w for p in kept)]
if added or len(kept) != len(plugins):
    plugins[:] = kept + [{"id": w} for w in added]
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    if added:
        print("enabled", ", ".join(added), "in", path)
PY
  # Make the running shell pick up the plugin now, not at next login.
  command -v omarchy-shell >/dev/null && omarchy-shell -q shell rescanPlugins || true
fi

cp setup/iris-controller.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now iris-controller
systemctl --user restart iris-controller
echo "Installed. Logs: journalctl --user -u iris-controller -f"
