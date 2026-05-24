# ESP32-C3 — chip pin reference

Reference for the **Espressif ESP32-C3** (single-core RISC-V at 160 MHz,
400 KB SRAM, 4 MB embedded flash on most variants, Wi-Fi 4 + BLE 5).
Covers behavior that's uniform across all boards using this chip; your
specific dev board may break out a subset of these pins, label them
differently, or share some with onboard peripherals (USB connector,
LEDs, buttons, CP2102/CH340 bridge) — always cross-check against your
board's silkscreen and schematic.

## GPIO summary

The SoC has **22 GPIOs**, numbered GP0–GP21. Notable differences from
the classic ESP32:

- **No flash-pin conflicts.** The QSPI flash is wired to dedicated SoC
  pins outside the GPIO numbering, so no GPIO toggling can crash the
  chip the way the classic ESP32's GP6–GP11 can.
- **No input-only pins.** All 22 GPIOs are bidirectional with
  internal pull-ups / pull-downs available.
- **Fewer strapping pins** than the classic ESP32 — only three, and
  with simpler boot rules.

Usable for general I/O: all 22 (GP0–GP21), subject to the strapping
and USB-Serial-JTAG caveats below.

## Strapping pins

The ESP32-C3 samples these three pins at reset. Wrong levels at boot
mean the chip won't start (GP9 is the most consequential — it's the
BOOT button on every dev board); safe to use as plain GPIOs after
boot, but pull them at boot time with care.

| GPIO | At boot                                  | Notes                                                                  |
|------|------------------------------------------|------------------------------------------------------------------------|
| GP2  | Sampled with GP8 to set the boot ROM log | Internal pull-down. Floating-or-LOW is the normal state.               |
| GP8  | Must be HIGH                             | Sampled for the boot ROM log level too. Internal pull-up on most modules; a LOW level at reset will prevent boot. |
| GP9  | LOW = download mode, HIGH = run          | Connected to the BOOT button on every dev board; internal pull-up. The C3's analog of the classic ESP32's GP0. |

## USB-Serial-JTAG

GP18 and GP19 are hard-wired to the SoC's native USB-Serial-JTAG
controller:

| GPIO | USB role | Notes                                                                                                          |
|------|----------|----------------------------------------------------------------------------------------------------------------|
| GP18 | USB D-   | Driving this from user code disconnects the USB CDC console (and MicroPython REPL over native USB).            |
| GP19 | USB D+   | Same.                                                                                                          |

On dev boards with a USB-C / micro-USB connector wired directly to the
SoC (no CP2102 / CH340 bridge), MicroPython appears as `/dev/ttyACM*`
via this peripheral. Even on bridge-equipped boards (e.g. the
CP2102-based ones common in cheap kits) the SoC pins are still
physically wired to the USB jack — re-purposing GP18 / GP19 as plain
GPIO can short the bus or load the data lines.

`esp32 lint --chip ESP32-C3` flags any literal use of GP18 / GP19 with
a warning.

## Analog (ADC)

12-bit ADC, 0 – 3.3 V range. Two converters:

- **ADC1** — usable while Wi-Fi is active. Channels:
  CH0 = GP0, CH1 = GP1, CH2 = GP2, CH3 = GP3, CH4 = GP4.
- **ADC2** — **conflicts with Wi-Fi** (reads fail while Wi-Fi is on),
  same constraint as the classic ESP32. Single channel:
  CH0 = GP5.

```python
from machine import ADC, Pin
adc = ADC(Pin(0))   # GP0 → ADC1 CH0
raw = adc.read_u16() # 0..65535 (12-bit value scaled to 16-bit)
```

## DAC

The ESP32-C3 has **no hardware DAC**. Use PWM (LEDC) with an external
RC filter for analog output.

## Capacitive touch

**None.** Espressif dropped touch from the C3 entirely — if you need
it, look at the S2 / S3 variants.

## Deep-sleep wake (RTC) pins

The C3 has 6 RTC GPIOs that can wake the chip from deep sleep:
GP0, GP1, GP2, GP3, GP4, GP5 (i.e. the same set that does ADC1 + ADC2).

## UART defaults

| Peripheral | TX  | RX  | Notes                                                                                      |
|------------|-----|-----|--------------------------------------------------------------------------------------------|
| UART(0)    | 21  | 20  | Bound to the boot log over UART (and to the CP2102/CH340 bridge on those dev boards). The native USB-Serial-JTAG on GP18/GP19 is the *other* console path; modules with both have UART(0) and USB CDC active in parallel. |
| UART(1)    | —   | —   | No fixed pins; route via the GPIO matrix: `UART(1, tx=Pin(4), rx=Pin(5))`.                 |

Like the rest of the ESP32 family, the C3's UARTs are matrix-routable
to any GPIO — the table above shows the conventional dev-board defaults.

## I²C — convention (pins are remappable)

`machine.I2C(0, scl=Pin(9), sda=Pin(8))` is one common convention but
varies by dev board. The hardware can route either channel to any
GPIO; the SoC doesn't fix the assignment.

## SPI — convention (pins are remappable)

