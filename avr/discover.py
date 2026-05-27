"""Discover AVR-adjacent USB-UART bridges on the host.

What "discover" means for this family is different from :mod:`esp32`
/ :mod:`pico` — there's no on-device MicroPython REPL to probe, so we
can't confirm a given port has an AVR behind it. We list serial ports
whose USB fingerprint matches a known bridge chip (FT232 / CH340 /
CP2102 / ATmega16U2-as-serial) and trust the user to know which one
they wired to their ATmega.

Pass ``--all`` to include serial ports we don't recognize as bridge
chips (useful for unrecognized FT-clone PIDs or onboard UARTs).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from serial.tools import list_ports

from avr.usb_ids import UsbSignature, match


@dataclass(frozen=True)
class DiscoveredDevice:
    """One USB-UART bridge enumerated on the host.

    Attributes:
        port: Device path (``/dev/ttyUSB0``, ``/dev/ttyACM0``, ``COM3``).
        vid: USB Vendor ID, when known.
        pid: USB Product ID, when known.
        serial_number: USB serial-number string, when reported.
        manufacturer: USB manufacturer string.
        product: USB product string.
        signature: Matched :class:`UsbSignature`, or ``None`` if the
            (vid, pid) wasn't in our catalogue.
    """

    port: str
    vid: int | None
    pid: int | None
    serial_number: str | None
    manufacturer: str | None
    product: str | None
    signature: UsbSignature | None

    @property
    def is_known_bridge(self) -> bool:
        """Whether the (vid, pid) matched a catalogued bridge chip."""
        return self.signature is not None


def discover(
    include_unknown: bool = False, port: str | None = None
) -> list[DiscoveredDevice]:
    """Enumerate USB-UART bridges that could be wired to an AVR.

    Args:
        include_unknown: If ``True``, also return serial ports that
            don't match a catalogued bridge VID/PID. The default is
            strict so the table isn't cluttered with the host's
            onboard UARTs / Bluetooth modems / virtual ports.
        port: If set, only inspect the given port path. ``include_unknown``
            is implicitly treated as ``True`` when a specific port is
            requested.

    Returns the matching devices sorted by port path.
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


# ---------- formatters -------------------------------------------------------


def _fmt_hex(value: int | None) -> str:
    return f"0x{value:04X}" if value is not None else "-"


def format_table(devices: list[DiscoveredDevice]) -> str:
    """Render discovered bridges as a human-readable text table.

    Output deliberately doesn't claim "this is an AVR" — the BRIDGE
    column reports the matched USB-UART chip, with a footer reminder
    that the actual chip on the other side is up to the user.
    """
    if not devices:
        return (
            "No USB-UART bridges found.\n"
            "Plug in the FTDI / CH340 / CP2102 bridge wired to the ATmega328 "
            "(or pass `--all` to list every serial port the host can see)."
        )

    headers = ("PORT", "VID", "PID", "BRIDGE", "MANUFACTURER", "PRODUCT", "SERIAL")
    rows: list[tuple[str, ...]] = []
    for dev in devices:
        label = dev.signature.label if dev.signature else "(unknown bridge)"
        rows.append(
            (
                dev.port,
                _fmt_hex(dev.vid),
                _fmt_hex(dev.pid),
                label,
                dev.manufacturer or "-",
                dev.product or "-",
                dev.serial_number or "-",
            )
        )

    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    lines: list[str] = []
    lines.append("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
    lines.append("")
    lines.append(
        "(A matched bridge proves a USB-UART chip is plugged in, not that "
        "an AVR is on the other side — `avr flash` confirms at upload time.)"
    )
    return "\n".join(lines)


def format_json(devices: list[DiscoveredDevice]) -> str:
    """Render discovered bridges as pretty-printed JSON."""
    payload: list[dict[str, Any]] = []
    for dev in devices:
        entry = asdict(dev)
        entry["vid"] = _fmt_hex(dev.vid) if dev.vid is not None else None
        entry["pid"] = _fmt_hex(dev.pid) if dev.pid is not None else None
        entry["is_known_bridge"] = dev.is_known_bridge
        payload.append(entry)
    return json.dumps(payload, indent=2)


# ---------- port resolution --------------------------------------------------


class PortResolutionError(RuntimeError):
    """Raised when ``avr`` can't pick a single port automatically."""


def resolve_port(explicit: str | None) -> str:
    """Pick a serial port for a subcommand that needs one.

    Honors ``--port`` first. Otherwise searches for catalogued bridges
    and uses the only match; raises :class:`PortResolutionError` when
    there's zero or more than one candidate so the user gets a clear
    "pass --port" message instead of a silent wrong-port write.
    """
    if explicit is not None:
        return explicit

    candidates = discover(include_unknown=False)
    if not candidates:
        raise PortResolutionError(
            "no USB-UART bridge found. Plug in the FTDI / CH340 / CP2102 "
            "wired to the ATmega328, or pass --port /dev/ttyUSB0."
        )
    if len(candidates) > 1:
        ports = ", ".join(d.port for d in candidates)
        raise PortResolutionError(
            f"multiple bridges found ({ports}); disambiguate with --port."
        )
    return candidates[0].port
