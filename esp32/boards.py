"""Board profiles: how to flash MicroPython onto each supported ESP32 variant.

A :class:`BoardProfile` ties together the USB fingerprint, the micropython.org
download-page slug, the esptool ``--chip`` argument, and the flash offset where
MicroPython firmware is expected to land for that chip family.

Flash offsets:
* ESP32 classic: ``0x1000`` (2nd stage bootloader lives in the boot partition).
* ESP32-S2 / S3 / C3: ``0x0`` (ROM bootloader chains straight into the image).
"""

from __future__ import annotations

from dataclasses import dataclass

from esp32.usb_ids import ESP32_SIGNATURES, UsbSignature


@dataclass(frozen=True)
class BoardProfile:
    """A flashable ESP32 board profile.

    Attributes:
        slug: micropython.org board slug (directory name under
            ``/download/``), e.g. ``"ARDUINO_NANO_ESP32"``.
        display_name: Human-friendly label shown in logs/prompts.
        chip: esptool ``--chip`` argument (``esp32``, ``esp32s2``, etc.).
            Use ``"auto"`` to let esptool detect.
        flash_offset: Byte offset where MicroPython firmware is written.
    """

    slug: str
    display_name: str
    chip: str
    flash_offset: int


ARDUINO_NANO_ESP32 = BoardProfile(
    slug="ARDUINO_NANO_ESP32",
    display_name="Arduino Nano ESP32",
    chip="esp32s3",
    flash_offset=0x0,
)

ESP32_GENERIC = BoardProfile(
    slug="ESP32_GENERIC",
    display_name="Generic ESP32",
    chip="esp32",
    flash_offset=0x1000,
)

ESP32_GENERIC_S2 = BoardProfile(
    slug="ESP32_GENERIC_S2",
    display_name="Generic ESP32-S2",
    chip="esp32s2",
    flash_offset=0x0,
)

ESP32_GENERIC_S3 = BoardProfile(
    slug="ESP32_GENERIC_S3",
    display_name="Generic ESP32-S3",
    chip="esp32s3",
    flash_offset=0x0,
)

ESP32_GENERIC_C3 = BoardProfile(
    slug="ESP32_GENERIC_C3",
    display_name="Generic ESP32-C3",
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
