"""Board profiles: how to flash MicroPython onto each supported ESP32 variant.

All supported boards are flashed via ``esptool`` talking to the ESP32 ROM
serial-download bootloader. For the Arduino Nano ESP32 that means the user
must enter ROM bootloader mode manually (hold BOOT while pressing RESET)
before flashing — doing so replaces the factory Arduino DFU bootloader.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from esp32.usb_ids import ESP32_SIGNATURES, UsbSignature

FlashMethod = Literal["esptool"]


@dataclass(frozen=True)
class BoardProfile:
    """A flashable ESP32 board profile.

    Attributes:
        slug: micropython.org board slug (directory name under ``/download/``).
        display_name: Human-friendly label shown in logs/prompts.
        flash_method: How the firmware is delivered to the device.
        firmware_extension: File extension of the firmware artifact on
            micropython.org (``".bin"`` for esptool, ``".uf2"`` for UF2).
        chip: esptool ``--chip`` argument (only meaningful for
            ``flash_method == "esptool"``; empty string for UF2 boards).
        flash_offset: Byte offset where firmware is written (only meaningful
            for ``flash_method == "esptool"``; ``0`` for UF2).
    """

    slug: str
    display_name: str
    flash_method: FlashMethod
    firmware_extension: str
    chip: str
    flash_offset: int


ARDUINO_NANO_ESP32 = BoardProfile(
    slug="ARDUINO_NANO_ESP32",
    display_name="Arduino Nano ESP32",
    # Flashed via the ESP32-S3 ROM bootloader. Enter ROM mode by holding the
    # B1 (BOOT) button while pressing RESET — the board then appears as
    # VID 0x303A / PID 0x1001 (USB JTAG/serial debug unit). This replaces
    # the factory Arduino DFU bootloader.
    flash_method="esptool",
    firmware_extension=".bin",
    chip="esp32s3",
    flash_offset=0x0,
)

ESP32_GENERIC = BoardProfile(
    slug="ESP32_GENERIC",
    display_name="Generic ESP32",
    flash_method="esptool",
    firmware_extension=".bin",
    chip="esp32",
    flash_offset=0x1000,
)

ESP32_GENERIC_S2 = BoardProfile(
    slug="ESP32_GENERIC_S2",
    display_name="Generic ESP32-S2",
    flash_method="esptool",
    firmware_extension=".bin",
    chip="esp32s2",
    flash_offset=0x0,
)

ESP32_GENERIC_S3 = BoardProfile(
    slug="ESP32_GENERIC_S3",
    display_name="Generic ESP32-S3",
    flash_method="esptool",
    firmware_extension=".bin",
    chip="esp32s3",
    flash_offset=0x0,
)

ESP32_GENERIC_C3 = BoardProfile(
    slug="ESP32_GENERIC_C3",
    display_name="Generic ESP32-C3",
    flash_method="esptool",
    firmware_extension=".bin",
    chip="esp32c3",
    flash_offset=0x0,
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
