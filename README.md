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
esp32 flash                                      # auto-detect board, download latest, prompt, flash
esp32 flash --firmware path/to/firmware          # use a local file, skip download
esp32 flash --firmware-url https://...           # download a specific URL
esp32 flash --board ESP32_GENERIC_S3             # override board slug (skip auto-infer)
esp32 flash --yes                                # non-interactive
esp32 flash --erase                              # (esptool boards only) erase flash first
```

The tool picks the right backend per board:

- **Generic ESP32 / S2 / S3 / C3** — `esptool` writes `.bin` at the chip's
  standard offset via the ROM serial-download bootloader. Install esptool
  comes in automatically via `uv sync`.
- **Arduino Nano ESP32** — `dfu-util` writes Arduino's `.app-bin` at the
  app region via the factory DFU bootloader. This preserves the Arduino
  bootloader, so you can still run Arduino sketches later.
  - **Prereq:** `brew install dfu-util` (one time).
  - **Procedure:** start `esp32 flash` from app mode; double-tap the blue
    RESET button when prompted to enter DFU mode; tool does the rest.

Firmware sources:
- Most boards pull from `micropython.org/download/<SLUG>/`.
- Arduino Nano ESP32 pulls the Arduino-built `.app-bin` from
  `downloads.arduino.cc/micropython/index.json` — micropython.org's `.bin`
  and `.uf2` for this board are full flash images that don't fit the
  DFU bootloader's partition layout.

Downloaded firmware is cached under `~/.cache/microcontroller-tools/firmware/`.
Delete that directory to force a fresh download.

### Push / pull code (Tool 3 — implemented)

Wraps the official `mpremote` tool for filesystem operations. The device must
already be running MicroPython (use `esp32 flash` first).

```sh
esp32 push main.py                      # upload a file to :/main.py
esp32 push app/ /app                    # upload a directory to :/app/
esp32 pull main.py                      # download :/main.py to ./main.py
esp32 pull --recursive /app /tmp/back   # download a directory
esp32 pull --all /tmp/devbackup         # whole-device backup; mirrors the device tree
esp32 pull main.py -q                   # --quiet: suppress per-file mpremote echoes
esp32 ls                                # list root of device filesystem
esp32 ls /lib                           # list a subdirectory
```

`pull --all` enumerates the device filesystem via a small on-device walk
script (sent through `mpremote run` against a host tempfile, same pattern
as the Wi-Fi tool) and `mpremote fs cp`s each file individually into the
destination. Per-file copies — rather than `mpremote fs -r cp` — sidestep
the recursive-cp flat-directory quirk we already work around on the push
side. Subdirectories on the host are created lazily.

`--quiet` / `-q` suppresses the `$ mpremote …` and `cp :foo …` echoes on
every per-file invocation; the summary lines (`Pulling N files into …`,
`Done. Pulled N files (… bytes total).`) and any errors still print, and
when a copy fails under `--quiet` the captured stderr from mpremote is
folded into the error message so the failure stays actionable.

Port auto-detection prefers MicroPython-running devices (PID `0x056B` for
the Nano ESP32); pass `--port` to override.

### Wi-Fi config (Tool 4 — implemented)

Connect the board's Wi-Fi STA interface to an AP and (optionally) pin a
static IP. Requires the board to be running MicroPython.

The generated MicroPython connect script is written to a 0600-mode host
tempfile and sent via `mpremote run` (not `mpremote exec <script>`), so
the embedded Wi-Fi password isn't visible to other local users via
`ps` / `/proc/<pid>/cmdline` while the connect runs. The tempfile is
unlinked in a `finally` block.

```sh
esp32 wifi MyNetwork                     # DHCP, prompts for password (no echo)
esp32 wifi MyNetwork --password hunter2  # DHCP, explicit password
esp32 wifi OpenAP --open                 # open network (no password)

# Static IP (netmask defaults to /24, gateway defaults to .1 of --ip, dns to 1.1.1.1):
esp32 wifi MyNetwork --ip 192.168.1.100

# Full static config:
esp32 wifi MyNetwork --ip 192.168.1.100 --netmask 255.255.0.0 \
    --gateway 192.168.1.254 --dns 9.9.9.9

# Also write a _wifi_cfg.py on the device for auto-reconnect on boot.
# (Password is stored in plaintext — standard IoT pattern but worth knowing.)
esp32 wifi MyNetwork --ip 192.168.1.100 --persist

# Just show current interface state, no config change:
esp32 wifi --status
```

On success the tool prints the associated IP. With `--persist`, the
`_wifi_cfg.py` is built on the host and copied to the device via
`mpremote fs cp` (rather than generated by an on-device writer script);
add `import _wifi_cfg` to your `boot.py` to have the device auto-reconnect.

**Replace, don't append:** if your `boot.py` already contains an inline
`wlan.connect(...)`, swap it out for `import _wifi_cfg` rather than
adding alongside. Back-to-back connects in the same boot trip ESP32
MicroPython's `OSError: Wifi Internal State Error` unless the wlan is
reset between — `_wifi_cfg.py` does the reset dance for you, but only on
its own attempt.

## Supported devices

Any ESP32-family board. Detection is by USB VID/PID fingerprinting, covering:

- Espressif native USB (ESP32-S2/S3/C3 in USB-CDC mode)
- Arduino Nano ESP32
- Silicon Labs CP210x (common on ESP32 DevKits)
- WCH CH340 / CH9102 (budget dev boards)
- FTDI FT232 (some ESP32 dev boards)
