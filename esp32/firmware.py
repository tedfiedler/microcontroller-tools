"""Resolve the MicroPython firmware binary to flash onto a board.

Three ways to supply firmware, in priority order:

1. ``--firmware <path>`` — use a local ``.bin`` the user already has; no network.
2. ``--firmware-url <url>`` — download from a specific URL (cached on disk).
3. Default — scrape ``https://micropython.org/download/<slug>/`` for the latest
   stable release ``.bin`` and download it.

Downloaded files are cached under ``~/.cache/microcontroller-tools/firmware/``
keyed by the remote filename, so repeated flashes hit the cache.
"""

from __future__ import annotations

import re
import ssl
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import certifi

from esp32.boards import BoardProfile

# Python installers from python.org on macOS don't link the system CA store,
# so stdlib urllib can't verify TLS certs out of the box. Use certifi's bundle
# explicitly so downloads work on a fresh install without the user running
# ``Install Certificates.command``.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

_MPY_DOWNLOAD_URL = "https://micropython.org/download/{slug}/"
_MPY_BASE_URL = "https://micropython.org"

# Matches a stable release .bin link in the download-page HTML. The filename
# has the shape ``<SLUG>-<YYYYMMDD>-v<VERSION>.bin``. We anchor on the slug at
# the start and ``.bin`` at the end to exclude preview/nightly builds, which
# contain ``-preview.`` or ``-unstable-`` segments before ``.bin``.
_RELEASE_RE_TEMPLATE = (
    r'href="(/resources/firmware/{slug}-\d{{8}}-v[\d.]+\.bin)"'
)


class FirmwareResolutionError(RuntimeError):
    """Raised when firmware can't be resolved (network error, no releases, etc.)."""


@dataclass(frozen=True)
class ResolvedFirmware:
    """Firmware ready to flash.

    Attributes:
        path: Absolute path to the ``.bin`` on the local filesystem.
        source_description: Human-friendly description of where it came from,
            shown in the confirmation prompt (e.g. ``"local: /tmp/x.bin"`` or
            ``"downloaded: https://micropython.org/.../ARDUINO_..."``).
    """

    path: Path
    source_description: str


def cache_dir() -> Path:
    """Return the firmware cache directory, creating it if necessary."""
    path = Path.home() / ".cache" / "microcontroller-tools" / "firmware"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_latest_release_url(board: BoardProfile) -> str:
    """Scrape the micropython.org download page for ``board`` and return the
    first stable release ``.bin`` URL it finds.

    Raises:
        FirmwareResolutionError: if the page can't be fetched or no stable
            release link is present.
    """
    page_url = _MPY_DOWNLOAD_URL.format(slug=board.slug)
    try:
        with urllib.request.urlopen(page_url, timeout=30, context=_SSL_CONTEXT) as response:
            html = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise FirmwareResolutionError(
            f"Failed to fetch {page_url}: {exc}"
        ) from exc

    pattern = _RELEASE_RE_TEMPLATE.format(slug=re.escape(board.slug))
    match = re.search(pattern, html)
    if match is None:
        raise FirmwareResolutionError(
            f"No stable release .bin found on {page_url}. "
            "Pass --firmware <path> with a local binary, or check the board slug."
        )
    return _MPY_BASE_URL + match.group(1)


def _download_to_cache(url: str) -> Path:
    """Download ``url`` into the firmware cache and return the local path.

    If the cached file already exists, skips the download.
    """
    filename = url.rsplit("/", 1)[-1]
    if not filename.endswith(".bin"):
        raise FirmwareResolutionError(
            f"Refusing to download {url}: URL does not end in .bin"
        )

    target = cache_dir() / filename
    if target.exists():
        print(f"Using cached firmware: {target}")
        return target

    print(f"Downloading {url} ...")
    try:
        with urllib.request.urlopen(url, timeout=120, context=_SSL_CONTEXT) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise FirmwareResolutionError(f"Failed to download {url}: {exc}") from exc

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
      1. ``local_path`` if given (user passed ``--firmware``).
      2. ``override_url`` if given (user passed ``--firmware-url``).
      3. Latest stable release scraped from micropython.org.

    Args:
        board: Target board profile (for the micropython.org slug).
        local_path: Optional local ``.bin`` path supplied by the user.
        override_url: Optional explicit URL to download.

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
