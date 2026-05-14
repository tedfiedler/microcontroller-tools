"""Shared building blocks used by both device-family packages.

The :mod:`common` package holds the chip-agnostic half of the CLI:
mpremote helpers, command runners that just shuttle bytes between the
host and a MicroPython REPL, the static-analysis AST walker, and the
on-device probe script for ``info``.

Each device-family package (currently :mod:`esp32` and :mod:`pico`)
contributes a :class:`common.family.FamilyContext` that injects
family-specific behavior — port resolution, error-prefix name —
into these shared runners.
"""

__all__: list[str] = []
