from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse

import asyncio
import voluptuous as vol
import websockets

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_BOSE_IP,
    CONF_DEBUG_LOGGING,
    CONF_DEBOUNCE_SECONDS,
    CONF_DEFAULT_VOLUME,
    CONF_MA_PLAYER,
    CONF_NOTIFY_ON_PRESS,
    CONF_PLAYBACK_VERIFY_ATTEMPTS,
    CONF_PLAYBACK_VERIFY_DELAY_SECONDS,
    CONF_STRICT_BOSE_CONFIRMATION,
    CONF_TOLERANT_BOSE_CONFIRMATION,
    DEFAULT_DEBUG_LOGGING,
    DEFAULT_DEBOUNCE_SECONDS,
    DEFAULT_NOTIFY_ON_PRESS,
    DEFAULT_PLAYBACK_VERIFY_ATTEMPTS,
    DEFAULT_PLAYBACK_VERIFY_DELAY_SECONDS,
    DEFAULT_STRICT_BOSE_CONFIRMATION,
    DEFAULT_TOLERANT_BOSE_CONFIRMATION,
    DOMAIN,
    PRESET_IDS,
    SUBENTRY_TYPE_DEVICE,
    WS_PORT,
    preset_enabled_key,
    preset_url_key,
    preset_volume_key,
)


def global_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NOTIFY_ON_PRESS, default=DEFAULT_NOTIFY_ON_PRESS): selector.BooleanSelector(),
            vol.Required(CONF_DEBUG_LOGGING, default=DEFAULT_DEBUG_LOGGING): selector.BooleanSelector(),
            vol.Required(CONF_DEBOUNCE_SECONDS, default=DEFAULT_DEBOUNCE_SECONDS): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=10, step=0.5, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_PLAYBACK_VERIFY_ATTEMPTS,
                default=DEFAULT_PLAYBACK_VERIFY_ATTEMPTS,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=10, step=1, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_PLAYBACK_VERIFY_DELAY_SECONDS,
                default=DEFAULT_PLAYBACK_VERIFY_DELAY_SECONDS,
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.5, max=10, step=0.5, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_STRICT_BOSE_CONFIRMATION,
                default=DEFAULT_STRICT_BOSE_CONFIRMATION,
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_TOLERANT_BOSE_CONFIRMATION,
                default=DEFAULT_TOLERANT_BOSE_CONFIRMATION,
            ): selector.BooleanSelector(),
        }
    )


def _volume_selector() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=100,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="%",
        )
    )


def device_basic_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME): selector.TextSelector(),
            vol.Required(CONF_BOSE_IP): selector.TextSelector(),
            vol.Required(CONF_MA_PLAYER): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
            vol.Optional(CONF_DEFAULT_VOLUME): _volume_selector(),
        }
    )


def _preset_schema(presets: tuple[int, ...]) -> vol.Schema:
    schema: dict = {}
    for preset in presets:
        schema[vol.Optional(preset_enabled_key(preset), default=True)] = selector.BooleanSelector()
        schema[vol.Optional(preset_volume_key(preset))] = _volume_selector()
        schema[vol.Optional(preset_url_key(preset))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        )

    return vol.Schema(schema)


def device_preset_schema_a() -> vol.Schema:
    return _preset_schema((1, 2, 3))


def device_preset_schema_b() -> vol.Schema:
    return _preset_schema((4, 5, 6))


def device_schema() -> vol.Schema:
    schema: dict = {
        vol.Required(CONF_NAME): selector.TextSelector(),
        vol.Required(CONF_BOSE_IP): selector.TextSelector(),
        vol.Required(CONF_MA_PLAYER): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="media_player")
        ),
        vol.Optional(CONF_DEFAULT_VOLUME): _volume_selector(),
    }

    for preset in PRESET_IDS:
        schema[vol.Optional(preset_enabled_key(preset), default=True)] = selector.BooleanSelector()
        schema[vol.Optional(preset_volume_key(preset))] = _volume_selector()
        schema[vol.Optional(preset_url_key(preset))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        )

    return vol.Schema(schema)


def _is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _normalize_device_input(user_input: dict) -> dict:
    normalized_input: dict = {}
    for key, value in user_input.items():
        if isinstance(value, str):
            stripped = value.strip()
            if stripped or key in (CONF_NAME, CONF_BOSE_IP, CONF_MA_PLAYER):
                normalized_input[key] = stripped
        else:
            normalized_input[key] = value

    for preset in PRESET_IDS:
        normalized_input.setdefault(preset_enabled_key(preset), True)

    return normalized_input


def _normalize_existing_devices(
    existing_devices: list[config_entries.ConfigSubentry | dict],
) -> list[dict]:
    return [
        device.data if isinstance(device, config_entries.ConfigSubentry) else device
        for device in existing_devices
    ]


