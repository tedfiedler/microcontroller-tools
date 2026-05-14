"""Port resolution for ESP32-family devices.

This module is intentionally thin: the mpremote primitives
(``MpyError``, ``mpremote_binary``, ``run_mpremote``,
``run_mpremote_capture``) all live in :mod:`common._mpy`. The only
piece that's family-specific is :func:`resolve_port`, which knows that
"a device of our family" means "a port whose USB fingerprint matches
:data:`esp32.usb_ids.ESP32_SIGNATURES`".

The ``common._mpy.MpyError`` class is re-exported here for callers that
still use the historical ``from esp32._mpy import MpyError`` form.
"""

from __future__ import annotations

from typing import Literal, overload

from common._mpy import MpyError
from esp32 import discover

__all__ = ["MpyError", "resolve_port"]


@overload
def resolve_port(
    explicit_port: str | None,
    *,
    prefer_micropython: bool = ...,
    allow_empty: Literal[False] = ...,
) -> str: ...


@overload
def resolve_port(
    explicit_port: str | None,
    *,
    prefer_micropython: bool = ...,
    allow_empty: Literal[True],
) -> str | None: ...


def resolve_port(
    explicit_port: str | None,
    *,
    prefer_micropython: bool = True,
    allow_empty: bool = False,
) -> str | None:
    """Return a connected ESP32's serial port.

    Args:
        explicit_port: If non-None, returned as-is — the caller already knows
            which port to use.
        prefer_micropython: If True, prefer devices whose USB signature
            explicitly indicates MicroPython (e.g. Arduino Nano ESP32 with
            PID ``0x056B``); fall back to any single detected ESP32 otherwise.
            Set to False for pre-flash flows where the device may still be
            running Arduino stock firmware (generic ESP32 boards keep the
            same VID/PID across firmwares, so this only changes behavior
            for the Arduino Nano ESP32).
        allow_empty: If True, return ``None`` when no devices are found
            rather than raising. Used by the DFU-flash path where the board
            may already be in DFU mode (no serial port enumerated).

    Raises:
        MpyError: If no device is found (and ``allow_empty`` is False), or
            multiple candidate ESP32 devices are present.
    """
    if explicit_port is not None:
        return explicit_port

    devices = discover.discover(include_unknown=False)
    if not devices:
        if allow_empty:
            return None
        hint = (
            "Plug one in running MicroPython, or pass --port."
            if prefer_micropython
            else "Plug one in and try again."
        )
        raise MpyError(f"No ESP32 devices found on USB. {hint}")

    if prefer_micropython:
        mpy = [d for d in devices if d.signature and "MicroPython" in d.signature.label]
        candidates = mpy or devices
    else:
        candidates = devices

    if len(candidates) > 1:
        port_list = ", ".join(d.port for d in candidates)
        raise MpyError(
            f"Multiple ESP32 devices found ({port_list}). "
            "Disambiguate with --port <path>."
        )
    return candidates[0].port
