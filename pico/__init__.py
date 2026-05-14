"""Raspberry Pi Pico (RP2040 / RP2350) CLI tooling.

Sibling of :mod:`esp32`, sharing :mod:`common` for the mpremote-driven
half of the toolchain (push/pull/ls, repl, reset, mip, wifi, info,
lint). Pico-specific bits — USB fingerprints, board profiles, the
UF2-MSC and ``picotool`` flash paths, and RP2040/RP2350 pin rules —
live here.
"""

__version__ = "0.1.0"
