"""Tool 4 (AVR family): open a serial console to an AVR.

There's no on-device REPL for an Arduino sketch — the AVR analog is
just "raw bytes on the UART". We delegate the terminal handling to
``serial.tools.miniterm``, the pyserial-bundled mini-terminal:

* It already ships in our dependency tree (``pyserial`` is a project
  dep used by every family's ``discover``).
* It handles raw-mode TTY, ANSI passthrough, exit keystrokes
  (``Ctrl-]`` by default), and reconnect on USB hotplug.
* No new system dep (vs. picocom / tio / screen).

``os.execvp`` replaces our process with miniterm so signals and the
terminal flow uninterrupted; once miniterm exits, the shell returns
control to the user directly. We never come back into this function.
"""

from __future__ import annotations

import argparse
import os
import sys

from avr import discover


class MonitorError(RuntimeError):
    """Raised for recoverable monitor-flow errors."""


def run(args: argparse.Namespace) -> int:
    """Entry point for ``avr monitor``.

    Returns an int for type-checking parity with the other runners,
    but in practice it never returns — :func:`os.execvp` replaces the
    process image. The only way out is :class:`MonitorError` from
    port resolution (raised before execvp).
    """
    try:
        port = discover.resolve_port(args.port)
    except discover.PortResolutionError as exc:
        print(f"avr monitor: {exc}", file=sys.stderr)
        return 1

    # `python -m serial.tools.miniterm <port> <baud>` is the canonical
    # invocation. Using `sys.executable` guarantees we run under the
    # same interpreter pyserial is installed into (under uv, that's
    # the project venv).
    argv = [
        sys.executable,
        "-m", "serial.tools.miniterm",
        "--raw",          # don't filter control characters
        port,
        str(args.baud),
    ]
    print(
        f"opening {port} at {args.baud} baud (Ctrl-] to exit) …",
        file=sys.stderr, flush=True,
    )
    try:
        os.execvp(argv[0], argv)
    except OSError as exc:  # pragma: no cover - execvp rarely fails after which()
        print(f"avr monitor: failed to exec miniterm: {exc}", file=sys.stderr)
        return 1
    # execvp doesn't return on success; this line is only reached when
    # the exec itself failed (and we already printed an error above).
    return 1
