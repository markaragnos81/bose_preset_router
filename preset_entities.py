from __future__ import annotations

import json
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import BoseSoundTouchCoordinator


class BosePresetSelect(
    CoordinatorEntity[BoseSoundTouchCoordinator],
    SelectEntity,
):
    _attr_has_entity_name = True

    def __init__(self, coordinator_id: str, coordinator: BoseSoundTouchCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator_id = coordinator_id
        self._attr_name = "Preset"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{coordinator_id}_preset_select"

    @property
    def options(self) -> list[str]:
        return [self._preset_label(preset) for preset in self._presets]

    @property
    def current_option(self) -> str | None:
        preset = self._current_preset
        return self._preset_label(preset) if preset is not None else None

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data)

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(self.coordinator.entry.domain, self.coordinator.registry_identifier)},
        }

    @property
    def _presets(self) -> list[dict[str, Any]]:
        return list(self.coordinator.data.get("presets", []) if self.coordinator.data else [])

    @property
    def _current_preset(self) -> dict[str, Any] | None:
        now_playing = self.coordinator.data.get("now_playing", {}) if self.coordinator.data else {}
        current_location = str(now_playing.get("location") or "")
        current_source = str(now_playing.get("source") or "")
        current_item_name = str(now_playing.get("item_name") or "")
        for preset in self._presets:
            preset_location = str(preset.get("location") or "")
            if current_location and preset_location and current_location == preset_location:
                return preset
            if (
                current_source
                and current_source == str(preset.get("source") or "")
                and current_item_name
                and current_item_name == str(preset.get("item_name") or "")
            ):
                return preset
        return None

    @staticmethod
    def _preset_label(preset: dict[str, Any]) -> str:
        preset_id = int(preset.get("id", 0))
        item_name = str(preset.get("item_name") or "").strip()
        return f"Preset {preset_id}: {item_name or 'Unnamed'}"

    @staticmethod
    def _preset_content_id(preset: dict[str, Any]) -> str:
        return json.dumps({"preset_id": int(preset.get("id", 0))}, sort_keys=True)

    async def async_select_option(self, option: str) -> None:
        preset = next((preset for preset in self._presets if self._preset_label(preset) == option), None)
        if preset is None:
            raise ValueError(f"Unknown preset option: {option}")
        await self.coordinator.api.async_select_preset(int(preset["id"]))
        await self.coordinator.async_request_refresh()


class BosePresetButton(
    CoordinatorEntity[BoseSoundTouchCoordinator],
    ButtonEntity,
):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator_id: str,
        coordinator: BoseSoundTouchCoordinator,
        *,
        preset_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._coordinator_id = coordinator_id
        self._preset_id = preset_id
        self._attr_name = f"Preset {preset_id}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{coordinator_id}_preset_button_{preset_id}"

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data)

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(self.coordinator.entry.domain, self.coordinator.registry_identifier)},
        }

    async def async_press(self) -> None:
        await self.coordinator.api.async_select_preset(self._preset_id)
        await self.coordinator.async_request_refresh()
