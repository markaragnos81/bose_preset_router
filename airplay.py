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

The scan reuses Home Assistant's own shared zeroconf instance rather than
opening a second one, but that only works if a ServiceBrowser for _raop._tcp is
actively running against it — pyatv.scan(aiozc=...) purely reads from that
instance's cache and does not browse on its own. AirPlayDiscovery keeps its own
AsyncServiceBrowser alive for the integration's whole lifetime so the cache is
genuinely and continuously populated, not just whatever another integration's
browser happened to already pick up.
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
from homeassistant.helpers.storage import Store
from zeroconf.asyncio import AsyncServiceBrowser

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL_SECONDS = 20.0
DEFAULT_CACHE_MAX_AGE_SECONDS = 45.0
DEFAULT_SCAN_TIMEOUT_SECONDS = 6
FALLBACK_RESCAN_ATTEMPTS = 3
FALLBACK_RESCAN_DELAY_SECONDS = 2.0
RAOP_SERVICE_TYPE = "_raop._tcp.local."
RESUME_STORAGE_VERSION = 1
RESUME_STORAGE_KEY = f"{DOMAIN}_airplay_resume"


def _noop_service_state_change(zeroconf, service_type, name, state_change) -> None:
    """No-op handler for AsyncServiceBrowser.

    We don't need per-event callbacks — the browser's only job is to keep
    zeroconf's cache populated with PTR/records for _raop._tcp so that
    pyatv.scan(aiozc=...) (which only reads from that cache) finds our
    devices. AsyncServiceBrowser requires at least one handler to construct.
    """


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
        self._aiozc = None
        self._browser: AsyncServiceBrowser | None = None

    async def async_start(self) -> None:
        self._stop_event.clear()
        # pyatv.scan(aiozc=...) only reads from the shared zeroconf instance's
        # cache — per pyatv's own docs, "a ServiceBrowser must be running for
        # all the types being scanned for", or the cache never learns which
        # devices exist. Without our own browser, results were incomplete and
        # inconsistent (2 of 4 Bose speakers found, seemingly at random,
        # depending on whether some other HA integration happened to already be
        # watching _raop._tcp). Keep our own browser running for the discovery's
        # whole lifetime so the cache is genuinely, continuously populated.
        self._aiozc = await ha_zeroconf.async_get_async_instance(self.hass)
        self._browser = AsyncServiceBrowser(
            self._aiozc.zeroconf, [RAOP_SERVICE_TYPE], handlers=[_noop_service_state_change]
        )
        self._task = self.entry.async_create_background_task(
            self.hass, self._scan_loop(), f"{DOMAIN}_airplay_discovery"
        )

    async def async_stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._browser:
            await self._browser.async_cancel()
            self._browser = None

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
        if self._aiozc is None:
            self._aiozc = await ha_zeroconf.async_get_async_instance(self.hass)
        start = time.monotonic()
        results = await pyatv.scan(
            loop, timeout=DEFAULT_SCAN_TIMEOUT_SECONDS, protocol={Protocol.RAOP}, aiozc=self._aiozc
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
        """Return a cached RAOP config for bose_ip, rescanning if missing/stale.

        Retries a few times with a short delay: mDNS PTR records for a device can
        briefly vanish from the cache around a Wi-Fi roaming event (moving between
        mesh APs) even though the speaker itself is fine — a short retry window
        rides out that gap instead of failing the whole preset trigger on the
        first empty scan.
        """
        cached = self._cache.get(bose_ip)
        if cached and (time.monotonic() - cached[1]) < max_age_seconds:
            return cached[0]

        for attempt in range(1, FALLBACK_RESCAN_ATTEMPTS + 1):
            try:
                await self._async_scan_once()
            except Exception as err:
                _LOGGER.warning(
                    "AirPlay discovery fallback scan failed for %s (attempt %d/%d): %s",
                    bose_ip, attempt, FALLBACK_RESCAN_ATTEMPTS, err, exc_info=True,
                )
            cached = self._cache.get(bose_ip)
            if cached:
                return cached[0]
            if attempt < FALLBACK_RESCAN_ATTEMPTS:
                await asyncio.sleep(FALLBACK_RESCAN_DELAY_SECONDS)

        return None


class AirPlayPlayer:
    """Owns the AirPlay/RAOP connection + streaming task for one Bose device."""

    def __init__(self, hass: HomeAssistant, bose_ip: str, discovery: AirPlayDiscovery) -> None:
        self.hass = hass
        self.bose_ip = bose_ip
        self._discovery = discovery
        self._atv: AppleTV | None = None
        self._stream_task: asyncio.Task | None = None

    async def play(
        self,
        url: str,
        *,
        title: str = "",
        artist: str = "",
        album: str = "",
        volume_percent: float | None = None,
    ) -> bool:
        """Stop any current stream, connect, and start streaming url via AirPlay.

        Returns True once the stream task was started (does not itself guarantee
        audible playback — the caller may optionally poll now_playing afterwards).

        Each play() call connects a fresh pyatv AppleTV instance, which starts
        with no "changed volume" of its own. Without volume_percent, pyatv's
        RAOP stream_file() falls back to either a device-reported "initialVolume"
        or its own hardcoded 33% default — either can be louder than whatever
        volume was last set on the speaker (e.g. via Bose's own app or a previous
        session), audibly resetting the volume on every replay. Passing the
        speaker's current volume here makes pyatv preserve it instead of guessing.
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

        if volume_percent is not None:
            try:
                await self._atv.audio.set_volume(volume_percent)
            except Exception as err:
                _LOGGER.debug(
                    "AirPlay: could not pre-set volume for %s: %s", self.bose_ip, err
                )

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


class AirPlayResumeStore:
    """Persists which preset was last playing via AirPlay per device, across restarts.

    UPnP-mode speakers don't need this — Bose fetches the stream URL itself and
    keeps playing independently of Home Assistant. AirPlay is different: pyatv
    actively decodes and pushes audio over a live connection, so when HA restarts
    that connection (and the speaker's audio) dies with it. This store lets the
    integration remember "device X was playing preset N" so it can replay it once
    HA and AirPlay discovery are back up, instead of the speaker just staying silent.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, RESUME_STORAGE_VERSION, RESUME_STORAGE_KEY)
        self._data: dict[str, int] = {}

    async def async_load(self) -> None:
        loaded = await self._store.async_load()
        self._data = dict(loaded) if loaded else {}

    def get(self, bose_ip: str) -> int | None:
        return self._data.get(bose_ip)

    async def async_set(self, bose_ip: str, preset: int) -> None:
        self._data[bose_ip] = preset
        await self._store.async_save(self._data)

    async def async_clear(self, bose_ip: str) -> None:
        if bose_ip in self._data:
            del self._data[bose_ip]
            await self._store.async_save(self._data)
