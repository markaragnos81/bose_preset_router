from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BoseSoundTouchApi
from .const import CONF_BOSE_IP, CONF_NAME, DEFAULT_COORDINATOR_REFRESH_SECONDS, PRESET_IDS, default_preset_url_key, preset_url_key
from .radio_browser import async_lookup_station

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
        # Cache: stream_url → {"name": str, "favicon": str}
        self._station_meta: dict[str, dict[str, str]] = {}
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

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            snapshot = await self.api.async_fetch_snapshot()
        except Exception as err:
            raise UpdateFailed(
                f"Failed to refresh SoundTouch state for {self.device_name} ({self.bose_ip}): {err}"
            ) from err

        snapshot["device_name"] = self.device_name
        snapshot["bose_ip"] = self.bose_ip
        return snapshot

    async def async_start(self) -> None:
        await self.async_refresh()
        if not self.last_update_success:
            _LOGGER.warning(
                "Initial SoundTouch refresh failed for %s (%s); will retry on next poll",
                self.device_name,
                self.bose_ip,
            )
        await self._async_provision_presets()

    def _resolve_preset_url(self, preset_id: int) -> str:
        url = str(self.device.get(preset_url_key(preset_id)) or "").strip()
        if not url:
            url = str(self.entry.data.get(default_preset_url_key(preset_id)) or "").strip()
        return url

    def get_station_meta(self, url: str) -> dict[str, str]:
        """Return cached station metadata for a stream URL."""
        return self._station_meta.get(url, {})

    async def _async_resolve_station_meta(self, url: str) -> dict[str, str]:
        """Lookup station metadata, using cache first."""
        if url in self._station_meta:
            return self._station_meta[url]
        meta = await async_lookup_station(self.hass, url)
        if not meta:
            # Fallback: derive a readable name from the hostname
            fallback_name = self._station_name_from_url(url)
            meta = {"name": fallback_name, "favicon": ""}
        self._station_meta[url] = meta
        return meta

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
        """Derive a readable station name from a stream URL hostname (fallback)."""
        try:
            host = urlsplit(url).hostname or ""
            skip = {"www", "stream", "streams", "live", "listen", "audio", "icecast", "ice", "cdn", "media"}
            for part in host.split("."):
                if part and part not in skip and not part.isdigit():
                    return part.replace("-", " ").title()
        except Exception:
            pass
        return ""

    async def async_stop(self) -> None:
        pass
