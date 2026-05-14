"""Chip-family pin rules consumed by ``esp32 lint``.

Hand-curated alongside the chip-doc markdown templates in
:mod:`esp32.docs`. The two are intentionally kept separate: the
markdown is for humans, this file is for the linter. Adding a new
chip means writing entries in both, which is fine for the small
number of supported chip families.

The :class:`PinRule` schema and ``Severity`` literal live in
:mod:`common.lint` — they're shared with the Pico rule set.
"""

from __future__ import annotations

from common.lint import PinRule

# Re-exported here so callers who care about ESP32 rules don't need to
# reach into common/ just to spell the type.
__all__ = ["ESP32_RULES", "RULES_BY_CHIP", "PinRule", "chips_with_rules", "rules_for_chip"]


ESP32_RULES: tuple[PinRule, ...] = (
    PinRule(
        pins=(6, 7, 8, 9, 10, 11),
        severity="error",
        reason=(
            "reserved for internal SPI flash on ESP32 — toggling will crash "
            "or corrupt the chip"
        ),
    ),
    PinRule(
        pins=(0, 2, 5, 12, 15),
        severity="warning",
        reason=(
            "a strapping pin on ESP32 — wrong level at boot prevents the "
            "chip from starting"
        ),
    ),
    PinRule(
        pins=(34, 35, 36, 39),
        severity="note",
        reason=(
            "input-only on ESP32 — no output drive, no internal pull-up or "
            "pull-down"
        ),
        output_only=True,
    ),
)


RULES_BY_CHIP: dict[str, tuple[PinRule, ...]] = {
    "ESP32": ESP32_RULES,
    # ESP32-S2, S3, C3 added once verified against hardware.
}


def rules_for_chip(chip: str) -> tuple[PinRule, ...]:
    """Return the rule set for a chip family, or an empty tuple."""
    return RULES_BY_CHIP.get(chip, ())


def chips_with_rules() -> list[str]:
    """Sorted list of chip families with defined rules."""
    return sorted(RULES_BY_CHIP)
