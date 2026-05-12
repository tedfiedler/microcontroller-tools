"""Tool 6: one-shot summary of a connected device.

Combines USB-level fingerprinting (from :mod:`esp32.discover`) with a
single on-device probe script that gathers everything we'd otherwise
query in five separate ``mpremote eval`` calls: chip family, profile,
MicroPython version, MAC, heap usage, filesystem usage, Wi-Fi state.

One mpremote ``run`` → one round-trip → one cold-connect penalty.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from esp32 import boards, discover
from esp32._mpy import MpyError, mpremote_binary, resolve_port

_PROBE_SCRIPT = r"""
# On-device probe: gather everything we care about in one shot and print
# a single JSON line. Everything is wrapped in try/except so a missing
# `network` module, an unsupported `wlan.config` key, or a read-only-fs
# mount doesn't sink the whole probe — keys whose probe failed come back
# as None.
import json, gc, os

machine = os.uname().machine
version = os.uname().version

mac = None
wlan_active = None
wlan_connected = None
wlan_status = None
ssid = None
ifconfig = None
try:
    import network
    wlan = network.WLAN(network.STA_IF)
    try:
        mac = ':'.join('%02x' % b for b in wlan.config('mac'))
    except Exception:
        pass
    try:
        wlan_active = wlan.active()
    except Exception:
        pass
    try:
        wlan_connected = wlan.isconnected()
    except Exception:
        pass
    try:
        wlan_status = wlan.status()
    except Exception:
        pass
    # Config key varies across MicroPython builds: ESP32 typically wants
    # 'essid', generic stubs accept 'ssid'. Try both.
    for _key in ('ssid', 'essid'):
        try:
            ssid = wlan.config(_key)
            break
        except Exception:
            continue
    try:
        if wlan_active:
            ifconfig = list(wlan.ifconfig())
    except Exception:
        pass
except ImportError:
    pass

fs = None
try:
    _s = os.statvfs('/')
    fs = {'bsize': _s[0], 'blocks': _s[2], 'bavail': _s[3]}
except Exception:
    pass

