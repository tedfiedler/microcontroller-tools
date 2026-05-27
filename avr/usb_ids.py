"""USB VID/PID fingerprints for common USB-to-UART bridges paired with AVRs.

Unlike :mod:`esp32.usb_ids` / :mod:`pico.usb_ids`, a matched signature
here does **not** prove the attached device is an AVR — it only proves
that *something* with a serial port is plugged in. The same FT232 /
CH340 / CP2102 bridges are routinely wired to ESP32, RP2040, STM32,
and one-off prototypes. ``avr discover`` therefore labels matches as
"USB-UART bridge (could be an AVR)" rather than claiming a specific
chip; the real disambiguation happens at ``avr flash`` time when
``avrdude`` actually talks the bootloader protocol.

Covered vendor IDs:

* ``0x0403`` — Future Technology Devices International (FTDI). The
  canonical bridge for "stock ATmega328 + FTDI breakout" setups; also
  used by the original Arduino Duemilanove and SparkFun FTDI boards.
* ``0x1A86`` — QinHeng Electronics (CH340 / CH341). Common on cheap
  Arduino Nano / Pro Mini clones.
* ``0x10C4`` — Silicon Labs (CP210x). Used on a smaller number of
  Arduino clones and on some breakout boards.
* ``0x2341`` — Arduino LLC (genuine Uno R3 / Mega2560 with the
  ATmega16U2 USB-bridge firmware). Different USB stack from FTDI but
  the bootloader protocol on the ATmega328P side is identical.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UsbSignature:
    """One known (vid, pid) tuple with a human label.

    ``role`` is informational here — every entry is a USB-UART bridge,
    so the field mostly records *which* bridge chip we matched. Kept
    parallel with the ESP32 / Pico signature shape so downstream
    table-rendering helpers can be reused.
    """

    vid: int
    pid: int
    label: str
    role: str  # "ftdi" | "ch340" | "cp210x" | "arduino-usb-serial"


AVR_SIGNATURES: tuple[UsbSignature, ...] = (
    # FTDI bridges.
    UsbSignature(0x0403, 0x6001, "FTDI FT232R / FT232RL (FTDI breakout)", role="ftdi"),
    UsbSignature(0x0403, 0x6010, "FTDI FT2232H (dual-channel)", role="ftdi"),
    UsbSignature(0x0403, 0x6011, "FTDI FT4232H (quad-channel)", role="ftdi"),
    UsbSignature(0x0403, 0x6014, "FTDI FT232H (single-channel)", role="ftdi"),
    UsbSignature(0x0403, 0x6015, "FTDI FT231X / FT230X (USB-serial)", role="ftdi"),
    # QinHeng CH340 / CH341 — the cheap-Nano-clone bridge.
    UsbSignature(0x1A86, 0x7523, "QinHeng CH340 (Nano clone bridge)", role="ch340"),
    UsbSignature(0x1A86, 0x5523, "QinHeng CH341A (parallel-serial bridge)", role="ch340"),
    UsbSignature(0x1A86, 0x55D4, "QinHeng CH9102F (USB-serial)", role="ch340"),
    # Silicon Labs CP210x.
    UsbSignature(0x10C4, 0xEA60, "Silicon Labs CP2102 / CP2102N", role="cp210x"),
    UsbSignature(0x10C4, 0xEA70, "Silicon Labs CP2105 (dual-channel)", role="cp210x"),
    # Arduino-branded USB-serial (Uno R3 / Mega2560 with ATmega16U2 stack).
    UsbSignature(
        0x2341, 0x0043, "Arduino Uno R3 (ATmega16U2 USB-serial)",
        role="arduino-usb-serial",
    ),
    UsbSignature(0x2341, 0x0001, "Arduino Uno (older revision)", role="arduino-usb-serial"),
    UsbSignature(0x2341, 0x0042, "Arduino Mega 2560 R3", role="arduino-usb-serial"),
)


def match(vid: int | None, pid: int | None) -> UsbSignature | None:
    """Return the matching :class:`UsbSignature`, or ``None``.

    Match is exact on the (vid, pid) pair. Bridges with VID/PID outside
    this catalogue (unusual FT-clone reprogrammings, exotic Silicon
    Labs SKUs) won't match — pass ``--all`` to ``avr discover`` to see
    them anyway.
    """
    if vid is None or pid is None:
        return None
    for sig in AVR_SIGNATURES:
        if sig.vid == vid and sig.pid == pid:
            return sig
    return None
