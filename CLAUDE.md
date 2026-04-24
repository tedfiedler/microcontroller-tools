# Project: microcontroller tools

A set of CLI tools for working with microcontrollers. All four originally-
planned tools are implemented and exposed through a single `esp32` console
script:

1. `esp32 discover` — list devices connected via USB (VID/PID fingerprinted)
2. `esp32 flash`    — flash MicroPython firmware onto a device
3. `esp32 push` / `pull` / `ls` — move code files to/from the device
4. `esp32 wifi`     — connect the device's Wi-Fi, optionally with a static IP

## Architecture
1. python 3.14, managed with `uv` (`uv sync --extra dev`, `uv run esp32 ...`)
2. Tools are command-line; one `esp32` entry point with subcommands
3. Third-party tooling wrapped as subprocesses:
   - `esptool` (pypi dep) — generic ESP32 flashing
   - `dfu-util` (brew install) — Arduino Nano ESP32 flashing
   - `mpremote` (pypi dep) — push/pull/ls and on-device exec for `wifi`

## Code conventions
1. Use doc strings and well document classes, methods, and functions
2. use dataclasses for modeling if needed
3. strict typing — `mypy --strict esp32/` must pass
4. follow pep standards — `ruff check esp32/` must pass

## Project conventions
1. Keep code in device-family directories (`esp32/`). The original spec said
   `arduino-nano-esp32`, but we went family-level because the tools span
   multiple ESP32 variants. Drop to per-board dirs only if behavior diverges.
2. One module per tool under `esp32/`: `discover.py`, `flash.py`, `code.py`
   (push/pull/ls), `wifi.py`. Shared mpremote / port-resolution helpers live
   in `_mpy.py`. USB fingerprint table in `usb_ids.py`, board profiles in
   `boards.py`, firmware URL resolution in `firmware.py`.
3. Run `mypy --strict esp32/` and `ruff check esp32/` before committing.

## Things to always do
1. always commit code
2. if there is a better way to do something I have suggested, please suggest that

## Things to never do
1. never commit secrets

## Gotchas (learned the hard way — see memory/ for details)
- **Arduino Nano ESP32 flashing is unusual.** Do NOT use esptool or
  micropython.org's `.bin`/`.uf2` — they're full-flash images that conflict
  with the factory Arduino DFU bootloader. Use `dfu-util` + Arduino's
  `.app-bin` from `downloads.arduino.cc/micropython/index.json`. See
  `memory/project_nano_esp32_flash_recipe.md`.
- **Wi-Fi connect needs a reset dance.** ESP32 MicroPython's STA interface
  throws "Wifi Internal State Error" if you call `wlan.connect()` after
  another session left it active. Always `disconnect()` + `active(False→True)`
  before connecting. See `memory/project_esp32_wifi_reset.md`.
- **mpremote `fs -r cp` has a flat-dir bug.** When the source directory
  has zero subdirectories and the destination doesn't exist yet, mpremote's
  recursive walker falls through to a non-recursive cp that errors out.
  `code.py` detects and works around this — don't "simplify" it away.
