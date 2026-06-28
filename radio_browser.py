"""Radio Browser API lookup for stream station metadata."""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

_RADIO_BROWSER_HOSTS = [
    "de1.api.radio-browser.info",
    "at1.api.radio-browser.info",
    "nl1.api.radio-browser.info",
]

# In-memory cache: url → {"name": str, "favicon": str}
_cache: dict[str, dict[str, str]] = {}


async def async_lookup_station(hass: HomeAssistant, url: str) -> dict[str, str]:
    """Return {"name": str, "favicon": str} for a stream URL, or {} if not found.

    Tries the exact URL, then the HTTPS variant, using multiple Radio Browser
    mirrors. Results are cached in-process to avoid repeated API calls.
    """
    url = url.strip()
    if not url:
        return {}

    if url in _cache:
        return _cache[url]

    candidates = [url]
    if url.startswith("http://"):
        candidates.append("https://" + url[7:])
    elif url.startswith("https://"):
        candidates.append("http://" + url[8:])

    session = async_get_clientsession(hass)

    for candidate in candidates:
        result = await _query_by_url(session, candidate)
        if result:
            _cache[url] = result
            return result

    _cache[url] = {}
    return {}


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
                timeout=__import__("aiohttp").ClientTimeout(total=4),
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
