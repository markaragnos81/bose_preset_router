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
import concurrent.futures
import logging
import threading
import time
from typing import Callable

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
    """Owns the AirPlay/RAOP connection + streaming task for one Bose device.

    pyatv's `stream_file()` is documented as an "incubating" API and — at least
    in the RAOP protocol's Icecast source reader (audio_source.py) — makes a
    synchronous, blocking `time.sleep(0.1)` call while polling its internal
    buffer, directly inside what is nominally a coroutine. Home Assistant's
    event-loop blocking-call guard correctly flags this if `stream_file()` runs
    on HA's main loop. Since this is pyatv's own internal behavior (not
    something fixable by awaiting differently on our side), the entire
    connect+stream lifecycle runs on a dedicated background thread with its own
    private event loop, fully isolated from HA's main loop — the blocking sleep
    then only ever stalls that private thread, never HA itself.
    """

    def __init__(self, hass: HomeAssistant, bose_ip: str, discovery: AirPlayDiscovery) -> None:
        self.hass = hass
        self.bose_ip = bose_ip
        self._discovery = discovery
        self._on_ended: Callable[[], None] | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream_task: asyncio.Task | None = None  # lives on the worker thread's loop
        self._lock = threading.Lock()
        self._playing = False

    @property
    def is_playing(self) -> bool:
        """Whether our own stream is verified still alive (not assumed).

        This is the one thing we can check directly rather than trust: Bose's own
        now_playing has proven unreliable for AirPlay (stale/slow to transition),
        and "we once asked to play X" can go stale too if the RAOP session dies in
        the background (observed: "connection was lost" errors). Callers should
        gate any "this preset is currently playing" claim on this being True.
        """
        with self._lock:
            return self._playing

    def set_on_ended(self, callback: Callable[[], None] | None) -> None:
        """Register a callback fired when the stream ends on its own (error or EOF).

        Not called when the stream is stopped intentionally via stop() (the caller
        that initiated the stop already knows and handles its own state update) —
        only for the "found out from a dead connection" case, so state like
        active_preset can be corrected promptly instead of staying stale until the
        next poll cycle happens to notice. Fired via call_soon_threadsafe since the
        stream itself runs on a separate worker-thread event loop.
        """
        self._on_ended = callback

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

        Returns True once the connection succeeded and streaming has started
        (does not itself guarantee audible playback — the caller may optionally
        poll now_playing afterwards).

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

        metadata = MediaMetadata(
            title=title or "Stream",
            artist=artist,
            album=album or "AirPlay",
        )

        connect_future: concurrent.futures.Future[bool] = concurrent.futures.Future()
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(config, url, metadata, volume_percent, connect_future),
            name=f"{DOMAIN}_airplay_{self.bose_ip}",
            daemon=True,
        )
        self._thread.start()

        try:
            return await self.hass.async_add_executor_job(connect_future.result, 15)
        except Exception as err:
            _LOGGER.warning("AirPlay: connect timed out for %s: %s", self.bose_ip, err)
            return False

    def _thread_main(
        self,
        config: BaseConfig,
        url: str,
        metadata: MediaMetadata,
        volume_percent: float | None,
        connect_future: concurrent.futures.Future,
    ) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(
                self._async_stream_lifecycle(url, metadata, volume_percent, config, connect_future)
            )
        finally:
            loop.close()
            self._loop = None

    async def _async_stream_lifecycle(
        self,
        url: str,
        metadata: MediaMetadata,
        volume_percent: float | None,
        config: BaseConfig,
        connect_future: concurrent.futures.Future,
    ) -> None:
        atv: AppleTV | None = None
        try:
            atv = await pyatv.connect(config, asyncio.get_running_loop())
        except Exception as err:
            _LOGGER.warning("AirPlay: connect failed for %s: %s", self.bose_ip, err)
            if not connect_future.done():
                connect_future.set_result(False)
            return

        if volume_percent is not None:
            try:
                await atv.audio.set_volume(volume_percent)
            except Exception as err:
                _LOGGER.debug(
                    "AirPlay: could not pre-set volume for %s: %s", self.bose_ip, err
                )

        with self._lock:
            self._playing = True
        if not connect_future.done():
            connect_future.set_result(True)

        stream_task = asyncio.ensure_future(atv.stream.stream_file(url, metadata=metadata))
        self._stream_task = stream_task
        was_cancelled = False
        try:
            await stream_task
        except asyncio.CancelledError:
            was_cancelled = True
        except Exception as err:
            _LOGGER.warning("AirPlay: stream_file error for %s: %s", self.bose_ip, err)
        finally:
            with self._lock:
                self._playing = False
            try:
                atv.close()
            except Exception:
                pass
            if not was_cancelled and self._on_ended is not None:
                self.hass.loop.call_soon_threadsafe(self._on_ended)

    async def stop(self) -> None:
        thread = self._thread
        loop = self._loop
        if thread is None:
            return
        self._thread = None
        task = self._stream_task
        self._stream_task = None
        if loop is not None and loop.is_running() and task is not None:
            loop.call_soon_threadsafe(task.cancel)
        try:
            await self.hass.async_add_executor_job(thread.join, 10)
        except Exception as err:
            _LOGGER.debug("AirPlay: stop join failed for %s: %s", self.bose_ip, err)
        if thread.is_alive():
            _LOGGER.warning(
                "AirPlay: worker thread for %s did not stop within timeout", self.bose_ip
            )
        with self._lock:
            self._playing = False
        self._loop = None


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
