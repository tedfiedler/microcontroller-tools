"""Chip-agnostic mpremote helpers.

Anything that talks to a MicroPython device over the ``mpremote`` CLI
goes through here. The shared runners under :mod:`common` and the
family-specific port resolvers under each device-family package all
build on top of these three primitives.

Port resolution itself (auto-detecting a connected device) is
*not* in this module — it depends on which USB fingerprints count as
"this family's devices", which is necessarily family-specific. See
each family's ``_mpy.resolve_port`` implementation.
"""

from __future__ import annotations

import shutil
import subprocess


class MpyError(RuntimeError):
    """Raised for recoverable errors when driving a device via mpremote.

    Family-specific ``resolve_port`` functions also raise this — they
    cover the broader "find a device of this family on USB" case used
    by pre-flash flows that don't yet involve MicroPython, but share
    the same error type so callers only need one ``except`` clause.
    """


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
