from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BoseSoundTouchApi
from .const import CONF_BOSE_IP, CONF_NAME, DEFAULT_COORDINATOR_REFRESH_SECONDS

_LOGGER = logging.getLogger(__name__)


class BoseSoundTouchCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        *,
        device: dict[str, Any],
    ) -> None:
        self.entry = entry
        self.device = device
        self.api = BoseSoundTouchApi(
            hass,
            host=device[CONF_BOSE_IP],
            device_name=device[CONF_NAME],
        )
        self._websocket_stop_event = asyncio.Event()
        self._websocket_task: asyncio.Task | None = None
        self._last_websocket_message: str | None = None

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
    def device_id(self) -> str:
        info = self.data.get("info", {}) if self.data else {}
        return str(info.get("device_id") or self.bose_ip)

    @property
    def last_websocket_message(self) -> str | None:
        return self._last_websocket_message

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            snapshot = await self.api.async_fetch_snapshot()
        except Exception as err:
            raise UpdateFailed(
                f"Failed to refresh SoundTouch state for {self.device_name} ({self.bose_ip}): {err}"
            ) from err

        snapshot["device_name"] = self.device_name
        snapshot["bose_ip"] = self.bose_ip
        snapshot["last_websocket_message"] = self._last_websocket_message
        return snapshot

    async def async_start(self) -> None:
        await self.async_refresh()
        if not self.last_update_success:
            _LOGGER.warning(
                "Initial SoundTouch refresh failed for %s (%s); continuing with websocket listener",
                self.device_name,
                self.bose_ip,
            )
        self._websocket_stop_event.clear()
        self._websocket_task = self.entry.async_create_background_task(
            self.hass,
            self._async_websocket_loop(),
            f"{self.entry.domain}_{self.device_name}_soundtouch_ws",
        )

    async def async_stop(self) -> None:
        self._websocket_stop_event.set()
        if self._websocket_task is not None:
            self._websocket_task.cancel()
            await asyncio.gather(self._websocket_task, return_exceptions=True)
            self._websocket_task = None

    async def _async_websocket_loop(self) -> None:
        await self.api.async_listen_websocket(
            stop_event=self._websocket_stop_event,
            message_callback=self._async_handle_websocket_message,
        )

    async def _async_handle_websocket_message(self, message: str) -> None:
        self._last_websocket_message = message
        self.async_set_updated_data(
            {
                **(self.data or {}),
                "last_websocket_message": message,
            }
        )
        self.hass.async_create_task(self.async_request_refresh())
