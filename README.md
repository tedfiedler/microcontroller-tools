# microcontroller-tools

CLI tools for working with microcontrollers over USB. Three device
families today: **ESP32** (classic ESP32 + S2 / S3 / C3 + Arduino Nano
ESP32), **Raspberry Pi Pico** (RP2040 + RP2350), and **AVR** (stock
ATmega328P with the Arduino bootloader, programmed over an FTDI /
CH340 / CP2102 USB-UART bridge). The first two run MicroPython; the
AVR CLI is intentionally narrower because the chip runs compiled C, not
Python.

## Install

Using [uv](https://github.com/astral-sh/uv) (recommended):

```sh
uv sync
```

Or with pip (inside a venv):

```sh
pip install -e .
```

This registers three console scripts:

- **`esp32`** — driver for ESP32-family boards.
- **`pico`** — driver for Raspberry Pi Pico-family boards.
- **`avr`** — driver for AVR-family boards (ATmega328P + Arduino bootloader by default).

`esp32` and `pico` share the same MicroPython-centric subcommand
structure (`discover`, `flash`, `push`, `pull`, `ls`, `wifi`, `repl`,
`info`, `reset`, `mip`, `lint`). The mpremote-driven half of each
command (`push` / `pull` / `ls`, `repl`, `reset`, `wifi`, `mip`, plus
the `info` probe and `lint` AST walker) lives in a shared `common/`
package — chip-agnostic and identical between the two CLIs.
Family-specific bits — USB fingerprints, flash backend (esptool /
dfu-util / UF2-MSC / picotool), board profiles, and chip-pin rule data
— live under `esp32/` and `pico/` respectively.

`avr` has a deliberately narrower surface (`discover`, `flash`,
`reset`, `monitor` only) because there's no MicroPython on AVRs —
nothing to `push` / `pull` / `repl` against, no `mip`, no Wi-Fi, and
`lint`'s Python-AST walker doesn't apply to `.ino` / `.cpp` sources.
See [AVR usage](#avr-usage) below for the AVR-specific commands.

## Usage

The examples below show `esp32 …` syntax; replace the program name
with `pico` and everything works the same way unless the section
calls out a Pico-specific difference.

### 1. Discover connected devices

```sh
esp32 discover               # list ESP32-family boards plugged into USB
esp32 discover --all         # include all USB serial ports (even non-ESP32)
esp32 discover --json        # machine-readable output
esp32 discover --port /dev/cu.usbmodem1101   # inspect a single port
esp32 discover --probe       # add CHIP + PROFILE columns (talks to each port)
esp32 discover --probe-esptool   # plus esptool fallback for CHIP (invasive)
esp32 discover --doc         # also drop a <CHIP>.md pin reference into cwd

pico discover                # list Pico-family boards (serial + BOOTSEL)
pico discover --probe        # add CHIP + PROFILE for serial-mode Picos
pico discover --doc          # also drop RP2040.md / RP2350.md into cwd
```

USB fingerprinting alone tells you the *bridge* (CP2102, CH340, FTDI…),
not the chip family behind it or which MicroPython build is running.
`--probe` adds two columns by calling `mpremote eval
"__import__('os').uname().machine"` against each detected port and
parsing the result two ways:

- **CHIP** — chip family (`ESP32`, `ESP32-S2`, `ESP32-S3`, `ESP32-C3`
  for ESP32; `RP2040`, `RP2350` for Pico), extracted from the tail of
  the `…with <chip>` suffix.
- **PROFILE** — `BoardProfile` slug matched against the
  `MICROPY_HW_BOARD_NAME` prefix (`ESP32_GENERIC`, `ARDUINO_NANO_ESP32`,
  `RPI_PICO`, `RPI_PICO_W`, …). This is the slug you'd pass to
  `<cli> flash --board <slug>`.

Probing is non-invasive but only works on boards already running
MicroPython. Cold USB-CDC connects routinely take 5–8 seconds per
port, so this is opt-in; a `probing …` note prints to stderr so you
aren't staring at silence. `esp32 discover --probe-esptool` falls
back to `esptool chip-id` when the mpremote path fails — that one
bounces the chip into the ROM bootloader, so don't use it casually.
The esptool fallback fills in `CHIP` only; `PROFILE` requires a
running MicroPython build to query.

`--doc` (implies `--probe`) drops a `<CHIP>.md` pin-reference file
into the current directory for each detected chip family — a short
header notes the detected port and PROFILE, followed by chip-family
info that's uniform across boards using that silicon (GPIO map,
strapping pins, ADC/DAC/touch channels, UART/I²C/SPI conventions).
Available on both CLIs: `esp32 discover --doc` ships `ESP32.md` and
`ESP32-C3.md` today (S2 / S3 templates added as boards are verified
against hardware); `pico discover --doc` ships `RP2040.md` and
`RP2350.md`. For Pico devices in BOOTSEL mode the chip family comes
from `INFO_UF2.TXT` on the mounted volume, so `--doc` works without
`--probe` connecting to a serial REPL.

**Pico-specific:** `pico discover` recognizes two modes a Pico can
show up in. **Serial mode** — board is running firmware, enumerates
as `/dev/ttyACM*` under VID `0x2E8A`. **BOOTSEL mode** — board is in
the ROM bootloader, mounted as a USB mass-storage volume labeled
`RPI-RP2` (RP2040) or `RP2350` (RP2350). Detection of BOOTSEL devices
scans platform-specific mount roots (`/run/media/$USER` on Linux,
`/Volumes` on macOS) for the `INFO_UF2.TXT` sentinel file. The `MODE`
column distinguishes them.

### 2. Flash MicroPython firmware

```sh
esp32 flash                                      # auto-detect board, download latest, prompt, flash
esp32 flash --firmware path/to/firmware          # use a local file, skip download
esp32 flash --firmware-url https://...           # download a specific URL
esp32 flash --board ESP32_GENERIC_S3             # override board slug (skip auto-infer)
esp32 flash --yes                                # non-interactive
esp32 flash --erase                              # (esptool boards only) erase flash first

pico flash                                       # auto-detect, hold BOOTSEL while plugging in
pico flash --board RPI_PICO_W                    # Pico W (cyw43 variant)
pico flash --via picotool                        # force picotool instead of UF2 drag-and-drop
pico flash --firmware path/to/firmware.uf2
```

The tool picks the right backend per family.

**ESP32:**

- **Generic ESP32 / S2 / S3 / C3** — `esptool` writes `.bin` at the chip's
  standard offset via the ROM serial-download bootloader. esptool comes
  in automatically via `uv sync`.
- **Arduino Nano ESP32** — `dfu-util` writes Arduino's `.app-bin` at the
  app region via the factory DFU bootloader. This preserves the Arduino
  bootloader, so you can still run Arduino sketches later.
  - **Prereq:** `brew install dfu-util` (one time).
  - **Procedure:** start `esp32 flash` from app mode; double-tap the blue
    RESET button when prompted to enter DFU mode; tool does the rest.

**Pico:**

- **UF2-MSC** (default) — wait for the `RPI-RP2` / `RP2350` BOOTSEL
  mass-storage volume to mount, `shutil.copy` the `.uf2` onto it, poll
  for the volume to detach (signals the Pico has rebooted into the new
  firmware). If the volume isn't already mounted, the tool prompts you
  to hold BOOTSEL and plug in, then polls for up to 60 s.
- **picotool** — used when no BOOTSEL volume is mounted but a
  serial-mode Pico is up and `picotool` is on PATH. Runs `picotool
  load --force --update --verify` which can bounce an app-mode Pico
  into BOOTSEL itself. Useful on headless Linux installs without
  filesystem automount.
- **Pico W / Pico 2 W detection:** the BOOTSEL ROM does not expose
  the cyw43 module's presence, so the tool can't distinguish a Pico W
  from a plain Pico. It defaults to the non-W slug and prints a
  reminder to pass `--board RPI_PICO_W` (or `RPI_PICO2_W`) if your
  board has Wi-Fi.

Firmware sources:

- Most ESP32 boards pull from `micropython.org/download/<SLUG>/`.
- Arduino Nano ESP32 pulls from `downloads.arduino.cc/micropython/index.json`.
- Pico boards pull from `micropython.org/download/<SLUG>/` (`.uf2`).

Downloaded firmware is cached under `~/.cache/microcontroller-tools/firmware/`
— shared between the two CLIs. Delete that directory to force a fresh
download.

### 3. Push / pull code

Wraps the official `mpremote` tool for filesystem operations. The device must
already be running MicroPython (use `flash` first).

```sh
esp32 push main.py                      # upload a file to :/main.py
esp32 push app/ /app                    # upload a directory to :/app/
esp32 pull main.py                      # download :/main.py to ./main.py
esp32 pull --recursive /app /tmp/back   # download a directory
esp32 pull --all /tmp/devbackup         # whole-device backup; mirrors the device tree
esp32 pull main.py -q                   # --quiet: suppress per-file mpremote echoes
esp32 ls                                # list root of device filesystem
esp32 ls /lib                           # list a subdirectory

pico push main.py                       # same flags, same behavior
pico pull --all /tmp/picobackup
pico ls
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

Port auto-detection prefers MicroPython-running devices; pass `--port` to
override.

### 4. Wi-Fi config

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

# Pico W (untested-on-hardware; should behave identically since the
# network.WLAN(STA_IF) API is the same on the cyw43 stack):
pico wifi MyNetwork --persist
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

### 5. MicroPython REPL

```sh
esp32 repl                          # auto-detect port, drop into the REPL
esp32 repl --port /dev/ttyUSB0      # explicit port

pico repl
```

A thin wrapper over `mpremote connect <port> repl` with the same
auto-port resolution as `push`/`pull`/`wifi`. Implemented via
`os.execvp` so terminal control sequences pass through directly — exit
with `Ctrl-]`, just like `mpremote repl` natively.

### 6. Device info

```sh
esp32 info                  # one-shot summary of the connected device
esp32 info --json           # same data, machine-readable