gc.collect()
print(json.dumps({
    'machine': machine,
    'version': version,
    'mac': mac,
    'heap_free': gc.mem_free(),
    'heap_used': gc.mem_alloc(),
    'wlan_active': wlan_active,
    'wlan_connected': wlan_connected,
    'wlan_status': wlan_status,
    'ssid': ssid,
    'ifconfig': ifconfig,
    'fs': fs,
}))
"""

_PROBE_TIMEOUT_SECS = 15.0


class InfoError(RuntimeError):
    """Raised for recoverable errors in the info-collection flow."""


@dataclass(frozen=True)
class DeviceInfo:
    """Everything we know about one connected device."""

    port: str
    usb_vid: int | None
    usb_pid: int | None
    usb_label: str | None
    product: str | None
    chip: str | None
    profile: str | None
    micropython_version: str
    mac: str | None
    heap_free: int
    heap_used: int
    wlan_active: bool | None
    wlan_connected: bool | None
    ssid: str | None
    ifconfig: tuple[str, str, str, str] | None
    fs_used_bytes: int | None
    fs_total_bytes: int | None


# ---------- on-device query --------------------------------------------------


def _run_probe_script(port: str) -> dict[str, Any]:
    """Run the probe script via ``mpremote run`` and return parsed JSON.

    The host tempfile + ``run`` pattern matches the rest of the codebase —
    no script bodies in argv, so anything we ever embed (Wi-Fi password,
    etc.) doesn't leak into ``ps`` / ``/proc``.
    """
    binary = mpremote_binary()
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(_PROBE_SCRIPT)
        tmp_path = tmp.name
    try:
        print(f"probing {port} …", file=sys.stderr, flush=True)
        result = subprocess.run(
            [binary, "connect", port, "run", tmp_path],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECS,
            check=False,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if result.returncode != 0:
        stderr = result.stderr.strip() or "(no stderr)"
        raise InfoError(
            f"mpremote exited with status {result.returncode}: {stderr}"
        )

    # The script prints exactly one JSON line. Find the last non-empty
    # line in stdout in case mpremote/REPL prepends anything.
    json_line = ""
    for line in reversed(result.stdout.splitlines()):
        if line.strip():
            json_line = line.strip()
            break
    try:
        payload: dict[str, Any] = json.loads(json_line)
    except json.JSONDecodeError as exc:
        raise InfoError(
            f"could not parse device output as JSON: {exc}\n  raw: {json_line!r}"
        ) from exc
    return payload


# ---------- collection -------------------------------------------------------


def collect(explicit_port: str | None) -> DeviceInfo:
    """Resolve a port, fetch all the info, and return a :class:`DeviceInfo`."""
    port = resolve_port(explicit_port)

    # USB-level info — fast, no device contact. Don't probe here because
    # the on-device script already returns os.uname().machine for both
    # chip and profile inference.
    usb_devices = discover.discover(include_unknown=True, port=port)
    if not usb_devices:
        # The port resolved but list_ports doesn't know about it — possible
        # for virtual ports or freshly hot-plugged devices. Carry on with
        # the device-side info; USB fields stay None.
        usb_vid = usb_pid = None
        usb_label = product = None
    else:
        d = usb_devices[0]
        usb_vid = d.vid
        usb_pid = d.pid
        usb_label = d.signature.label if d.signature else None
        product = d.product

    payload = _run_probe_script(port)

    machine = str(payload.get("machine") or "")
    chip = discover.normalize_chip(machine) if machine else None
    profile_obj = boards.infer_from_machine(machine) if machine else None
    profile = profile_obj.slug if profile_obj else None

    ifconfig_raw = payload.get("ifconfig")
    ifconfig: tuple[str, str, str, str] | None = None
    if isinstance(ifconfig_raw, list) and len(ifconfig_raw) == 4:
        ifconfig = (
            str(ifconfig_raw[0]),
            str(ifconfig_raw[1]),
            str(ifconfig_raw[2]),
            str(ifconfig_raw[3]),
        )

    fs_payload = payload.get("fs")
    fs_used = fs_total = None
    if isinstance(fs_payload, dict):
        bsize = fs_payload.get("bsize")
        blocks = fs_payload.get("blocks")
        bavail = fs_payload.get("bavail", 0)
        if isinstance(bsize, int) and isinstance(blocks, int):
            fs_total = bsize * blocks
            fs_used = bsize * (blocks - int(bavail or 0))

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
        ifconfig=ifconfig,
        fs_used_bytes=fs_used,
        fs_total_bytes=fs_total,
    )


# ---------- formatting -------------------------------------------------------


def _fmt_bytes(n: int) -> str:
    """Format ``n`` bytes as "12,345 B" or "1.2 MiB" etc."""
    if n < 1024:
        return f"{n:,} B"
    if n < 1024**2:
        return f"{n/1024:.1f} KiB"
    return f"{n/(1024**2):.1f} MiB"


def _fmt_hex(value: int | None) -> str:
    return f"0x{value:04X}" if value is not None else "-"


def format_text(info: DeviceInfo) -> str:
    """Render the info as an aligned ``Key : Value`` block."""
    lines: list[tuple[str, str]] = []

    lines.append(("Port", info.port))
    usb = f"{_fmt_hex(info.usb_vid)}:{_fmt_hex(info.usb_pid)}"
    if info.usb_label:
        usb += f" ({info.usb_label})"
    lines.append(("USB", usb))
    if info.product:
        lines.append(("Product", info.product))
    if info.chip:
        lines.append(("Chip", info.chip))
    if info.profile:
        lines.append(("Profile", info.profile))
    lines.append(("MicroPython", info.micropython_version))
    if info.mac:
        lines.append(("MAC", info.mac))

    total_heap = info.heap_free + info.heap_used
    if total_heap > 0:
        pct = 100.0 * info.heap_free / total_heap
        lines.append((
            "Heap",
            f"{info.heap_free:,} B free / {info.heap_used:,} B used "
            f"({pct:.1f}% free)",
        ))

    if info.fs_total_bytes is not None and info.fs_used_bytes is not None:
        pct = 100.0 * info.fs_used_bytes / info.fs_total_bytes if info.fs_total_bytes else 0
        lines.append((
            "Filesystem",
            f"{_fmt_bytes(info.fs_used_bytes)} used / "
            f"{_fmt_bytes(info.fs_total_bytes)} total ({pct:.1f}% used)",
        ))

    if info.wlan_connected and info.ifconfig:
        ip, netmask, gw, dns = info.ifconfig
        ssid_part = f"connected to {info.ssid!r}; " if info.ssid else "connected; "
        lines.append(("Wi-Fi", f"{ssid_part}{ip} / {netmask} → gw {gw}, dns {dns}"))
    elif info.wlan_active:
        lines.append(("Wi-Fi", "active but not associated"))
    elif info.wlan_active is False:
        lines.append(("Wi-Fi", "STA interface inactive"))

    key_width = max(len(k) for k, _ in lines)
    return "\n".join(f"{k.ljust(key_width)} : {v}" for k, v in lines)


def format_json(info: DeviceInfo) -> str:
    """Render the info as pretty-printed JSON."""
    payload = {
        "port": info.port,
        "usb": {
            "vid": _fmt_hex(info.usb_vid) if info.usb_vid is not None else None,
            "pid": _fmt_hex(info.usb_pid) if info.usb_pid is not None else None,
            "label": info.usb_label,
            "product": info.product,
        },
        "chip": info.chip,
        "profile": info.profile,
        "micropython_version": info.micropython_version,
        "mac": info.mac,
        "heap": {"free": info.heap_free, "used": info.heap_used},
        "filesystem": (
            None
            if info.fs_total_bytes is None
            else {
                "used_bytes": info.fs_used_bytes,
                "total_bytes": info.fs_total_bytes,
            }
        ),
        "wifi": {
            "active": info.wlan_active,
            "connected": info.wlan_connected,
            "ssid": info.ssid,
            "ifconfig": list(info.ifconfig) if info.ifconfig else None,
        },
    }
    return json.dumps(payload, indent=2)


# ---------- CLI entry --------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    """Entry point for ``esp32 info``."""
    try:
        info = collect(args.port)
    except (MpyError, InfoError) as exc:
        print(f"esp32 info: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(format_json(info))
    else:
        print(format_text(info))
    return 0
