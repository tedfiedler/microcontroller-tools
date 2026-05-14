"""Chip-family pin rules for Raspberry Pi Pico boards (RP2040 / RP2350).

Hand-curated alongside the chip-doc markdown templates in
:mod:`pico.docs`. The :class:`PinRule` schema and ``Severity`` literal
live in :mod:`common.lint` — they're shared with the ESP32 rule set.

Rule tables are populated in the next commit (Task 4). For now this
module exists so ``pico lint`` can dispatch without import errors and
so future contributors have a clear place to add data.
"""

from __future__ import annotations

from common.lint import PinRule

__all__ = ["RULES_BY_CHIP", "PinRule", "chips_with_rules", "rules_for_chip"]


# Empty until the Pico pin rules are filled in. Once populated, keyed
# by chip family — ``"RP2040"`` and ``"RP2350"`` — same convention as
# :mod:`esp32.pin_rules`.
RULES_BY_CHIP: dict[str, tuple[PinRule, ...]] = {}


def rules_for_chip(chip: str) -> tuple[PinRule, ...]:
    """Return the rule set for a chip family, or an empty tuple."""
    return RULES_BY_CHIP.get(chip, ())


def chips_with_rules() -> list[str]:
    """Sorted list of chip families with defined rules."""
    return sorted(RULES_BY_CHIP)
