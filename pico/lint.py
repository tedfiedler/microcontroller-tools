"""Tool 9 (Pico family): lint MicroPython source for chip-pin hazards.

Thin family wrapper over :mod:`common.lint`. The AST walker, diagnostic
dataclass, and formatters all live in common; this module supplies the
Pico-specific glue: rule lookup via :mod:`pico.pin_rules`, and the
device-probe path that auto-detects which chip's rules to apply by
inspecting the attached board via :mod:`pico.info`.

The pin-rule tables in :mod:`pico.pin_rules` are populated in a
follow-up commit (Task 4). Until then, running ``pico lint`` without
``--chip`` against a connected device works structurally but will
report "no rules" once the chip is identified.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common._mpy import MpyError
from common.lint import (
    Diagnostic,
    LintError,
    format_json,
    format_text,
    lint_source,
    walk_targets,
)
from pico import info, pin_rules

__all__ = ["Diagnostic", "LintError", "run"]


def _resolve_chip(explicit_chip: str | None, explicit_port: str | None) -> str:
    """Resolve which chip's rules to apply.

    Either ``--chip`` is given (skip device probe), or we call into
    :mod:`pico.info` to identify the connected device's chip. Errors
    if the chip can't be resolved or has no rules defined.
    """
    known = ", ".join(pin_rules.chips_with_rules()) or "(none yet)"

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
            "device detected but chip couldn't be identified. "
            f"Pass --chip <name>. Known: {known}"
        )
    if device.chip not in pin_rules.RULES_BY_CHIP:
        raise LintError(
            f"detected chip {device.chip!r} has no lint rules yet. "
            f"Pass --chip <known>, or contribute rules. Known: {known}"
        )
    return device.chip


def run(args: argparse.Namespace) -> int:
    """Entry point for ``pico lint``."""
    try:
        chip = _resolve_chip(args.chip, args.port)
    except LintError as exc:
        print(f"pico lint: {exc}", file=sys.stderr)
        return 1

    rules = pin_rules.rules_for_chip(chip)

    target = Path(args.target).expanduser()
    if not target.exists():
        print(f"pico lint: path does not exist: {target}", file=sys.stderr)
        return 1

    all_diagnostics: list[Diagnostic] = []
    for source_path in walk_targets(target):
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
