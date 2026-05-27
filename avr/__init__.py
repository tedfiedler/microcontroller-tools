"""CLI tools for AVR-family microcontrollers programmed via a USB-UART bridge.

Initial target: stock ATmega328P with the Arduino bootloader (optiboot
or the classic Duemilanove STK500v1), programmed over an FT232 / CH340
/ CP2102 USB-to-serial bridge. Other ``avrdude``-supported AVRs can be
flashed by overriding ``--mcu`` / ``--programmer`` on the command line.

This family is intentionally narrower than :mod:`esp32` / :mod:`pico`:
there's no MicroPython on the chip, so no ``push`` / ``pull`` / ``ls``
/ ``repl`` / ``info`` / ``mip`` / ``wifi`` / ``lint`` subcommands —
only ``discover``, ``flash``, ``reset``, and ``monitor``.
"""

from __future__ import annotations

__version__ = "0.1.0"
