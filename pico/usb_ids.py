"""USB VID/PID fingerprints for Raspberry Pi Pico-family devices.

Two main vendor IDs cover everything in this family:

* ``0x2E8A`` — Raspberry Pi Trading Ltd, used by all official Pico SDK
  USB CDC stacks plus the BOOTSEL mass-storage interfaces.
* (Third-party RP2040 boards sometimes ship with a different VID; those
  show up under ``pico discover --all`` rather than being recognized.)

PIDs in the ``0x2E8A`` space split into two functional groups:

* BOOTSEL ROM bootloader (mass-storage drive that accepts ``.uf2``
  drops). These PIDs are baked into silicon and are stable: ``0x0003``
  for RP2040, ``0x000F`` for RP2350.
* USB CDC (serial REPL — MicroPython, Pico SDK examples, picotool
  protocol). MicroPython's official builds use ``0x0005`` (RP2040) and
  ``0x000A`` is also seen for some MicroPython/Pico-SDK variants.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UsbSignature:
    """One known (vid, pid) tuple with a human label.

    ``role`` indicates what state the device is in — useful for
    distinguishing "Pico in BOOTSEL" from "Pico running MicroPython"
    when both are physically the same board.
    """

    vid: int
    pid: int
    label: str
    role: str  # "bootsel" | "micropython" | "picotool" | "sdk"


PICO_SIGNATURES: tuple[UsbSignature, ...] = (
    # BOOTSEL ROM bootloader — drag .uf2 onto the mounted volume.
    UsbSignature(0x2E8A, 0x0003, "Raspberry Pi RP2 Boot (BOOTSEL)", role="bootsel"),
    UsbSignature(0x2E8A, 0x000F, "Raspberry Pi RP2350 Boot (BOOTSEL)", role="bootsel"),
    # USB CDC — running firmware.
    UsbSignature(0x2E8A, 0x0005, "Raspberry Pi Pico (MicroPython)", role="micropython"),
    UsbSignature(0x2E8A, 0x000A, "Raspberry Pi Pico SDK CDC", role="sdk"),
    UsbSignature(0x2E8A, 0x0009, "Raspberry Pi Pico SDK reset", role="sdk"),
    # picotool's exposed USB interface (PicoBoot stub or app cooperating
    # with `picotool save --vid 2e8a --pid 0009` — kept here so the
    # fallback flash path can match against it explicitly).
    UsbSignature(0x2E8A, 0x000C, "Raspberry Pi picotool interface", role="picotool"),
)


def match(vid: int | None, pid: int | None) -> UsbSignature | None:
    """Return the matching :class:`UsbSignature`, or ``None``.

    Match is exact on the (vid, pid) pair. Unknown PIDs under the
    ``0x2E8A`` VID still come back as ``None`` so ``discover`` doesn't
    over-claim — third-party boards may reuse the Pico VID with a
    different PID we haven't catalogued.
    """
    if vid is None or pid is None:
        return None
    for sig in PICO_SIGNATURES:
        if sig.vid == vid and sig.pid == pid:
            return sig
    return None


def matches_pico_vid(vid: int | None) -> bool:
    """True iff ``vid`` is the Raspberry Pi VID, regardless of PID.

    Used by the BOOTSEL-mount discovery path to confirm a mounted
    volume actually belongs to a Pico (in case the user has another
    drive labeled ``RPI-RP2`` mounted, which would be unusual but
    cheap to guard against).
    """
    return vid == 0x2E8A
