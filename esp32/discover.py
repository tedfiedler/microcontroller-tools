"""Tool 1: Discover ESP32-family devices connected via USB.

Wraps :mod:`serial.tools.list_ports` and classifies each port by VID/PID against
:data:`esp32.usb_ids.ESP32_SIGNATURES`. Ports whose VID/PID match a known ESP32
fingerprint are flagged as likely ESP32 devices; all other ports are returned
only when explicitly requested via ``include_unknown=True``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Any

from serial.tools import list_ports

from esp32 import boards
from esp32.usb_ids import UsbSignature, match

# NB: deliberately not importing from ``esp32._mpy`` here — ``_mpy`` already
# imports this module for ``resolve_port``, and adding a back-edge would
# create an import cycle. Probing inlines its own ``shutil.which("mpremote")``
# lookup instead.


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
        chip: Chip family detected by ``--probe`` (e.g. ``"ESP32"``,
            ``"ESP32-S3"``), or one of the placeholder strings
            (``"(no mpy)"``, ``"(unknown)"``, …) when probing was
            attempted but inconclusive. ``None`` when probing was not
            requested at all.
        profile: Board profile slug matched from the device's
            ``os.uname().machine`` prefix (e.g. ``"ESP32_GENERIC"``,
            ``"ARDUINO_NANO_ESP32"``). ``None`` when probing wasn't
            requested, the probe failed, or the machine string didn't
            match any known :class:`boards.BoardProfile`.
    """

    port: str
    vid: int | None
    pid: int | None
    serial_number: str | None
    manufacturer: str | None
    product: str | None
    signature: UsbSignature | None
    chip: str | None = None
    profile: str | None = None

    @property
    def is_likely_esp32(self) -> bool:
        """Whether this device matched a known ESP32-family fingerprint."""
        return self.signature is not None


# ---------- chip probing -----------------------------------------------------
#
# `discover --probe` adds a CHIP column by talking to each detected port:
#   1. `mpremote ... eval "uname().machine"` — non-invasive, only works when
#      MicroPython is already running on the device.
#   2. `esptool --port ... chip-id` — fallback when --probe-esptool is set;
#      this one bounces the chip into the ROM bootloader, so it's opt-in.

# Cold mpremote-eval connects to an ESP32 over USB-CDC routinely take 5-8s
# (USB negotiation, REPL handshake, paste-mode entry, then the eval). 15s is
# generous enough to absorb that without making a truly hung device feel
# unbounded.
_PROBE_TIMEOUT_SECS = 15.0
_ESPTOOL_TIMEOUT_SECS = 30.0

# Match any ESP32-family chip token in a uname-style string. Captures things
# like "ESP32", "ESP32S3", "ESP32-S3", "ESP32-D0WDQ6", "ESP32C3" — the last
# occurrence in the string is taken as the chip identifier.
_CHIP_TOKEN_RE = re.compile(r"ESP32[A-Z0-9-]*", re.IGNORECASE)


def normalize_chip(raw: str) -> str:
    """Extract and normalize an ESP32 chip family from a uname-style string.

    Examples::

        "Generic ESP32 module with ESP32"       → "ESP32"
        "ESP32S3 module with ESP32S3"           → "ESP32-S3"
        "Arduino Nano ESP32 with ESP32-S3"      → "ESP32-S3"
        "Chip is ESP32-D0WDQ6 (revision v1.0)"  → "ESP32-D0WDQ6"
    """
    # ``re.findall`` is typed as ``list[Any]`` in the stdlib stubs; force the
    # element type to ``str`` so mypy --strict accepts the .upper() call.
    matches: list[str] = _CHIP_TOKEN_RE.findall(raw)
    if not matches:
        return raw.strip()[:30]  # surface whatever came back, truncated
    tag = matches[-1].upper()
    # Insert the conventional dash for the bare S2/S3/C2/C3 variants.
    m = re.fullmatch(r"ESP32([SC]\d)", tag)
    if m:
        return f"ESP32-{m.group(1)}"
    return tag


