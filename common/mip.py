"""Install MicroPython packages on the device via mip.

Thin wrapper over ``mpremote mip install <package>`` with the same
auto-port resolution as the rest of the CLI.

**Why we chain ``exec "import _wifi_cfg"`` before mip:** mpremote does a
soft-reset on every new connection, which clears the wlan stack — and
``mip`` needs working network to fetch package metadata and files. By
chaining commands in one mpremote invocation (soft-reset happens once
at session start), we can re-establish Wi-Fi inside the same session
before mip runs.

This requires ``_wifi_cfg.py`` to exist on the device. Run
``<cli> wifi <SSID> --persist`` once to create it. If it isn't present,
the ``import`` step will fail with a clear ``ImportError`` before mip
even starts — that's the signal to set up persistent Wi-Fi first.
"""

from __future__ import annotations

import argparse
import sys

from common._mpy import MpyError, run_mpremote
from common.family import FamilyContext


def run(args: argparse.Namespace, *, family: FamilyContext) -> int:
    """Entry point for ``<cli> mip``."""
    try:
        port = family.resolve_port(args.port)
        # Chain commands within one mpremote session so the soft-reset
        # happens once at connect; we then re-establish Wi-Fi via
        # `import _wifi_cfg`, and mip's network fetch sees an active wlan.
        run_mpremote(
            port,
            ["exec", "import _wifi_cfg", "mip", "install", args.package],
        )
    except MpyError as exc:
        print(f"{family.name} mip: {exc}", file=sys.stderr)
        return 1
    return 0
