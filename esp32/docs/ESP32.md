# ESP32 — chip pin reference

Reference for the **classic ESP32 SoC** (Tensilica LX6, dual-core, 240 MHz).
Covers behavior that's uniform across all boards using this chip; your
specific dev board may break out a subset of these pins, label them
differently, or share some with onboard peripherals (USB-UART, LEDs,
buttons) — always cross-check against your board's silkscreen and
datasheet.

## GPIO summary

The SoC numbers GPIOs 0–39, with 6 numbers absent (20, 24, 28–31) — 34
GPIOs in total.

- **Usable for general I/O:** 0, 2, 4, 5, 12, 13, 14, 15, 16, 17, 18,
  19, 21, 22, 23, 25, 26, 27, 32, 33
- **Input-only** (no output drive, no internal pull-up/pull-down):
  34, 35, 36 (VP), 39 (VN)
- **Reserved — do NOT use:** 6, 7, 8, 9, 10, 11
  (wired to the internal SPI flash on every ESP32 module; toggling them
  will crash or corrupt the chip)

## Strapping pins

The ESP32 samples these pins at reset to choose boot mode and flash
voltage. Wrong levels at boot mean the chip won't start — safe to use
after boot, but pull them at boot time with care.

| GPIO | At boot                          | Notes                                                              |
|------|----------------------------------|--------------------------------------------------------------------|
| 0    | LOW = download mode, HIGH = run  | Connected to the BOOT button on most dev boards; internal pull-up. |
| 2    | Must be LOW or floating          | Internal pull-down. Often wired to an onboard LED.                 |
| 5    | Must be HIGH                     | Internal pull-up.                                                  |
| 12   | LOW selects 3.3 V flash supply   | MTDI. HIGH selects 1.8 V flash (rare); a standard 3.3 V module pulled HIGH at boot won't start. |
| 15   | Must be HIGH                     | Internal pull-up. LOW silences the bootloader log on UART(0).      |

## Analog (ADC)

12-bit by default, 0–3.3 V range. Readings are non-linear above ~3.1 V —
calibrate (`machine.ADC.atten(...)`) if you care about absolute values.

- **ADC1** — usable while Wi-Fi is active. Channels:
  CH0=GPIO 36 (VP), CH1=37, CH2=38, CH3=39 (VN),
  CH4=32, CH5=33, CH6=34, CH7=35.
  (CH1 / CH2 are typically not bonded out on most ESP32 modules.)
- **ADC2** — **conflicts with Wi-Fi**; reads fail while Wi-Fi is on.
  Channels on GPIO 0, 2, 4, 12, 13, 14, 15, 25, 26, 27.

## DAC

8-bit DACs on GPIO 25 (DAC1) and GPIO 26 (DAC2). Use as
`machine.DAC(machine.Pin(25))`.

## Capacitive touch

10 touch channels: T0=GPIO 4, T1=0, T2=2, T3=15, T4=13, T5=12, T6=14,
T7=27, T8=33, T9=32. Use as `machine.TouchPad(machine.Pin(N))`.

## Deep-sleep wake (RTC) pins

GPIOs that can wake the chip from deep sleep:
0, 2, 4, 12, 13, 14, 15, 25, 26, 27, 32, 33, 34, 35, 36, 37, 38, 39.

## UART defaults

| Peripheral | TX  | RX  | Notes                                                                 |
|------------|-----|-----|-----------------------------------------------------------------------|
| UART(0)    | 1   | 3   | Bound to the USB serial console — leave alone unless you really need the pins. |
| UART(1)    | 10  | 9   | **Default pins clash with internal flash.** Always remap: `UART(1, tx=Pin(17), rx=Pin(16))`. |
| UART(2)    | 17  | 16  | Generally safe.                                                       |

## I²C — convention (pins are remappable)

`machine.I2C(0, scl=Pin(22), sda=Pin(21))` matches the convention used
by most ESP32 dev boards. The hardware can route either channel to any
GPIO; the SoC doesn't fix the assignment.

## SPI — convention (pins are remappable)

| Bus           | MISO | MOSI | SCK | Notes                                                                                              |
|---------------|------|------|-----|----------------------------------------------------------------------------------------------------|
| HSPI (SPI 1)  | 12   | 13   | 14  | MISO clashes with the GPIO 12 flash-voltage strapping pin — boot consequences if held HIGH at reset. Remap to dodge. |
| VSPI (SPI 2)  | 19   | 23   | 18  | Cleaner default; no strapping-pin conflicts.                                                       |

```python
spi = machine.SPI(2, baudrate=8_000_000,
                  sck=Pin(18), mosi=Pin(23), miso=Pin(19))
```

## Power

- **3.3 V logic; no 5 V tolerance on any pin.** Driving an ESP32 GPIO
  with a 5 V signal will damage it.
- Peak current during Wi-Fi/BLE TX bursts can spike to ~500 mA. Undersized
  USB cables (or weak laptop ports) brown-out the regulator and trigger
  random resets — if your board is flaky, try a beefier cable first.
- Deep sleep: < 10 µA on a properly-laid-out module.

## Boot log

UART(0) at 115200 baud prints a bootloader log every reset. Useful for
diagnosing "won't start" problems — visible via `mpremote repl` or any
serial monitor before MicroPython's REPL takes over.
