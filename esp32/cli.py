"""CLI entry point for the ``esp32`` console script.

Exposes subcommands for each of the four tools described in ``CLAUDE.md``:

* ``discover`` — Tool 1 (implemented): enumerate ESP32-family USB devices.
* ``flash``    — Tool 2 (implemented): write MicroPython firmware.
* ``push``     — Tool 3a (implemented): upload code to the device via mpremote.
* ``pull``     — Tool 3b (implemented): download code from the device via mpremote.
* ``ls``       — Tool 3c (implemented): list files on the device.
* ``wifi``     — Tool 4 (implemented): configure Wi-Fi (DHCP or static IP).
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

    p_flash = subparsers.add_parser(
        "flash",
        help="Flash MicroPython firmware onto an ESP32-family board.",
        description=(
            "Flash MicroPython firmware onto an ESP32-family board via esptool. "
            "Arduino Nano ESP32: double-tap RESET to enter DFU mode before flashing."
        ),
    )
    p_flash.add_argument(
        "--port",
        dest="port",
        default=None,
        help="Serial port to flash (default: auto-detect the only ESP32 on USB).",
    )
    p_flash.add_argument(
        "--board",
        dest="board",
        default=None,
        help="micropython.org board slug (default: auto-infer from USB fingerprint).",
    )
    p_flash.add_argument(
        "--firmware",
        dest="firmware",
        default=None,
        help="Local path to a MicroPython .bin. Skips the download step.",
    )
    p_flash.add_argument(
        "--firmware-url",
        dest="firmware_url",
        default=None,
        help=(
            "Specific firmware URL to download "
            "(default: scrape micropython.org for latest stable)."
        ),
    )
    p_flash.add_argument(
        "--baud",
        dest="baud",
        type=int,
        default=460800,
        help="Flashing baud rate (default: 460800).",
    )
    p_flash.add_argument(
        "--erase",
        dest="erase",
        action="store_true",
        help="Erase the entire flash before writing firmware.",
    )
    p_flash.add_argument(
        "--yes",
        dest="yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )

    p_push = subparsers.add_parser(
        "push",
        help="Copy a local file or directory onto the device.",
        description=(
            "Copy a local file or directory onto the device's filesystem via "
            "mpremote. Directories are copied recursively."
        ),
    )
    p_push.add_argument("local", help="Local path to copy (file or directory).")
    p_push.add_argument(
        "remote",
        nargs="?",
        default=None,
        help=(
            "Destination path on the device (e.g. main.py, /lib/foo). "
            "Default: the local basename at device root."
        ),
    )
    p_push.add_argument(
        "--port",
        dest="port",
        default=None,
        help="Serial port (default: auto-detect a MicroPython-running ESP32).",
    )

    p_pull = subparsers.add_parser(
        "pull",
        help="Copy a file or directory off the device.",
        description=(
            "Copy a file or directory off the device's filesystem via "
            "mpremote. Use --all <dir> to back up every file on the device."
        ),
    )
    p_pull.add_argument(
        "remote",
        nargs="?",
        default=None,
        help="Source path on the device (e.g. main.py). Omit when using --all.",
    )
    p_pull.add_argument(
        "local",
        nargs="?",
        default=None,
        help="Destination path on the host. Default: the remote basename in CWD.",
    )
    p_pull.add_argument(
        "--recursive",
        "-r",
        dest="recursive",
        action="store_true",
        help="Copy recursively (required when pulling a directory).",
    )
    p_pull.add_argument(
        "--all",
        dest="all_into",
        metavar="DIR",
        default=None,
        help=(
            "Pull every file from the device into DIR, mirroring the "
            "device's subdirectory structure. Mutually exclusive with the "
            "positional remote arg."
        ),
    )
    p_pull.add_argument(
        "--quiet",
        "-q",
        dest="quiet",
        action="store_true",
        help=(
            "Suppress per-file `mpremote` echoes. Summary lines and errors "
            "still print."
        ),
    )
    p_pull.add_argument(
        "--port",
        dest="port",
        default=None,
        help="Serial port (default: auto-detect a MicroPython-running ESP32).",
    )

    p_ls = subparsers.add_parser(
        "ls",
        help="List files on the device.",
    )
    p_ls.add_argument(
        "remote",
        nargs="?",
        default=None,
        help="Directory on the device to list (default: root).",
    )
    p_ls.add_argument(
        "--port",
        dest="port",
        default=None,
        help="Serial port (default: auto-detect a MicroPython-running ESP32).",
    )

    p_wifi = subparsers.add_parser(
        "wifi",
        help="Connect to a Wi-Fi network and optionally set a static IP.",
        description=(
            "Drive the ESP32's Wi-Fi STA interface via mpremote exec: "
            "connect to an SSID, optionally pin a static IP, optionally "
            "persist the config on the device."
        ),
    )
    wifi.add_arguments(p_wifi)

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
        case "ls":
            return code.run_ls(args)
        case "wifi":
            return wifi.run(args)
        case _:  # pragma: no cover - argparse required=True prevents this
            parser.error(f"unknown command: {args.command!r}")
            return 2


if __name__ == "__main__":
    sys.exit(main())