def _validate_device_input(
    user_input: dict,
    existing_devices: list[config_entries.ConfigSubentry | dict],
    current_name: str | None = None,
    current_ip: str | None = None,
) -> tuple[dict[str, str], dict]:
    errors: dict[str, str] = {}
    normalized_input = _normalize_device_input(user_input)

    device_name = str(normalized_input.get(CONF_NAME, "")).strip()
    bose_ip = str(normalized_input.get(CONF_BOSE_IP, "")).strip()

    if not device_name:
        errors[CONF_NAME] = "name_required"

    if not bose_ip:
        errors[CONF_BOSE_IP] = "ip_required"
    else:
        try:
            ip_address(bose_ip)
        except ValueError:
            errors[CONF_BOSE_IP] = "invalid_ip"

    normalized_devices = _normalize_existing_devices(existing_devices)

    if not errors and any(
        device[CONF_NAME].casefold() == device_name.casefold()
        and device[CONF_NAME] != current_name
        for device in normalized_devices
    ):
        errors[CONF_NAME] = "name_exists"

    if CONF_BOSE_IP not in errors and any(
        device[CONF_BOSE_IP] == bose_ip and device[CONF_BOSE_IP] != current_ip
        for device in normalized_devices
    ):
        errors[CONF_BOSE_IP] = "ip_exists"

    has_active_preset = False
    for preset in PRESET_IDS:
        enabled_key = preset_enabled_key(preset)
        url_key = preset_url_key(preset)
        volume_key = preset_volume_key(preset)
        enabled = bool(normalized_input.get(enabled_key, True))
        url_value = str(normalized_input.get(url_key, "")).strip()

        if enabled:
            has_active_preset = True

        if url_value and not _is_valid_url(url_value):
            errors[url_key] = "invalid_url"

        if enabled and not url_value:
            errors[url_key] = "preset_url_required"

        preset_volume = normalized_input.get(volume_key)
        if preset_volume is not None and not 0 <= float(preset_volume) <= 100:
            errors[volume_key] = "invalid_volume"

    if not has_active_preset:
        errors["base"] = "no_enabled_presets"

    default_volume = normalized_input.get(CONF_DEFAULT_VOLUME)
    if default_volume is not None and not 0 <= float(default_volume) <= 100:
        errors[CONF_DEFAULT_VOLUME] = "invalid_volume"

    return errors, normalized_input


def _default_device_suggestions() -> dict[str, str | bool]:
    suggestions: dict[str, str | bool] = {}
    for preset in PRESET_IDS:
        suggestions[preset_enabled_key(preset)] = False
    return suggestions


def _device_title(data: dict) -> str:
    return f"{data[CONF_NAME]} ({data[CONF_BOSE_IP]})"


async def _async_validate_device_connection(host: str) -> bool:
    ws = None
    try:
        ws = await asyncio.wait_for(
            websockets.connect(f"ws://{host}:{WS_PORT}/", subprotocols=["gabbo"]),
            timeout=5,
        )
    except Exception:
        return False
    finally:
        if ws is not None:
            await ws.close()

    return True


class BosePresetRouterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[config_entries.ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_DEVICE: BosePresetRouterDeviceSubentryFlow}

    async def async_step_user(self, user_input=None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="Bose Preset Router", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(global_schema(), {}),
            errors={},
        )

    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data_updates=user_input,
                reason="reconfigure_successful",
            )

        defaults = {**entry.data, **entry.options}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(global_schema(), defaults),
            errors={},
        )


