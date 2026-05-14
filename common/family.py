"""Family-context object that adapts shared runners to a device family.

Shared command runners under :mod:`common` (``code``, ``repl``,
``reset``, ``mip``, ``wifi``, ``info``, ``lint``) are chip-agnostic — they
know how to talk MicroPython over mpremote, but not how to find the
right port or which name to use in error messages. Each family
(:mod:`esp32`, :mod:`pico`) constructs a :class:`FamilyContext` with
its own port resolver and CLI name, and passes that into the runners.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class FamilyContext:
    """Per-family configuration injected into shared command runners.

    Attributes:
        name: Short identifier used as the prefix in error messages
            (``"esp32 push: ..."``, ``"pico push: ..."``). Matches the
            console-script name for the family.
        resolve_port: Callable that turns the user's ``--port`` value
            (possibly ``None``) into a concrete serial-port path, or
            raises :class:`common._mpy.MpyError` if no unambiguous port
            can be found. Each family's resolver knows which USB
            fingerprints count as "this family's devices".
    """

    name: str
    resolve_port: Callable[[str | None], str]
