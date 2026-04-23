"""Tool 1: Discover ESP32-family devices connected via USB.

Wraps :mod:`serial.tools.list_ports` and classifies each port by VID/PID against
:data:`esp32.usb_ids.ESP32_SIGNATURES`. Ports whose VID/PID match a known ESP32
fingerprint are flagged as likely ESP32 devices; all other ports are returned
only when explicitly requested via ``include_unknown=True``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from serial.tools import list_ports

from esp32.usb_ids import UsbSignature, match


@dataclass(frozen=True)
class DiscoveredDevice:
    """A USB serial port discovered on the host, with optional ESP32 fingerprint.

    Attributes:
        port: OS path / device name (e.g. ``/dev/cu.usbmodem1101`` on macOS).
        vid: USB Vendor ID if reported by the OS, else ``None``.
        pid: USB Product ID if reported by the OS, else ``None``.
        serial_number: USB serial number string if available.
        manufacturer: USB manufacturer string if available.
        product: USB product string if available.
        signature: Matched ESP32 fingerprint, or ``None`` if unknown.
    """

    port: str
    vid: int | None
    pid: int | None
    serial_number: str | None
    manufacturer: str | None
    product: str | None
    signature: UsbSignature | None

    @property
    def is_likely_esp32(self) -> bool:
        """Whether this device matched a known ESP32-family fingerprint."""
        return self.signature is not None


def discover(include_unknown: bool = False, port: str | None = None) -> list[DiscoveredDevice]:
    """Enumerate USB serial ports and classify ESP32-family devices.

    Args:
        include_unknown: If ``True``, also return ports that do not match any
            known ESP32 fingerprint. Useful for troubleshooting ("why isn't my
            board showing up?").
        port: If set, only inspect the given port path; all other ports are
            skipped. ``include_unknown`` is implicitly treated as ``True`` when
            a specific port is requested.

    Returns:
        A list of :class:`DiscoveredDevice`, ordered by port name.
    """
    devices: list[DiscoveredDevice] = []

    for info in list_ports.comports():
        if port is not None and info.device != port:
            continue

        vid = info.vid if info.vid is not None else None
        pid = info.pid if info.pid is not None else None
        signature = match(vid, pid)

        if signature is None and not include_unknown and port is None:
            continue

        devices.append(
            DiscoveredDevice(
                port=info.device,
                vid=vid,
                pid=pid,
                serial_number=info.serial_number,
                manufacturer=info.manufacturer,
                product=info.product,
                signature=signature,
            )
        )

    devices.sort(key=lambda d: d.port)
    return devices


def _fmt_hex(value: int | None) -> str:
    """Format an optional USB ID as a 4-hex-digit string, or ``"-"`` if missing."""
    return f"0x{value:04X}" if value is not None else "-"


def format_table(devices: list[DiscoveredDevice]) -> str:
    """Render discovered devices as a human-readable text table.

    No external dependencies; columns are padded with f-string formatting.
    """
    if not devices:
        return (
            "No ESP32 devices found.\n"
            "Re-run with `--all` to list other serial ports."
        )

    headers = ("PORT", "VID", "PID", "BOARD / BRIDGE", "PRODUCT")
    rows: list[tuple[str, str, str, str, str]] = []
    for dev in devices:
        label = dev.signature.label if dev.signature else "(unknown)"
        rows.append(
            (
                dev.port,
                _fmt_hex(dev.vid),
                _fmt_hex(dev.pid),
                label,
                dev.product or "-",
            )
        )

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    lines: list[str] = []
    lines.append("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(lines)


def format_json(devices: list[DiscoveredDevice]) -> str:
    """Render discovered devices as pretty-printed JSON.

    VID/PID are emitted as hex strings (``"0x303A"``) rather than raw ints so the
    output is easy to eyeball. ``signature`` is expanded as a nested object with
    all fields, or ``null`` if no match.
    """
    payload: list[dict[str, Any]] = []
    for dev in devices:
        entry = asdict(dev)
        entry["vid"] = _fmt_hex(dev.vid) if dev.vid is not None else None
        entry["pid"] = _fmt_hex(dev.pid) if dev.pid is not None else None
        entry["is_likely_esp32"] = dev.is_likely_esp32
        payload.append(entry)
    return json.dumps(payload, indent=2)
