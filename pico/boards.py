"""Board profiles for Raspberry Pi Pico-family devices.

Each profile records:

* what micropython.org calls the board (``slug``) — used to scrape the
  matching ``.uf2`` download.
* what string the running firmware reports as ``os.uname().machine`` —
  used to map a probed device back to its profile.
* which mass-storage volume label appears when the board is in BOOTSEL
  mode — used by the flash path to find the drop target.
* which chip family is inside — used to pick the right lint rule set.

Flash method is always ``"uf2-msc"`` (drag-and-drop onto BOOTSEL
volume) at the data layer. The :mod:`pico.flash` runner can also fall
back to ``picotool`` when the board is already running app firmware
and BOOTSEL hasn't been triggered; that choice is made at runtime, not
encoded per-board.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ChipFamily = Literal["RP2040", "RP2350"]


@dataclass(frozen=True)
class BoardProfile:
    """A flashable Raspberry Pi Pico-family board profile.

    Attributes:
        slug: micropython.org board slug (directory name under
            ``/download/``). E.g. ``"RPI_PICO"``, ``"RPI_PICO_W"``.
        display_name: Human-friendly label shown in logs/prompts.
        chip: Chip family — ``"RP2040"`` or ``"RP2350"``.
        bootsel_volume_label: Volume label that appears when the board
            is in BOOTSEL mode. ``"RPI-RP2"`` for all RP2040 boards;
            ``"RP2350"`` for RP2350 boards.
        has_wifi: True for cyw43-equipped boards (Pico W / Pico 2 W).
            Affects which lint rules apply (extra reserved GPIOs for
            the cyw43 SPI link) and lets ``pico info`` know whether to
            expect Wi-Fi state at all.
        machine_name: Prefix of ``os.uname().machine`` reported by a
            board running this profile's firmware. Set per-board in
            MicroPython's ``MICROPY_HW_BOARD_NAME``. Used by
            :func:`infer_from_machine` to map a live device back to a
            profile slug.
    """

    slug: str
    display_name: str
    chip: ChipFamily
    bootsel_volume_label: str
    has_wifi: bool
    machine_name: str


RPI_PICO = BoardProfile(
    slug="RPI_PICO",
    display_name="Raspberry Pi Pico",
    chip="RP2040",
    bootsel_volume_label="RPI-RP2",
    has_wifi=False,
    machine_name="Raspberry Pi Pico",
)

RPI_PICO_W = BoardProfile(
    slug="RPI_PICO_W",
    display_name="Raspberry Pi Pico W",
    chip="RP2040",
    bootsel_volume_label="RPI-RP2",
    has_wifi=True,
    machine_name="Raspberry Pi Pico W",
)

RPI_PICO2 = BoardProfile(
    slug="RPI_PICO2",
    display_name="Raspberry Pi Pico 2",
    chip="RP2350",
    bootsel_volume_label="RP2350",
    has_wifi=False,
    machine_name="Raspberry Pi Pico 2",
)

RPI_PICO2_W = BoardProfile(
    slug="RPI_PICO2_W",
    display_name="Raspberry Pi Pico 2 W",
    chip="RP2350",
    bootsel_volume_label="RP2350",
    has_wifi=True,
    machine_name="Raspberry Pi Pico 2 W",
)


BOARD_PROFILES: tuple[BoardProfile, ...] = (
    RPI_PICO,
    RPI_PICO_W,
    RPI_PICO2,
    RPI_PICO2_W,
)


def by_slug(slug: str) -> BoardProfile | None:
    """Look up a :class:`BoardProfile` by its micropython.org slug."""
    for profile in BOARD_PROFILES:
        if profile.slug == slug:
            return profile
    return None


def infer_from_machine(machine: str) -> BoardProfile | None:
    """Return the :class:`BoardProfile` matching a live device's
    ``os.uname().machine`` string, or ``None`` if no profile matches.

    ``os.uname().machine`` is formatted as
    ``"<MICROPY_HW_BOARD_NAME> with <chip_family>"``. We match against
    the longest ``machine_name`` prefix first so that ``Raspberry Pi
    Pico 2 W`` doesn't accidentally match the plain ``Raspberry Pi
    Pico 2`` profile (it would be a substring).
    """
    candidates = sorted(BOARD_PROFILES, key=lambda p: len(p.machine_name), reverse=True)
    for profile in candidates:
        if machine.startswith(profile.machine_name):
            return profile
    return None
