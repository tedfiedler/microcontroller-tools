"""CLI entry point for the ``avr`` console script.

Sibling of :mod:`esp32.cli` / :mod:`pico.cli` but deliberately
narrower — the AVR family has no on-device MicroPython, so the shared
:mod:`common` runners (``push``, ``pull``, ``ls``, ``repl``,
``info``, ``mip``, ``wifi``, ``lint``) don't apply. ``avr`` exposes
only the four subcommands that make sense for "stock AVR + bootloader
over a USB-UART bridge":

* ``discover`` — list USB-UART bridges that could be wired to an AVR.
* ``flash``    — upload a compiled .hex via ``avrdude``.
* ``reset``    — pulse DTR to retrigger the bootloader / sketch.
* ``monitor``  — open a raw serial console (delegates to
  ``serial.tools.miniterm``).

No :class:`common.family.FamilyContext` here — none of the shared
runners are reused, so threading one through would be dead weight.
"""

from __future__ import annotations

import argparse
import sys

from avr import __version__, discover, flash, monitor, reset


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands wired up."""
    parser = argparse.ArgumentParser(
        prog="avr",
        description=(
            "CLI tools for AVR-family microcontrollers (e.g. ATmega328P) "
            "programmed over a USB-UART bridge."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"avr {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # ---------- discover -----------------------------------------------------

    p_discover = subparsers.add_parser(
        "discover",
        help="List USB-UART bridges (FT232 / CH340 / CP2102 / ATmega16U2).",
        description=(
            "Enumerate USB-UART bridge chips plugged into the host. A "
            "match here means a serial port exists — not that an AVR is "
            "on the far end of it; that's confirmed at `avr flash` time."
        ),
    )
    p_discover.add_argument(
        "--all", dest="include_unknown", action="store_true",
        help="Also list serial ports that don't match a known USB-UART bridge.",
    )
    p_discover.add_argument(
        "--json", dest="as_json", action="store_true",
        help="Emit JSON instead of a text table.",
    )
    p_discover.add_argument(
        "--port", dest="port", default=None,
        help="Inspect only the given port path (e.g. /dev/ttyUSB0).",
    )

    # ---------- flash --------------------------------------------------------

    p_flash = subparsers.add_parser(
        "flash",
        help="Upload a compiled .hex onto an AVR via avrdude.",
        description=(
            "Run `avrdude` against the AVR's bootloader. Defaults target "
            "a stock ATmega328P with the Arduino bootloader (optiboot, "
            "115200 baud). Use --mcu / --programmer / --baud to talk to "
            "other AVRs or older bootloader variants."
        ),
    )
    p_flash.add_argument(
        "firmware",
        help="Path to the Intel-HEX file to flash (output of avr-gcc / arduino-cli).",
    )
    p_flash.add_argument(
        "--port", dest="port", default=None,
        help="Serial port of the USB-UART bridge (default: auto-detect).",
    )
    p_flash.add_argument(
        "--board", dest="board", default=None,
        help=(
            "Board profile slug (default: atmega328p-arduino). "
            "Try `atmega328p-duemilanove` for the older 57600-baud "
            "bootloader."
        ),
    )
    p_flash.add_argument(
        "--mcu", dest="mcu", default=None,
        help=(
            "Override `avrdude -p` part number (e.g. atmega168, "
            "attiny85). Default: from --board profile."
        ),
    )
    p_flash.add_argument(
        "--programmer", dest="programmer", default=None,
        help=(
            "Override `avrdude -c` programmer (e.g. stk500v1, usbtiny). "
            "Default: arduino (STK500v1 over serial)."
        ),
    )
    p_flash.add_argument(
        "--baud", dest="baud", type=int, default=None,
        help=(
            "Override the upload baud rate. Optiboot = 115200, "
            "Duemilanove = 57600, LilyPad = 19200."
        ),
    )
    p_flash.add_argument(
        "--verbose", "-v", dest="verbose", action="store_true",
        help="Pass `-v` through to avrdude for verbose progress.",
    )
    p_flash.add_argument(
        "--yes", dest="yes", action="store_true",
        help="Skip the confirmation prompt.",
    )

    # ---------- reset --------------------------------------------------------

    p_reset = subparsers.add_parser(
        "reset",
        help="Pulse DTR on the bridge to reset the attached AVR.",
        description=(
            "Briefly drop DTR on the USB-UART bridge to trigger the "
            "Arduino auto-reset circuit (DTR → 100 nF cap → AVR RESET). "
            "Effectively `press the reset button`. Boards without the "
            "DTR-coupling cap won't respond."
        ),
    )
    p_reset.add_argument(
        "--port", dest="port", default=None,
        help="Serial port of the USB-UART bridge (default: auto-detect).",
    )

    # ---------- monitor ------------------------------------------------------

    p_monitor = subparsers.add_parser(
        "monitor",
        help="Open a raw serial console to the AVR (Ctrl-] to exit).",
        description=(
            "Delegate to `python -m serial.tools.miniterm` — the "
            "pyserial-bundled mini-terminal. Replaces this process via "
            "execvp, so signals and TTY state flow through cleanly."
        ),
    )
    p_monitor.add_argument(
        "--port", dest="port", default=None,
        help="Serial port (default: auto-detect).",
    )
    p_monitor.add_argument(
        "--baud", dest="baud", type=int, default=9600,
        help=(
            "Application baud rate. Match whatever the sketch passes to "
            "`Serial.begin()` (Arduino's default is 9600)."
        ),
    )

    return parser


def _run_discover(args: argparse.Namespace) -> int:
    """Handle the ``discover`` subcommand and render the result."""
    devices = discover.discover(
        include_unknown=args.include_unknown, port=args.port,
    )
    if args.as_json:
        print(discover.format_json(devices))
    else:
        print(discover.format_table(devices))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    match args.command:
        case "discover":
            return _run_discover(args)
        case "flash":
            return flash.run(args)
        case "reset":
            return reset.run(args)
        case "monitor":
            return monitor.run(args)
        case _:  # pragma: no cover - argparse required=True prevents this
            parser.error(f"unknown command: {args.command!r}")
            return 2


if __name__ == "__main__":
    sys.exit(main())
