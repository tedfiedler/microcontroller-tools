"""Small helpers shared by tools that talk to an ESP32 over USB.

Keeping this module private (leading underscore) because it's internal wiring,
not part of the CLI surface.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Literal, overload

from esp32 import discover


class MpyError(RuntimeError):
    """Raised for recoverable errors when driving a device via mpremote.

    Also raised by :func:`resolve_port` for the broader "find an ESP32 on USB"
    cases used by pre-flash flows that don't yet involve MicroPython.
    """


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


def mpremote_binary() -> str:
    """Locate the ``mpremote`` binary or raise :class:`MpyError`."""
    binary = shutil.which("mpremote")
    if binary is None:
        raise MpyError(
            "mpremote not found on PATH. Re-run `uv sync` to install the dep."
        )
    return binary


def run_mpremote(
    port: str,
    argv: list[str],
    *,
    echo: bool = True,
    check: bool = True,
) -> int:
    """Invoke mpremote with ``connect <port>`` prefixed.

    Args:
        port: Serial port passed to ``mpremote connect``.
        argv: The mpremote subcommand args (e.g. ``["fs", "ls", ":"]``).
        echo: If True, print the command line and stream the child's
            stdout/stderr to the terminal. If False, suppress the echo and
            capture (and discard, on success) the child's output — used by
            ``--quiet`` flows that want clean output but still loud errors.
        check: If True, raise :class:`MpyError` when mpremote exits non-zero.
            Set False for best-effort calls like speculative ``fs mkdir``.

    Returns:
        mpremote's exit code.

    Raises:
        MpyError: If ``check`` is True and mpremote exits non-zero. When
            ``echo=False`` the captured stderr is folded into the error
            message so failures stay actionable under ``--quiet``.
    """
    binary = mpremote_binary()
    cmd = [binary, "connect", port, *argv]
    if echo:
        print(f"$ {' '.join(cmd)}", flush=True)
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=not echo,
        text=not echo,
    )
    if check and result.returncode != 0:
        msg = f"mpremote exited with status {result.returncode}"
        if not echo and result.stderr:
            msg += f": {result.stderr.strip()}"
        raise MpyError(msg)
    return result.returncode


def run_mpremote_capture(
    port: str, argv: list[str], *, echo: bool = True
) -> str:
    """Invoke mpremote and return captured stdout as text.

    Use this when the caller needs to parse mpremote/device output (e.g.
    enumerating files via a walk script). The child's stdout is captured
    rather than streamed; ``echo`` controls only whether we print the
    invoked command line for transparency.

    Raises:
        MpyError: If mpremote exits non-zero. Stderr is included in the
            error message to make remote-side failures actionable.
    """
    binary = mpremote_binary()
    cmd = [binary, "connect", port, *argv]
    if echo:
        print(f"$ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise MpyError(
            f"mpremote exited with status {result.returncode}"
            + (f": {stderr}" if stderr else "")
        )
    return result.stdout
