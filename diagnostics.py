from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BOSE_IP,
    CONF_MA_PLAYER,
    DATA_COORDINATORS,
    DOMAIN,
    PRESET_IDS,
    preset_url_key,
)

TO_REDACT = {CONF_BOSE_IP, CONF_MA_PLAYER, *(preset_url_key(preset) for preset in PRESET_IDS)}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinators = entry_data.get(DATA_COORDINATORS, {})

    return {
        "entry": async_redact_data(
            {
                "entry_id": entry.entry_id,
                "title": entry.title,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "subentries": {
            subentry_id: async_redact_data(
                {
                    "title": subentry.title,
                    "subentry_type": subentry.subentry_type,
                    "data": dict(subentry.data),
                },
                TO_REDACT,
            )
            for subentry_id, subentry in entry.subentries.items()
        },
        "coordinators": {
            subentry_id: async_redact_data(
                {
                    "device_name": coordinator.device_name,
                    "last_update_success": coordinator.last_update_success,
                    "last_websocket_message": coordinator.last_websocket_message,
                    "data": coordinator.data,
                },
                TO_REDACT,
            )
            for subentry_id, coordinator in coordinators.items()
        },
    }
