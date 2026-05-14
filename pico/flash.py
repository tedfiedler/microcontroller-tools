"""Tool 2 (Pico family): flash MicroPython onto a Raspberry Pi Pico.

Two backends, auto-selected unless ``--via`` overrides:

* **UF2-MSC** (preferred when available) — wait for the BOOTSEL
  mass-storage volume to appear, copy the ``.uf2`` onto it, wait for
  the device to detach. This is what the user does by hand when
  dragging a UF2 onto the RPI-RP2 drive; we just automate it.
* **picotool** (used when there's no BOOTSEL mount and ``picotool`` is
  installed) — invokes ``picotool load`` with ``--force`` so it
  bounces a serial-mode Pico into BOOTSEL itself, flashes, then
  reboots. Works without filesystem automount, which makes it useful
  on headless / minimal Linux installs.

Board selection: ``--board <slug>`` is explicit; otherwise we read the
chip family off ``INFO_UF2.TXT`` on the BOOTSEL mount and default to
the non-Wi-Fi variant (``RPI_PICO`` for RP2040, ``RPI_PICO2`` for
RP2350). Pico W / Pico 2 W users **must** pass ``--board`` because
the BOOTSEL ROM gives us no way to tell those apart from their
non-W siblings.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from pico import boards, discover, firmware
from pico.boards import BoardProfile

# How long ``--via uf2`` / auto waits for a BOOTSEL mount to appear
# after the user is told to hold BOOTSEL and plug in. Picos enumerate
# in 1-3s typically; 60s is generous enough for slow USB hubs and
# automounts.
_BOOTSEL_WAIT_TIMEOUT_SECS = 60.0
# How long we wait for the volume to detach after the UF2 is written.
# A successful flash causes the Pico to reboot, which usually unmounts
# the volume within a few seconds.
_UNMOUNT_WAIT_TIMEOUT_SECS = 30.0
_POLL_INTERVAL_SECS = 0.5

Backend = Literal["uf2", "picotool"]


class FlashError(RuntimeError):
    """Raised for recoverable flash-flow errors."""


# ---------- backend selection ------------------------------------------------


def _picotool_available() -> bool:
    """True iff a ``picotool`` binary is on PATH."""
    return shutil.which("picotool") is not None


def _serial_pico_present() -> bool:
    """True iff at least one Pico in serial mode is enumerated."""
    return any(d.mode == "serial" for d in discover.discover(include_unknown=False))


def _detect_bootsel() -> tuple[Path, str] | None:
    """Return ``(mount_path, chip_family)`` for the first BOOTSEL Pico
    we can see, or ``None`` if no BOOTSEL volume is mounted."""
    found = discover._find_bootsel_mounts()
    return found[0] if found else None


def _pick_backend(args: argparse.Namespace) -> Backend:
    """Decide which flash backend to use, honoring ``--via`` if set.

    Auto rules:

    * BOOTSEL volume mounted → ``uf2``.
    * Else, ``picotool`` on PATH and a serial Pico is up → ``picotool``
      (it'll bounce the device into BOOTSEL itself).
    * Else → ``uf2`` (we'll wait for the user to hold BOOTSEL and plug
      in, then auto-mount happens).
    """
    if args.via is not None:
        if args.via == "picotool" and not _picotool_available():
            raise FlashError(
                "--via picotool given but `picotool` is not on PATH. "
                "Install it (e.g. `apt install picotool`) or use --via uf2."
            )
        backend: Backend = args.via
        return backend

    if _detect_bootsel() is not None:
        return "uf2"
    if _picotool_available() and _serial_pico_present():
        return "picotool"
    return "uf2"


# ---------- board / firmware resolution --------------------------------------


def _resolve_board(args: argparse.Namespace) -> BoardProfile:
    """Pick the :class:`BoardProfile` to flash.

    Order:

    1. ``--board <slug>`` explicit.
    2. Auto from BOOTSEL ``INFO_UF2.TXT`` chip family: RP2040 →
       ``RPI_PICO``, RP2350 → ``RPI_PICO2``. Pico W / Pico 2 W cannot
       be inferred here — the BOOTSEL ROM doesn't expose the cyw43
       presence — so we default to the non-W variant and warn.
    """
    if args.board is not None:
        profile = boards.by_slug(args.board)
        if profile is None:
            known = ", ".join(b.slug for b in boards.BOARD_PROFILES)
            raise FlashError(
                f"Unknown --board: {args.board!r}. Known: {known}"
            )
        return profile

    detected = _detect_bootsel()
    if detected is None:
        raise FlashError(
            "No BOOTSEL volume mounted and no --board given. Either "
            "hold BOOTSEL while plugging in the Pico, or pass "
            "--board <slug> (e.g. RPI_PICO, RPI_PICO_W, RPI_PICO2)."
        )

    _, chip = detected
    if chip == "RP2040":
        default = boards.RPI_PICO
    elif chip == "RP2350":
        default = boards.RPI_PICO2
    else:  # pragma: no cover - _detect_bootsel only returns these two
        raise FlashError(f"Unknown BOOTSEL chip family: {chip!r}")

    print(
        f"detected {chip} via BOOTSEL volume; defaulting to {default.slug}.",
        file=sys.stderr,
    )
    print(
        "  pass --board RPI_PICO_W (or RPI_PICO2_W) if your board has Wi-Fi.",
        file=sys.stderr,
    )
    return default


# ---------- UF2 backend ------------------------------------------------------


def _wait_for_bootsel(
    expected_label: str, *, timeout: float = _BOOTSEL_WAIT_TIMEOUT_SECS
) -> Path:
    """Block until a BOOTSEL volume with ``expected_label`` is mounted.

    If one is already mounted at call time, return its path immediately.
    Otherwise prompt the user once, then poll until either the volume
    appears or ``timeout`` elapses.
    """
    already = _detect_bootsel()
    if already is not None:
        mount, _ = already
        return mount

    print(
        f"Waiting for BOOTSEL volume {expected_label!r} to mount.\n"
        "  Hold BOOTSEL on the Pico while plugging in the USB cable. "
        "(Or if already plugged in: unplug, hold BOOTSEL, replug.)",
        file=sys.stderr,
    )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = _detect_bootsel()
        if found is not None:
            mount, _ = found
            print(f"  mounted at {mount}", file=sys.stderr)
            return mount
        time.sleep(_POLL_INTERVAL_SECS)

    raise FlashError(
        f"Timed out after {timeout:.0f}s waiting for a BOOTSEL volume. "
        "Re-plug while holding BOOTSEL, or check the cable / port."
    )


def _wait_for_unmount(
    mount: Path, *, timeout: float = _UNMOUNT_WAIT_TIMEOUT_SECS
) -> bool:
    """Block until ``mount`` no longer exists, or ``timeout`` elapses.

    Returns True if the mount detached cleanly. Returns False on
    timeout — not raised, because some Picos (especially under
    custom firmware) leave the volume mounted briefly even after a
    successful write; the user shouldn't see a noisy error in that
    case.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not mount.exists():
            return True
        time.sleep(_POLL_INTERVAL_SECS)
    return False


def _flash_uf2(board: BoardProfile, uf2_path: Path) -> int:
    """Copy ``uf2_path`` onto the Pico's BOOTSEL volume and wait for the
    reboot.

    The actual write is a single ``shutil.copy``. The Pico's ROM
    bootloader watches for any ``.uf2`` file landing on the volume,
    flashes it, and reboots into the new firmware — at which point
    the volume detaches and we know the flash succeeded.
    """
    mount = _wait_for_bootsel(board.bootsel_volume_label)
    target = mount / uf2_path.name

    print(f"Copying {uf2_path} → {target}", file=sys.stderr)
    try:
        shutil.copy(uf2_path, target)
    except OSError as exc:
        raise FlashError(f"failed to write UF2 to {target}: {exc}") from exc

    print("Waiting for the Pico to reboot into the new firmware …", file=sys.stderr)
    if _wait_for_unmount(mount):
        print("Done. The Pico is back up with the new firmware.")
    else:
        # Not necessarily a failure — print a softer note and return 0.
        print(
            "BOOTSEL volume is still mounted after writing the UF2; the "
            "Pico may not have rebooted yet. Power-cycle it if it doesn't "
            "come back on its own.",
            file=sys.stderr,
        )
    return 0


# ---------- picotool backend -------------------------------------------------


def _flash_picotool(board: BoardProfile, uf2_path: Path) -> int:
    """Run ``picotool load`` with ``--force`` to bounce-and-flash the Pico.

    ``picotool`` knows how to talk to both BOOTSEL-mode devices and to
    app-mode firmwares that include the picoboard library (which
    MicroPython does). ``--force`` lets it reset an app-mode Pico
    into BOOTSEL automatically before flashing.
    """
    del board  # unused: picotool figures out the chip itself.

    cmd = [
        "picotool",
        "load",
        "--force",  # bounce app-mode Pico into BOOTSEL if needed
        "--update",  # only write changed sectors
        "--verify",  # read back to confirm the flash matches
        str(uf2_path),
    ]
    print(f"$ {' '.join(cmd)}", flush=True)
    try:
        result = subprocess.run(cmd, check=False)
    except FileNotFoundError as exc:
        raise FlashError(
            "picotool not found on PATH (it was earlier — did the "
            "environment change?)."
        ) from exc

    if result.returncode != 0:
        raise FlashError(
            f"picotool exited with status {result.returncode}. "
            "Hold BOOTSEL and plug the Pico in, then re-run."
        )

    print("Rebooting the Pico into the new firmware …", file=sys.stderr)
    reboot = subprocess.run(["picotool", "reboot"], check=False)
    if reboot.returncode != 0:
        print(
            "  picotool reboot returned non-zero; the firmware was "
            "flashed but you may need to power-cycle the Pico manually.",
            file=sys.stderr,
        )
    return 0


# ---------- confirmation prompt ----------------------------------------------


def _confirm(board: BoardProfile, fw_description: str, backend: Backend) -> bool:
    """Yes/no prompt unless the user passed ``--yes``."""
    print()
    print(f"  Board   : {board.display_name} ({board.slug})")
    print(f"  Chip    : {board.chip}")
    print(f"  Backend : {backend}")
    print(f"  Firmware: {fw_description}")
    print()
    try:
        answer = input("Proceed? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


# ---------- CLI entry --------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    """Entry point for ``pico flash``."""
    try:
        board = _resolve_board(args)
        backend = _pick_backend(args)
        fw = firmware.resolve(
            board=board,
            local_path=Path(args.firmware).expanduser() if args.firmware else None,
            override_url=args.firmware_url,
        )

        if not args.yes and not _confirm(board, fw.source_description, backend):
            print("Aborted.", file=sys.stderr)
            return 1

        if backend == "uf2":
            return _flash_uf2(board, fw.path)
        return _flash_picotool(board, fw.path)
    except (FlashError, firmware.FirmwareResolutionError) as exc:
        print(f"pico flash: {exc}", file=sys.stderr)
        return 1
