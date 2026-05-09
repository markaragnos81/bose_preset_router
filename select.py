from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATORS
from .coordinator import BoseSoundTouchCoordinator
from .preset_entities import BosePresetSelect


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[entry.domain][entry.entry_id]
    coordinators: dict[str, BoseSoundTouchCoordinator] = entry_data[DATA_COORDINATORS]
    async_add_entities(
        BosePresetSelect(coordinator_id, coordinator)
        for coordinator_id, coordinator in coordinators.items()
    )
