"""Tool 1 (Pico family): Discover Raspberry Pi Pico devices on USB.

A Pico can show up in two visibly distinct states:

* **Serial mode** — board is running firmware (MicroPython or any other
  Pico-SDK application with a USB CDC interface). It enumerates as a
  ``/dev/ttyACM*`` (Linux/macOS) or COM port (Windows) under VID
  ``0x2E8A``. :mod:`serial.tools.list_ports` finds these.

* **BOOTSEL mode** — board is in its ROM bootloader (the user pressed
  BOOTSEL before plugging in, or the firmware triggered ``reset_to_bootsel``).
  It enumerates as a USB Mass Storage device with volume label
  ``RPI-RP2`` (RP2040) or ``RP2350`` (RP2350). It has no serial port,
  so ``list_ports`` won't see it; instead we scan platform-specific
  mount roots.

``discover()`` returns both kinds as :class:`DiscoveredDevice`. ``mode``
distinguishes them; ``port`` is the device path for serial entries and
the mount path for BOOTSEL entries.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from serial.tools import list_ports

from pico import boards
from pico.usb_ids import UsbSignature, match

# NB: intentionally not importing from ``pico._mpy`` — that module
# imports from this one (for resolve_port), so any back-edge would
# create a cycle. Probing inlines its own ``shutil.which("mpremote")``
# lookup instead.


Mode = Literal["serial", "bootsel"]


@dataclass(frozen=True)
class DiscoveredDevice:
    """A connected Pico-family device.

    Attributes:
        port: Path the rest of the CLI hands to mpremote (serial mode)
            or to the flash runner (bootsel mode). For serial mode this
            is ``/dev/ttyACM0`` / ``COM3``; for bootsel mode it's the
            mass-storage mount path (e.g. ``/run/media/$USER/RPI-RP2``).
        mode: ``"serial"`` if the board is running firmware,
            ``"bootsel"`` if it's in the ROM bootloader.
        vid: USB Vendor ID, when known.
        pid: USB Product ID, when known.
        serial_number: USB serial-number string, when reported (serial
            mode only; the BOOTSEL ROM exposes a serial but we don't
            read it from the mount).
        manufacturer: USB manufacturer string (serial mode only).
        product: USB product string (serial mode only).
        signature: Matched :class:`UsbSignature`, or ``None`` if the
            (vid, pid) wasn't in our catalogue.
        chip: Chip family detected by ``--probe`` or read off the
            BOOTSEL volume's ``INFO_UF2.TXT``. ``None`` when probing
            wasn't requested or was inconclusive.
        profile: Board profile slug matched from the device's
            ``os.uname().machine`` prefix. ``None`` when probing
            wasn't requested, the probe failed, or the machine string
            didn't match any known :class:`boards.BoardProfile`.
    """

    port: str
    mode: Mode
    vid: int | None
    pid: int | None
    serial_number: str | None
    manufacturer: str | None
    product: str | None
    signature: UsbSignature | None
    chip: str | None = None
    profile: str | None = None

    @property
    def is_likely_pico(self) -> bool:
        """Whether this device matched a known Pico fingerprint."""
        return self.signature is not None


# ---------- chip probing -----------------------------------------------------
#
# `pico discover --probe` adds CHIP / PROFILE columns by talking to each
# serial-mode device. BOOTSEL devices already carry chip info in
# `INFO_UF2.TXT`, so we read that directly instead of probing.

_PROBE_TIMEOUT_SECS = 15.0

# RP2040 / RP2350 / future RPxxxx chip-family tokens. Matched
# case-insensitively against the device's ``os.uname().machine``
# string.
_CHIP_TOKEN_RE = re.compile(r"RP\d{4,}", re.IGNORECASE)


def normalize_chip(raw: str) -> str:
    """Extract and normalize a Pico chip family from a uname-style string.

    Examples::

        "Raspberry Pi Pico with RP2040"   → "RP2040"
        "Raspberry Pi Pico 2 with RP2350" → "RP2350"
    """
    matches: list[str] = _CHIP_TOKEN_RE.findall(raw)
    if not matches:
        return raw.strip()[:30]
    return matches[-1].upper()


def _probe_identity(port: str) -> tuple[str, str | None]:
    """Probe a serial-mode Pico for chip family + board profile.

    Single ``mpremote eval "__import__('os').uname().machine"`` call;
    the result string is parsed two ways — chip-family token at the
    tail (via :func:`normalize_chip`), board-name prefix via
    :func:`boards.infer_from_machine`. Returns
    ``(chip_label, profile_slug_or_None)``. ``chip_label`` is always
    a string (a placeholder like ``"(no mpy)"`` if probing fails).

    Prints a short ``probing …`` progress note to stderr so the user
    isn't staring at silence for 7+s during cold USB-CDC handshakes.
    """
    print(f"probing {port} …", file=sys.stderr, flush=True)
    binary = shutil.which("mpremote")
    if binary is None:
        return "(no mpremote)", None
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
    except subprocess.TimeoutExpired:
        return "(timeout)", None
    if result.returncode != 0 or not result.stdout.strip():
        return "(no mpy)", None
    raw = result.stdout.strip()
    # Some mpremote versions print repr() of strings, some print the
    # raw value. Strip surrounding quotes if present.
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        raw = raw[1:-1]
    chip = normalize_chip(raw)
    profile_match = boards.infer_from_machine(raw)
    profile = profile_match.slug if profile_match else None
    return chip, profile


# ---------- BOOTSEL mount discovery ------------------------------------------


def _bootsel_mount_roots() -> list[Path]:
    """Return platform-specific candidate parents that may contain a
    mounted BOOTSEL volume.

    The actual ``RPI-RP2`` / ``RP2350`` subdirectory inside one of
    these is what gets returned by :func:`_find_bootsel_mounts`.
    """
    user = os.environ.get("USER", "")
    roots: list[Path] = []
    if sys.platform == "darwin":
        roots.append(Path("/Volumes"))
    else:
        # Linux / BSD. Order from most-likely to least-likely.
        if user:
            roots.append(Path(f"/run/media/{user}"))
            roots.append(Path(f"/media/{user}"))
        roots.append(Path("/media"))
        roots.append(Path("/run/media"))
        roots.append(Path("/mnt"))
    return [r for r in roots if r.is_dir()]


_BOOTSEL_VOLUME_LABELS = {
    "RPI-RP2": "RP2040",  # original Pico, Pico W, Pico Lite, etc.
    "RP2350": "RP2350",   # Pico 2, Pico 2 W.
}


def _find_bootsel_mounts() -> list[tuple[Path, str]]:
    """Scan likely mount roots for a Pico BOOTSEL volume.

    Returns a list of ``(mount_path, chip_family)`` pairs. A mount is
    considered a real BOOTSEL drive only if it contains the
    ``INFO_UF2.TXT`` sentinel file that the Pico ROM bootloader
    always writes; otherwise we might pick up an unrelated USB
    drive that happens to share a label.
    """
    found: list[tuple[Path, str]] = []
    for root in _bootsel_mount_roots():
        try:
            entries = list(root.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            chip = _BOOTSEL_VOLUME_LABELS.get(entry.name)
            if chip is None:
                continue
            if not (entry / "INFO_UF2.TXT").is_file():
                continue
            found.append((entry, chip))
    return found


def _read_info_uf2_model(mount: Path) -> str | None:
    """Return the ``Model:`` field from ``INFO_UF2.TXT``, if readable.

    Used as the ``product`` string for BOOTSEL devices so the table
    shows something more useful than ``-``. Best-effort: a Pico in
    BOOTSEL with an unreadable mount just leaves ``product`` blank.
    """
    try:
        text = (mount / "INFO_UF2.TXT").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("Model:"):
            return line[len("Model:"):].strip()
    return None


# ---------- top-level discover -----------------------------------------------


def discover(
    include_unknown: bool = False,
    port: str | None = None,
    *,
    probe: bool = False,
) -> list[DiscoveredDevice]:
    """Enumerate Pico-family devices on USB.

    Returns serial-mode devices (Pico running firmware) and BOOTSEL-mode
    devices (Pico mounted as USB mass storage) merged into one list,
    sorted by port path.

    Args:
        include_unknown: If ``True``, also return serial ports that
            don't match a known Pico fingerprint. Useful for
            troubleshooting unrecognized boards. Has no effect on
            BOOTSEL enumeration — that path is already strict
            (requires the ``INFO_UF2.TXT`` sentinel).
        port: If set, only inspect the given port path; all other ports
            and mounts are skipped. ``include_unknown`` is implicitly
            treated as ``True`` when a specific port is requested.
        probe: If ``True``, talk to each serial-mode device to identify
            the chip family and board profile behind it. BOOTSEL
            devices skip the mpremote probe and use ``INFO_UF2.TXT``
            instead — no serial REPL is available in that state.
    """
    devices: list[DiscoveredDevice] = []

    # Serial-mode (CDC) enumeration via pyserial.
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
            chip, profile = _probe_identity(info.device)

        devices.append(
            DiscoveredDevice(
                port=info.device,
                mode="serial",
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

    # BOOTSEL-mode enumeration via mass-storage mount scan. Skipped
    # entirely when ``port`` filters to a specific (presumably serial)
    # path the user already named.
    if port is None:
        for mount, chip_family in _find_bootsel_mounts():
            devices.append(
                DiscoveredDevice(
                    port=str(mount),
                    mode="bootsel",
                    vid=0x2E8A,
                    pid=0x0003 if chip_family == "RP2040" else 0x000F,
                    serial_number=None,
                    manufacturer="Raspberry Pi",
                    product=_read_info_uf2_model(mount),
                    signature=match(
                        0x2E8A, 0x0003 if chip_family == "RP2040" else 0x000F
                    ),
                    chip=chip_family,
                    profile=None,  # BOOTSEL can't tell us which build is about to run
                )
            )

    devices.sort(key=lambda d: d.port)
    return devices


# ---------- formatters -------------------------------------------------------


def _fmt_hex(value: int | None) -> str:
    return f"0x{value:04X}" if value is not None else "-"


def format_table(devices: list[DiscoveredDevice]) -> str:
    """Render discovered devices as a human-readable text table.

    The ``CHIP`` and ``PROFILE`` columns appear together when at least
    one device has been probed (or comes from a BOOTSEL mount, which
    fills CHIP directly). The ``MODE`` column is always shown so
    serial vs BOOTSEL entries are unambiguous.
    """
    if not devices:
        return (
            "No Raspberry Pi Pico devices found.\n"
            "Re-run with `--all` to list other serial ports, or hold BOOTSEL "
            "while plugging in the board to surface it as a mass-storage drive."
        )

    include_probe = any(dev.chip is not None for dev in devices)

    headers: tuple[str, ...]
    rows: list[tuple[str, ...]] = []
    if include_probe:
        headers = (
            "PORT", "MODE", "VID", "PID", "BOARD / ROLE",
            "CHIP", "PROFILE", "PRODUCT",
        )
    else:
        headers = ("PORT", "MODE", "VID", "PID", "BOARD / ROLE", "PRODUCT")

    for dev in devices:
        label = dev.signature.label if dev.signature else "(unknown)"
        if include_probe:
            rows.append(
                (
                    dev.port,
                    dev.mode,
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
                    dev.mode,
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

    VID/PID become hex strings; ``signature`` is expanded as a nested
    object (or ``null``); ``is_likely_pico`` is included for
    consumers that don't want to re-check ``signature``.
    """
    payload: list[dict[str, Any]] = []
    for dev in devices:
        entry = asdict(dev)
        entry["vid"] = _fmt_hex(dev.vid) if dev.vid is not None else None
        entry["pid"] = _fmt_hex(dev.pid) if dev.pid is not None else None
        entry["is_likely_pico"] = dev.is_likely_pico
        payload.append(entry)
    return json.dumps(payload, indent=2)
