## Working style

When reviewing code, lead with what works, then identify 2-3 specific
areas for improvement (performance, readability, Pythonic style). Push
back when there's a better approach — don't reflexively agree.

Prioritize security, correctness, reliability, and standards compliance
over novelty or speed. Avoid unsafe practices unless explicitly
requested, and warn clearly when something is risky. If uncertain about
an answer, state the uncertainty and suggest validation steps.

# Project: microcontroller tools

A set of CLI tools for working with microcontrollers. Two device
families supported today, exposed through two console scripts that
share the same subcommand structure:

- **`esp32`** — ESP32-family (classic ESP32, S2, S3, C3, Arduino Nano ESP32).
- **`pico`** — Raspberry Pi Pico-family (RP2040 + RP2350; Pico / Pico W / Pico 2 / Pico 2 W).

Shared subcommands: `discover`, `flash`, `push`, `pull`, `ls`, `wifi`,
`repl`, `info`, `reset`, `mip`, `lint`.

## Architecture
1. python 3.14, managed with `uv` (`uv sync --extra dev`, `uv run esp32 ...` / `uv run pico ...`)
2. Tools are command-line; one entry point per device family with shared subcommands.
3. Third-party tooling wrapped as subprocesses:
   - `esptool` (pypi dep) — generic ESP32 flashing
   - `dfu-util` (brew install) — Arduino Nano ESP32 flashing
   - `picotool` (optional, apt / brew) — Pico flashing fallback when no BOOTSEL mount is available
   - `mpremote` (pypi dep) — push/pull/ls, REPL, on-device exec / probe scripts

## Code conventions
1. Use doc strings and well document classes, methods, and functions
2. use dataclasses for modeling if needed
3. strict typing — `mypy --strict esp32/ common/ pico/` must pass
4. follow pep standards — `ruff check esp32/ common/ pico/` must pass

## Project conventions
1. Three top-level packages:
   - `common/` — chip-agnostic shared modules. Holds the mpremote primitives
     (`_mpy.py`), the FamilyContext dataclass (`family.py`), and the
     subcommand runners that don't depend on which chip is connected
     (`code.py`, `repl.py`, `reset.py`, `mip.py`, `wifi.py`, plus the
     `info` probe + dataclass + formatters in `info.py` and the lint
     AST walker + formatters in `lint.py`).
   - `esp32/` and `pico/` — device-family packages. Each holds its own
     `usb_ids.py`, `boards.py`, `discover.py`, `flash.py`, `firmware.py`,
     `pin_rules.py`, plus thin wrappers (`info.py`, `lint.py`) that
     supply family-specific data to the shared runners, plus a `cli.py`
     that builds a `FamilyContext` and dispatches subcommands.
2. Adding a new chip family means creating a new sibling package next to
   `esp32/` / `pico/` with the same shape, registering its console
   script in `pyproject.toml`, and adding the directory to the
   `packages = [...]` line of `[tool.hatch.build.targets.wheel]`. The
   shared runners under `common/` are reused as-is.
3. Run `mypy --strict esp32/ common/ pico/` and
   `ruff check esp32/ common/ pico/` before committing.

## Things to always do
1. always commit code
2. if there is a better way to do something I have suggested, please suggest that

## Things to never do
1. never commit secrets
2. never introduce unnecessary dependencies
3. never assume permissive environments or broad access by default

## Gotchas (learned the hard way)
- **Arduino Nano ESP32 flashing is unusual.** Do NOT use esptool or
  micropython.org's `.bin`/`.uf2` — they're full-flash images that conflict
  with the factory Arduino DFU bootloader. Use `dfu-util` + Arduino's
  `.app-bin` from `downloads.arduino.cc/micropython/index.json`.
- **Wi-Fi connect needs a reset dance.** ESP32 MicroPython's STA interface
  throws "Wifi Internal State Error" if you call `wlan.connect()` after
  another session left it active. Always `disconnect()` + `active(False→True)`
  before connecting. The same connect script runs on Pico W (cyw43)
  unchanged; reset dance is harmless there.
- **mpremote `fs -r cp` has a flat-dir bug.** When the source directory
  has zero subdirectories and the destination doesn't exist yet, mpremote's
  recursive walker falls through to a non-recursive cp that errors out.
  `common/code.py` detects and works around this — don't "simplify" it away.
- **Pico W ≠ Pico at the BOOTSEL layer.** The BOOTSEL ROM bootloader's
  `INFO_UF2.TXT` exposes chip family (RP2040 / RP2350) but says nothing
  about the cyw43 module's presence. `pico flash` therefore defaults to
  the non-W board slug and prints a reminder to pass `--board RPI_PICO_W`
  (or `RPI_PICO2_W`) for W variants. Don't try to detect W-ness via
  USB-level fields; it isn't there.
- **esptool 5.x changed the chip-id output.** The legacy `Chip is …`
  line was replaced by `Chip type:` and `Detecting chip type… <FAMILY>`.
  `esp32/discover.py` parses both prefixes plus a broad regex fallback;
  if you add new chip support, leave the broad fallback in place.
