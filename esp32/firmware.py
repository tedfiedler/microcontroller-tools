"""Resolve the MicroPython firmware binary to flash onto a board.

Three ways to supply firmware, in priority order:

1. ``--firmware <path>`` — local file; no network.
2. ``--firmware-url <url>`` — download from a specific URL (cached on disk).
3. Default — look up the latest stable release from the board profile's
   ``firmware_source``:

   * ``micropython.org`` — scrape the board's download page HTML.
   * ``arduino.cc``      — fetch the JSON manifest at
     ``downloads.arduino.cc/micropython/index.json`` and find the matching
     ``.app-bin`` entry. Required for the Arduino Nano ESP32, whose canonical
     firmware is Arduino-built and only published through this channel.

Downloaded files are cached under ``~/.cache/microcontroller-tools/firmware/``
keyed by the remote filename, so repeated flashes hit the cache.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import certifi

from esp32.boards import BoardProfile

# Python installers from python.org on macOS don't link the system CA store,
# so stdlib urllib can't verify TLS certs out of the box. Use certifi's bundle
# explicitly so downloads work on a fresh install without the user running
# ``Install Certificates.command``.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

# micropython.org source -----------------------------------------------------

_MPY_DOWNLOAD_URL = "https://micropython.org/download/{slug}/"
_MPY_BASE_URL = "https://micropython.org"

# Matches a stable release firmware link in the download-page HTML. Filenames
# have the shape ``<SLUG>-<YYYYMMDD>-v<VERSION>.<EXT>``. We anchor on the slug
# and exact extension to exclude preview / nightly builds (which include
# ``-preview.`` or ``-unstable-`` segments in the filename).
_MPY_RELEASE_RE_TEMPLATE = (
    r'href="(/resources/firmware/{slug}-\d{{8}}-v[\d.]+{ext})"'
)

# arduino.cc source ----------------------------------------------------------

_ARDUINO_MANIFEST_URL = "https://downloads.arduino.cc/micropython/index.json"
_ARDUINO_BASE_URL = "https://downloads.arduino.cc"


class FirmwareResolutionError(RuntimeError):
    """Raised when firmware can't be resolved (network error, no releases, etc.)."""


@dataclass(frozen=True)
class ResolvedFirmware:
    """Firmware ready to flash.

    Attributes:
        path: Absolute path to the binary on the local filesystem.
        source_description: Human-friendly description of where it came from,
            shown in the confirmation prompt.
    """

    path: Path
    source_description: str


def cache_dir() -> Path:
    """Return the firmware cache directory, creating it if necessary."""
    path = Path.home() / ".cache" / "microcontroller-tools" / "firmware"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _fetch_bytes(url: str, timeout: float) -> bytes:
    """Fetch ``url`` and return its bytes, wrapping errors in FirmwareResolutionError."""
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=_SSL_CONTEXT) as response:
            result: bytes = response.read()
            return result
    except (urllib.error.URLError, TimeoutError) as exc:
        raise FirmwareResolutionError(f"Failed to fetch {url}: {exc}") from exc


def _find_latest_release_url_mpy(board: BoardProfile) -> str:
    """Scrape micropython.org for the first stable release matching the board."""
    page_url = _MPY_DOWNLOAD_URL.format(slug=board.slug)
    html = _fetch_bytes(page_url, timeout=30).decode("utf-8", errors="replace")

    pattern = _MPY_RELEASE_RE_TEMPLATE.format(
        slug=re.escape(board.slug),
        ext=re.escape(board.firmware_extension),
    )
    match = re.search(pattern, html)
    if match is None:
        raise FirmwareResolutionError(
            f"No stable {board.firmware_extension} release on {page_url}. "
            "Pass --firmware <path> with a local binary, or check the slug."
        )
    return _MPY_BASE_URL + match.group(1)


def _find_latest_release_url_arduino(board: BoardProfile) -> str:
    """Look up the Arduino manifest for the first stable release matching the board.

    Manifest shape (simplified)::

        {
          "boards": [
            { "name": "ARDUINO_NANO_ESP32",
              "releases": [
                {"type": "(stable)", "url": "/micropython/ARDUINO_NANO_ESP32-...app-bin"},
                ...
              ]
            }
          ]
        }
    """
    raw = _fetch_bytes(_ARDUINO_MANIFEST_URL, timeout=30)
    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FirmwareResolutionError(
            f"Arduino manifest at {_ARDUINO_MANIFEST_URL} is not valid JSON: {exc}"
        ) from exc

    boards = [b for b in data.get("boards", []) if b.get("name") == board.slug]
    if not boards:
        raise FirmwareResolutionError(
            f"Board {board.slug!r} not found in Arduino manifest "
            f"({_ARDUINO_MANIFEST_URL})."
        )

    releases: list[dict[str, Any]] = boards[0].get("releases", [])
    for release in releases:
        url: str = release.get("url", "")
        if release.get("type", "").strip() == "(stable)" and url.endswith(
            board.firmware_extension
        ):
            return _ARDUINO_BASE_URL + url

    raise FirmwareResolutionError(
        f"No stable {board.firmware_extension} release for {board.slug} in "
        f"Arduino manifest ({_ARDUINO_MANIFEST_URL})."
    )


def _find_latest_release_url(board: BoardProfile) -> str:
    """Look up the latest stable firmware URL for ``board`` from its source."""
    if board.firmware_source == "micropython.org":
        return _find_latest_release_url_mpy(board)
    elif board.firmware_source == "arduino.cc":
        return _find_latest_release_url_arduino(board)
    else:  # pragma: no cover - Literal keeps this unreachable
        raise FirmwareResolutionError(
            f"Unknown firmware_source: {board.firmware_source!r}"
        )


_ALLOWED_EXTENSIONS: tuple[str, ...] = (".bin", ".uf2", ".app-bin")


def _download_to_cache(url: str) -> Path:
    """Download ``url`` into the firmware cache and return the local path.

    If the cached file already exists, skips the download.
    """
    filename = url.rsplit("/", 1)[-1]
    if not any(filename.endswith(ext) for ext in _ALLOWED_EXTENSIONS):
        raise FirmwareResolutionError(
            f"Refusing to download {url}: URL does not end in one of "
            f"{_ALLOWED_EXTENSIONS}"
        )

    target = cache_dir() / filename
    if target.exists():
        print(f"Using cached firmware: {target}")
        return target

    print(f"Downloading {url} ...")
    data = _fetch_bytes(url, timeout=120)

    # Write atomically: temp file then rename, so a Ctrl-C mid-write doesn't
    # leave a truncated "valid-looking" cache entry.
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    print(f"Saved {len(data):,} bytes to {target}")
    return target


def resolve(
    board: BoardProfile,
    local_path: Path | None = None,
    override_url: str | None = None,
) -> ResolvedFirmware:
    """Return a :class:`ResolvedFirmware` for the given board.

    Resolution order:
      1. ``local_path`` if given.
      2. ``override_url`` if given.
      3. Latest stable release from the board's firmware source.

    Raises:
        FirmwareResolutionError: If the firmware can't be located.
    """
    if local_path is not None:
        expanded = local_path.expanduser().resolve()
        if not expanded.is_file():
            raise FirmwareResolutionError(
                f"--firmware path does not exist or is not a file: {expanded}"
            )
        return ResolvedFirmware(
            path=expanded,
            source_description=f"local: {expanded}",
        )

    url = override_url or _find_latest_release_url(board)
    cached = _download_to_cache(url)
    return ResolvedFirmware(
        path=cached,
        source_description=f"downloaded: {url}",
    )
