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
import sys
import tempfile
from pathlib import Path

from esp32._mpy import MpyError, resolve_port, run_mpremote, run_mpremote_capture


class CodeError(RuntimeError):
    """Raised for recoverable push/pull/ls errors (missing port, mpremote failure)."""


def _ensure_remote_dir(port: str, remote_dir: str) -> None:
    """Make sure ``remote_dir`` exists on the device.

    Used as a workaround for an mpremote quirk: when ``fs -r cp <src> <dest>``
    runs with ``dest`` not yet existing *and* ``src`` has no subdirectories,
    mpremote falls through to the non-recursive cp path and errors out with
    ``"cp: -r not specified"``. Pre-creating the dest dir dodges that.
    """
    # Idempotent: silently ignore "File exists".
    run_mpremote(port, ["fs", "mkdir", remote_dir], quiet=True)


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
        port = resolve_port(args.port)
        remote = _resolve_push_remote(local, args.remote)

        if local.is_file():
            run_mpremote(port, ["fs", "cp", str(local), remote])
        else:
            _push_directory(port, local, remote)
    except (CodeError, MpyError) as exc:
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
        run_mpremote(port, ["fs", "-r", "cp", str(local), remote])
    else:
        _ensure_remote_dir(port, remote)
        remote_base = remote.rstrip("/")
        for entry in sorted(local.iterdir()):
            if entry.is_file():
                run_mpremote(
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
        port = resolve_port(args.port)

        if args.all_into is not None:
            if args.remote is not None:
                raise CodeError(
                    "--all and a remote positional are mutually exclusive."
                )
            _pull_all(port, Path(args.all_into).expanduser())
            return 0

        if args.remote is None:
            raise CodeError("Provide a remote path, or use --all <dir>.")

        remote = _remote(args.remote)
        local = _resolve_pull_local(args.remote, args.local)

        fs_argv = ["fs"]
        if args.recursive:
            fs_argv.append("-r")
        fs_argv.extend(["cp", remote, str(local)])

        run_mpremote(port, fs_argv)
    except (CodeError, MpyError) as exc:
        print(f"esp32 pull: {exc}", file=sys.stderr)
        return 1
    return 0


# ---------- pull --all (whole-device backup) ---------------------------------


# Walks the device filesystem from "/" and prints one "<size> <abs_path>" line
# per file. Uses ``os.ilistdir`` (MicroPython's typed listdir) so we don't
# need a separate ``stat`` round-trip per entry: ``type_`` is ``0x4000`` for
# directories and ``0x8000`` for regular files.
_DEVICE_WALK_SCRIPT = """\
import os
def walk(path):
    for name, type_, *_ in os.ilistdir(path):
        full = (path + '/' + name) if path != '/' else ('/' + name)
        if type_ == 0x4000:
            walk(full)
        else:
            try:
                size = os.stat(full)[6]
            except OSError:
                size = 0
            print(size, full)
walk('/')
"""


def _walk_device(port: str) -> list[tuple[int, str]]:
    """Enumerate every regular file on the device.

    Sends a small walker script via ``mpremote run`` (host tempfile) rather
    than ``mpremote exec`` so the invocation pattern matches the rest of the
    codebase and we don't depend on long-argv quoting behavior.

    Returns:
        A list of ``(size, absolute_device_path)`` tuples, in walk order.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(_DEVICE_WALK_SCRIPT)
        tmp_path = tmp.name
    try:
        stdout = run_mpremote_capture(port, ["run", tmp_path])
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    entries: list[tuple[int, str]] = []
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        size_str, _, path = line.partition(" ")
        try:
            size = int(size_str)
        except ValueError:
            # Skip anything the device printed that wasn't from the walker
            # (banners, REPL noise from earlier mpremote sessions, etc.).
            continue
        if path.startswith("/"):
            entries.append((size, path))
    return entries


def _pull_all(port: str, into: Path) -> None:
    """Pull every file from the device into ``into``, mirroring the device tree.

    Per-file ``fs cp`` rather than mpremote's recursive ``fs -r cp`` to dodge
    the same flat-dir quirk we work around on push. Subdirectories on the
    host are created lazily.
    """
    if into.exists() and not into.is_dir():
        raise CodeError(
            f"--all destination exists but is not a directory: {into}"
        )

    entries = _walk_device(port)
    if not entries:
        print("Device filesystem is empty; nothing to pull.")
        return

    into.mkdir(parents=True, exist_ok=True)
    print(f"Pulling {len(entries)} files into {into}/")
    for _, device_path in entries:
        # device_path is absolute ("/boot.py", "/lib/foo.py"). Mirror it
        # under `into` by stripping the leading slash.
        local_path = into / device_path.lstrip("/")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        run_mpremote(port, ["fs", "cp", f":{device_path}", str(local_path)])
    total = sum(size for size, _ in entries)
    print(f"Done. Pulled {len(entries)} files ({total:,} bytes total).")


# ---------- ls ---------------------------------------------------------------


def run_ls(args: argparse.Namespace) -> int:
    """Entry point for ``esp32 ls``."""
    try:
        port = resolve_port(args.port)
        remote = _remote(args.remote) if args.remote else ":"
        run_mpremote(port, ["fs", "ls", remote])
    except (CodeError, MpyError) as exc:
        print(f"esp32 ls: {exc}", file=sys.stderr)
        return 1
    return 0
