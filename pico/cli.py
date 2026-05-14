"""CLI entry point for the ``pico`` console script.

Sibling of :mod:`esp32.cli`. The bulk of the runners live in
:mod:`common` and are chip-agnostic — this module supplies the Pico
:class:`common.family.FamilyContext` that adapts them to Raspberry Pi
Pico USB fingerprints and ports.

Subcommands:

* ``discover`` — enumerate Pico-family USB devices (serial + BOOTSEL).
* ``flash``    — write MicroPython firmware (UF2-MSC / picotool).
* ``push``     — upload code to the device via mpremote.
* ``pull``     — download code from the device via mpremote.
* ``ls``       — list files on the device.
* ``wifi``     — configure Wi-Fi (Pico W only).
* ``repl``     — drop into the device's MicroPython REPL.
* ``info``     — one-shot summary of a connected device's state.
* ``reset``    — hard- or soft-reset the device.
* ``mip``      — install a MicroPython package via mip (needs Wi-Fi).
* ``lint``     — static analysis for chip-pin hazards.
"""

from __future__ import annotations

import argparse
import sys
from importlib.resources import files
from pathlib import Path

from common import code, mip, repl, reset, wifi
from common.family import FamilyContext
from pico import (
    __version__,
    discover,
    flash,
    info,
    lint,
)
from pico._mpy import resolve_port