pico info
```

One mpremote round-trip pulls everything in a single shot: USB ID and
bridge, chip, profile slug, MicroPython version, MAC, heap usage,
filesystem usage, current Wi-Fi state (active / connected / SSID /
ifconfig). The on-device probe script is sent through the same host
tempfile + `mpremote run` pattern as `wifi` and `pull --all`. Same
probe script for both families — missing modules (e.g. `network` on a
non-Wi-Fi Pico) are caught locally so the surrounding JSON still
comes back intact.

**Caveat — Wi-Fi state.** `mpremote run` does a soft reset before
executing scripts. `_wifi_cfg.py` auto-connects only at *hard*-boot via
`boot.py`, so a recent series of `mpremote run`/`mpremote eval`
invocations may have left the STA interface inactive. `info` faithfully
reports point-in-time state; hard-reset (`<cli> reset`) and re-run
`info` if you want the boot-time picture.

### 7. Reset

```sh
esp32 reset                 # hard reset (DTR/RTS toggle; ~= power-cycle)
esp32 reset --soft          # Ctrl-D in REPL; clears Python state, re-runs main.py
esp32 reset --port /dev/ttyUSB0

pico reset
pico reset --soft
```

Wraps `mpremote reset` / `mpremote soft-reset` with the same auto-port
resolution as everything else. Hard reset is the right choice when you
want `boot.py` (and therefore `_wifi_cfg.py`) to re-run; soft reset
just bounces the Python interpreter. After a hard reset, give the USB
stack ~5-10s before reconnecting via another `<cli>` command — the
serial port re-enumerates and mpremote can't talk to it during that
window.

### 8. Install MicroPython packages

```sh
esp32 mip umqtt.simple              # install from micropython-lib
esp32 mip github:user/repo          # install from a GitHub repo
esp32 mip github:user/repo@branch   # specific branch

