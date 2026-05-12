"""Tool 7: reset the connected MicroPython device.

Thin wrapper over ``mpremote reset`` (hard reset, DTR/RTS toggled —
equivalent to a power-cycle for ``boot.py`` purposes) and
``mpremote soft-reset`` (Ctrl-D in REPL, preserves running RAM until
the next reboot but re-runs ``main.py``).
"""

from __future__ import annotations

import argparse
import sys

from esp32._mpy import MpyError, resolve_port, run_mpremote


def run(args: argparse.Namespace) -> int:
    """Entry point for ``esp32 reset``."""
    try:
        port = resolve_port(args.port)
        subcommand = "soft-reset" if args.soft else "reset"
        run_mpremote(port, [subcommand])
    except MpyError as exc:
        print(f"esp32 reset: {exc}", file=sys.stderr)
        return 1
    kind = "soft" if args.soft else "hard"
    print(f"{kind} reset issued; the device should be back up shortly.")
    return 0
