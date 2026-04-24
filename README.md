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

**Arduino Nano ESP32 users:** the board must be in DFU/bootloader mode before
flashing. Double-tap the RESET button; the USB port will reappear with a new
name. Run `esp32 discover` to see the new port, then `esp32 flash`.

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
