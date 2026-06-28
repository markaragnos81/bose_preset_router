from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BoseSoundTouchApi
from .const import CONF_BOSE_IP, CONF_NAME, DEFAULT_COORDINATOR_REFRESH_SECONDS, PRESET_IDS, preset_url_key

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

    async def _async_provision_presets(self) -> None:
        for preset_id in PRESET_IDS:
            url = str(self.device.get(preset_url_key(preset_id)) or "").strip()
            if not url:
                continue
            try:
                await self.api.async_store_preset(preset_id, url, f"Preset {preset_id}")
                _LOGGER.debug("Stored preset %s on %s (%s)", preset_id, self.device_name, self.bose_ip)
            except Exception as err:
                _LOGGER.debug("Could not store preset %s on %s (%s): %s", preset_id, self.device_name, self.bose_ip, err)

    async def async_stop(self) -> None:
        pass
