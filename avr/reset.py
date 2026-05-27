"""Tool 3 (AVR family): pulse DTR to reset an Arduino-style AVR.

The standard Arduino auto-reset circuit ties the FTDI / CH340 / ATmega
USB-bridge's ``DTR`` line through a 100 nF capacitor to the AVR's
``RESET`` pin. Dropping DTR (USB host → bridge: assert), waiting a
hair, then raising it again produces a brief LOW pulse on RESET via
the cap — same effect as poking the reset button. The bootloader then
runs for ~1 s waiting for an upload before falling through to the
sketch.

Boards without the DTR-coupling cap (raw breadboarded ATmega328
without the canonical reset circuit, or boards with the auto-reset
jumper cut) won't react to this; in that case the user has to ground
RESET manually.
"""

from __future__ import annotations

import argparse
import sys
import time

import serial

from avr import discover

# How long to hold DTR asserted (RESET pulled LOW through the cap).
# 50 ms is well over the chip's required RESET LOW time and
# comfortably above any host-side debounce. Keeping it brief means
# the bootloader window starts ASAP.
_DTR_HOLD_SECS = 0.05


class ResetError(RuntimeError):
    """Raised for recoverable reset-flow errors."""


def pulse_reset(port: str) -> None:
    """Pulse DTR LOW briefly on ``port`` to reset the attached AVR.

    Opens the port without changing the baud rate (the cap-coupled
    RESET pulse is rate-independent), drops DTR, sleeps, then raises
    DTR before closing. The context-manager exit re-closes the port
    cleanly even if the user CTRL-Cs mid-pulse.
    """
    try:
        with serial.Serial(port) as ser:
            ser.dtr = False
            time.sleep(_DTR_HOLD_SECS)
            ser.dtr = True
    except (serial.SerialException, OSError) as exc:
        raise ResetError(
            f"could not open {port} to pulse DTR: {exc}"
        ) from exc


def run(args: argparse.Namespace) -> int:
    """Entry point for ``avr reset``."""
    try:
        port = discover.resolve_port(args.port)
        pulse_reset(port)
    except (ResetError, discover.PortResolutionError) as exc:
        print(f"avr reset: {exc}", file=sys.stderr)
        return 1
    print(f"Pulsed DTR on {port}. The AVR should be back in setup() now.")
    return 0