# One FamilyContext for every subcommand dispatch. Built once at import
# time so it's cheap to pass into the shared runners.
PICO_FAMILY = FamilyContext(name="pico", resolve_port=resolve_port)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands wired up."""
    parser = argparse.ArgumentParser(
        prog="pico",
        description="CLI tools for Raspberry Pi Pico-family microcontrollers.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pico {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p_discover = subparsers.add_parser(
        "discover",
        help="List Pico-family devices connected via USB.",
        description=(
            "Enumerate Raspberry Pi Pico-family devices: serial-mode "
            "(running firmware, /dev/ttyACM*) and BOOTSEL-mode "
            "(mounted as USB mass storage). --probe queries serial "
            "devices for chip / board profile; BOOTSEL devices already "
            "have chip info on the mounted volume."
        ),
    )
    p_discover.add_argument(
        "--all",
        dest="include_unknown",
        action="store_true",
        help="Include USB serial ports that do not match a known Pico fingerprint.",
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
        help="Inspect only the given port path (e.g. /dev/ttyACM0).",
    )
    p_discover.add_argument(
        "--probe",
        dest="probe",
        action="store_true",
        help=(
            "Talk to each serial-mode device to identify the actual chip "
            "family and board profile (adds CHIP / PROFILE columns). "
            "Non-invasive: only works on ports already running MicroPython."
        ),
    )
    p_discover.add_argument(
        "--doc",
        dest="doc",
        action="store_true",
        help=(
            "After probing, write a markdown pin-reference file for each "
            "detected chip family (e.g. `RP2040.md`) into the current "
            "directory. Implies --probe (so serial-mode Picos get probed; "
            "BOOTSEL-mode Picos already report chip from INFO_UF2.TXT)."
        ),
    )

    p_flash = subparsers.add_parser(
        "flash",
        help="Flash MicroPython firmware onto a Pico (UF2 drag-and-drop or picotool).",
        description=(
            "Flash MicroPython onto a Pico-family board. Default path: "
            "wait for the BOOTSEL mass-storage volume to appear, copy "
            "the .uf2 onto it, wait for the device to detach. Falls "
            "back to `picotool` when the device is in app mode and "
            "picotool is on PATH; --via {uf2,picotool} overrides."
        ),
    )
    p_flash.add_argument(
        "--port",
        dest="port",
        default=None,
        help="Serial port or BOOTSEL mount path (default: auto-detect).",
    )
    p_flash.add_argument(
        "--board",
        dest="board",
        default=None,
        help="micropython.org board slug (default: auto-detect from BOOTSEL volume).",
    )
    p_flash.add_argument(
        "--firmware",
        dest="firmware",
        default=None,
        help="Local path to a MicroPython .uf2. Skips the download step.",
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
        "--via",
        dest="via",
        choices=("uf2", "picotool"),
        default=None,
        help="Force a specific flash backend (default: auto).",
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
        help="Serial port (default: auto-detect a MicroPython-running Pico).",
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
            "device's subdirectory structure."
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
        help="Serial port (default: auto-detect a MicroPython-running Pico).",
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
        help="Serial port (default: auto-detect a MicroPython-running Pico).",
    )

    p_wifi = subparsers.add_parser(
        "wifi",
        help="Connect to a Wi-Fi network and optionally set a static IP (Pico W).",
        description=(
            "Drive the Pico W's Wi-Fi STA interface via mpremote: "
            "connect to an SSID, optionally pin a static IP, optionally "
            "persist the config on the device. Untested on hardware "
            "(no Pico W on hand); should match the ESP32 behavior since "
            "MicroPython's network.WLAN(STA_IF) API is identical."
        ),
    )
    wifi.add_arguments(p_wifi)

    p_repl = subparsers.add_parser(
        "repl",
        help="Drop into the MicroPython REPL on the connected device.",
    )
    p_repl.add_argument(
        "--port",
        dest="port",
        default=None,
        help="Serial port (default: auto-detect a MicroPython-running Pico).",
    )

    p_info = subparsers.add_parser(
        "info",
        help="Print a one-shot summary of the connected device.",
    )
    p_info.add_argument(
        "--port",
        dest="port",
        default=None,
        help="Serial port (default: auto-detect a MicroPython-running Pico).",
    )
    p_info.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit JSON instead of the aligned text block.",
    )

    p_reset = subparsers.add_parser(
        "reset",
        help="Reset the device (hard by default; --soft for a REPL soft-reset).",
    )
    p_reset.add_argument(
        "--port",
        dest="port",
        default=None,
        help="Serial port (default: auto-detect a MicroPython-running Pico).",
    )
    p_reset.add_argument(
        "--soft",
        dest="soft",
        action="store_true",
        help="Soft-reset (Ctrl-D in REPL) instead of the default hard reset.",
    )

    p_lint = subparsers.add_parser(
        "lint",
        help="Static-analyze MicroPython source for chip-pin hazards.",
        description=(
            "AST-walks the given file or directory, flags Pin(N) calls "
            "(and peripheral kwargs like scl=, sck=) that hit reserved "
            "or advisory pins on the target chip family. Use --chip to "
            "skip the device probe; --json for machine-readable output."
        ),
    )
    p_lint.add_argument(
        "target",
        help="Python file or directory to lint.",
    )
    p_lint.add_argument(
        "--chip",
        dest="chip",
        default=None,
        help=(
            "Chip family to check against (e.g. RP2040). Default: probe "
            "the connected device. Pass explicitly to skip the probe."
        ),
    )
    p_lint.add_argument(
        "--port",
        dest="port",
        default=None,
        help=(
            "Serial port for the device probe (used only when --chip "
            "isn't given). Default: auto-detect."
        ),
    )
    p_lint.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit JSON instead of the aligned text block.",
    )

    p_mip = subparsers.add_parser(
        "mip",
        help="Install a MicroPython package on the device via mip (needs Wi-Fi).",
        description=(
            "Install a MicroPython package via mip. Requires the device "
            "to have internet access — Pico W only, with Wi-Fi "
            "established at boot via `_wifi_cfg.py`. Untested on "
            "hardware (no Pico W on hand)."
        ),
    )
    p_mip.add_argument(
        "package",
        help=(
            "Package spec. Examples: `umqtt.simple`, `github:user/repo`."
        ),
    )
    p_mip.add_argument(
        "--port",
        dest="port",
        default=None,
        help="Serial port (default: auto-detect a MicroPython-running Pico).",
    )

    return parser


def _run_discover(args: argparse.Namespace) -> int:
    """Handle the ``discover`` subcommand and render the result."""
    # --doc implies --probe so we can fill the CHIP field for
    # serial-mode Picos. BOOTSEL devices already carry chip info from
    # INFO_UF2.TXT regardless.
    probe = args.probe or args.doc
    devices = discover.discover(
        include_unknown=args.include_unknown,
        port=args.port,
        probe=probe,
    )
    if args.as_json:
        print(discover.format_json(devices))
    else:
        print(discover.format_table(devices))

    if args.doc:
        _write_chip_docs(devices)

    return 0


def _write_chip_docs(devices: list[discover.DiscoveredDevice]) -> None:
    """Dump a ``<CHIP>.md`` reference into the current directory for each
    distinct chip family present in ``devices``.

    Skips placeholder chip strings (``"(no mpy)"`` etc.) and chips with
    no bundled template — a one-line note goes to stderr for those.
    """
    seen: set[str] = set()
    for dev in devices:
        if dev.chip is None or dev.chip.startswith("("):
            continue
        if dev.chip in seen:
            continue
        seen.add(dev.chip)
        _write_one_chip_doc(dev.chip, dev)


def _write_one_chip_doc(
    chip: str, dev: discover.DiscoveredDevice
) -> None:
    """Look up the bundled template for ``chip`` and write it (with a
    short detection header) to ``./<chip>.md``."""
    try:
        template = (
            files("pico") / "docs" / f"{chip}.md"
        ).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(
            f"pico discover --doc: no template for {chip} bundled yet "
            f"(detected on {dev.port}; RP2040 and RP2350 are shipped today)",
            file=sys.stderr,
        )
        return

    header = (
        f"> **Detected:** `{chip}` chip, "
        f"`{dev.profile or '(unknown profile)'}` on `{dev.port}` "
        f"(mode={dev.mode}).\n"
        f"> Auto-generated by `pico discover --probe --doc`. Edit a copy "
        f"rather than this file — re-running --doc will overwrite.\n\n"
    )
    out_path = Path.cwd() / f"{chip}.md"
    out_path.write_text(header + template, encoding="utf-8")
    print(f"pico discover --doc: wrote {out_path}", file=sys.stderr)


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
            return code.run_push(args, family=PICO_FAMILY)
        case "pull":
            return code.run_pull(args, family=PICO_FAMILY)
        case "ls":
            return code.run_ls(args, family=PICO_FAMILY)
        case "wifi":
            return wifi.run(args, family=PICO_FAMILY)
        case "repl":
            return repl.run(args, family=PICO_FAMILY)
        case "info":
            return info.run(args)
        case "reset":
            return reset.run(args, family=PICO_FAMILY)
        case "mip":
            return mip.run(args, family=PICO_FAMILY)
        case "lint":
            return lint.run(args)
        case _:  # pragma: no cover - argparse required=True prevents this
            parser.error(f"unknown command: {args.command!r}")
            return 2


if __name__ == "__main__":
    sys.exit(main())
