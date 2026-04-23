"""CLI entry point for the ``esp32`` console script.

Exposes subcommands for each of the four tools described in ``CLAUDE.md``:

* ``discover`` — Tool 1 (implemented): enumerate ESP32-family USB devices.
* ``flash``    — Tool 2 (stub): write MicroPython firmware.
* ``push``     — Tool 3a (stub): upload code to the device.
* ``pull``     — Tool 3b (stub): download code from the device.
* ``wifi``     — Tool 4 (stub): configure a Wi-Fi IP.
"""

from __future__ import annotations

import argparse
import sys

from esp32 import __version__, code, discover, flash, wifi


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands wired up."""
    parser = argparse.ArgumentParser(
        prog="esp32",
        description="CLI tools for ESP32-family microcontrollers.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"esp32 {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_discover = subparsers.add_parser(
        "discover",
        help="List ESP32-family devices connected via USB.",
    )
    p_discover.add_argument(
        "--all",
        dest="include_unknown",
        action="store_true",
        help="Include USB serial ports that do not match a known ESP32 fingerprint.",
    )
    p_discover.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit JSON instead of a text table.",
    )
    p_discover.add_argument(
        "--port",
        dest="port",
        default=None,
        help="Inspect only the given port path (e.g. /dev/cu.usbmodem1101).",
    )

    subparsers.add_parser("flash", help="(stub) Flash MicroPython firmware onto a device.")
    subparsers.add_parser("push", help="(stub) Push code to a device.")
    subparsers.add_parser("pull", help="(stub) Pull code from a device.")
    subparsers.add_parser("wifi", help="(stub) Configure a Wi-Fi IP on the device.")

    return parser


def _run_discover(args: argparse.Namespace) -> int:
    """Handle the ``discover`` subcommand and render the result."""
    devices = discover.discover(
        include_unknown=args.include_unknown,
        port=args.port,
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
        case "push":
            return code.run_push(args)
        case "pull":
            return code.run_pull(args)
        case "wifi":
            return wifi.run(args)
        case _:  # pragma: no cover - argparse required=True prevents this
            parser.error(f"unknown command: {args.command!r}")
            return 2


if __name__ == "__main__":
    sys.exit(main())
