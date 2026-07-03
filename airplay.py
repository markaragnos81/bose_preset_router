"""AirPlay (RAOP) playback via pyatv — independent of the UPnP/AVTransport pipeline.

Proven live: streaming a URL via pyatv's RAOP protocol starts audio on a Bose
SoundTouch speaker even while its UPnP renderer is wedged (accepts AVTransport
SOAP calls with HTTP 200 but never plays). AirPlay is a fully separate playback
pipeline in the speaker's firmware.

pyatv's targeted `scan(hosts=[ip])` is proven broken for these RAOP-only Bose
speakers (returns 0 results even with a protocol filter) — only a full network
multicast scan reliably finds them. AirPlayDiscovery runs that scan periodically
in the background and caches results by IP, so playback doesn't pay the ~6s scan
cost on every preset trigger.
"""
from __future__ import annotations

import asyncio
import logging
import time

import pyatv
from pyatv.const import Protocol
from pyatv.interface import AppleTV, BaseConfig, MediaMetadata
from homeassistant.components import zeroconf as ha_zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL_SECONDS = 90.0
DEFAULT_CACHE_MAX_AGE_SECONDS = 180.0
DEFAULT_SCAN_TIMEOUT_SECONDS = 6


class AirPlayDiscovery:
    """Shared, periodic RAOP discovery cache for one config entry.

    One instance per config entry (not per device) avoids redundant concurrent
    network scans when multiple devices are configured for AirPlay.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._cache: dict[str, tuple[BaseConfig, float]] = {}
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    def async_start(self) -> None:
        self._stop_event.clear()
        self._task = self.entry.async_create_background_task(
            self.hass, self._scan_loop(), f"{DOMAIN}_airplay_discovery"
        )

    async def async_stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _scan_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._async_scan_once()
            except Exception as err:
                _LOGGER.warning("AirPlay discovery scan failed: %s", err, exc_info=True)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=DEFAULT_SCAN_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                pass

    async def _async_scan_once(self) -> None:
        loop = asyncio.get_running_loop()
        # Reuse HA's own shared zeroconf instance instead of letting pyatv open a
        # second, independent one. Two concurrent zeroconf listeners on the same
        # host can miss each other's multicast responses — pyatv.scan() found
        # both Bose speakers reliably in isolated testing but returned zero
        # results when run inside Home Assistant, which already owns the mDNS
        # socket via its own zeroconf integration.
        start = time.monotonic()
        aiozc = await ha_zeroconf.async_get_async_instance(self.hass)
        results = await pyatv.scan(
            loop, timeout=DEFAULT_SCAN_TIMEOUT_SECONDS, protocol={Protocol.RAOP}, aiozc=aiozc
        )
        elapsed = time.monotonic() - start
        _LOGGER.info(
            "AirPlay scan finished in %.2fs, found %d device(s): %s",
            elapsed, len(results), [str(c.address) for c in results],
        )
        now = time.monotonic()
        for cfg in results:
            self._cache[str(cfg.address)] = (cfg, now)

    async def async_get_config(
        self, bose_ip: str, *, max_age_seconds: float = DEFAULT_CACHE_MAX_AGE_SECONDS
    ) -> BaseConfig | None:
        """Return a cached RAOP config for bose_ip, rescanning once if missing/stale."""
        cached = self._cache.get(bose_ip)
        if cached and (time.monotonic() - cached[1]) < max_age_seconds:
            return cached[0]
        try:
            await self._async_scan_once()
        except Exception as err:
            _LOGGER.warning(
                "AirPlay discovery fallback scan failed for %s: %s", bose_ip, err, exc_info=True
            )
        cached = self._cache.get(bose_ip)
        return cached[0] if cached else None


class AirPlayPlayer:
    """Owns the AirPlay/RAOP connection + streaming task for one Bose device."""

    def __init__(self, hass: HomeAssistant, bose_ip: str, discovery: AirPlayDiscovery) -> None:
        self.hass = hass
        self.bose_ip = bose_ip
        self._discovery = discovery
        self._atv: AppleTV | None = None
        self._stream_task: asyncio.Task | None = None

    async def play(
        self, url: str, *, title: str = "", artist: str = "", album: str = ""
    ) -> bool:
        """Stop any current stream, connect, and start streaming url via AirPlay.

        Returns True once the stream task was started (does not itself guarantee
        audible playback — the caller may optionally poll now_playing afterwards).
        """
        await self.stop()

        config = await self._discovery.async_get_config(self.bose_ip)
        if config is None:
            _LOGGER.warning("AirPlay: no discovered RAOP target for %s", self.bose_ip)
            return False

        try:
            self._atv = await pyatv.connect(config, asyncio.get_running_loop())
        except Exception as err:
            _LOGGER.warning("AirPlay: connect failed for %s: %s", self.bose_ip, err)
            self._atv = None
            return False

        metadata = MediaMetadata(
            title=title or "Stream",
            artist=artist or "Bose Preset Router",
            album=album or "AirPlay",
        )

        async def _run_stream() -> None:
            try:
                await self._atv.stream.stream_file(url, metadata=metadata)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.warning("AirPlay: stream_file error for %s: %s", self.bose_ip, err)

        self._stream_task = self.hass.async_create_task(
            _run_stream(), name=f"{DOMAIN}_airplay_stream_{self.bose_ip}"
        )
        return True

    async def stop(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
            await asyncio.gather(self._stream_task, return_exceptions=True)
            self._stream_task = None
        if self._atv is not None:
            try:
                self._atv.close()
            except Exception:
                pass
            self._atv = None
