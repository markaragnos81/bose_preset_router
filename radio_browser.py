"""Radio Browser API lookup and ICY stream metadata for internet radio stations."""
from __future__ import annotations

import logging
import re
import struct
from urllib.parse import urlencode, urlsplit

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

_RADIO_BROWSER_HOSTS = [
    "de1.api.radio-browser.info",
    "at1.api.radio-browser.info",
    "nl1.api.radio-browser.info",
]

# In-memory cache: url → {"name": str, "favicon": str}
_station_cache: dict[str, dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Radio Browser station lookup
# ---------------------------------------------------------------------------

async def async_lookup_station(hass: HomeAssistant, url: str) -> dict[str, str]:
    """Return {"name": str, "favicon": str} for a stream URL, or {} if not found.

    Tries the exact URL then the http/https variant across multiple mirrors.
    Augments with a DuckDuckGo favicon when Radio Browser returns none.
    Results are cached in-process to avoid repeated API calls.
    """
    url = url.strip()
    if not url:
        return {}

    if url in _station_cache:
        return _station_cache[url]

    candidates = [url]
    if url.startswith("http://"):
        candidates.append("https://" + url[7:])
    elif url.startswith("https://"):
        candidates.append("http://" + url[8:])

    session = async_get_clientsession(hass)

    result: dict[str, str] = {}
    for candidate in candidates:
        result = await _query_by_url(session, candidate)
        if result:
            break

    # Always fill favicon when Radio Browser has none or station unknown
    if not result.get("favicon"):
        fav = _best_favicon(url)
        if result:
            result["favicon"] = fav
        else:
            result = {"name": "", "favicon": fav}

    _station_cache[url] = result
    return result


async def _query_by_url(session, url: str) -> dict[str, str]:
    body = urlencode({"url": url}).encode()
    for host in _RADIO_BROWSER_HOSTS:
        try:
            async with session.post(
                f"https://{host}/json/stations/byurl",
                data=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "bose_preset_router/homeassistant",
                },
                timeout=aiohttp.ClientTimeout(total=4),
            ) as resp:
                if resp.status != 200:
                    continue
                stations = await resp.json()
                if stations:
                    s = stations[0]
                    return {
                        "name": str(s.get("name") or "").strip(),
                        "favicon": str(s.get("favicon") or "").strip(),
                    }
                return {}
        except Exception as err:
            _LOGGER.debug("Radio Browser %s failed for %s: %s", host, url, err)
            continue
    return {}


def _best_favicon(url: str) -> str:
    """Return the best available favicon URL for the given stream URL's domain.

    Uses Google's favicon CDN with sz=128 for a usable image in HA media cards.
    """
    try:
        host = urlsplit(url).hostname or ""
        if host:
            return f"https://www.google.com/s2/favicons?domain={host}&sz=128"
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# ICY stream metadata (current track / artist)
# ---------------------------------------------------------------------------

async def async_fetch_icy_meta(hass: HomeAssistant, url: str) -> dict[str, str]:
    """Fetch live ICY metadata from an internet radio stream.

    Returns {"stream_title": str, "icy_name": str}.
    stream_title is typically "Artist - Title" or just the station name.
    Returns {} on any error or timeout.
    """
    url = url.strip()
    if not url:
        return {}

    session = async_get_clientsession(hass)
    try:
        async with session.get(
            url,
            headers={"Icy-MetaData": "1", "User-Agent": "bose_preset_router/homeassistant"},
            timeout=aiohttp.ClientTimeout(total=5, connect=3),
        ) as resp:
            if resp.status not in (200, 206):
                return {}

            icy_name = resp.headers.get("icy-name", "").strip()
            metaint_str = resp.headers.get("icy-metaint", "0")
            metaint = int(metaint_str) if metaint_str.isdigit() else 0

            if not metaint:
                return {"stream_title": "", "icy_name": icy_name}

            # Read audio bytes up to the first metadata block
            audio = await resp.content.readexactly(metaint)  # noqa: F841
            length_byte = await resp.content.readexactly(1)
            meta_len = struct.unpack("B", length_byte)[0] * 16

            stream_title = ""
            if meta_len:
                meta_bytes = await resp.content.readexactly(meta_len)
                try:
                    raw = meta_bytes.decode("utf-8").rstrip("\x00")
                except UnicodeDecodeError:
                    raw = meta_bytes.decode("latin-1").rstrip("\x00")
                m = re.search(r"StreamTitle='([^']*)'", raw)
                if m:
                    stream_title = m.group(1).strip()

            return {"stream_title": stream_title, "icy_name": icy_name}

    except Exception as err:
        _LOGGER.debug("ICY fetch failed for %s: %s", url, err)
        return {}


def parse_icy_stream_title(stream_title: str) -> tuple[str, str]:
    """Parse 'Artist - Title' into (artist, title). Returns ('', stream_title) if no separator."""
    if " - " in stream_title:
        artist, _, title = stream_title.partition(" - ")
        return artist.strip(), title.strip()
    return "", stream_title
