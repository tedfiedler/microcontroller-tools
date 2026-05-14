"""Configure a MicroPython device's Wi-Fi STA interface from the host.

Drives the device via ``mpremote run`` against a host-built tempfile —
we assemble a small MicroPython script that activates
``network.WLAN(network.STA_IF)``, optionally sets a static ``ifconfig``,
connects to an SSID, waits for association, and prints the resulting
interface configuration.

The ``network.WLAN(STA_IF)`` API is identical on ESP32 MicroPython and
Pico W MicroPython (cyw43-based), so this module is shared.

Flows:

* ``<cli> wifi <SSID>``             — connect (DHCP), prompts for password.
* ``<cli> wifi <SSID> --open``      — connect to an open (no-password) AP.
* ``<cli> wifi <SSID> --ip 192.168.1.100 ...`` — connect with a static IP.
* ``<cli> wifi --status``           — just print the current interface state.
* ``<cli> wifi <SSID> ... --persist`` — also write a ``_wifi_cfg.py`` on the
  device so it reconnects at boot. The user adds ``import _wifi_cfg`` to
  ``boot.py`` (or ``main.py``) themselves.

.. note::
   ``--persist`` stores the Wi-Fi password **in plaintext** in
   ``_wifi_cfg.py`` on the device. That's the standard MicroPython pattern
   for IoT projects but worth knowing.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from common._mpy import MpyError, mpremote_binary, run_mpremote
from common.family import FamilyContext


class WifiError(RuntimeError):
    """Raised for recoverable wifi-flow errors (bad input, connect timeout, etc.)."""


@dataclass(frozen=True)
class WifiConfig:
    """Desired Wi-Fi configuration.

    Attributes:
        ssid: Network SSID.
        password: Password, or ``""`` for open networks.
        static_ip: Static IPv4 address, or ``None`` for DHCP.
        netmask: IPv4 netmask (used only when ``static_ip`` is set).
        gateway: Default gateway (used only when ``static_ip`` is set).
            If ``None``, derived from ``static_ip`` by replacing the last
            octet with ``.1``.
        dns: Primary DNS server (used only when ``static_ip`` is set).
        timeout_secs: How long to wait for association before giving up.
    """

    ssid: str
    password: str
    static_ip: str | None
    netmask: str
    gateway: str | None
    dns: str
    timeout_secs: float

    def resolved_gateway(self) -> str:
        """Return the effective gateway — explicit or derived from static IP."""
        if self.gateway is not None:
            return self.gateway
        if self.static_ip is None:
            raise WifiError("resolved_gateway() called without a static IP")
        octets = self.static_ip.split(".")
        if len(octets) != 4:
            raise WifiError(f"invalid static IP: {self.static_ip!r}")
        return ".".join([*octets[:3], "1"])


# ---------- script generators ------------------------------------------------


def _build_connect_script(cfg: WifiConfig) -> str:
    """Generate the MicroPython script that connects and prints ifconfig.

    Starts with a deliberate ``active(False) → active(True)`` reset so a
    previously-running wlan state (half-connected, a stale connect from a
    prior REPL session, etc.) doesn't cause ``OSError: Wifi Internal State
    Error`` when we call ``connect()`` again.
    """
    lines: list[str] = [
        "import network, time",
        "wlan = network.WLAN(network.STA_IF)",
        # Reset to a clean slate. ESP32 MicroPython is picky if there's a
        # pending / stale connection state when you call connect() a second
        # time in the same boot.
        "try: wlan.disconnect()",
        "except OSError: pass",
        "wlan.active(False)",
        "time.sleep_ms(100)",
        "wlan.active(True)",
    ]
    if cfg.static_ip is not None:
        gw = cfg.resolved_gateway()
        lines.append(
            f"wlan.ifconfig(({cfg.static_ip!r}, {cfg.netmask!r}, "
            f"{gw!r}, {cfg.dns!r}))"
        )
    lines.extend(
        [
            # ESP32 MicroPython wlan.status() codes. Translate the most
            # useful ones so the on-device error is actionable rather than
            # just an integer. The Pico W's cyw43 stack uses overlapping
            # but not identical codes; unknown values fall through to '?'.
            "_S = {201:'wrong password', 202:'AP not found', "
            "203:'connect failed', 204:'no ap found', 1000:'idle', "
            "1001:'connecting', 1010:'got ip'}",
            f"wlan.connect({cfg.ssid!r}, {cfg.password!r})",
            f"deadline = time.ticks_add(time.ticks_ms(), {int(cfg.timeout_secs * 1000)})",
            "while not wlan.isconnected():",
            "    s = wlan.status()",
            # A non-transient failure (wrong password, no AP) won't recover
            # by waiting — bail out immediately with the decoded reason.
            "    if s in (201, 202, 203, 204):",
            "        raise RuntimeError('Wi-Fi connect failed: status=' "
            "+ str(s) + ' (' + _S.get(s, '?') + ')')",
            "    if time.ticks_diff(deadline, time.ticks_ms()) <= 0:",
            "        raise RuntimeError('Timed out waiting for Wi-Fi; "
            "status=' + str(s) + ' (' + _S.get(s, '?') + ')')",
            "    time.sleep_ms(200)",
            "print('connected; ifconfig =', wlan.ifconfig())",
        ]
    )
    return "\n".join(lines)


def _build_status_script() -> str:
    """Generate the MicroPython script that prints current interface state."""
    return "\n".join(
        [
            "import network",
            "wlan = network.WLAN(network.STA_IF)",
            "print('active     :', wlan.active())",
            "print('isconnected:', wlan.isconnected())",
            "print('status     :', wlan.status())",
            "print('ifconfig   :', wlan.ifconfig())",
        ]
    )


# ---------- CLI --------------------------------------------------------------


def _get_password(args: argparse.Namespace) -> str:
    """Pick the password: ``--password``, ``--open`` (empty), or prompt."""
    if args.open:
        if args.password:
            raise WifiError("--open and --password are mutually exclusive.")
        return ""
    if args.password is not None:
        pw: str = args.password
        return pw
    try:
        return getpass.getpass(f"Password for {args.ssid!r}: ")
    except (EOFError, KeyboardInterrupt) as exc:
        raise WifiError("No password provided.") from exc


def _exec_script(port: str, script: str) -> None:
    """Run ``script`` on the device by writing it to a tempfile and calling
    ``mpremote run``.

    Why not ``mpremote exec <script>``? That passes the script body as an
    argv element, which means an embedded Wi-Fi password is briefly visible
    to other local users via ``ps`` / ``/proc/<pid>/cmdline`` for the
    lifetime of the subprocess. Writing the script to a 0600-mode tempfile
    (``NamedTemporaryFile`` uses ``mkstemp`` under the hood on POSIX) and
    invoking ``mpremote run <path>`` keeps the secret off the process table.
    The file is unlinked in the ``finally`` block.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(script)
        tmp_path = tmp.name
    try:
        run_mpremote(port, ["run", tmp_path])
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _persist_config(port: str, cfg: WifiConfig) -> None:
    """Write ``_wifi_cfg.py`` onto the device by building the file as a
    plain Python literal on the host and copying it over with
    ``mpremote fs cp``.

    The on-device file content is identical to the script we run live for
    the immediate connect — ``import _wifi_cfg`` from ``boot.py`` /
    ``main.py`` to reapply at startup.

    Same secret-handling discipline as :func:`_exec_script`: the host
    tempfile is 0600 and unlinked in ``finally``. The on-device file is
    necessarily readable by anything else running on the device (MicroPython
    has no per-file permissions) — that's the standard plaintext trade-off
    called out in the module docstring.
    """
    body = _build_connect_script(cfg)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(body)
        tmp_path = tmp.name
    try:
        run_mpremote(port, ["fs", "cp", tmp_path, ":_wifi_cfg.py"])
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    print("wrote _wifi_cfg.py on device")
    print(
        "  run `import _wifi_cfg` from boot.py/main.py "
        "to auto-connect on startup"
    )


