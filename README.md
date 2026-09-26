# omarchy-controller

Use a PlayStation DualSense controller as a mouse and keyboard on
[Omarchy](https://omarchy.org) / Hyprland: move the pointer, scroll, click,
switch windows and workspaces, open the Omarchy menu, all from the couch.
Press the **mic button** for an on-screen cheat sheet of every binding.

The program itself is called **iris-controller**: `iris-controller.service`, `~/.config/iris-controller/`.

When a Steam game goes fullscreen the controller is handed back to the game
automatically, and handed back to the desktop when you leave it.

## What the buttons do

The short version (full list in [docs/KEYMAP.md](docs/KEYMAP.md), or press the mic
button):

| Input | Action |
|---|---|
| Left stick | Move pointer |
| Right stick | Scroll |
| ✕ / ○ / □ / △ | Left click / Escape / Enter / Backspace |
| D-pad | Arrow keys (hold to repeat) |
| Touchpad | Tap: arrow key toward the side you touch (click and hold to repeat), swipe up/down: volume |
| Options | Omarchy menu (D-pad or right stick to move, ✕ or □ to open) |
| L2 + ✕ | Right click (hold = drag) |
| L2 + right stick ←/→ | Previous / next workspace |
| L2 + right stick ↑/↓ | Bigger / smaller text |
| L2 + D-pad ↑/↓ | Volume up / down |
| L2 + D-pad ←/→ | Back / forward (browsers, file managers) |
| L2 + △ / □ / ○ | Close window / copy / paste |
| L2 + R2 | Fullscreen |
| R2 held + left stick | Move the window |
| R2 held + right stick | Resize the window (→/↓ bigger, ←/↑ smaller) |
| R2 held, dragging + right stick ←/→ | Take the window to the previous / next workspace |
| R2 + △ | Refresh (Ctrl + R) |
| R2 + □ | Space (hold to repeat) |
| R2 + ○ | On-screen keyboard: D-pad moves, ✕ types (hold to repeat), □ space, △ backspace, L1 held shift, ○ closes |
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
~/.local/share/omarchy-controller/setup/install.sh
```

The installer puts a launcher at `~/.local/bin/iris-controller`, links the
cheat sheet, the flash and the on-screen keyboard into
`~/.config/omarchy/plugins/`, enables them in
`~/.config/omarchy/shell.json`, and starts a systemd user service. Run it
again after pulling updates.

Logs: `journalctl --user -u iris-controller -f`

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

Optional. Copy [setup/config.example.toml](setup/config.example.toml) to
`~/.config/iris-controller/config.toml`. It can:

- make **R1** push-to-talk dictation with
  [omarchy-dictation](https://github.com/p4ulcristian/omarchy-dictation) (or any daemon whose Unix
  socket accepts `start` / `stop`),
- make **R1 tap, then hold** talk to an Iris server: dictate, and on release
  the transcript is posted to Iris instead of typed,
- rename actions in the cheat sheet, e.g. if you rebound Super+Enter.
- turn off the flash: what each press did appears in the middle of the
  screen (the buttons pop in, then what they did: "L2 + □ ▸ Copy",
  "□ ▸ Enter"). Combos and plain presses have separate switches.
- add your own buttons: `[[bind]]` entries for L1 + a button, PS + a button, R2 + a D-pad direction,
  or a double tap on L2/R2, that run a command or send keys. They appear in the
  cheat sheet too.

The bindings themselves are the tables in
`iris_controller/keymap/bindings.py`. After changing them, regenerate the keymap:

```sh
XDG_CONFIG_HOME=/nonexistent python3 -m iris_controller.core.main --keymap > docs/KEYMAP.md
```

## How it works

One Python process reads the controller through evdev, grabs it, and writes
to a virtual mouse and keyboard through uinput. Window actions go through
`hyprctl`. The kernel's DualSense driver does not report the mic button, so
it is read from the raw HID report instead.

A press travels device → core → output, and the keymap decides what it means:

```
iris_controller/
├── core/           the brain: mapper (buttons, combos), sticks, the main
│                   loop (main.py) and reading config.toml (config.py)
├── device/         the controller: finder, touchpad, mic button
├── keymap/         what each button does: bindings, your [[bind]]s, the keymap doc
├── modes/          window (R2 held), game, talk (R1)
├── output/         virtual mouse + keyboard, Hyprland commands
└── screen/         what you see, each an Omarchy shell plugin:
    ├── flash/      what a press just did, mid-screen
    ├── help/       the cheat sheet (mic button)
    └── keyboard/   the on-screen keyboard
setup/              install.sh, the systemd service, config.example.toml
docs/               KEYMAP.md
```

## Uninstall

```sh
systemctl --user disable --now iris-controller
rm ~/.local/bin/iris-controller ~/.config/systemd/user/iris-controller.service
rm ~/.config/omarchy/plugins/p4ulcristian.iris-controller-{help,flash,keyboard}
```

Then remove those three from the `plugins` list in
`~/.config/omarchy/shell.json`.

## License

MIT
