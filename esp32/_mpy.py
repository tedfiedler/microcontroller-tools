"""Small helpers shared by tools that talk to a MicroPython-running ESP32.

Keeping this module private (leading underscore) because it's internal wiring,
not part of the CLI surface.
"""

from __future__ import annotations

import shutil
import subprocess

from esp32 import discover


class MpyError(RuntimeError):
    """Raised for recoverable errors when driving a MicroPython device."""


def resolve_port(explicit_port: str | None) -> str:
    """Return a MicroPython-running ESP32's serial port.

    Prefers devices whose USB signature explicitly indicates MicroPython
    (e.g. Arduino Nano ESP32 with PID ``0x056B``). Falls back to any single
    detected ESP32 if no MicroPython-specific fingerprint is present —
    generic ESP32 boards don't change VID/PID between Arduino stock and
    MicroPython, so we can't always tell without actually talking to it.
    """
    if explicit_port is not None:
        return explicit_port

    devices = discover.discover(include_unknown=False)
    if not devices:
        raise MpyError(
            "No ESP32 devices found on USB. Plug one in running MicroPython, "
            "or pass --port."
        )

    mpy = [d for d in devices if d.signature and "MicroPython" in d.signature.label]
    candidates = mpy or devices
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
    port: str, argv: list[str], *, quiet: bool = False, echo: bool = True
) -> int:
    """Invoke mpremote with ``connect <port>`` prefixed, streaming output.

    Args:
        port: Serial port passed to ``mpremote connect``.
        argv: The mpremote subcommand args (e.g. ``["fs", "ls", ":"]``).
        quiet: If True, suppress stdout/stderr and don't raise on non-zero
            exit (used for best-effort commands like speculative mkdir).
        echo: If True and not ``quiet``, echo the full command to stdout
            before running so the user can see what's being dispatched.

    Returns:
        mpremote's exit code.

    Raises:
        MpyError: If ``quiet`` is False and mpremote exits non-zero.
    """
    binary = mpremote_binary()
    cmd = [binary, "connect", port, *argv]
    if echo and not quiet:
        print(f"$ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, check=False, capture_output=quiet)
    if not quiet and result.returncode != 0:
        raise MpyError(f"mpremote exited with status {result.returncode}")
    return result.returncode
