"""Tool 2: Flash MicroPython firmware onto an ESP32-family board.

Dispatches to a method-specific backend based on the board profile:

* ``esptool`` — ESP32 ROM serial-download flow. Used for generic ESP32 boards.
* ``dfu``     — shells out to ``dfu-util`` and targets the board's factory
  USB DFU bootloader. Used for the Arduino Nano ESP32. Preserves the factory
  DFU bootloader rather than overwriting it.

**Arduino Nano ESP32 flow (dfu):** with the board running normally, start
``esp32 flash``. When the tool prompts, double-tap the RESET button. The
board's serial port will disappear and a DFU device will enumerate under
the same VID/PID; ``dfu-util`` then writes the ``.uf2`` and issues a reset.
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
from esp32._mpy import MpyError, resolve_port
from esp32.boards import BoardProfile
from esp32.firmware import FirmwareResolutionError, ResolvedFirmware


class FlashError(RuntimeError):
    """Raised for recoverable flash-flow errors (missing port, tool failure, etc.)."""


@dataclass(frozen=True)
class FlashPlan:
    """Everything needed to flash, assembled before user confirmation."""

    port: str | None  # None allowed for DFU boards already in bootloader mode.
    board: BoardProfile
    firmware: ResolvedFirmware
    baud: int
    erase_first: bool


def _resolve_board(explicit_slug: str | None, port: str | None) -> BoardProfile:
    """Return the :class:`BoardProfile` for the target board.

    Resolution order: explicit ``--board`` → inferred from port's USB
    fingerprint → error. If ``port`` is ``None`` (e.g. board already in DFU
    mode with no serial port), ``--board`` is required.
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
            "No serial port found and --board not given. "
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
        sig_label = matches[0].signature.label if matches[0].signature else "unknown"
        known = ", ".join(b.slug for b in boards.BOARD_PROFILES)
        raise FlashError(
            f"Can't infer board from {port}'s USB fingerprint ({sig_label}).\n"
            f"  Pass --board <slug>. Known: {known}"
        )
    return inferred


def _confirm(plan: FlashPlan) -> bool:
    """Print the flash plan and prompt the user for a yes/no."""
    print("About to flash:")
    print(f"  Board       : {plan.board.display_name} ({plan.board.slug})")
    print(f"  Method      : {plan.board.flash_method}")
    print(f"  Firmware    : {plan.firmware.source_description}")

    if plan.board.flash_method == "esptool":
        print(f"  Port        : {plan.port}")
        print(f"  Chip        : {plan.board.chip}")
        print(f"  Flash offset: 0x{plan.board.flash_offset:X}")
        print(f"  Baud        : {plan.baud}")
        print(f"  Erase first : {plan.erase_first}")
    else:  # dfu
        assert plan.board.dfu_vid_pid is not None
        vid, pid = plan.board.dfu_vid_pid
        print(f"  DFU target  : {vid:04x}:{pid:04x} (alt {plan.board.dfu_alt})")
        print("  Action      : double-tap RESET on the board when prompted")
        if plan.erase_first:
            print("  Note        : --erase has no effect on DFU boards (ignored)")

    try:
        reply = input("Continue? [y/N] ").strip().lower()
    except EOFError:
        return False
    return reply in {"y", "yes"}


# ---------- esptool method ---------------------------------------------------


def _run_esptool(argv: list[str]) -> None:
    """Invoke esptool, streaming stdout/stderr to the terminal."""
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


# ---------- dfu-util method --------------------------------------------------


_DFU_WAIT_TIMEOUT_SECS = 60.0
_DFU_POLL_INTERVAL_SECS = 0.5


def _dfu_util_path() -> str:
    """Locate the ``dfu-util`` binary or raise :class:`FlashError`."""
    binary = shutil.which("dfu-util")
    if binary is None:
        raise FlashError(
            "dfu-util not found on PATH. Install it with `brew install dfu-util` "
            "(macOS) or your distro's package manager."
        )
    return binary


