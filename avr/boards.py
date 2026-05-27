"""Board / chip profiles for ``avr flash``.

Unlike :mod:`esp32.boards` / :mod:`pico.boards`, these profiles do
**not** point at a downloadable firmware artifact — there's no
canonical Python firmware for AVRs, so the user always supplies a
locally-built ``.hex`` (compiled from an Arduino sketch via
``arduino-cli compile`` / ``platformio run`` / ``avr-gcc``).

A profile here just captures the ``avrdude`` arguments needed to talk
the bootloader protocol on the chip: which ``-p`` value, which ``-c``
programmer, and the upload baud rate. ``--mcu`` / ``--programmer`` /
``--baud`` on the CLI override these defaults so the same tool can
drive any AVR avrdude can.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoardProfile:
    """A flashable AVR board profile.

    Attributes:
        slug: Short identifier accepted by ``--board``.
        display_name: Human-friendly label shown in logs / prompts.
        mcu: ``avrdude -p`` argument (e.g. ``atmega328p``). This is the
            "part number" string from ``avrdude.conf``; see
            ``avrdude -p \\?`` for the full list.
        programmer: ``avrdude -c`` argument. ``arduino`` speaks
            STK500v1 over serial, which is what every stock Arduino
            bootloader (optiboot, the older Duemilanove bootloader,
            and the LilyPad bootloader) implements.
        baud: Upload baud rate the bootloader expects. Optiboot (Uno
            R3, modern Nanos, most "Arduino-compatible" ATmega328
            breakouts shipped after ~2011) speaks 115200; the older
            Duemilanove STK500v1 bootloader uses 57600; the LilyPad /
            Pro 3.3 V variant uses 19200.
        flash_size_kb: Application flash region (after the bootloader
            is subtracted). Informational only — avrdude enforces the
            real limit, this is just so ``avr flash`` can print a
            sanity-check warning if the .hex is suspiciously large.
    """

    slug: str
    display_name: str
    mcu: str
    programmer: str
    baud: int
    flash_size_kb: int


ATMEGA328P_ARDUINO = BoardProfile(
    slug="atmega328p-arduino",
    display_name="ATmega328P with Arduino bootloader (optiboot, 115200)",
    mcu="atmega328p",
    programmer="arduino",
    baud=115200,
    # 32 KB total flash, 512 B taken by optiboot → ~31.5 KB usable.
    # Older STK500v1 bootloader takes 2 KB → ~30 KB usable. Default to
    # the optiboot number; "your hex is too big" warnings should still
    # fire correctly for the older bootloader case.
    flash_size_kb=32,
)


ATMEGA328P_DUEMILANOVE = BoardProfile(
    slug="atmega328p-duemilanove",
    display_name="ATmega328P with Duemilanove bootloader (STK500v1, 57600)",
    mcu="atmega328p",
    programmer="arduino",
    baud=57600,
    flash_size_kb=32,
)


BOARD_PROFILES: tuple[BoardProfile, ...] = (
    ATMEGA328P_ARDUINO,
    ATMEGA328P_DUEMILANOVE,
)


def by_slug(slug: str) -> BoardProfile | None:
    """Look up a :class:`BoardProfile` by its slug, or ``None``."""
    for profile in BOARD_PROFILES:
        if profile.slug == slug:
            return profile
    return None