def run(args: argparse.Namespace, *, family: FamilyContext) -> int:
    """Entry point for the ``<cli> wifi`` subcommand."""
    try:
        # Make sure mpremote is available before we start soliciting passwords.
        mpremote_binary()
        port = family.resolve_port(args.port)

        if args.status:
            _exec_script(port, _build_status_script())
            return 0

        if not args.ssid:
            raise WifiError(
                "SSID is required. Pass it as a positional argument, "
                "or use --status to query current state."
            )

        password = _get_password(args)

        if args.ip is None:
            for name in ("netmask", "gateway", "dns"):
                if getattr(args, name) != _DEFAULTS[name]:
                    raise WifiError(
                        f"--{name} requires --ip to also be given."
                    )

        cfg = WifiConfig(
            ssid=args.ssid,
            password=password,
            static_ip=args.ip,
            netmask=args.netmask,
            gateway=args.gateway,
            dns=args.dns,
            timeout_secs=args.timeout,
        )

        _exec_script(port, _build_connect_script(cfg))

        if args.persist:
            _persist_config(port, cfg)
    except (WifiError, MpyError) as exc:
        print(f"{family.name} wifi: {exc}", file=sys.stderr)
        return 1
    return 0


# Defaults are module-level so the CLI builder and ``run()`` agree on them
# (needed for the "--X without --ip" check in ``run()``).
_DEFAULTS: dict[str, str | None] = {
    "netmask": "255.255.255.0",
    "gateway": None,
    "dns": "1.1.1.1",
}


def add_arguments(p: argparse.ArgumentParser) -> None:
    """Register the ``wifi`` subcommand's flags on ``p``."""
    p.add_argument(
        "ssid",
        nargs="?",
        default=None,
        help="Wi-Fi SSID to connect to (omit only with --status).",
    )
    p.add_argument(
        "--password",
        default=None,
        help="Password (default: prompt interactively without echo).",
    )
    p.add_argument(
        "--open",
        dest="open",
        action="store_true",
        help="Connect to an open (no-password) network.",
    )
    p.add_argument(
        "--ip",
        default=None,
        help="Static IPv4 address (default: use DHCP).",
    )
    p.add_argument(
        "--netmask",
        default=_DEFAULTS["netmask"],
        help="Netmask for the static IP (default: 255.255.255.0).",
    )
    p.add_argument(
        "--gateway",
        default=_DEFAULTS["gateway"],
        help="Default gateway (default: derived as .1 of --ip).",
    )
    p.add_argument(
        "--dns",
        default=_DEFAULTS["dns"],
        help="Primary DNS server for the static IP (default: 1.1.1.1).",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Seconds to wait for Wi-Fi association (default: 15).",
    )
    p.add_argument(
        "--status",
        action="store_true",
        help="Print current STA interface state and exit. No SSID needed.",
    )
    p.add_argument(
        "--persist",
        action="store_true",
        help=(
            "Also write a _wifi_cfg.py on the device that reapplies this "
            "config on boot. Password is stored in plaintext."
        ),
    )
    p.add_argument(
        "--port",
        default=None,
        help="Serial port (default: auto-detect a MicroPython-running device).",
    )
