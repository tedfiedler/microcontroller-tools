"""Tool 9: lint MicroPython source files for chip-pin hazards.

Static analysis via Python's ``ast`` module. Walks the source for
``Pin(N)`` constructions plus peripheral kwargs that accept raw GPIO
numbers (``I2C(scl=22)``, ``SPI(sck=Pin(18))``, …), and cross-references
each literal integer pin against :mod:`esp32.pin_rules` for the target
chip family.

What it catches in v1:

- ``Pin(N)`` / ``machine.Pin(N)`` — direct construction with a literal.
- Pin args to peripherals — ``I2C/SPI/UART(scl=, sda=, tx=, rx=, sck=,
  mosi=, miso=)`` — whether the value is a literal int or a ``Pin(N)``.

What it doesn't catch (yet):

- **Indirection.** ``n = 6; Pin(n)`` is invisible — only literal int
  args fire. A future flow-analysis pass could chase simple aliases.
- **Boot-time vs runtime.** Strapping-pin warnings fire on every use;
  use after ``boot.py`` has settled is perfectly safe. Suppress with a
  comment or ``# noqa`` once that mechanism exists.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from esp32 import info, pin_rules
from esp32._mpy import MpyError
from esp32.pin_rules import PinRule, Severity

# Names that resolve to the Pin constructor — covers both ``Pin`` and
# ``machine.Pin``. We match on the trailing attribute name, so
# ``something.Pin(N)`` is treated the same.
_PIN_CTOR_NAMES = {"Pin"}

# Kwarg names that peripherals use to accept pin numbers. MicroPython's
# machine.I2C / SPI / UART / I2S / PWM / etc. all accept either a Pin
# object or a raw int here.
_PERIPHERAL_KWARGS = {
    "scl", "sda",            # I2C
    "tx", "rx",              # UART
    "sck", "mosi", "miso",   # SPI
    "ws", "sd", "bck",       # I2S
    "pin",                   # PWM / TouchPad / DAC / ADC
}


class LintError(RuntimeError):
    """Raised for recoverable lint-flow errors (bad path, unknown chip)."""


@dataclass(frozen=True)
class Diagnostic:
    """One lint finding."""

    path: str
    line: int
    column: int
    pin: int
    severity: Severity
    message: str


# ---------- AST walker -------------------------------------------------------


PinMode = Literal["IN", "OUT", "unknown"]


class _PinVisitor(ast.NodeVisitor):
    """Walks an AST and collects diagnostics for hazardous pin uses."""

    def __init__(self, path: Path, rules: tuple[PinRule, ...]) -> None:
        self.path = path
        self.rules = rules
        self.diagnostics: list[Diagnostic] = []

    def visit_Call(self, node: ast.Call) -> None:
        # Case 1: Pin(N) / machine.Pin(N) — check the first positional arg.
        if self._is_pin_call(node.func) and node.args:
            self._check_pin_arg(
                node.args[0], mode=self._mode_for_pin_call(node)
            )

        # Case 2: peripheral kwargs that take a raw int — e.g.
        # ``I2C(0, scl=22, sda=21)``. Nested ``Pin(N)`` calls inside
        # these kwargs are caught by the generic descent below, not here.
        for kw in node.keywords:
            if kw.arg in _PERIPHERAL_KWARGS and _is_literal_int(kw.value):
                self._check_pin_arg(kw.value, mode="unknown")

        self.generic_visit(node)

    @staticmethod
    def _is_pin_call(func: ast.expr) -> bool:
        """True if ``func`` looks like a Pin constructor reference."""
        if isinstance(func, ast.Name):
            return func.id in _PIN_CTOR_NAMES
        if isinstance(func, ast.Attribute):
            return func.attr in _PIN_CTOR_NAMES
        return False

    @staticmethod
    def _mode_for_pin_call(call_node: ast.Call) -> PinMode:
        """Detect Pin.IN / Pin.OUT from a Pin(...) call's args, if statable.

        Recognizes both positional (``Pin(N, Pin.OUT)``) and keyword
        (``Pin(N, mode=Pin.OUT)``) forms. Returns ``"unknown"`` for
        anything we can't statically resolve to IN or OUT.
        """
        # Positional second arg.
        if len(call_node.args) >= 2:
            attr = _attr_name(call_node.args[1])
            if attr in ("OUT", "IN"):
                return attr  # type: ignore[return-value]
        # Keyword ``mode=Pin.OUT``.
        for kw in call_node.keywords:
            if kw.arg == "mode":
                attr = _attr_name(kw.value)
                if attr in ("OUT", "IN"):
                    return attr  # type: ignore[return-value]
        return "unknown"

    def _check_pin_arg(self, pin_node: ast.expr, *, mode: PinMode) -> None:
        if not _is_literal_int(pin_node):
            return  # skip non-literals like Pin(some_var)
        # mypy: _is_literal_int narrows pin_node.value to int
        pin = pin_node.value  # type: ignore[attr-defined]
        assert isinstance(pin, int)

        for rule in self.rules:
            if pin not in rule.pins:
                continue
            if rule.output_only and mode == "IN":
                # Input-only-pin advisory: harmless when used as input.
                continue
            extra = ""
            if rule.output_only and mode == "OUT":
                extra = " (used here as Pin.OUT)"
            self.diagnostics.append(
                Diagnostic(
                    path=str(self.path),
                    line=pin_node.lineno,
                    column=pin_node.col_offset,
                    pin=pin,
                    severity=rule.severity,
                    message=f"Pin({pin}) is {rule.reason}{extra}",
                )
            )


def _is_literal_int(node: ast.expr) -> bool:
    """True iff ``node`` is an int constant (and not a bool — ``True`` is
    technically ``isinstance(_, int)`` but isn't a GPIO number)."""
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    )


