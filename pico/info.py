"""Tool 6 (Pico family): one-shot summary of a connected Pico.

Thin family wrapper over :mod:`common.info`. The on-device probe
script, ``DeviceInfo`` dataclass, and the ``format_text`` / ``format_json``
renderers all live in common; this module supplies the Pico-specific
glue: USB-level fingerprint lookup via :mod:`pico.discover`, and
chip-family / board-profile inference from the device's
``os.uname().machine`` string.
"""

from __future__ import annotations

import argparse
import sys

from common._mpy import MpyError
from common.info import (
    DeviceInfo,
    InfoError,
    format_json,
    format_text,
    parse_fs_usage,
    parse_ifconfig,
    run_probe_script,
)
from pico import boards, discover
from pico._mpy import resolve_port

__all__ = ["DeviceInfo", "InfoError", "collect", "run"]


def collect(explicit_port: str | None) -> DeviceInfo:
    """Resolve a port, fetch all the info, and return a :class:`DeviceInfo`.

    Combines USB-level info (from :mod:`pico.discover`) with the
    on-device probe payload. Chip family and board profile are derived
    from ``os.uname().machine`` via :func:`pico.discover.normalize_chip`
    and :func:`pico.boards.infer_from_machine`. Only serial-mode
    devices are addressable — a Pico in BOOTSEL has no REPL.
    """
    port = resolve_port(explicit_port)

    usb_devices = discover.discover(include_unknown=True, port=port)
    if not usb_devices:
        usb_vid = usb_pid = None
        usb_label = product = None
    else:
        d = usb_devices[0]
        usb_vid = d.vid
        usb_pid = d.pid
        usb_label = d.signature.label if d.signature else None
        product = d.product

    payload = run_probe_script(port)

    machine = str(payload.get("machine") or "")
    chip = discover.normalize_chip(machine) if machine else None
    profile_obj = boards.infer_from_machine(machine) if machine else None
    profile = profile_obj.slug if profile_obj else None

    fs_used, fs_total = parse_fs_usage(payload.get("fs"))

    return DeviceInfo(
        port=port,
        usb_vid=usb_vid,
        usb_pid=usb_pid,
        usb_label=usb_label,
        product=product,
        chip=chip,
        profile=profile,
        micropython_version=str(payload.get("version") or "?"),
        mac=payload.get("mac"),
        heap_free=int(payload.get("heap_free") or 0),
        heap_used=int(payload.get("heap_used") or 0),
        wlan_active=payload.get("wlan_active"),
        wlan_connected=payload.get("wlan_connected"),
        ssid=payload.get("ssid"),
        ifconfig=parse_ifconfig(payload.get("ifconfig")),
        fs_used_bytes=fs_used,
        fs_total_bytes=fs_total,
    )


def run(args: argparse.Namespace) -> int:
    """Entry point for ``pico info``."""
    try:
        info = collect(args.port)
    except (MpyError, InfoError) as exc:
        print(f"pico info: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(format_json(info))
    else:
        print(format_text(info))
    return 0
