"""Tool 2 (AVR family): flash a compiled .hex onto an AVR via avrdude.

Default flow targets a stock ATmega328P with the Arduino bootloader
(optiboot at 115200 baud over an FT232 / CH340 / CP2102 USB-UART
bridge). Override ``--mcu`` / ``--programmer`` / ``--baud`` to talk
to other AVRs or older bootloader variants.

The actual flash is a single ``avrdude`` invocation:

    avrdude -c arduino -p atmega328p -P /dev/ttyUSB0 -b 115200 \\
            -D -U flash:w:<hex>:i

``-D`` disables the implicit erase cycle — the Arduino bootloader
(STK500v1) doesn't expose a chip-erase command, but optiboot erases
per-page during the write, so the right flag here is "don't try to
erase up front". Without ``-D`` the upload fails with a confusing
``stk500_recv()`` error.

This tool *does not* compile a sketch — the user runs
``arduino-cli compile`` / ``platformio run`` / ``avr-gcc`` separately
and passes the resulting Intel-HEX file as the positional argument.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from avr import boards, discover
from avr.boards import BoardProfile


class FlashError(RuntimeError):
    """Raised for recoverable flash-flow errors."""


# ---------- avrdude availability --------------------------------------------


def _avrdude_binary() -> str:
    """Return the path to ``avrdude``, or raise :class:`FlashError`."""
    binary = shutil.which("avrdude")
    if binary is None:
        raise FlashError(
            "`avrdude` not found on PATH. Install it first:\n"
            "  Debian/Ubuntu : sudo apt install avrdude\n"
            "  macOS (brew)  : brew install avrdude\n"
            "  Arch          : sudo pacman -S avrdude"
        )
    return binary


# ---------- profile / argument resolution -----------------------------------


def _resolve_profile(args: argparse.Namespace) -> BoardProfile:
    """Pick the :class:`BoardProfile` whose defaults drive avrdude.

    ``--board <slug>`` is the explicit path; the default is the
    standard ATmega328P + optiboot profile. ``--mcu`` / ``--programmer``
    / ``--baud`` override the profile field-by-field below, so the
    profile's main job is to set sensible defaults.
    """
    if args.board is None:
        return boards.ATMEGA328P_ARDUINO
    profile = boards.by_slug(args.board)
    if profile is None:
        known = ", ".join(b.slug for b in boards.BOARD_PROFILES)
        raise FlashError(
            f"Unknown --board: {args.board!r}. Known: {known}"
        )
    return profile


def _validate_hex(hex_path: Path, profile: BoardProfile) -> None:
    """Sanity-check the .hex file before invoking avrdude.

    Catches the easy "wrong file" mistakes early — pointing the tool at
    a binary instead of the Intel-HEX text, or at a hex that's larger
    than the chip's application flash region.
    """
    if not hex_path.is_file():
        raise FlashError(f"firmware file not found: {hex_path}")
    # Intel-HEX is ASCII text; the first byte of every record is a colon.
    with hex_path.open("rb") as fh:
        first = fh.read(1)
    if first != b":":
        raise FlashError(
            f"{hex_path} does not look like an Intel-HEX file (first byte "
            f"is {first!r}, expected b':'). Pass the .hex output of your "
            "compiler, not the .elf or .bin."
        )
    size_kb = hex_path.stat().st_size / 1024
    # Intel-HEX is ~2.5x larger than the binary it encodes (hex digits
    # + framing); the 4x multiplier is a conservative "this is obviously
    # too big for the part" guard, not a precise check.
    if size_kb > profile.flash_size_kb * 4:
        print(
            f"avr flash: warning — {hex_path.name} is {size_kb:.1f} KB of "
            f"Intel-HEX text; {profile.mcu} only has "
            f"{profile.flash_size_kb} KB of application flash. "
            f"avrdude will refuse the upload if the decoded binary "
            f"exceeds the chip's capacity.",
            file=sys.stderr,
        )


def _build_avrdude_argv(
    binary: str,
    *,
    port: str,
    hex_path: Path,
    profile: BoardProfile,
    mcu: str | None,
    programmer: str | None,
    baud: int | None,
    verbose: bool,
) -> list[str]:
    """Compose the full ``avrdude`` argv from profile + overrides."""
    cmd: list[str] = [
        binary,
        "-c", programmer or profile.programmer,
        "-p", mcu or profile.mcu,
        "-P", port,
        "-b", str(baud or profile.baud),
        # Skip the implicit chip-erase — Arduino bootloaders don't
        # support it and avrdude will error out without `-D`.
        "-D",
        "-U", f"flash:w:{hex_path}:i",
    ]
    if verbose:
        cmd.insert(1, "-v")
    return cmd


# ---------- confirmation -----------------------------------------------------


def _confirm(
    port: str, profile: BoardProfile, hex_path: Path,
    mcu: str | None, programmer: str | None, baud: int | None,
) -> bool:
    """Yes/no prompt unless the user passed ``--yes``."""
    print()
    print(f"  Port      : {port}")
    print(f"  MCU       : {mcu or profile.mcu}")
    print(f"  Programmer: {programmer or profile.programmer}")
    print(f"  Baud      : {baud or profile.baud}")
    print(f"  Firmware  : {hex_path}")
    print()
    try:
        answer = input("Proceed? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


# ---------- CLI entry --------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    """Entry point for ``avr flash``."""
    try:
        binary = _avrdude_binary()
        profile = _resolve_profile(args)
        hex_path = Path(args.firmware).expanduser().resolve()
        _validate_hex(hex_path, profile)
        port = discover.resolve_port(args.port)

        if not args.yes and not _confirm(
            port, profile, hex_path, args.mcu, args.programmer, args.baud,
        ):
            print("Aborted.", file=sys.stderr)
            return 1

        cmd = _build_avrdude_argv(
            binary,
            port=port,
            hex_path=hex_path,
            profile=profile,
            mcu=args.mcu,
            programmer=args.programmer,
            baud=args.baud,
            verbose=args.verbose,
        )
        print(f"$ {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            raise FlashError(
                f"avrdude exited with status {result.returncode}. "
                "Check the wiring (DTR → RESET via a 100 nF cap), confirm "
                "the bootloader baud matches, and try again."
            )
        print("Done. The AVR has been flashed and should be running the new sketch.")
        return 0
    except (FlashError, discover.PortResolutionError) as exc:
        print(f"avr flash: {exc}", file=sys.stderr)
        return 1
