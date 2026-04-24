"""Tool 2: Flash MicroPython firmware onto an ESP32-family board.

Resolves (port, board profile, firmware binary), prompts for confirmation,
then shells out to ``esptool`` to write the image. ``esptool`` is installed
as a runtime dependency so the command is available inside the project venv.

**Arduino Nano ESP32 note:** the board must be in bootloader/DFU mode before
flashing — double-tap the RESET button and the port name will change (typical
pattern: ``/dev/cu.usbmodem...`` → a new ``/dev/cu.usbmodem...`` with a
different suffix). Re-run ``esp32 discover`` to find the new port.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from esp32 import boards, discover, firmware
from esp32.boards import BoardProfile
from esp32.firmware import FirmwareResolutionError, ResolvedFirmware


class FlashError(RuntimeError):
    """Raised for recoverable flash-flow errors (missing port, esptool failure, etc.)."""


@dataclass(frozen=True)
class FlashPlan:
    """Everything needed to invoke esptool, assembled before user confirmation."""

    port: str
    board: BoardProfile
    firmware: ResolvedFirmware
    baud: int
    erase_first: bool


def _resolve_port(explicit_port: str | None) -> str:
    """Return the serial port to flash — explicit if given, else the sole
    auto-detected ESP32 port on the host.

    Raises:
        FlashError: if no ESP32 is found, or if multiple are found and the user
            didn't disambiguate with ``--port``.
    """
    if explicit_port is not None:
        return explicit_port

    devices = discover.discover(include_unknown=False)
    if not devices:
        raise FlashError(
            "No ESP32 devices found on USB.\n"
            "  - Make sure the board is plugged in.\n"
            "  - For Arduino Nano ESP32: double-tap the RESET button to enter DFU mode.\n"
            "  - Then re-run with --port if auto-detection still fails."
        )
    if len(devices) > 1:
        port_list = ", ".join(d.port for d in devices)
        raise FlashError(
            f"Multiple ESP32 devices found ({port_list}). "
            "Disambiguate with --port <path>."
        )
    return devices[0].port


def _resolve_board(explicit_slug: str | None, port: str) -> BoardProfile:
    """Return the :class:`BoardProfile` for the target board.

    Resolution order: explicit ``--board`` flag → inferred from the port's USB
    fingerprint → error.
    """
    if explicit_slug is not None:
        profile = boards.by_slug(explicit_slug)
        if profile is None:
            known = ", ".join(b.slug for b in boards.BOARD_PROFILES)
            raise FlashError(
                f"Unknown --board slug: {explicit_slug!r}. Known slugs: {known}"
            )
        return profile

    matches = discover.discover(include_unknown=False, port=port)
    if not matches:
        raise FlashError(
            f"Port {port} does not appear to be an ESP32. "
            "Pass --board <slug> to override."
        )
    inferred = boards.infer_from_signature(matches[0].signature)
    if inferred is None:
        known = ", ".join(b.slug for b in boards.BOARD_PROFILES)
        raise FlashError(
            f"Can't infer board from {port}'s USB fingerprint "
            f"({matches[0].signature.label if matches[0].signature else 'unknown'}). "
            f"Pass --board <slug>. Known: {known}"
        )
    return inferred


def _confirm(plan: FlashPlan) -> bool:
    """Print the flash plan and ask the user to confirm with ``y``/``Y``."""
    print("About to flash:")
    print(f"  Port          : {plan.port}")
    print(f"  Board         : {plan.board.display_name} ({plan.board.slug})")
    print(f"  Chip (esptool): {plan.board.chip}")
    print(f"  Flash offset  : 0x{plan.board.flash_offset:X}")
    print(f"  Baud          : {plan.baud}")
    print(f"  Firmware      : {plan.firmware.source_description}")
    print(f"  Erase first   : {plan.erase_first}")
    try:
        reply = input("Continue? [y/N] ").strip().lower()
    except EOFError:
        return False
    return reply in {"y", "yes"}


def _run_esptool(argv: list[str]) -> None:
    """Invoke esptool, streaming stdout/stderr to the terminal.

    Raises:
        FlashError: If ``esptool`` isn't on PATH or it exits non-zero.
    """
    binary = shutil.which("esptool") or shutil.which("esptool.py")
    if binary is None:
        raise FlashError(
            "esptool not found on PATH. Re-run `uv sync` (or "
            "`pip install esptool`) to install the dependency."
        )
    cmd = [binary, *argv]
    print(f"\n$ {' '.join(cmd)}\n", flush=True)
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise FlashError(f"esptool exited with status {result.returncode}")


def flash(plan: FlashPlan) -> None:
    """Execute ``plan``: optional erase, then write firmware at the board's offset."""
    common = [
        "--chip", plan.board.chip,
        "--port", plan.port,
        "--baud", str(plan.baud),
    ]
    if plan.erase_first:
        _run_esptool([*common, "erase_flash"])
    _run_esptool(
        [
            *common,
            "write_flash",
            "-z",
            f"0x{plan.board.flash_offset:X}",
            str(plan.firmware.path),
        ]
    )


def run(args: argparse.Namespace) -> int:
    """Entry point for the ``esp32 flash`` subcommand."""
    try:
        port = _resolve_port(args.port)
        board = _resolve_board(args.board, port)
        resolved = firmware.resolve(
            board=board,
            local_path=Path(args.firmware) if args.firmware else None,
            override_url=args.firmware_url,
        )
        plan = FlashPlan(
            port=port,
            board=board,
            firmware=resolved,
            baud=args.baud,
            erase_first=args.erase,
        )
    except (FlashError, FirmwareResolutionError) as exc:
        print(f"esp32 flash: {exc}", file=sys.stderr)
        return 1

    if not args.yes and not _confirm(plan):
        print("Aborted.", file=sys.stderr)
        return 1

    try:
        flash(plan)
    except FlashError as exc:
        print(f"esp32 flash: {exc}", file=sys.stderr)
        return 1

    print("\nDone. If this was a fresh MicroPython install, press RESET to boot it.")
    return 0
