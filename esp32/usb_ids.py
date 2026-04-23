"""USB VID/PID fingerprints for ESP32-family boards and their USB-to-UART bridges.

The goal is to identify whether a given USB serial port is likely an ESP32-family
board so the discover tool can flag it. Matching is done by USB Vendor ID and,
optionally, Product ID. When ``pid`` is ``None`` on a signature, any PID from that
vendor matches (useful for broad vendors like FTDI where many variants ship on
ESP32 dev boards).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UsbSignature:
    """A USB VID/PID fingerprint that identifies an ESP32-family device.

    Attributes:
        vid: USB Vendor ID.
        pid: USB Product ID, or ``None`` to match any PID from this vendor.
        label: Human-friendly label for the board or bridge chip.
        notes: Extra context (which chips or boards this covers).
    """

    vid: int
    pid: int | None
    label: str
    notes: str


ESP32_SIGNATURES: tuple[UsbSignature, ...] = (
    UsbSignature(
        vid=0x303A,
        pid=None,
        label="Espressif native USB",
        notes="ESP32-S2 / S3 / C3 in native USB-CDC mode.",
    ),
    UsbSignature(
        vid=0x2341,
        pid=0x0070,
        label="Arduino Nano ESP32",
        notes="Official Arduino Nano ESP32 board (ESP32-S3 under the hood).",
    ),
    UsbSignature(
        vid=0x10C4,
        pid=0xEA60,
        label="Silicon Labs CP2102/CP2104",
        notes="Common USB-UART bridge on ESP32 DevKits.",
    ),
    UsbSignature(
        vid=0x1A86,
        pid=0x7523,
        label="WCH CH340",
        notes="Budget USB-UART bridge on many inexpensive ESP32 boards.",
    ),
    UsbSignature(
        vid=0x1A86,
        pid=0x55D4,
        label="WCH CH9102",
        notes="Newer WCH USB-UART bridge on recent ESP32 boards.",
    ),
    UsbSignature(
        vid=0x0403,
        pid=None,
        label="FTDI FT232 (likely ESP32 dev board)",
        notes="Broad FTDI match; some ESP32 dev boards ship with FT232.",
    ),
)


def match(vid: int | None, pid: int | None) -> UsbSignature | None:
    """Return the matching :class:`UsbSignature` for ``vid``/``pid``, or ``None``.

    Exact-PID signatures are preferred over vendor-only matches, so a port with a
    specific known PID doesn't get shadowed by a broad vendor entry.

    Args:
        vid: USB Vendor ID, or ``None`` (e.g. for virtual ports without USB metadata).
        pid: USB Product ID, or ``None``.

    Returns:
        The best matching signature, or ``None`` if nothing matches.
    """
    if vid is None:
        return None

    exact: UsbSignature | None = None
    vendor_only: UsbSignature | None = None

    for sig in ESP32_SIGNATURES:
        if sig.vid != vid:
            continue
        if sig.pid is None:
            vendor_only = sig
        elif sig.pid == pid:
            exact = sig
            break

    return exact or vendor_only
