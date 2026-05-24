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
__all__ = [
    "ESP32_C3_RULES",
    "ESP32_RULES",
    "RULES_BY_CHIP",
    "PinRule",
    "chips_with_rules",
    "rules_for_chip",
]


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


# ESP32-C3 (RISC-V single-core). Different rule shape from the classic
# ESP32: no flash-pin error class (QSPI flash is on dedicated chip pins
# outside the GPIO numbering), no input-only-pin note class (all 22
# GPIOs are bidirectional). Just two warning classes.
ESP32_C3_RULES: tuple[PinRule, ...] = (
    PinRule(
        pins=(2, 8, 9),
        severity="warning",
        reason=(
            "a strapping pin on ESP32-C3 — sampled at reset; wrong level "
            "at boot prevents the chip from starting (GP9 is the BOOT "
            "button on every dev board)"
        ),
    ),
    PinRule(
        pins=(18, 19),
        severity="warning",
        reason=(
            "wired to the native USB-Serial-JTAG on ESP32-C3 (GP18 = "
            "USB D-, GP19 = USB D+) — driving from user code breaks the "
            "USB CDC console and the MicroPython REPL on native-USB boards"
        ),
    ),
)


RULES_BY_CHIP: dict[str, tuple[PinRule, ...]] = {
    "ESP32": ESP32_RULES,
    "ESP32-C3": ESP32_C3_RULES,
    # ESP32-S2 / S3 added once verified against hardware.
}


def rules_for_chip(chip: str) -> tuple[PinRule, ...]:
    """Return the rule set for a chip family, or an empty tuple."""
    return RULES_BY_CHIP.get(chip, ())


def chips_with_rules() -> list[str]:
    """Sorted list of chip families with defined rules."""
    return sorted(RULES_BY_CHIP)
