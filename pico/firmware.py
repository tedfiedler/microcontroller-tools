"""Resolve the MicroPython ``.uf2`` to flash onto a Raspberry Pi Pico.

Three ways to supply firmware, in priority order:

1. ``--firmware <path>`` — local file; no network.
2. ``--firmware-url <url>`` — download from a specific URL (cached).
3. Default — scrape the latest stable release from
   ``micropython.org/download/<slug>/``.

Downloaded files are cached under
``~/.cache/microcontroller-tools/firmware/`` keyed by the remote
filename, so repeated flashes hit the cache.

The cache directory and download helpers are deliberately the same as
those used by :mod:`esp32.firmware`; bug fixes (TLS context, atomic
renames) live in both modules until/unless we factor them out to
``common/``.
"""

from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import certifi

from pico.boards import BoardProfile

# Python installers from python.org on macOS don't link the system CA store,
# so stdlib urllib can't verify TLS certs out of the box. Use certifi's bundle
# explicitly so downloads work on a fresh install without the user running
# ``Install Certificates.command``.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

_MPY_DOWNLOAD_URL = "https://micropython.org/download/{slug}/"
_MPY_BASE_URL = "https://micropython.org"

# Matches a stable release firmware link in the download-page HTML.
# Pico filenames take the shape ``<SLUG>-<YYYYMMDD>-v<VERSION>.uf2``.
# We anchor on the slug and the .uf2 extension to exclude preview /
# nightly builds (whose filenames include ``-preview.`` segments).
_MPY_RELEASE_RE_TEMPLATE = (
    r'href="(/resources/firmware/{slug}-\d{{8}}-v[\d.]+\.uf2)"'
)


class FirmwareResolutionError(RuntimeError):
    """Raised when firmware can't be resolved (network error, no releases, etc.)."""


@dataclass(frozen=True)
class ResolvedFirmware:
    """Firmware ready to flash.

    Attributes:
        path: Absolute path to the ``.uf2`` on the local filesystem.
        source_description: Human-friendly description of where it came
            from, shown in the confirmation prompt.
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


def _find_latest_release_url(board: BoardProfile) -> str:
    """Scrape micropython.org for the first stable .uf2 matching the board."""
    page_url = _MPY_DOWNLOAD_URL.format(slug=board.slug)
    html = _fetch_bytes(page_url, timeout=30).decode("utf-8", errors="replace")

    pattern = _MPY_RELEASE_RE_TEMPLATE.format(slug=re.escape(board.slug))
    match = re.search(pattern, html)
    if match is None:
        raise FirmwareResolutionError(
            f"No stable .uf2 release on {page_url}. "
            "Pass --firmware <path> with a local file, or check the slug."
        )
    return _MPY_BASE_URL + match.group(1)


def _download_to_cache(url: str) -> Path:
    """Download ``url`` into the firmware cache and return the local path.

    If the cached file already exists, skips the download. Writes are
    atomic — a temp ``.part`` file is renamed once the bytes are on
    disk, so a Ctrl-C mid-download doesn't leave a truncated
    valid-looking ``.uf2``.
    """
    filename = url.rsplit("/", 1)[-1]
    if not filename.endswith(".uf2"):
        raise FirmwareResolutionError(
            f"Refusing to download {url}: URL does not end in .uf2"
        )

    target = cache_dir() / filename
    if target.exists():
        print(f"Using cached firmware: {target}")
        return target

    print(f"Downloading {url} ...")
    data = _fetch_bytes(url, timeout=120)

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
      3. Latest stable .uf2 release from micropython.org.

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
