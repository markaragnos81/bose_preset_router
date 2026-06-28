from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BoseSoundTouchApi
from .const import CONF_BOSE_IP, CONF_NAME, DEFAULT_COORDINATOR_REFRESH_SECONDS, PRESET_IDS, default_preset_url_key, preset_url_key
from .radio_browser import async_fetch_icy_meta, async_lookup_station
from .websocket import BoseSoundTouchWebSocket

_LOGGER = logging.getLogger(__name__)


class BoseSoundTouchCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        subentry_id: str,
        device: dict[str, Any],
    ) -> None:
        self.entry = entry
        self.subentry_id = subentry_id
        self.device = device
        self.active_preset: int | None = None
        self._station_meta: dict[str, dict[str, str]] = {}
        self._last_icy_location: str = ""
        self._ws: BoseSoundTouchWebSocket | None = None
        self.api = BoseSoundTouchApi(
            hass,
            host=device[CONF_BOSE_IP],
            device_name=device[CONF_NAME],
        )

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

    # ------------------------------------------------------------------
    # WebSocket event handling
    # ------------------------------------------------------------------

    def _on_ws_event(self, event_type: str, element: ET.Element) -> None:
        """Called from the WebSocket listener for each incoming event."""
        if event_type == "nowPlayingUpdated":
            self._handle_now_playing_updated(element)
        elif event_type == "volumeUpdated":
            self._handle_volume_updated(element)
        elif event_type in ("presetsUpdated", "recentsUpdated"):
            # Full refresh needed to pick up preset changes
            self.hass.async_create_task(self.async_request_refresh())

    def _handle_now_playing_updated(self, element: ET.Element) -> None:
        np = element.find("nowPlaying")
        if np is None:
            return

        content_item = np.find("ContentItem")
        now_playing: dict[str, Any] = {
            "source": np.get("source", ""),
            "source_account": np.get("sourceAccount", ""),
            "device_id": np.get("deviceID", ""),
            "item_name": np.findtext("ContentItem/itemName", default=""),
            "track": np.findtext("track", default=""),
            "artist": np.findtext("artist", default=""),
            "album": np.findtext("album", default=""),
            "station_name": np.findtext("stationName", default=""),
            "play_status": np.findtext("playStatus", default=""),
            "description": np.findtext("description", default=""),
            "image": np.findtext("art", default=""),
            "location": content_item.get("location", "") if content_item is not None else "",
            "source_type": content_item.get("source", "") if content_item is not None else "",
        }

        if self.data:
            merged = dict(self.data)
            merged["now_playing"] = now_playing
            # Trigger async ICY fetch if UPNP stream location changed
            location = now_playing.get("location", "")
            if str(now_playing.get("source", "")).upper() == "UPNP" and location:
                self.hass.async_create_task(self._async_update_icy(merged, location))
            else:
                merged["icy_meta"] = {}
                self.async_set_updated_data(merged)

    def _handle_volume_updated(self, element: ET.Element) -> None:
        vol = element.find("volume")
        if vol is None:
            return
        volume: dict[str, Any] = {
            "target": int(vol.findtext("targetvolume", default="0") or 0),
            "actual": int(vol.findtext("actualvolume", default="0") or 0),
            "muted": (vol.findtext("muteenabled", default="false") or "").strip().lower() == "true",
        }
        if self.data:
            merged = dict(self.data)
            merged["volume"] = volume
            self.async_set_updated_data(merged)

    async def _async_update_icy(self, data: dict[str, Any], location: str) -> None:
        """Fetch ICY metadata and station meta for a UPNP stream, then push to HA."""
        # Ensure station meta (name + favicon) is cached for this location
        if location not in self._station_meta:
            await self._async_resolve_station_meta(location)

        # Only re-fetch ICY bytes if the stream location changed
        if location != self._last_icy_location or not data.get("icy_meta"):
            self._last_icy_location = location
            icy = await async_fetch_icy_meta(self.hass, location)
        else:
            icy = data.get("icy_meta", {})
        data["icy_meta"] = icy
        self.async_set_updated_data(data)

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
        if str(now_playing.get("source") or "").upper() == "UPNP":
            location = str(now_playing.get("location") or "").strip()
            if location:
                icy = await async_fetch_icy_meta(self.hass, location)
                snapshot["icy_meta"] = icy
            else:
                snapshot["icy_meta"] = {}
        else:
            snapshot["icy_meta"] = {}

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

        # Start WebSocket listener for real-time events
        self._ws = BoseSoundTouchWebSocket(self.hass, self.bose_ip, self._on_ws_event)
        await self._ws.async_start()

    async def async_stop(self) -> None:
        if self._ws:
            await self._ws.async_stop()
            self._ws = None

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
            fallback_name = self._station_name_from_url(url)
            meta = {"name": fallback_name, "favicon": ""}
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
            meta = await self._async_resolve_station_meta(url)
            name = meta.get("name") or f"Preset {preset_id}"
            try:
                await self.api.async_store_preset(preset_id, url, name)
                _LOGGER.debug(
                    "Stored preset %s (%s) on %s (%s)", preset_id, name, self.device_name, self.bose_ip
                )
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
