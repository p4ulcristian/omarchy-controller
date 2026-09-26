# omarchy-controller

Use a PlayStation DualSense controller as a mouse and keyboard on
[Omarchy](https://omarchy.org) / Hyprland: move the pointer, scroll, click,
switch windows and workspaces, open the Omarchy menu, all from the couch.
Press the **mic button** for an on-screen cheat sheet of every binding.

When a Steam game goes fullscreen the controller is handed back to the game
automatically, and handed back to the desktop when you leave it.

## What the buttons do

The short version (full list in [KEYMAP.md](KEYMAP.md), or press the mic
button):

| Input | Action |
|---|---|
| Left stick | Move pointer (click and hold right stick for precision) |
| Right stick | Scroll |
| ✕ / ○ / □ / △ | Left click / Escape / Enter / Backspace |
| D-pad | Focus the window in that direction |
| Touchpad | Tap: arrow key toward the side you touch (click and hold to repeat), swipe up/down: volume |
| Options | Omarchy menu (D-pad or right stick to move, ✕ or □ to open) |
| Create | Close window |
| L1 + right stick ←/→ | Previous / next workspace |
| L1 + right stick ↑/↓ | Bigger / smaller text |
| L1 + ✕ / △ | Terminal / close window |
| L2 held | Move the window with the left stick; right stick ←/→ takes it to the previous / next workspace |
| L2 + R2 | Fullscreen |
| Hold PS 1 s | Game mode on/off (release / retake the controller) |
| Mic | Show / hide the cheat sheet |

## Requirements

- Omarchy (Hyprland with the Omarchy shell). The cheat sheet is an Omarchy
  shell plugin; everything else only needs Hyprland.
- A DualSense or DualSense Edge, over USB or Bluetooth.
- `python-evdev`
- `steam-devices`, for the udev rules that let your user read the controller
  and create the virtual mouse/keyboard. Already there if Steam is installed.

```sh
sudo pacman -S python-evdev steam-devices
```

## Install

```sh
git clone https://github.com/p4ulcristian/omarchy-controller ~/.local/share/omarchy-controller
~/.local/share/omarchy-controller/install.sh
```

The installer links the script to `~/.local/bin/omarchy-controller`, links the
cheat sheet into `~/.config/omarchy/plugins/`, enables it in
`~/.config/omarchy/shell.json`, and starts a systemd user service. Run it
again after pulling updates.

Logs: `journalctl --user -u omarchy-controller -f`

## Game mode

While it runs, the mapper grabs the controller so its buttons don't also reach
other apps. That would hide it from games, so:

- It lets go automatically when the focused window is fullscreen and is a
  Steam game (`steam_app_*`) or gamescope.
- Holding the PS button for one second toggles it by hand, for anything else.

While it drives the desktop it also turns on Hyprland's
`misc:mouse_move_focuses_monitor`, so pointing at another monitor focuses it
and the Omarchy menu opens where the pointer is. In game mode, and when it
stops, your own value is put back (some setups turn it off so a fullscreen
game can't lose focus to a neighbouring monitor).

## Configuration

Optional. Copy [config.example.toml](config.example.toml) to
`~/.config/omarchy-controller/config.toml`. It can:

- make **R1** push-to-talk dictation with
  [omarchy-dictation](https://github.com/p4ulcristian/omarchy-dictation) (or any daemon whose Unix
  socket accepts `start` / `stop`),
- make **R2** dictate and send the text to an Iris server,
- rename actions in the cheat sheet, e.g. if you rebound Super+Enter.

The bindings themselves are the tables at the top of `omarchy_controller.py`.
After changing them, regenerate the keymap:

```sh
XDG_CONFIG_HOME=/nonexistent python3 omarchy_controller.py --keymap > KEYMAP.md
```

## How it works

One Python process reads the controller through evdev, grabs it, and writes
to a virtual mouse and keyboard through uinput. Window actions go through
`hyprctl`. The kernel's DualSense driver does not report the mic button, so
it is read from the raw HID report instead.

## Uninstall

```sh
systemctl --user disable --now omarchy-controller
rm ~/.local/bin/omarchy-controller ~/.config/systemd/user/omarchy-controller.service
rm ~/.config/omarchy/plugins/p4ulcristian.controller-help
```

Then remove `p4ulcristian.controller-help` from the `plugins` list in
`~/.config/omarchy/shell.json`.

## License

MIT
