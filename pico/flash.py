"""Tool 2 (Pico family): flash MicroPython onto a Raspberry Pi Pico.

This is a scaffold — the real implementation lives in a follow-up
commit. Two flash backends are planned:

* **UF2-MSC** (default) — wait for the BOOTSEL mass-storage volume to
  appear, copy the ``.uf2`` onto it, wait for the volume to detach.
  Hold BOOTSEL while plugging in to enter this mode.
* **picotool** (fallback) — used when the device is in app mode (so
  no BOOTSEL volume is mounted) and ``picotool`` is on PATH.
  ``--via picotool`` forces it; ``--via uf2`` forces the MSC path.
"""

from __future__ import annotations

import argparse
import sys


def run(args: argparse.Namespace) -> int:
    """Entry point for ``pico flash``. Stubbed until the UF2/picotool
    implementation lands."""
    del args  # silence unused-arg lint
    print(
        "pico flash: not implemented yet. "
        "Hold BOOTSEL on the Pico while plugging in, then copy a .uf2 "
        "onto the mounted RPI-RP2 (RP2040) or RP2350 volume by hand.",
        file=sys.stderr,
    )
    return 1