# Pico W (untested-on-hardware; depends on _wifi_cfg.py being present):
pico mip umqtt.simple
```

Wraps `mpremote mip install` with auto-port resolution. Internally
chains `mpremote ... exec "import _wifi_cfg" mip install <pkg>` in a
single session so the wlan stack — which the soft-reset on connect
would otherwise drop — gets re-established before mip's network fetch
runs.

**Requires `_wifi_cfg.py` on the device.** Run `<cli> wifi <SSID>
--persist` once to create it. Without it, the auto-import errors out
with a clear `ImportError: no module named '_wifi_cfg'` *before* mip
even starts — the signal to set up persistent Wi-Fi first. For custom
Wi-Fi setups, just call `mpremote ... exec '<your-setup>' mip install
<pkg>` directly.

### 9. Lint for chip-pin hazards

```sh
esp32 lint main.py                       # auto-detect chip from device
esp32 lint --chip ESP32 main.py          # skip the device probe
esp32 lint --chip ESP32 src/             # walk a directory
esp32 lint --chip ESP32 main.py --json   # machine-readable output

pico lint main.py                        # auto-detect chip (RP2040 / RP2350)
pico lint --chip RP2040 src/
```

Static-analyzes Python files for `Pin(N)` constructions and peripheral
kwargs (`I2C(scl=, sda=)`, `SPI(sck=, mosi=, miso=)`, `UART(tx=, rx=)`,
`PWM(pin=)`, …) that target pins which are reserved, strapping,
input-only, or otherwise wired to onboard hardware on the configured
chip family. Three severities, each cross-referenced against the
family's rule table:

**ESP32 (classic):**

| Severity | Pins | Why |
|---|---|---|
| **error**   | 6, 7, 8, 9, 10, 11 | Reserved for internal SPI flash — toggling crashes the chip. |
| **warning** | 0, 2, 5, 12, 15    | Strapping pins — wrong level at boot prevents startup. |
| **note**    | 34, 35, 36, 39 (only when `Pin.OUT`) | Input-only — no output drive, no internal pulls. |

**ESP32-C3:**

| Severity | Pins | Why |
|---|---|---|
| **warning** | 2, 8, 9   | Strapping pins — sampled at reset; GP9 is the BOOT button on every dev board. |
| **warning** | 18, 19    | Native USB-Serial-JTAG (GP18 = D-, GP19 = D+) — using as plain GPIO breaks the USB CDC console. |

No flash-pin `error` class on the C3 — its QSPI flash is wired to dedicated chip pins outside the GPIO numbering.

**Pico (RP2040 / RP2350):**

| Severity | Pins | Why |
|---|---|---|
| **warning** | 23, 24, 25, 29 | Reserved for onboard hardware on Raspberry-Pi reference boards: cyw43 module on Pico W / Pico 2 W; SMPS PS / VBUS sense / onboard LED / VSYS-divider on non-W variants. Third-party RP2040 / RP2350 modules may free them up. |

No catastrophic-flash-pin equivalent to the ESP32 on RP2040 / RP2350 —
QSPI flash is wired to dedicated chip pins outside the GPIO numbering.

Example ESP32 output against a fixture with each category:

```
main.py:5:10   warning  Pin(2) is a strapping pin on ESP32 — wrong level at boot prevents the chip from starting
main.py:6:12   error    Pin(7) is reserved for internal SPI flash on ESP32 — toggling will crash or corrupt the chip
main.py:7:18   note     Pin(34) is input-only on ESP32 — no output drive, no internal pull-up or pull-down (used here as Pin.OUT)