class BosePresetRouterDeviceSubentryFlow(config_entries.ConfigSubentryFlow):
    def __init__(self) -> None:
        self._pending_user_input: dict = {}
        self._reconfigure_subentry = None

    def _device_defaults(self, entry: config_entries.ConfigEntry, subentry=None) -> dict:
        base = _default_device_suggestions()
        if subentry is not None:
            return base | subentry.data
        return base

    @staticmethod
    def _basic_fields(data: dict) -> dict:
        return {
            key: data[key]
            for key in (CONF_NAME, CONF_BOSE_IP, CONF_MA_PLAYER, CONF_DEFAULT_VOLUME)
            if key in data
        }

    @staticmethod
    def _preset_fields(data: dict, presets: tuple[int, ...]) -> dict:
        selected: dict = {}
        for preset in presets:
            for key in (
                preset_enabled_key(preset),
                preset_volume_key(preset),
                preset_url_key(preset),
            ):
                if key in data:
                    selected[key] = data[key]
        return selected

    async def _async_process_device_input(
        self,
        entry: config_entries.ConfigEntry,
        user_input: dict,
        *,
        current_name: str | None = None,
        current_ip: str | None = None,
    ) -> tuple[dict[str, str], dict]:
        errors, normalized_input = _validate_device_input(
            user_input,
            list(entry.subentries.values()),
            current_name=current_name,
            current_ip=current_ip,
        )
        if errors:
            return errors, normalized_input

        if not await _async_validate_device_connection(normalized_input[CONF_BOSE_IP]):
            return {"base": "cannot_connect"}, normalized_input

        return {}, normalized_input

    async def async_step_user(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._pending_user_input = user_input
            return await self.async_step_presets_a()

        self._pending_user_input = {}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(device_basic_schema(), {}),
            errors={},
        )

    async def async_step_presets_a(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._pending_user_input.update(user_input)
            return await self.async_step_presets_b()

        return self.async_show_form(
            step_id="presets_a",
            data_schema=self.add_suggested_values_to_schema(
                device_preset_schema_a(),
                self._preset_fields(self._pending_user_input, (1, 2, 3)),
            ),
            errors={},
        )

    async def async_step_presets_b(self, user_input=None) -> FlowResult:
        entry = self._get_entry()

        if user_input is not None:
            self._pending_user_input.update(user_input)
            errors, normalized_input = await self._async_process_device_input(entry, self._pending_user_input)
            if not errors:
                return self.async_create_entry(
                    title=_device_title(normalized_input),
                    data=normalized_input,
                )

            self._pending_user_input = normalized_input
            basic_errors = {
                key: value for key, value in errors.items() if key in self._basic_fields(normalized_input)
            }
            preset_a_errors = {
                key: value
                for key, value in errors.items()
                if key in self._preset_fields(normalized_input, (1, 2, 3)) or key == "base"
            }
            preset_b_errors = {
                key: value
                for key, value in errors.items()
                if key in self._preset_fields(normalized_input, (4, 5, 6)) or key == "base"
            }

            if basic_errors:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self.add_suggested_values_to_schema(
                        device_basic_schema(),
                        self._basic_fields(normalized_input),
                    ),
                    errors=basic_errors,
                )
            if preset_a_errors:
                return self.async_show_form(
                    step_id="presets_a",
                    data_schema=self.add_suggested_values_to_schema(
                        device_preset_schema_a(),
                        self._preset_fields(normalized_input, (1, 2, 3)),
                    ),
                    errors=preset_a_errors,
                )

            return self.async_show_form(
                step_id="presets_b",
                data_schema=self.add_suggested_values_to_schema(
                    device_preset_schema_b(),
                    self._preset_fields(normalized_input, (4, 5, 6)),
                ),
                errors=preset_b_errors,
            )

        return self.async_show_form(
            step_id="presets_b",
            data_schema=self.add_suggested_values_to_schema(
                device_preset_schema_b(),
                self._preset_fields(self._pending_user_input, (4, 5, 6)),
            ),
            errors={},
        )

    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        subentry = self._get_reconfigure_subentry()
        self._reconfigure_subentry = subentry
        if user_input is not None:
            self._pending_user_input.update(user_input)
            return await self.async_step_reconfigure_presets_a()

        self._pending_user_input = self._device_defaults(self._get_entry(), subentry)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                device_basic_schema(),
                self._basic_fields(self._pending_user_input),
            ),
            errors={},
        )

    async def async_step_reconfigure_presets_a(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._pending_user_input.update(user_input)
            return await self.async_step_reconfigure_presets_b()

        return self.async_show_form(
            step_id="reconfigure_presets_a",
            data_schema=self.add_suggested_values_to_schema(
                device_preset_schema_a(),
                self._preset_fields(self._pending_user_input, (1, 2, 3)),
            ),
            errors={},
        )

    async def async_step_reconfigure_presets_b(self, user_input=None) -> FlowResult:
        entry = self._get_entry()
        subentry = self._reconfigure_subentry or self._get_reconfigure_subentry()

        if user_input is not None:
            self._pending_user_input.update(user_input)
            errors, normalized_input = await self._async_process_device_input(
                entry,
                self._pending_user_input,
                current_name=subentry.data[CONF_NAME],
                current_ip=subentry.data[CONF_BOSE_IP],
            )
            if not errors:
                self.hass.config_entries.async_update_subentry(
                    entry,
                    subentry,
                    data=normalized_input,
                    title=_device_title(normalized_input),
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

            self._pending_user_input = normalized_input
            basic_errors = {
                key: value for key, value in errors.items() if key in self._basic_fields(normalized_input)
            }
            preset_a_errors = {
                key: value
                for key, value in errors.items()
                if key in self._preset_fields(normalized_input, (1, 2, 3)) or key == "base"
            }
            preset_b_errors = {
                key: value
                for key, value in errors.items()
                if key in self._preset_fields(normalized_input, (4, 5, 6)) or key == "base"
            }

            if basic_errors:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=self.add_suggested_values_to_schema(
                        device_basic_schema(),
                        self._basic_fields(normalized_input),
                    ),
                    errors=basic_errors,
                )
            if preset_a_errors:
                return self.async_show_form(
                    step_id="reconfigure_presets_a",
                    data_schema=self.add_suggested_values_to_schema(
                        device_preset_schema_a(),
                        self._preset_fields(normalized_input, (1, 2, 3)),
                    ),
                    errors=preset_a_errors,
                )

            return self.async_show_form(
                step_id="reconfigure_presets_b",
                data_schema=self.add_suggested_values_to_schema(
                    device_preset_schema_b(),
                    self._preset_fields(normalized_input, (4, 5, 6)),
                ),
                errors=preset_b_errors,
            )

        return self.async_show_form(
            step_id="reconfigure_presets_b",
            data_schema=self.add_suggested_values_to_schema(
                device_preset_schema_b(),
                self._preset_fields(self._pending_user_input, (4, 5, 6)),
            ),
            errors={},
        )
