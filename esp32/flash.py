"""Tool 2: Flash MicroPython firmware onto an ESP32-family board.

Dispatches to a method-specific flasher based on the board profile:

* ``esptool`` — shells out to the ``esptool`` CLI; ROM serial-download flow.
* ``uf2``     — waits for the board's UF2 mass-storage volume to mount (on
  macOS that's a directory under ``/Volumes/``), then copies the ``.uf2``
  file onto it; the board auto-reboots into the new firmware.

**Arduino Nano ESP32 note:** uses the ``uf2`` method. Double-tap the RESET
button to enter the bootloader; a USB volume will mount. You do *not* need
to run ``esp32 discover`` first for the UF2 flow — we watch ``/Volumes``
directly.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from esp32 import boards, discover, firmware
from esp32.boards import BoardProfile
from esp32.firmware import FirmwareResolutionError, ResolvedFirmware


class FlashError(RuntimeError):
    """Raised for recoverable flash-flow errors (missing port, tool failure, etc.)."""


@dataclass(frozen=True)
class FlashPlan:
    """Everything needed to flash, assembled before user confirmation."""

    port: str | None  # None for UF2 boards — we don't need a serial port.
    board: BoardProfile
    firmware: ResolvedFirmware
    baud: int
    erase_first: bool


def _resolve_port(explicit_port: str | None, required: bool) -> str | None:
    """Return the serial port for flashing, or ``None`` if not required.

    For UF2 boards (``required=False``) we tolerate no device being connected
    since the flasher watches ``/Volumes`` for the bootloader volume instead.

    Raises:
        FlashError: if ``required`` and we can't pick a single port.
    """
    if explicit_port is not None:
        return explicit_port

    devices = discover.discover(include_unknown=False)
    if not devices:
        if not required:
            return None
        raise FlashError(
            "No ESP32 devices found on USB. Plug one in and try again."
        )
    if len(devices) > 1:
        port_list = ", ".join(d.port for d in devices)
        raise FlashError(
            f"Multiple ESP32 devices found ({port_list}). "
            "Disambiguate with --port <path>."
        )
    return devices[0].port


def _resolve_board(explicit_slug: str | None, port: str | None) -> BoardProfile:
    """Return the :class:`BoardProfile` for the target board.

    Resolution order: explicit ``--board`` → inferred from the port's USB
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

    if port is None:
        known = ", ".join(b.slug for b in boards.BOARD_PROFILES)
        raise FlashError(
            f"Can't infer board without a connected device. "
            f"Pass --board <slug>. Known: {known}"
        )

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
    """Print the flash plan and prompt the user for a yes/no."""
    print("About to flash:")
    print(f"  Board         : {plan.board.display_name} ({plan.board.slug})")
    print(f"  Method        : {plan.board.flash_method}")
    if plan.board.flash_method == "esptool":
        print(f"  Port          : {plan.port}")
        print(f"  Chip (esptool): {plan.board.chip}")
        print(f"  Flash offset  : 0x{plan.board.flash_offset:X}")
        print(f"  Baud          : {plan.baud}")
        print(f"  Erase first   : {plan.erase_first}")
    else:
        print("  Action        : copy .uf2 to the board's UF2 mass-storage volume")
        if plan.erase_first:
            print("  Note          : --erase has no effect on UF2 boards (ignored)")
    print(f"  Firmware      : {plan.firmware.source_description}")
    try:
        reply = input("Continue? [y/N] ").strip().lower()
    except EOFError:
        return False
    return reply in {"y", "yes"}


# ---------- esptool method ---------------------------------------------------


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


def _flash_esptool(plan: FlashPlan) -> None:
    """Execute an esptool-based flash: optional erase, then write firmware."""
    assert plan.port is not None, "esptool path requires a serial port"
    common = [
        "--chip", plan.board.chip,
        "--port", plan.port,
        "--baud", str(plan.baud),
    ]
    # esptool v5.x renamed subcommands from ``foo_flash`` to ``foo-flash``;
    # the underscore form still works but emits a deprecation warning.
    if plan.erase_first:
        _run_esptool([*common, "erase-flash"])
    _run_esptool(
        [
            *common,
            "write-flash",
            "-z",
            f"0x{plan.board.flash_offset:X}",
            str(plan.firmware.path),
        ]
    )


# ---------- UF2 method -------------------------------------------------------


# UF2 bootloaders expose a FAT volume containing a well-known INFO_UF2.TXT
# file at the root. We use that as the discriminator, so the flasher works
# on any UF2 board (Nano ESP32, RP2040, etc.) without hardcoding volume names.
_UF2_INFO_FILE = "INFO_UF2.TXT"
_VOLUMES_ROOT = Path("/Volumes")
_UF2_MOUNT_TIMEOUT_SECS = 60.0
_UF2_POLL_INTERVAL_SECS = 0.5