1 error, 1 warning, 1 note
```

Exit code = number of errors, so the command slots into pre-commit
hooks. v1 limitations: only literal int args fire (no flow analysis
yet, so `n = 7; Pin(n)` is invisible), and ESP32 + ESP32-C3 + RP2040
+ RP2350 rules ship today — ESP32-S2 / S3 rules will land as boards
are verified against hardware.

## AVR usage

The `avr` CLI is intentionally narrower than `esp32` / `pico`. There's
no MicroPython on AVRs — the chip runs compiled C from an Intel-HEX
file you build separately (`arduino-cli compile`, `platformio run`,
plain `avr-gcc`), and `avr flash` is the bootloader-driven upload step.

Subcommands: `discover`, `flash`, `reset`, `monitor`. Nothing else
shares with the MicroPython CLIs.

**Prereq:** `avrdude` on PATH.

```sh
sudo apt install avrdude     # Debian/Ubuntu/Raspberry Pi OS
brew install avrdude         # macOS
sudo pacman -S avrdude       # Arch
```

### Discover bridges

```sh
avr discover                 # list known USB-UART bridge chips
avr discover --all           # include unrecognized serial ports
avr discover --json
```

A matched row proves a USB-UART bridge is plugged in (FT232, CH340,
CP2102, or an Arduino board's onboard ATmega16U2 USB-serial stack) —
**not** that an AVR is on the other side. Disambiguation happens at
`avr flash` time when avrdude actually talks the bootloader.

### Flash a .hex

```sh
avr flash sketch.hex                              # default: ATmega328P + optiboot (115200)
avr flash sketch.hex --port /dev/ttyUSB0          # explicit port
avr flash sketch.hex --board atmega328p-duemilanove   # older 57600-baud bootloader
avr flash sketch.hex --mcu atmega168              # different AVR
avr flash sketch.hex --baud 19200                 # LilyPad / Pro 3.3 V
avr flash sketch.hex -v --yes                     # verbose, non-interactive
```

Internally runs:

```
avrdude -c arduino -p atmega328p -P <port> -b 115200 -D \
        -U flash:w:sketch.hex:i
