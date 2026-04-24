"""Board profiles: how to flash MicroPython onto each supported ESP32 variant.

Two flash methods are supported:

* ``esptool`` — shells out to ``esptool`` and talks to the ESP32 ROM
  serial-download bootloader. Used for generic ESP32 / S2 / S3 / C3 boards
  where holding BOOT while pressing RESET (or the board's auto-reset circuit)
  drops the chip into ROM download mode.
* ``dfu`` — shells out to ``dfu-util``. Used for boards that ship with a
  factory USB DFU-class bootloader, notably the Arduino Nano ESP32. Double-
  tapping RESET enters the DFU bootloader; this method preserves the factory
  Arduino bootloader rather than overwriting it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from esp32.usb_ids import ESP32_SIGNATURES, UsbSignature

FlashMethod = Literal["esptool", "dfu"]


@dataclass(frozen=True)
class BoardProfile:
    """A flashable ESP32 board profile.

    Attributes:
        slug: micropython.org board slug (directory name under ``/download/``).
        display_name: Human-friendly label shown in logs/prompts.
        flash_method: Which flash backend drives the write.
        firmware_extension: File extension of the firmware artifact on
            micropython.org (``".bin"`` for esptool, ``".uf2"`` for DFU on
            Arduino mbed bootloaders).
        chip: esptool ``--chip`` argument (only meaningful when
            ``flash_method == "esptool"``).
        flash_offset: Byte offset where firmware is written by esptool
            (only meaningful when ``flash_method == "esptool"``).
        dfu_vid_pid: ``(vid, pid)`` that ``dfu-util`` should target, or
            ``None`` for non-DFU boards. For Arduino mbed boards the DFU
            bootloader reuses the application VID/PID.
        dfu_alt: DFU alternate interface index (only meaningful when
            ``flash_method == "dfu"``); almost always ``0``.
    """

    slug: str
    display_name: str
    flash_method: FlashMethod
    firmware_extension: str
    chip: str
    flash_offset: int
    dfu_vid_pid: tuple[int, int] | None
    dfu_alt: int


ARDUINO_NANO_ESP32 = BoardProfile(
    slug="ARDUINO_NANO_ESP32",
    display_name="Arduino Nano ESP32",
    flash_method="dfu",
    # Arduino's DFU bootloader wants the raw .bin, not .uf2 — the .uf2 is
    # UF2-wrapped and the bootloader fails with errWRITE on block 0 when
    # fed UF2 framing.
    firmware_extension=".bin",
    chip="",
    flash_offset=0,
    # Arduino mbed DFU bootloader keeps the same USB VID/PID as the running
    # application; you can tell the modes apart only by USB class descriptor.
    dfu_vid_pid=(0x2341, 0x0070),
    dfu_alt=0,
)

ESP32_GENERIC = BoardProfile(
    slug="ESP32_GENERIC",
    display_name="Generic ESP32",
    flash_method="esptool",
    firmware_extension=".bin",
    chip="esp32",
    flash_offset=0x1000,
    dfu_vid_pid=None,
    dfu_alt=0,
)

ESP32_GENERIC_S2 = BoardProfile(
    slug="ESP32_GENERIC_S2",
    display_name="Generic ESP32-S2",
    flash_method="esptool",
    firmware_extension=".bin",
    chip="esp32s2",
    flash_offset=0x0,
    dfu_vid_pid=None,
    dfu_alt=0,
)

ESP32_GENERIC_S3 = BoardProfile(
    slug="ESP32_GENERIC_S3",
    display_name="Generic ESP32-S3",
    flash_method="esptool",
    firmware_extension=".bin",
    chip="esp32s3",
    flash_offset=0x0,
    dfu_vid_pid=None,
    dfu_alt=0,
)

ESP32_GENERIC_C3 = BoardProfile(
    slug="ESP32_GENERIC_C3",
    display_name="Generic ESP32-C3",
    flash_method="esptool",
    firmware_extension=".bin",
    chip="esp32c3",
    flash_offset=0x0,
    dfu_vid_pid=None,
    dfu_alt=0,
)


BOARD_PROFILES: tuple[BoardProfile, ...] = (
    ARDUINO_NANO_ESP32,
    ESP32_GENERIC,
    ESP32_GENERIC_S2,
    ESP32_GENERIC_S3,
    ESP32_GENERIC_C3,
)


# Board profiles that can be inferred from a USB fingerprint alone.
# Keyed by ``UsbSignature`` (frozen dataclass, hashable).
SIGNATURE_TO_BOARD: dict[UsbSignature, BoardProfile] = {
    next(s for s in ESP32_SIGNATURES if s.label == "Arduino Nano ESP32"): ARDUINO_NANO_ESP32,
}


def by_slug(slug: str) -> BoardProfile | None:
    """Look up a :class:`BoardProfile` by its micropython.org slug."""
    for profile in BOARD_PROFILES:
        if profile.slug == slug:
            return profile
    return None


def infer_from_signature(signature: UsbSignature | None) -> BoardProfile | None:
    """Return the :class:`BoardProfile` implied by a USB fingerprint, if any.

    Most generic USB-UART bridges (CP210x, CH340, FTDI) could be wired to any
    ESP32 variant, so they don't imply a board. Only fingerprints tied to a
    specific product (e.g. Arduino Nano ESP32's VID/PID) return a profile.
    """
    if signature is None:
        return None
    return SIGNATURE_TO_BOARD.get(signature)
