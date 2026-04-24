"""Tool 4: configure the ESP32's Wi-Fi STA interface from the host.

Drives the device via ``mpremote exec`` — we assemble a small MicroPython
script that activates ``network.WLAN(network.STA_IF)``, optionally sets a
static ``ifconfig``, connects to an SSID, waits for association, and prints
the resulting interface configuration.

Flows:

* ``esp32 wifi <SSID>``             — connect (DHCP), prompts for password.
* ``esp32 wifi <SSID> --open``      — connect to an open (no-password) AP.
* ``esp32 wifi <SSID> --ip 192.168.1.100 ...`` — connect with a static IP.
* ``esp32 wifi --status``           — just print the current interface state.
* ``esp32 wifi <SSID> ... --persist`` — also write a ``_wifi_cfg.py`` on the
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
from dataclasses import dataclass

from esp32._mpy import MpyError, mpremote_binary, resolve_port, run_mpremote


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
            f"wlan.connect({cfg.ssid!r}, {cfg.password!r})",
            f"deadline = time.ticks_add(time.ticks_ms(), {int(cfg.timeout_secs * 1000)})",
            "while not wlan.isconnected():",
            "    if time.ticks_diff(deadline, time.ticks_ms()) <= 0:",
            "        raise RuntimeError('Timed out waiting for Wi-Fi; "
            "status=' + str(wlan.status()))",
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


def _build_persist_script(cfg: WifiConfig) -> str:
    """Generate a script that writes ``_wifi_cfg.py`` on the device."""
    body = _build_connect_script(cfg)
    # ``repr(body)`` produces a valid Python string literal we can embed as
    # the argument to ``f.write(...)``; MicroPython re-parses it exactly.
    return (
        "with open('_wifi_cfg.py', 'w') as f:\n"
        f"    f.write({body!r})\n"
        "print('wrote _wifi_cfg.py')\n"
        "print('  run `import _wifi_cfg` from boot.py/main.py "
        "to auto-connect on startup')"
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


def _exec_script(port: str, script: str, *, contains_secret: bool = False) -> None:
    """Run ``script`` on the device via ``mpremote exec``.

    Args:
        port: Serial port.
        script: MicroPython source to execute on the device.
        contains_secret: If True, suppress the default command echo so a
            password embedded in the script doesn't end up in the user's
            scrollback. The device's ``print`` output is still shown.
    """
    # mpremote exec takes the script as a single positional arg.
    run_mpremote(port, ["exec", script], echo=not contains_secret)


def run(args: argparse.Namespace) -> int:
    """Entry point for the ``esp32 wifi`` subcommand."""
    try:
        # Make sure mpremote is available before we start soliciting passwords.
        mpremote_binary()
        port = resolve_port(args.port)

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

        _exec_script(
            port, _build_connect_script(cfg), contains_secret=bool(password)
        )

        if args.persist:
            _exec_script(
                port, _build_persist_script(cfg), contains_secret=bool(password)
            )
    except (WifiError, MpyError) as exc:
        print(f"esp32 wifi: {exc}", file=sys.stderr)
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
        help="Serial port (default: auto-detect a MicroPython-running ESP32).",
    )
