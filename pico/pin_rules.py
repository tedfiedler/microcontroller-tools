"""Chip-family pin rules for Raspberry Pi Pico boards (RP2040 / RP2350).

Hand-curated alongside the chip-doc markdown templates in
:mod:`pico.docs`. The :class:`PinRule` schema and ``Severity`` literal
live in :mod:`common.lint` — they're shared with the ESP32 rule set.

The four onboard-hardware pins on every Raspberry-Pi reference board
(GP23, GP24, GP25, GP29) are flagged at ``warning`` severity. They're
**usable** as GPIOs if your board doesn't actually wire them to
anything (e.g. third-party RP2040 modules) or if you're prepared to
give up the corresponding onboard feature, but in either case the
user should know.

RP2350 rules mirror RP2040 because the Raspberry-Pi reference Pico 2
and Pico 2 W keep the same wiring conventions. These RP2350 rules
have **not** been verified on hardware yet.

No catastrophic-flash-pin equivalent to the ESP32: the RP2040 and
RP2350 wire QSPI flash to dedicated chip pins outside the GPIO
numbering, so no GPIO toggle can corrupt the flash interface.
"""

from __future__ import annotations

from common.lint import PinRule

__all__ = [
    "RP2040_RULES",
    "RP2350_RULES",
    "RULES_BY_CHIP",
    "PinRule",
    "chips_with_rules",
    "rules_for_chip",
]


_ONBOARD_REASON = (
    "reserved for onboard hardware on Raspberry-Pi reference boards "
    "(cyw43 module on Pico W / Pico 2 W; SMPS PS / VBUS sense / "
    "onboard LED / VSYS-divider on non-W variants) — third-party "
    "RP2040 / RP2350 modules may free it up"
)


RP2040_RULES: tuple[PinRule, ...] = (
    PinRule(
        pins=(23, 24, 25, 29),
        severity="warning",
        reason=_ONBOARD_REASON,
    ),
)

# Same wiring conventions on Pico 2 / Pico 2 W. Untested on hardware
# (no Pico 2 on hand at curation time); reasonable per the RP2350 and
# Pico 2 datasheets.
RP2350_RULES: tuple[PinRule, ...] = (
    PinRule(
        pins=(23, 24, 25, 29),
        severity="warning",
        reason=_ONBOARD_REASON,
    ),
)


RULES_BY_CHIP: dict[str, tuple[PinRule, ...]] = {
    "RP2040": RP2040_RULES,
    "RP2350": RP2350_RULES,
}


def rules_for_chip(chip: str) -> tuple[PinRule, ...]:
    """Return the rule set for a chip family, or an empty tuple."""
    return RULES_BY_CHIP.get(chip, ())


def chips_with_rules() -> list[str]:
    """Sorted list of chip families with defined rules."""
    return sorted(RULES_BY_CHIP)