```

`-D` is mandatory — Arduino bootloaders (STK500v1) don't expose a
chip-erase command, and without `-D` avrdude tries to erase up front
and bails with a `stk500_recv()` error. Optiboot erases per-page
during the write itself, so `-D` is correct (not a workaround).

This tool **does not compile** the sketch — bring your own `.hex`. To
build one from an `.ino`:

```sh
arduino-cli compile --fqbn arduino:avr:uno --output-dir build sketch.ino
avr flash build/sketch.ino.hex
```

### Reset

```sh
avr reset                    # pulse DTR (~= press the reset button)
avr reset --port /dev/ttyUSB0
```

Briefly drops DTR on the USB-UART bridge. On a standard Arduino reset
circuit (DTR → 100 nF cap → AVR RESET), that produces a brief LOW
pulse on RESET — same effect as pressing the button. The bootloader
then runs for ~1 s waiting for an upload before falling through to the
sketch. Breadboarded ATmega328 setups without the DTR-coupling cap
won't respond; ground RESET manually in that case.

### Monitor (serial console)

```sh
avr monitor                  # opens at 9600 baud (Arduino default)
avr monitor --baud 115200    # match Serial.begin(115200) in the sketch
avr monitor --port /dev/ttyUSB0
```

Delegates to `python -m serial.tools.miniterm` — the mini-terminal
that ships with pyserial. Replaces the process via `execvp` so signals
and TTY state pass through cleanly; exit with `Ctrl-]`. No extra
system dep (no picocom / tio / screen required).

## Supported devices

### ESP32 family

Any ESP32-family board. Detection is by USB VID/PID fingerprinting, covering:

- Espressif native USB (ESP32-S2/S3/C3 in USB-CDC mode)
- Arduino Nano ESP32
- Silicon Labs CP210x (common on ESP32 DevKits)
- WCH CH340 / CH9102 (budget dev boards)
- FTDI FT232 (some ESP32 dev boards)

### Pico family

Raspberry Pi Pico-family boards (VID `0x2E8A`):

- **Raspberry Pi Pico** (RP2040) — verified on hardware.
- **Raspberry Pi Pico W** (RP2040 + cyw43) — code paths implemented,
  not yet verified on hardware.
- **Raspberry Pi Pico 2** (RP2350) — datasheet-only, not yet verified.
- **Raspberry Pi Pico 2 W** (RP2350 + cyw43) — datasheet-only, not yet
  verified.

Third-party RP2040 / RP2350 modules that re-use Raspberry Pi's VID
should work as far as USB-level discovery is concerned; the
onboard-hardware warnings from `pico lint` may not apply since those
boards typically free up GP23 / GP24 / GP25 / GP29.

### AVR family

Any AVR `avrdude` can talk to. The default profile targets a stock
**ATmega328P** with the Arduino bootloader (optiboot, 115200 baud), but
`--mcu` / `--programmer` / `--baud` overrides cover the rest of the
AVR catalogue. Common known-good combinations:

- **ATmega328P + optiboot** (Arduino Uno R3, modern Nano, most
  "Arduino-compatible" ATmega328 breakouts shipped after ~2011) —
  default; nothing to override.
- **ATmega328P + Duemilanove bootloader** (older Arduino Duemilanove,
  LilyPad variants with STK500v1 at 57600) — `--board atmega328p-duemilanove`.
- **ATmega168 / ATmega32U4 / ATtiny85** — `--mcu` override; the
  Arduino bootloader speaks the same protocol on each.

USB-side detection covers the four common USB-UART bridges (FTDI
FT232 family, QinHeng CH340/CH341, Silicon Labs CP210x, Arduino-branded
ATmega16U2-as-USB-serial on Uno R3 / Mega2560). A matched bridge does
**not** prove an AVR is on the other side — that's confirmed at
`avr flash` time when avrdude actually negotiates with the bootloader.