def _probe_identity(
    port: str, *, esptool_fallback: bool = False
) -> tuple[str, str | None]:
    """Probe ``port`` for both chip family and board profile slug.

    Returns ``(chip_label, profile_slug_or_None)``. ``chip_label`` is
    always a string — either a normalized chip name (``"ESP32-S3"``) or a
    parenthesized placeholder (``"(no mpy)"``, ``"(connect fail)"``).
    ``profile_slug`` is the matching :class:`boards.BoardProfile` slug
    (``"ESP32_GENERIC"``, ``"ARDUINO_NANO_ESP32"``, …) when the
    ``os.uname().machine`` prefix matches a known profile, or ``None``.

    Mechanism: a single ``mpremote eval "__import__('os').uname().machine"``
    invocation, whose result (e.g. ``"Generic ESP32 module with ESP32"``)
    is parsed two ways — chip-family token at the tail, board-name prefix
    via :func:`boards.infer_from_machine`. If ``esptool_fallback`` is True
    and the mpremote path fails, we fall back to ``esptool chip-id``; that
    yields only the chip (esptool can't tell us the firmware build), so
    ``profile`` stays ``None``.

    Prints a short ``probing …`` progress note to stderr so the user isn't
    staring at silence for 7+s during cold USB-CDC handshakes. Stderr is
    used so JSON output piped to a parser stays clean.
    """
    print(f"probing {port} …", file=sys.stderr, flush=True)
    binary = shutil.which("mpremote")
    if binary is not None:
        try:
            result = subprocess.run(
                [
                    binary, "connect", port,
                    "eval", "__import__('os').uname().machine",
                ],
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT_SECS,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                raw = result.stdout.strip()
                # Some mpremote versions print repr() of strings, some print
                # the raw value. Strip surrounding quotes if present.
                if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
                    raw = raw[1:-1]
                chip = normalize_chip(raw)
                profile_match = boards.infer_from_machine(raw)
                profile = profile_match.slug if profile_match else None
                return chip, profile
        except subprocess.TimeoutExpired:
            pass

    if not esptool_fallback:
        return "(no mpy)", None

    return _probe_chip_esptool(port), None


def _probe_chip_esptool(port: str) -> str:
    """Run ``esptool chip-id`` and parse the chip-family line out of stdout.

    Output format has drifted across esptool releases:

    * esptool 4.x and earlier: ``Chip is ESP32-C3 (revision v0.3)``
    * esptool 5.x: ``Chip type:          ESP32-C3 AZ (QFN32) (revision v1.1)``
      and ``Detecting chip type... ESP32-C3``

    Rather than chase prefixes forever, we let :func:`normalize_chip`
    pull the chip token out of any line that contains one — preferring
    the explicit ``Chip type:`` / ``Chip is`` declaration lines, and
    falling back to scanning all of stdout if neither is present.
    """
    binary = shutil.which("esptool") or shutil.which("esptool.py")
    if binary is None:
        return "(no esptool)"
    try:
        result = subprocess.run(
            [binary, "--port", port, "chip-id"],
            capture_output=True,
            text=True,
            timeout=_ESPTOOL_TIMEOUT_SECS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "(timeout)"
    if result.returncode != 0:
        return "(connect fail)"
    # Prefer the explicit declaration lines when present.
    for line in result.stdout.splitlines():
        stripped = line.strip()
        for prefix in ("Chip type:", "Chip is "):
            if stripped.startswith(prefix):
                return normalize_chip(stripped[len(prefix):])
    # Fallback: scan the whole stdout. normalize_chip takes the last
    # ESP32* token it finds, which on every esptool version observed so
    # far is the actual chip family.
    if _CHIP_TOKEN_RE.search(result.stdout):
        return normalize_chip(result.stdout)
    return "(unknown)"


def discover(
    include_unknown: bool = False,
    port: str | None = None,
    *,
    probe: bool = False,
    probe_esptool: bool = False,
) -> list[DiscoveredDevice]:
    """Enumerate USB serial ports and classify ESP32-family devices.

    Args:
        include_unknown: If ``True``, also return ports that do not match any
            known ESP32 fingerprint. Useful for troubleshooting ("why isn't my
            board showing up?").
        port: If set, only inspect the given port path; all other ports are
            skipped. ``include_unknown`` is implicitly treated as ``True`` when
            a specific port is requested.
        probe: If ``True``, talk to each detected port to identify the chip
            family behind it (see :func:`_probe_chip`). Probing is skipped on
            ports without a known ESP32 signature unless ``port`` was given
            explicitly — we don't want to bother arbitrary USB-CDC devices.
        probe_esptool: If ``True``, additionally fall back to ``esptool``
            when the mpremote probe fails. Implies ``probe``; bounces the
            chip into the ROM bootloader.

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

        chip: str | None = None
        profile: str | None = None
        if probe and (signature is not None or port is not None):
            chip, profile = _probe_identity(
                info.device, esptool_fallback=probe_esptool
            )

        devices.append(
            DiscoveredDevice(
                port=info.device,
                vid=vid,
                pid=pid,
                serial_number=info.serial_number,
                manufacturer=info.manufacturer,
                product=info.product,
                signature=signature,
                chip=chip,
                profile=profile,
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
    The ``CHIP`` column appears only when at least one device was probed.
    """
    if not devices:
        return (
            "No ESP32 devices found.\n"
            "Re-run with `--all` to list other serial ports."
        )

    # Probe-derived columns appear together: if anyone has chip data we
    # also show profile (which may still be "-" when the machine string
    # didn't match a known board).
    include_probe = any(dev.chip is not None for dev in devices)

    headers: tuple[str, ...]
    rows: list[tuple[str, ...]] = []
    if include_probe:
        headers = (
            "PORT", "VID", "PID", "BOARD / BRIDGE",
            "CHIP", "PROFILE", "PRODUCT",
        )
    else:
        headers = ("PORT", "VID", "PID", "BOARD / BRIDGE", "PRODUCT")

    for dev in devices:
        label = dev.signature.label if dev.signature else "(unknown)"
        if include_probe:
            rows.append(
                (
                    dev.port,
                    _fmt_hex(dev.vid),
                    _fmt_hex(dev.pid),
                    label,
                    dev.chip or "-",
                    dev.profile or "-",
                    dev.product or "-",
                )
            )
        else:
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
