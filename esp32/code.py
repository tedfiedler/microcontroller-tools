"""Tool 3 (stub): Push and pull code to/from an ESP32 running MicroPython.

Planned implementation: wrap ``mpremote`` (or speak the raw MicroPython paste-mode
protocol) to sync a local project directory to the device's filesystem, and to
pull device files back to the host.
"""

from __future__ import annotations

import argparse

from esp32._stub import not_implemented


def run_push(args: argparse.Namespace) -> int:
    """Entry point for the ``esp32 push`` subcommand. Currently a stub."""
    return not_implemented("push", "Tool 3a")


def run_pull(args: argparse.Namespace) -> int:
    """Entry point for the ``esp32 pull`` subcommand. Currently a stub."""
    return not_implemented("pull", "Tool 3b")
