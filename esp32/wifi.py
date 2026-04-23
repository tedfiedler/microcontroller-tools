"""Tool 4 (stub): Configure a static Wi-Fi IP on an ESP32's wireless interface.

Planned implementation: open the MicroPython REPL over serial, execute a short
script that configures ``network.WLAN(network.STA_IF)`` with ``ifconfig(...)``
using the provided static IP / netmask / gateway / DNS, and persist the settings
to a boot script on the device.
"""

from __future__ import annotations

import argparse

from esp32._stub import not_implemented


def run(args: argparse.Namespace) -> int:
    """Entry point for the ``esp32 wifi`` subcommand. Currently a stub."""
    return not_implemented("wifi", "Tool 4")
