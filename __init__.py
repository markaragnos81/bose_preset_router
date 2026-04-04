from __future__ import annotations

import asyncio
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_DEVICE,
    ATTR_PRESET,
    DOMAIN,
    SERVICE_TRIGGER_PRESET,
)
from .router import BosePresetRouterManager

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE): str,
        vol.Required(ATTR_PRESET): vol.All(vol.Coerce(int), vol.Range(min=1, max=6)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})

    async def handle_trigger_preset(call: ServiceCall) -> None:
        entry_id = next(iter(hass.data[DOMAIN]), None)
        if entry_id is None:
            raise HomeAssistantError("No Bose Preset Router config entry loaded")

        manager: BosePresetRouterManager = hass.data[DOMAIN][entry_id]
        await manager.async_handle_preset(
            device_name=call.data[ATTR_DEVICE],
            preset=call.data[ATTR_PRESET],
            reason="manual_service",
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_TRIGGER_PRESET,
        handle_trigger_preset,
        schema=SERVICE_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager = BosePresetRouterManager(hass, entry)
    await manager.async_start()

    hass.data[DOMAIN][entry.entry_id] = manager
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    manager: BosePresetRouterManager = hass.data[DOMAIN].pop(entry.entry_id)
    await manager.async_stop()
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)