def _attr_name(node: ast.expr) -> str | None:
    """Return the trailing attribute name of an Attribute node, else None.

    ``Pin.OUT`` → ``"OUT"``; ``machine.Pin.OUT`` → ``"OUT"``.
    """
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


# ---------- file-level driving -----------------------------------------------


def lint_source(
    path: Path, source: str, rules: tuple[PinRule, ...]
) -> list[Diagnostic]:
    """Parse ``source`` and emit diagnostics for any pin hazards."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        # Skip files we can't parse; surface a single note so the user
        # knows we passed it over rather than silently ignoring.
        return [
            Diagnostic(
                path=str(path),
                line=exc.lineno or 0,
                column=exc.offset or 0,
                pin=-1,
                severity="note",
                message=f"skipped (couldn't parse): {exc.msg}",
            )
        ]

    visitor = _PinVisitor(path, rules)
    visitor.visit(tree)
    return visitor.diagnostics


def _walk_targets(target: Path) -> Iterator[Path]:
    """Yield .py files at or under ``target``."""
    if target.is_file():
        yield target
        return
    for path in sorted(target.rglob("*.py")):
        if any(part in {"__pycache__", ".venv", "venv", ".git"} for part in path.parts):
            continue
        yield path


# ---------- formatting -------------------------------------------------------


def format_text(diagnostics: list[Diagnostic]) -> str:
    """Render diagnostics as an aligned three-column block + summary."""
    if not diagnostics:
        return "no issues found."

    locs = [f"{d.path}:{d.line}:{d.column}" for d in diagnostics]
    loc_width = max(len(loc) for loc in locs)
    sev_width = max(len(d.severity) for d in diagnostics)

    lines = [
        f"{loc.ljust(loc_width)}  {d.severity.ljust(sev_width)}  {d.message}"
        for d, loc in zip(diagnostics, locs, strict=True)
    ]

    counts = {
        sev: sum(1 for d in diagnostics if d.severity == sev)
        for sev in ("error", "warning", "note")
    }
    parts = [
        f"{n} {sev}{'s' if n != 1 else ''}"
        for sev, n in counts.items()
        if n > 0
    ]
    lines.append("")
    lines.append(", ".join(parts))
    return "\n".join(lines)


def format_json(diagnostics: list[Diagnostic]) -> str:
    return json.dumps([asdict(d) for d in diagnostics], indent=2)


# ---------- CLI entry --------------------------------------------------------


def _resolve_chip(explicit_chip: str | None, explicit_port: str | None) -> str:
    """Resolve which chip's rules to apply.

    Either ``--chip`` is given (skip device probe), or we call into
    :mod:`esp32.info` to identify the connected device's chip. Errors
    if the chip can't be resolved or has no rules defined.
    """
    known = ", ".join(pin_rules.chips_with_rules()) or "(none)"

    if explicit_chip is not None:
        if explicit_chip not in pin_rules.RULES_BY_CHIP:
            raise LintError(
                f"unknown --chip: {explicit_chip!r}. Known: {known}"
            )
        return explicit_chip

    try:
        device = info.collect(explicit_port)
    except (MpyError, info.InfoError) as exc:
        raise LintError(
            f"couldn't probe a connected device ({exc}). "
            f"Pass --chip <name>. Known: {known}"
        ) from exc

    if not device.chip:
        raise LintError(
            f"device detected but chip couldn't be identified. "
            f"Pass --chip <name>. Known: {known}"
        )
    if device.chip not in pin_rules.RULES_BY_CHIP:
        raise LintError(
            f"detected chip {device.chip!r} has no lint rules yet. "
            f"Pass --chip <known>, or contribute rules. Known: {known}"
        )
    return device.chip


def run(args: argparse.Namespace) -> int:
    """Entry point for ``esp32 lint``."""
    try:
        chip = _resolve_chip(args.chip, args.port)
    except LintError as exc:
        print(f"esp32 lint: {exc}", file=sys.stderr)
        return 1

    rules = pin_rules.rules_for_chip(chip)

    target = Path(args.target).expanduser()
    if not target.exists():
        print(f"esp32 lint: path does not exist: {target}", file=sys.stderr)
        return 1

    all_diagnostics: list[Diagnostic] = []
    for source_path in _walk_targets(target):
        try:
            source = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        all_diagnostics.extend(lint_source(source_path, source, rules))

    if args.as_json:
        print(format_json(all_diagnostics))
    else:
        print(format_text(all_diagnostics))

    errors = sum(1 for d in all_diagnostics if d.severity == "error")
    return min(errors, 255)
