"""Shared helper for stubbed subcommands (Tools 2-4, not yet implemented)."""

from __future__ import annotations

import sys


def not_implemented(name: str, tool_label: str) -> int:
    """Print a "not implemented" message and return exit code ``2``.

    Args:
        name: Subcommand name as the user invoked it (e.g. ``"flash"``).
        tool_label: Human label for the tool in the CLAUDE.md spec
            (e.g. ``"Tool 2"``).

    Returns:
        Exit code ``2``, indicating the subcommand exists but is not yet usable.
    """
    print(f"esp32 {name}: not implemented yet ({tool_label}).", file=sys.stderr)
    return 2
