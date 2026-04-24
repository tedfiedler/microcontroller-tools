"""Tool 3: Push/pull code between the host and an ESP32 running MicroPython.

Wraps the official ``mpremote`` CLI so we get its well-tested filesystem
protocol (paste mode + raw REPL) without reimplementing any of it. Three
user-facing operations:

* ``esp32 push <local> [remote]`` — copy a file or directory onto the device.
* ``esp32 pull <remote> [local]`` — copy a file or directory off the device.
* ``esp32 ls   [remote]``         — list files on the device.

Remote paths are **unprefixed** at our CLI layer (``main.py``, ``/lib/foo``)
and get the ``:`` prefix mpremote expects added automatically. Host paths
are whatever makes sense to the shell (``./app/main.py``, ``/tmp/backup``).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from esp32 import discover


class CodeError(RuntimeError):
    """Raised for recoverable push/pull/ls errors (missing port, mpremote failure)."""


def _resolve_port(explicit_port: str | None) -> str:
    """Return the serial port of a MicroPython-running ESP32.

    Prefers devices whose USB signature indicates MicroPython (e.g. the
    Nano ESP32's PID ``0x056B``) when multiple ESP32s are connected. Falls
    back to any single detected ESP32 if no MicroPython-specific signature
    is present (generic ESP32 boards don't change VID/PID across firmware).
    """
    if explicit_port is not None:
        return explicit_port

    devices = discover.discover(include_unknown=False)
    if not devices:
        raise CodeError(
            "No ESP32 devices found on USB. Plug in a board running "
            "MicroPython, or pass --port."
        )

    mpy = [d for d in devices if d.signature and "MicroPython" in d.signature.label]
    candidates = mpy or devices
    if len(candidates) > 1:
        port_list = ", ".join(d.port for d in candidates)
        raise CodeError(
            f"Multiple ESP32 devices found ({port_list}). "
            "Disambiguate with --port <path>."
        )
    return candidates[0].port


def _mpremote_path() -> str:
    """Locate the ``mpremote`` binary or raise :class:`CodeError`."""
    binary = shutil.which("mpremote")
    if binary is None:
        raise CodeError(
            "mpremote not found on PATH. Re-run `uv sync` to install the dep."
        )
    return binary


def _run_mpremote(port: str, argv: list[str], *, quiet: bool = False) -> int:
    """Invoke mpremote with ``connect <port>`` prefixed, streaming output.

    Args:
        port: Serial port passed to ``mpremote connect``.
        argv: The mpremote subcommand args (e.g. ``["fs", "ls", ":"]``).
        quiet: When True, suppress the ``$`` echo and capture output (still
            exits non-zero via return code). Used for best-effort commands
            like pre-creating a destination directory.

    Returns:
        mpremote's exit code (so callers can distinguish "it failed" from
        "it ran and produced output").

    Raises:
        CodeError: If ``quiet`` is False and mpremote exits non-zero.
    """
    binary = _mpremote_path()
    cmd = [binary, "connect", port, *argv]
    if not quiet:
        print(f"$ {' '.join(cmd)}", flush=True)
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=quiet,
    )
    if not quiet and result.returncode != 0:
        raise CodeError(f"mpremote exited with status {result.returncode}")
    return result.returncode


def _ensure_remote_dir(port: str, remote_dir: str) -> None:
    """Make sure ``remote_dir`` exists on the device.

    Workaround for an mpremote quirk: when ``fs -r cp <src_dir> <dest>`` runs
    with ``dest`` not yet existing *and* ``src_dir`` has no subdirectories,
    mpremote falls through to the non-recursive cp path and errors out with
    ``"cp: -r not specified"``. Pre-creating the destination dir makes the
    recursive walker take the correct path.
    """
    # Silently ignore "File exists" etc — mkdir is idempotent for our purposes.
    _run_mpremote(port, ["fs", "mkdir", remote_dir], quiet=True)


def _remote(path: str) -> str:
    """Add mpremote's ``:`` prefix for device paths if not already present."""
    return path if path.startswith(":") else f":{path}"


# ---------- push -------------------------------------------------------------


def _resolve_push_remote(local: Path, remote_arg: str | None) -> str:
    """Pick a destination path on the device for a local source.

    If the user gave an explicit remote path, use it. Otherwise default to
    the device filesystem root plus the source's basename, so
    ``esp32 push app.py`` lands at ``:app.py``.
    """
    if remote_arg is not None:
        return _remote(remote_arg)
    return _remote(local.name)


def run_push(args: argparse.Namespace) -> int:
    """Entry point for ``esp32 push``."""
    try:
        local = Path(args.local).expanduser()
        if not local.exists():
            raise CodeError(f"local path does not exist: {local}")
        port = _resolve_port(args.port)
        remote = _resolve_push_remote(local, args.remote)

        if local.is_file():
            _run_mpremote(port, ["fs", "cp", str(local), remote])
        else:
            _push_directory(port, local, remote)
    except CodeError as exc:
        print(f"esp32 push: {exc}", file=sys.stderr)
        return 1
    return 0


def _push_directory(port: str, local: Path, remote: str) -> None:
    """Push a local directory tree to the device at ``remote``.

    mpremote's ``fs -r cp`` has a quirk: when the source directory has no
    subdirectories, the recursive walker ends with an empty ``dirs`` list
    and falls through to a non-recursive cp that then errors out with
    ``cp: -r not specified``. We detect that case (flat top-level) and
    copy each file individually after pre-creating the destination dir.
    For non-flat trees, mpremote's native recursive cp is used as-is.
    """
    has_subdirs = any(p.is_dir() for p in local.iterdir())
    if has_subdirs:
        # Native recursive cp works here; don't pre-create dest (doing so
        # flips mpremote into "copy INTO parent" mode and creates a nested
        # duplicate directory).
        _run_mpremote(port, ["fs", "-r", "cp", str(local), remote])
    else:
        _ensure_remote_dir(port, remote)
        remote_base = remote.rstrip("/")
        for entry in sorted(local.iterdir()):
            if entry.is_file():
                _run_mpremote(
                    port, ["fs", "cp", str(entry), f"{remote_base}/{entry.name}"]
                )


# ---------- pull -------------------------------------------------------------


def _resolve_pull_local(remote: str, local_arg: str | None) -> Path:
    """Pick a destination path on the host for a remote source."""
    if local_arg is not None:
        return Path(local_arg).expanduser()
    # Strip the `:` prefix and any leading slashes, then take the basename.
    # E.g. `:main.py` -> `main.py`, `:/lib/foo.py` -> `foo.py`. If the user
    # asked for the whole filesystem (`:` or `:/`), default to the CWD.
    basename = Path(remote.lstrip(":").lstrip("/")).name
    return Path(basename) if basename else Path(".")


def run_pull(args: argparse.Namespace) -> int:
    """Entry point for ``esp32 pull``."""
    try:
        port = _resolve_port(args.port)
        remote = _remote(args.remote)
        local = _resolve_pull_local(args.remote, args.local)

        fs_argv = ["fs"]
        if args.recursive:
            fs_argv.append("-r")
        fs_argv.extend(["cp", remote, str(local)])

        _run_mpremote(port, fs_argv)
    except CodeError as exc:
        print(f"esp32 pull: {exc}", file=sys.stderr)
        return 1
    return 0


# ---------- ls ---------------------------------------------------------------


def run_ls(args: argparse.Namespace) -> int:
    """Entry point for ``esp32 ls``."""
    try:
        port = _resolve_port(args.port)
        remote = _remote(args.remote) if args.remote else ":"
        _run_mpremote(port, ["fs", "ls", remote])
    except CodeError as exc:
        print(f"esp32 ls: {exc}", file=sys.stderr)
        return 1
    return 0
