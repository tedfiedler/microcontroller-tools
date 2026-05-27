## Working style

When reviewing code, lead with what works, then identify 2-3 specific
areas for improvement (performance, readability, Pythonic style). Push
back when there's a better approach — don't reflexively agree.

Prioritize security, correctness, reliability, and standards compliance
over novelty or speed. Avoid unsafe practices unless explicitly
requested, and warn clearly when something is risky. If uncertain about
an answer, state the uncertainty and suggest validation steps.

# Project: microcontroller tools

A set of CLI tools for working with microcontrollers. Three device
families today, exposed through three console scripts. Two of them
(`esp32`, `pico`) share the MicroPython-centric subcommand structure;
the third (`avr`) is intentionally narrower because there's no
MicroPython on AVRs.

- **`esp32`** — ESP32-family (classic ESP32, S2, S3, C3, Arduino Nano ESP32).
- **`pico`** — Raspberry Pi Pico-family (RP2040 + RP2350; Pico / Pico W / Pico 2 / Pico 2 W).
- **`avr`** — AVR family programmed via a USB-UART bridge (FT232 / CH340 /
  CP2102). Default target is a stock ATmega328P with the Arduino
  bootloader; other AVRs work via `--mcu` / `--programmer` overrides.

MicroPython shared subcommands (`esp32`, `pico`): `discover`, `flash`,
`push`, `pull`, `ls`, `wifi`, `repl`, `info`, `reset`, `mip`, `lint`.

AVR subcommands: `discover`, `flash`, `reset`, `monitor` only — no
filesystem / REPL / Wi-Fi / lint, since the chip runs compiled C, not
MicroPython.

## Architecture
1. python 3.14, managed with `uv` (`uv sync --extra dev`, `uv run esp32 ...` / `uv run pico ...` / `uv run avr ...`)
2. Tools are command-line; one entry point per device family with shared subcommands.
3. Third-party tooling wrapped as subprocesses:
   - `esptool` (pypi dep) — generic ESP32 flashing
   - `dfu-util` (brew install) — Arduino Nano ESP32 flashing
   - `picotool` (optional, apt / brew) — Pico flashing fallback when no BOOTSEL mount is available
   - `mpremote` (pypi dep) — push/pull/ls, REPL, on-device exec / probe scripts
   - `avrdude` (apt / brew install) — AVR flashing

## Code conventions
1. Use doc strings and well document classes, methods, and functions
2. use dataclasses for modeling if needed
3. strict typing — `mypy --strict esp32/ common/ pico/ avr/` must pass
4. follow pep standards — `ruff check esp32/ common/ pico/ avr/` must pass

## Project conventions
1. Four top-level packages:
   - `common/` — chip-agnostic shared modules used by MicroPython-running
     families (esp32, pico). Holds the mpremote primitives (`_mpy.py`),
     the FamilyContext dataclass (`family.py`), and the subcommand
     runners that don't depend on which chip is connected (`code.py`,
     `repl.py`, `reset.py`, `mip.py`, `wifi.py`, plus the `info` probe
     + dataclass + formatters in `info.py` and the lint AST walker +
     formatters in `lint.py`).
   - `esp32/` and `pico/` — MicroPython device-family packages. Each
     holds its own `usb_ids.py`, `boards.py`, `discover.py`, `flash.py`,
     `firmware.py`, `pin_rules.py`, plus thin wrappers (`info.py`,
     `lint.py`) that supply family-specific data to the shared runners,
     plus a `cli.py` that builds a `FamilyContext` and dispatches
     subcommands.
   - `avr/` — non-MicroPython device-family package. Holds its own
     `usb_ids.py`, `boards.py`, `discover.py`, `flash.py`, `reset.py`,
     `monitor.py`, `cli.py`. Doesn't use `common/` because none of the
     shared runners apply (no mpremote on AVRs).
2. Adding a new chip family means creating a new sibling package next to
   `esp32/` / `pico/` / `avr/` with the same shape, registering its
   console script in `pyproject.toml`, and adding the directory to the
   `packages = [...]` line of `[tool.hatch.build.targets.wheel]`. If the
   chip runs MicroPython, the shared runners under `common/` are reused
   as-is; if not (e.g. another bare-metal chip like AVR), the family
   ships its own thin runners.
3. Run `mypy --strict esp32/ common/ pico/ avr/` and
   `ruff check esp32/ common/ pico/ avr/` before committing.

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
- **`avr flash` needs `avrdude -D`.** The Arduino bootloader speaks
  STK500v1 over serial, which does not expose a chip-erase command.
  Without `-D`, avrdude tries to erase up front and fails with a
  confusing `stk500_recv()` error. Optiboot erases per-page during the
  write itself, so `-D` is the correct flag (not a workaround).
- **`avr discover` can't prove the chip is an AVR.** Matching an
  FT232 / CH340 / CP2102 VID/PID only proves a USB-UART bridge is
  plugged in — those same bridges are routinely wired to ESP32 /
  RP2040 / STM32. We label the row "USB-UART bridge" rather than
  claiming a specific chip; disambiguation happens at `avr flash` time
  when avrdude actually talks the bootloader.