def _dfu_device_present(vid: int, pid: int) -> bool:
    """Return whether a DFU device matching ``vid:pid`` is currently enumerated.

    Uses ``dfu-util -l`` which prints an entry like
    ``Found DFU: [2341:0070] ...`` for each DFU-class USB device.
    """
    binary = _dfu_util_path()
    # -l lists DFU devices; with -d it only reports the matching ones. Stderr
    # carries permission warnings on some macOS setups — we ignore it.
    proc = subprocess.run(
        [binary, "-l", "-d", f"{vid:04x}:{pid:04x}"],
        capture_output=True,
        text=True,
        check=False,
    )
    # dfu-util prints "Found DFU: [VID:PID] ..." on match.
    return "Found DFU" in proc.stdout


def _wait_for_dfu_device(
    vid: int,
    pid: int,
    timeout: float = _DFU_WAIT_TIMEOUT_SECS,
) -> None:
    """Poll for the target DFU device to appear, printing guidance on the way.

    Raises:
        FlashError: on timeout.
    """
    # Fast path: already in DFU mode.
    if _dfu_device_present(vid, pid):
        return

    print(
        f"\nWaiting for DFU device {vid:04x}:{pid:04x} to enumerate ...\n"
        "  Arduino Nano ESP32: double-tap the RESET (blue) button now.\n"
        f"  (Timeout in {timeout:.0f}s — Ctrl-C to abort.)",
        flush=True,
    )
    deadline = time.monotonic() + timeout
    while True:
        if _dfu_device_present(vid, pid):
            print("DFU device detected.")
            return
        if time.monotonic() >= deadline:
            raise FlashError(
                f"Timed out after {timeout:.0f}s waiting for DFU device "
                f"{vid:04x}:{pid:04x}. Did you double-tap RESET? If the LED is "
                "pulsing slowly, the bootloader is active but not being seen — "
                "check `dfu-util -l` manually."
            )
        time.sleep(_DFU_POLL_INTERVAL_SECS)


def _flash_dfu(plan: FlashPlan) -> None:
    """Wait for the DFU device, then run ``dfu-util`` to write and reset."""
    assert plan.board.dfu_vid_pid is not None, "dfu path requires dfu_vid_pid"
    vid, pid = plan.board.dfu_vid_pid

    binary = _dfu_util_path()
    _wait_for_dfu_device(vid, pid)

    cmd = [
        binary,
        "-d", f"{vid:04x}:{pid:04x}",
        "-a", str(plan.board.dfu_alt),
        "-R",  # reset + run firmware after download
        "-D", str(plan.firmware.path),
    ]
    print(f"\n$ {' '.join(cmd)}\n", flush=True)
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise FlashError(f"dfu-util exited with status {result.returncode}")


# ---------- orchestrator -----------------------------------------------------


def flash(plan: FlashPlan) -> None:
    """Dispatch to the backend matching the board's flash method."""
    if plan.board.flash_method == "esptool":
        _flash_esptool(plan)
    elif plan.board.flash_method == "dfu":
        _flash_dfu(plan)
    else:  # pragma: no cover - Literal keeps this unreachable
        raise FlashError(f"Unknown flash method: {plan.board.flash_method}")


def run(args: argparse.Namespace) -> int:
    """Entry point for the ``esp32 flash`` subcommand."""
    try:
        # Try to find a serial port, but don't require one — DFU boards might
        # already be in bootloader mode (no serial port). prefer_micropython
        # is False because pre-flash the board may still be running Arduino
        # stock firmware, which uses a different USB PID than the MicroPython
        # build.
        port = resolve_port(
            args.port, prefer_micropython=False, allow_empty=True
        )
        board = _resolve_board(args.board, port)

        # esptool boards *do* need a serial port; enforce now that we know
        # the method.
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
    except (FlashError, FirmwareResolutionError, MpyError) as exc:
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

    print("\nDone. The board should reboot into MicroPython shortly.")
    return 0