def _find_uf2_volumes() -> list[Path]:
    """Return all currently-mounted volumes that look like a UF2 bootloader."""
    if not _VOLUMES_ROOT.is_dir():
        return []
    return [
        entry
        for entry in _VOLUMES_ROOT.iterdir()
        if entry.is_dir() and (entry / _UF2_INFO_FILE).is_file()
    ]


def _read_uf2_info(volume: Path) -> str:
    """Best-effort read of a volume's ``INFO_UF2.TXT`` (returns ``""`` on error)."""
    try:
        return (volume / _UF2_INFO_FILE).read_text(errors="replace")
    except OSError:
        return ""


def _wait_for_uf2_volume(timeout: float = _UF2_MOUNT_TIMEOUT_SECS) -> Path:
    """Poll ``/Volumes`` until a UF2 bootloader volume appears.

    Prints guidance the first time we fail to find one, then polls quietly.

    Raises:
        FlashError: On timeout or if multiple UF2 volumes are mounted at once
            (ambiguous — user should unplug one).
    """
    deadline = time.monotonic() + timeout
    hinted = False

    while True:
        volumes = _find_uf2_volumes()
        if len(volumes) == 1:
            return volumes[0]
        if len(volumes) > 1:
            names = ", ".join(str(v) for v in volumes)
            raise FlashError(
                f"Multiple UF2 volumes mounted ({names}). "
                "Unplug all but the target board and retry."
            )

        if not hinted:
            print(
                "\nWaiting for UF2 bootloader volume to mount under /Volumes ...\n"
                "  On the Arduino Nano ESP32: double-tap the RESET button now.\n"
                f"  (Timeout in {timeout:.0f}s — Ctrl-C to abort.)",
                flush=True,
            )
            hinted = True

        if time.monotonic() >= deadline:
            raise FlashError(
                f"Timed out after {timeout:.0f}s waiting for a UF2 volume. "
                "Did you double-tap RESET? Is the board's DFU bootloader intact?"
            )
        time.sleep(_UF2_POLL_INTERVAL_SECS)


def _flash_uf2(plan: FlashPlan) -> None:
    """Copy the firmware ``.uf2`` onto the board's bootloader volume.

    The write triggers the bootloader to flash the new firmware and reboot;
    the volume will unmount on its own, which we wait for as a success signal.
    """
    volume = _wait_for_uf2_volume()
    print(f"Found UF2 volume: {volume}")
    info = _read_uf2_info(volume)
    if info:
        first_line = info.splitlines()[0] if info.splitlines() else info
        print(f"  {first_line}")

    target = volume / plan.firmware.path.name
    print(f"Copying {plan.firmware.path} -> {target} ...")
    # Use copyfile (not copy2) because FAT volumes reject chmod/chown metadata
    # copies. The file contents are all we need.
    shutil.copyfile(plan.firmware.path, target)
    print(
        "Copy complete. The bootloader will now flash and reboot; "
        "the volume should unmount shortly."
    )

    # Wait (best-effort) for the volume to disappear — that's our "done" signal.
    deadline = time.monotonic() + 30.0
    while volume.exists():
        if time.monotonic() >= deadline:
            print(
                "Note: volume is still mounted after 30s. "
                "The flash may still have succeeded — check the board."
            )
            return
        time.sleep(_UF2_POLL_INTERVAL_SECS)
    print("Volume unmounted. Flash complete.")


# ---------- Orchestrator -----------------------------------------------------


def flash(plan: FlashPlan) -> None:
    """Dispatch to the appropriate backend based on the board's flash method."""
    if plan.board.flash_method == "esptool":
        _flash_esptool(plan)
    elif plan.board.flash_method == "uf2":
        _flash_uf2(plan)
    else:  # pragma: no cover - Literal keeps this unreachable
        raise FlashError(f"Unknown flash method: {plan.board.flash_method}")


def run(args: argparse.Namespace) -> int:
    """Entry point for the ``esp32 flash`` subcommand."""
    try:
        # First, figure out what board we're flashing — the flash method
        # determines whether we even need a serial port.
        #
        # If --board is given we use that. Otherwise we need to look at a
        # connected device to infer. For UF2 boards the application-mode
        # port gives us enough to infer (Arduino VID/PID), but after the
        # reset dance there won't be a port — hence the flexible flow.
        port = _resolve_port(args.port, required=False)
        board = _resolve_board(args.board, port)

        # Now we know the method, enforce the serial-port requirement for
        # esptool boards that didn't have one found above.
        if board.flash_method == "esptool" and port is None:
            raise FlashError(
                f"{board.display_name} is flashed via esptool and requires a "
                "serial port. Plug the board in, or pass --port."
            )

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
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 1

    print("\nDone. If this was a fresh MicroPython install, press RESET to boot it.")
    return 0
