"""Port resolution for Pico-family devices.

Thin module: the mpremote primitives (``MpyError``, ``mpremote_binary``,
``run_mpremote``, ``run_mpremote_capture``) live in :mod:`common._mpy`.
The only family-specific piece is :func:`resolve_port`, which knows
that "a Pico we can talk to" means a *serial-mode* port whose
fingerprint matches :data:`pico.usb_ids.PICO_SIGNATURES`. BOOTSEL-mode
devices are intentionally skipped here — they can't run mpremote.

``common._mpy.MpyError`` is re-exported for callers that still use the
historical ``from pico._mpy import MpyError`` form.
"""

from __future__ import annotations

from common._mpy import MpyError
from pico import discover

__all__ = ["MpyError", "resolve_port"]


def resolve_port(explicit_port: str | None) -> str:
    """Return a connected Pico's serial port.

    Args:
        explicit_port: If non-None, returned as-is — the caller already
            knows which port to use.

    Raises:
        MpyError: If no Pico device is found, or multiple candidate
            serial-mode Picos are present.
    """
    if explicit_port is not None:
        return explicit_port

    devices = discover.discover(include_unknown=False)
    serial_devices = [d for d in devices if d.mode == "serial"]
    bootsel_count = sum(1 for d in devices if d.mode == "bootsel")

    if not serial_devices:
        if bootsel_count:
            raise MpyError(
                f"Found {bootsel_count} Pico in BOOTSEL mode but no serial-mode "
                "Pico. Flash MicroPython with `pico flash`, then try again."
            )
        raise MpyError(
            "No Raspberry Pi Pico devices found on USB. "
            "Plug one in running MicroPython, or pass --port."
        )

    if len(serial_devices) > 1:
        port_list = ", ".join(d.port for d in serial_devices)
        raise MpyError(
            f"Multiple Pico devices found ({port_list}). "
            "Disambiguate with --port <path>."
        )
    return serial_devices[0].port
