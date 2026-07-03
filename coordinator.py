from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .airplay import AirPlayDiscovery, AirPlayPlayer, AirPlayResumeStore
from .api import BoseSoundTouchApi
from .const import CONF_BOSE_IP, CONF_NAME, DEFAULT_COORDINATOR_REFRESH_SECONDS, PRESET_IDS, default_preset_url_key, preset_url_key
from .radio_browser import async_fetch_icy_meta, async_lookup_radio_logo, async_lookup_station

_LOGGER = logging.getLogger(__name__)


class BoseSoundTouchCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        subentry_id: str,
        device: dict[str, Any],
        airplay_discovery: AirPlayDiscovery,
        airplay_resume_store: AirPlayResumeStore,
    ) -> None:
        self.entry = entry
        self.subentry_id = subentry_id
        self.device = device
        self.active_preset: int | None = None
        self.active_stream_url: str | None = None
        self._station_meta: dict[str, dict[str, str]] = {}
        self._last_icy_location: str = ""
        self.api = BoseSoundTouchApi(
            hass,
            host=device[CONF_BOSE_IP],
            device_name=device[CONF_NAME],
        )
        self.airplay_player = AirPlayPlayer(hass, device[CONF_BOSE_IP], airplay_discovery)
        self.airplay_player.set_on_ended(self._on_airplay_ended)
        self.airplay_resume_store = airplay_resume_store

        super().__init__(
            hass,
            _LOGGER,
            name=f"bose_soundtouch_{device[CONF_NAME]}",
            update_interval=timedelta(seconds=DEFAULT_COORDINATOR_REFRESH_SECONDS),
        )

    @property
    def device_name(self) -> str:
        return str(self.device[CONF_NAME])

    @property
    def bose_ip(self) -> str:
        return str(self.device[CONF_BOSE_IP])

    @property
    def registry_identifier(self) -> str:
        return f"subentry:{self.subentry_id}"

    @property
    def device_id(self) -> str:
        info = self.data.get("info", {}) if self.data else {}
        return str(info.get("device_id") or self.bose_ip)

    def _on_airplay_ended(self) -> None:
        """Fired (sync, from a task done-callback) when our own RAOP stream dies

        on its own — not via an intentional stop()/replace via play(). Bose's own
        now_playing has proven unreliable/stale for AirPlay, so we can't count on
        it to ever reflect this; correct our own state immediately instead of
        waiting for the next poll to notice a mismatch.
        """
        self.active_preset = None
        self.active_stream_url = None
        if self.data is not None:
            self.hass.async_create_task(self._async_refresh_after_airplay_ended())

    async def _async_refresh_after_airplay_ended(self) -> None:
        try:
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.debug("AirPlay ended: refresh failed for %s: %s", self.device_name, err)

    def _resolve_icy_url(self, now_playing: dict[str, Any]) -> str:
        location = str(now_playing.get("location") or "").strip()
        if location:
            return location
        # AirPlay's ContentItem never carries a location — we are the streamer,
        # so fall back to the URL we ourselves pushed via pyatv.
        if str(now_playing.get("source") or "").upper() == "AIRPLAY" and self.active_stream_url:
            return self.active_stream_url
        return ""

    async def push_now_playing(self, now_playing: dict[str, Any]) -> None:
        """Called by router when a nowPlayingUpdated WS event arrives."""
        if not self.data:
            return
        merged = dict(self.data)
        merged["now_playing"] = now_playing

        source = str(now_playing.get("source") or "").upper()
        location = self._resolve_icy_url(now_playing)
        if source in {"UPNP", "AIRPLAY"} and location:
            if location not in self._station_meta:
                await self._async_resolve_station_meta(location)
            icy = await async_fetch_icy_meta(self.hass, location)
            merged["icy_meta"] = icy
        else:
            merged["icy_meta"] = {}

        self.async_set_updated_data(merged)

    # ------------------------------------------------------------------
    # HTTP polling (fallback / full state refresh)
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            snapshot = await self.api.async_fetch_snapshot()
        except Exception as err:
            raise UpdateFailed(
                f"Failed to refresh SoundTouch state for {self.device_name} ({self.bose_ip}): {err}"
            ) from err

        snapshot["device_name"] = self.device_name
        snapshot["bose_ip"] = self.bose_ip

        # ICY metadata fetch (fallback when WS is not connected or for initial load)
        now_playing = snapshot.get("now_playing", {})
        source = str(now_playing.get("source") or "").upper()
        location = self._resolve_icy_url(now_playing)
        if source in {"UPNP", "AIRPLAY"} and location:
            icy = await async_fetch_icy_meta(self.hass, location)
            snapshot["icy_meta"] = icy
        else:
            snapshot["icy_meta"] = {}

        # Cross-check: if we believe AirPlay is active but our own stream task
        # has actually died, don't keep reporting a preset that isn't playing.
        if source == "AIRPLAY" and self.active_preset is not None and not self.airplay_player.is_playing:
            self.active_preset = None
            self.active_stream_url = None

        return snapshot

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        await self.async_refresh()
        if not self.last_update_success:
            _LOGGER.warning(
                "Initial SoundTouch refresh failed for %s (%s); will retry on next poll",
                self.device_name,
                self.bose_ip,
            )
        await self._async_provision_presets()

    async def async_stop(self) -> None:
        await self.airplay_player.stop()

    # ------------------------------------------------------------------
    # Station metadata & presets
    # ------------------------------------------------------------------

    def get_station_meta(self, url: str) -> dict[str, str]:
        return self._station_meta.get(url, {})

    async def _async_resolve_station_meta(self, url: str) -> dict[str, str]:
        if url in self._station_meta:
            return self._station_meta[url]
        meta = await async_lookup_station(self.hass, url)
        if not meta:
            meta = {"name": "", "favicon": ""}
        if not meta.get("name"):
            meta["name"] = self._station_name_from_url(url)

        # Prefer a high-res radio.net station logo (matched by stream URL) over the
        # plain favicon. Only overrides when an exact URL match is found.
        try:
            logo = await async_lookup_radio_logo(self.hass, meta.get("name", ""), url)
        except Exception as err:
            _LOGGER.debug("radio.net logo lookup failed for %s: %s", url, err)
            logo = ""
        if logo:
            meta["favicon"] = logo

        self._station_meta[url] = meta
        return meta

    def _resolve_preset_url(self, preset_id: int) -> str:
        url = str(self.device.get(preset_url_key(preset_id)) or "").strip()
        if not url:
            url = str(self.entry.data.get(default_preset_url_key(preset_id)) or "").strip()
        return url

    async def _async_provision_presets(self) -> None:
        for preset_id in PRESET_IDS:
            url = self._resolve_preset_url(preset_id)
            if not url:
                continue
            try:
                meta = await self._async_resolve_station_meta(url)
            except Exception as err:
                _LOGGER.warning(
                    "Station meta lookup failed for preset %s url=%s on %s: %s",
                    preset_id, url, self.device_name, err,
                )
                meta = {}
            name = meta.get("name") or self._station_name_from_url(url) or f"Preset {preset_id}"
            favicon = meta.get("favicon", "")
            _LOGGER.debug(
                "Provisioning preset %s on %s: name=%r favicon=%r url=%s",
                preset_id, self.device_name, name, favicon, url,
            )
            try:
                await self.api.async_store_preset(preset_id, url, name)
            except Exception as err:
                _LOGGER.debug(
                    "Could not store preset %s on %s (%s): %s", preset_id, self.device_name, self.bose_ip, err
                )

    @staticmethod
    def _station_name_from_url(url: str) -> str:
        try:
            host = urlsplit(url).hostname or ""
            skip = {"www", "stream", "streams", "live", "listen", "audio", "icecast", "ice", "cdn", "media"}
            for part in host.split("."):
                if part and part not in skip and not part.isdigit():
                    return part.replace("-", " ").title()
        except Exception:
            pass
        return ""