The C3 has two SPI controllers (SPI 1 is reserved for the flash;
user-accessible is SPI 2 only):

| Bus     | MISO | MOSI | SCK | Notes                                                                                        |
|---------|------|------|-----|----------------------------------------------------------------------------------------------|
| SPI(2)  | 2    | 7    | 6   | Common dev-board default. Note MISO clashes with the GP2 strapping pin — fine after boot but watch the boot level. |

```python
spi = machine.SPI(2, baudrate=8_000_000,
                  sck=Pin(6), mosi=Pin(7), miso=Pin(2))
```

## Power

- **3.3 V logic; no 5 V tolerance on any pin.** Driving an ESP32-C3
  GPIO with a 5 V signal will damage it.
- Peak current during Wi-Fi TX bursts is lower than the classic ESP32
  (single core, simpler radio) but still spikes to ~250 mA — undersized
  USB cables can still brown out the regulator.
- Deep sleep: < 5 µA on a properly-laid-out module (better than the
  classic ESP32; comparable to the S3).

## Boot log

UART(0) at 115200 baud prints a bootloader log every reset. Useful for
diagnosing "won't start" problems — visible via `mpremote repl` over
the bridge serial port, or over USB-CDC on native-USB boards.

## ESP32-C3-DevKitM-1 — board specifics

Espressif's official reference dev board (ESP32-C3-MINI-1 module on a
breakout with two USB connectors and a 2 × 15-pin header). What follows
is in addition to the chip-level info above — anything not called out
here behaves as the chip-level sections describe.

### Onboard hardware

| Pin / part         | Role                                                                                 |
|--------------------|--------------------------------------------------------------------------------------|
| GP8                | Onboard addressable RGB LED (WS2812-style). Series resistor sized so the LED doesn't pull the strapping level wrong at boot. |
| GP9                | BOOT button (active LOW). Also the strapping pin for download mode — see [Strapping pins](#strapping-pins). |
| RST                | Hardware reset button. Not on a GPIO.                                                |
| GP20 / GP21        | UART(0) RX / TX, wired through the onboard CP2102N USB-UART bridge to the **UART** USB connector. This is where the boot log and the MicroPython REPL appear over the bridge path. |
| GP18 / GP19        | Native USB D- / D+, wired to the **USB** USB connector (the C-DevKitM-1 has both connectors; some board revisions label them differently). |

### Driving a single LED — board-specific picks

Onboard RGB LED on GP8 is the easiest path if one LED is enough:

```python
import neopixel, machine
np = neopixel.NeoPixel(machine.Pin(8), 1)
np[0] = (255, 0, 0); np.write()    # red
```

For external LEDs through the header, the safe picks are
**GP0, GP1, GP3, GP4, GP5, GP6, GP7, GP10**. Caveats per pin:

| Pin       | OK for LED? | Notes                                                                                                                       |
|-----------|-------------|-----------------------------------------------------------------------------------------------------------------------------|
| GP0–GP4   | ✅          | ADC1 channels but plain GPIO output is fine. GP4 / GP5 are common UART(1) fallback pins — pick others if you'll add a UART. |
| GP5       | ✅          | ADC2 — ADC *reads* conflict with Wi-Fi, but you're outputting.                                                              |
| GP6, GP7  | ✅          | Common SPI(2) SCK / MOSI defaults — pick others if you'll add SPI peripherals.                                              |
| GP10      | ✅          | General-purpose, no conflicts.                                                                                              |
| GP2       | ⚠️           | Strapping. An LED + 220 Ω–1 kΩ resistor pulls weakly enough that boot usually still works, but it's not guaranteed.         |
| GP8       | ⚠️           | Onboard RGB LED — use that instead of adding a parallel external LED here.                                                  |
| GP9       | ❌          | BOOT button. An LED here can hold boot mode LOW at power-up and the chip won't start.                                       |
| GP18, GP19| ⚠️           | Wired to the native-USB connector. Safe as GPIO only if you exclusively plug into the UART connector. Plugging into the USB connector while these are driven fights the host. |
| GP20, GP21| ⚠️           | UART(0) RX / TX to the CP2102. LEDs would flicker on every console byte and you'd lose the REPL.                             |

Driver sizing: 220 Ω for typical red / yellow at ~10 mA, 330 Ω for
green / blue, 1 kΩ for a dim indicator. Stay under ~12 mA continuous
per GPIO; use a small NPN / N-channel MOSFET for anything brighter or
for LED strips.

For PWM dimming, the LEDC peripheral works on any of these pins:

```python
from machine import Pin, PWM
pwm = PWM(Pin(4), freq=1000)
pwm.duty_u16(32768)               # 50% brightness
```

### What's on the headers

The DevKitM-1 breaks out GP0–GP10 and GP18–GP21 (15 GPIOs in total),
plus 3.3 V, 5 V, GND, and EN. The remaining GPIO numbers (GP11–GP17)
aren't exposed — they're either bonded to the internal QSPI flash on
the MINI-1 module or simply not pulled out. If a code example mentions
GP11 / GP12 / etc. it's targeting a different dev board.
