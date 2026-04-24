# microcontroller-tools

CLI tools for working with MicroPython-capable microcontrollers over USB.

## Install

Using [uv](https://github.com/astral-sh/uv) (recommended):

```sh
uv sync
```

Or with pip (inside a venv):

```sh
pip install -e .
```

This registers an `esp32` console script.

## Usage

### Discover connected ESP32 devices (Tool 1 — implemented)

```sh
esp32 discover               # list ESP32-family boards plugged into USB
esp32 discover --all         # include all USB serial ports (even non-ESP32)
esp32 discover --json        # machine-readable output
esp32 discover --port /dev/cu.usbmodem1101   # inspect a single port
```

### Flash MicroPython firmware (Tool 2 — implemented)

```sh
esp32 flash                                      # auto-detect board, download latest stable firmware, prompt, flash
esp32 flash --erase                              # erase whole flash first (clean install)
esp32 flash --firmware path/to/firmware.bin      # use a local .bin, skip download
esp32 flash --firmware-url https://...           # download a specific URL
esp32 flash --board ESP32_GENERIC_S3             # override board slug (skip auto-infer)
esp32 flash --port /dev/cu.usbmodem1234 --yes    # non-interactive
```

All boards are flashed via `esptool` talking to the ESP32 ROM serial-download
bootloader. Most dev-board designs (e.g. Espressif DevKits) handle the reset
automatically — just run `esp32 flash`.

**Arduino Nano ESP32:** you have to enter the ESP32-S3 ROM bootloader manually:

1. **Hold the B1 (BOOT) button** while pressing RESET (or while plugging USB in).
2. Run `esp32 discover` — the board will appear as `USB JTAG/serial debug unit`
   at VID `0x303A` / PID `0x1001`.
3. Run `esp32 flash --board ARDUINO_NANO_ESP32`.

Note: flashing the Nano ESP32 this way **overwrites the factory Arduino DFU
bootloader**. To return to Arduino sketches later, follow Arduino's
[bootloader restore instructions](https://support.arduino.cc/hc/en-us/articles/9810414060188-Reset-the-Arduino-bootloader-on-the-Nano-ESP32).

Downloaded firmware is cached under `~/.cache/microcontroller-tools/firmware/`.
Delete that directory to force a fresh download.

### Other tools (stubbed)

- `esp32 push`  — push code to device. *Not implemented yet.*
- `esp32 pull`  — pull code from device. *Not implemented yet.*
- `esp32 wifi`  — configure wireless IP. *Not implemented yet.*

## Supported devices

Any ESP32-family board. Detection is by USB VID/PID fingerprinting, covering:

- Espressif native USB (ESP32-S2/S3/C3 in USB-CDC mode)
- Arduino Nano ESP32
- Silicon Labs CP210x (common on ESP32 DevKits)
- WCH CH340 / CH9102 (budget dev boards)
- FTDI FT232 (some ESP32 dev boards)
