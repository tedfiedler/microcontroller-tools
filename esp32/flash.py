"""Tool 2 (stub): Flash MicroPython firmware onto an ESP32-family board.

Planned implementation: wrap ``esptool.py`` to download the correct MicroPython
firmware binary for the detected chip variant (ESP32 / S2 / S3 / C3), erase
flash if requested, and write the firmware to 0x0 (S-series) or 0x1000 (classic).
"""

from __future__ import annotations

import argparse

from esp32._stub import not_implemented


def run(args: argparse.Namespace) -> int:
    """Entry point for the ``esp32 flash`` subcommand. Currently a stub."""
    return not_implemented("flash", "Tool 2")
