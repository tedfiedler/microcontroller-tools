"""Tool 5: drop into the MicroPython REPL on the connected device.

A thin wrapper over ``mpremote repl`` that adds the same auto-port
resolution used by the rest of the CLI. Uses :func:`os.execvp` to
replace the current process with mpremote so terminal control
characters (Ctrl-], Ctrl-C) and signals pass through unmediated — a
subprocess wrapper would sit between the user's terminal and mpremote
and could interfere with the REPL's own escape handling.
"""

from __future__ import annotations

import argparse
import os
import sys

from esp32._mpy import MpyError, mpremote_binary, resolve_port


def run(args: argparse.Namespace) -> int:
    """Entry point for ``esp32 repl``.

    Resolves the port, prints the invocation for transparency (so the
    user sees which port auto-detection chose), then execs mpremote.
    The return value is meaningful only when port/binary resolution
    fails before exec — once :func:`os.execvp` succeeds, control never
    returns and mpremote's exit code becomes the shell's.
    """
    try:
        port = resolve_port(args.port)
        binary = mpremote_binary()
    except MpyError as exc:
        print(f"esp32 repl: {exc}", file=sys.stderr)
        return 1

    cmd = [binary, "connect", port, "repl"]
    print(f"$ {' '.join(cmd)}", flush=True)
    os.execvp(binary, cmd)
    return 1  # unreachable; satisfies mypy's "function returns int".
