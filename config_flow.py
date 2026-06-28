from __future__ import annotations

import asyncio
from ipaddress import ip_address
import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
import websockets

from homeassistant import config_entries
from homeassistant.components import ssdp
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import BoseSoundTouchApi
from .const import (
    CONF_BOSE_IP,
    CONF_DEBUG_LOGGING,
    CONF_DEBOUNCE_SECONDS,
    CONF_DEFAULT_VOLUME,
    CONF_MA_PLAYER,
    CONF_NOTIFY_ON_PRESS,
    CONF_ROUTING_MODE,
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
    default_preset_url_key,
    preset_url_key,
    preset_volume_key,
)

DISCOVERY_SETUP_METHOD = "discover"
MANUAL_SETUP_METHOD = "manual"
SETUP_MODE_QUICK = "quick"
SETUP_MODE_EXPERT = "expert"
ROUTING_MODE_NONE = "none"
ROUTING_MODE_DIRECT = "direct"
ROUTING_MODE_PLAYER = "player"

ATTR_SETUP_METHOD = "setup_method"
ATTR_SETUP_MODE = "setup_mode"
ATTR_ROUTING_MODE = "routing_mode"
ATTR_DISCOVERED_DEVICE = "discovered_device"

SSDP_MEDIA_RENDERER_ST = "urn:schemas-upnp-org:device:MediaRenderer:1"
DEVICE_KEYS = {CONF_NAME, CONF_BOSE_IP}
ROUTING_KEYS = {ATTR_ROUTING_MODE, CONF_MA_PLAYER}
ADVANCED_KEYS = {CONF_DEFAULT_VOLUME}

_LOGGER = logging.getLogger(__name__)


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
            **{
                vol.Optional(default_preset_url_key(p)): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                )
                for p in PRESET_IDS
            },
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


def device_start_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(ATTR_SETUP_METHOD, default=DISCOVERY_SETUP_METHOD): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=DISCOVERY_SETUP_METHOD,
                            label="Discover Bose devices on the network",
                        ),
                        selector.SelectOptionDict(
                            value=MANUAL_SETUP_METHOD,
                            label="Enter device details manually",
                        ),
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required(ATTR_SETUP_MODE, default=SETUP_MODE_QUICK): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=SETUP_MODE_QUICK,
                            label="Quick setup",
                        ),
                        selector.SelectOptionDict(
                            value=SETUP_MODE_EXPERT,
                            label="Expert setup",
                        ),
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        }
    )


def reconfigure_start_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(ATTR_SETUP_MODE, default=SETUP_MODE_QUICK): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(
                            value=SETUP_MODE_QUICK,
                            label="Quick setup",
                        ),
                        selector.SelectOptionDict(
                            value=SETUP_MODE_EXPERT,
                            label="Expert setup",
                        ),
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
    )


def device_basic_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME): selector.TextSelector(),
            vol.Required(CONF_BOSE_IP): selector.TextSelector(),
        }
    )


def _routing_mode_options() -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=ROUTING_MODE_NONE,
            label="Only create the Bose player",
        ),
        selector.SelectOptionDict(
            value=ROUTING_MODE_DIRECT,
            label="Play presets directly on Bose via UPNP (no Music Assistant needed)",
        ),
        selector.SelectOptionDict(
            value=ROUTING_MODE_PLAYER,
            label="Route presets to another player (Music Assistant)",
        ),
    ]


def routing_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(ATTR_ROUTING_MODE, default=ROUTING_MODE_NONE): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_routing_mode_options(),
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        }
    )


def routing_player_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_MA_PLAYER): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="media_player")
            ),
        }
    )


def advanced_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_DEFAULT_VOLUME): _volume_selector(),
        }
    )


def preset_schema(*, expert: bool) -> vol.Schema:
    schema: dict = {}
    for preset in PRESET_IDS:
        schema[vol.Optional(preset_url_key(preset))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
        )
        if expert:
            schema[vol.Optional(preset_volume_key(preset))] = _volume_selector()
    return vol.Schema(schema)


def _is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _normalize_device_input(user_input: dict) -> dict:
    normalized_input: dict = {}
    for key, value in user_input.items():
        if isinstance(value, str):
            stripped = value.strip()
            if stripped or key in (CONF_NAME, CONF_BOSE_IP, CONF_MA_PLAYER, ATTR_ROUTING_MODE):
                normalized_input[key] = stripped
        else:
            normalized_input[key] = value

    normalized_input.setdefault(ATTR_ROUTING_MODE, ROUTING_MODE_NONE)

    return normalized_input


def _normalize_existing_devices(
    existing_devices: list[config_entries.ConfigSubentry | dict],
) -> list[dict]:
    return [
        device.data if isinstance(device, config_entries.ConfigSubentry) else device
        for device in existing_devices
    ]


def _ssdp_value(discovery_info: Any, *keys: str) -> str:
    for key in keys:
        value = None
        if hasattr(discovery_info, "get"):
            try:
                value = discovery_info.get(key)
            except Exception:
                value = None
        if value:
            return str(value)

        if hasattr(discovery_info, key):
            value = getattr(discovery_info, key, None)
            if value:
                return str(value)

        upnp = getattr(discovery_info, "upnp", None)
        if isinstance(upnp, dict):
            value = upnp.get(key)
            if value:
                return str(value)

    return ""


def _routing_mode_from_data(data: dict) -> str:
    stored = str(data.get(CONF_ROUTING_MODE) or "").strip()
    if stored == ROUTING_MODE_DIRECT:
        return ROUTING_MODE_DIRECT
    return ROUTING_MODE_PLAYER if str(data.get(CONF_MA_PLAYER) or "").strip() else ROUTING_MODE_NONE


def _finalize_device_data(normalized_input: dict) -> dict:
    final_data = dict(normalized_input)
    final_data.pop(ATTR_SETUP_METHOD, None)
    final_data.pop(ATTR_SETUP_MODE, None)
    routing_mode = str(final_data.pop(ATTR_ROUTING_MODE, ROUTING_MODE_NONE) or ROUTING_MODE_NONE)
    if routing_mode == ROUTING_MODE_DIRECT:
        final_data[CONF_ROUTING_MODE] = ROUTING_MODE_DIRECT
        final_data.pop(CONF_MA_PLAYER, None)
    elif routing_mode == ROUTING_MODE_PLAYER and str(final_data.get(CONF_MA_PLAYER) or "").strip():
        final_data.pop(CONF_ROUTING_MODE, None)
    else:
        final_data.pop(CONF_MA_PLAYER, None)
        final_data.pop(CONF_ROUTING_MODE, None)
    return final_data


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
    routing_mode = str(normalized_input.get(ATTR_ROUTING_MODE) or ROUTING_MODE_NONE)

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

    if device_name and any(
        device[CONF_NAME].casefold() == device_name.casefold()
        and device[CONF_NAME] != current_name
        for device in normalized_devices
    ):
        errors[CONF_NAME] = "name_exists"

    if bose_ip and CONF_BOSE_IP not in errors and any(
        device[CONF_BOSE_IP] == bose_ip and device[CONF_BOSE_IP] != current_ip
        for device in normalized_devices
    ):
        errors[CONF_BOSE_IP] = "ip_exists"

    if routing_mode == ROUTING_MODE_PLAYER and not str(normalized_input.get(CONF_MA_PLAYER) or "").strip():
        errors[CONF_MA_PLAYER] = "target_player_required"

    for preset in PRESET_IDS:
        url_key = preset_url_key(preset)
        volume_key = preset_volume_key(preset)
        url_value = str(normalized_input.get(url_key, "")).strip()

        if url_value and not _is_valid_url(url_value):
            errors[url_key] = "invalid_url"

        preset_volume = normalized_input.get(volume_key)
        if preset_volume is not None and not 0 <= float(preset_volume) <= 100:
            errors[volume_key] = "invalid_volume"

    default_volume = normalized_input.get(CONF_DEFAULT_VOLUME)
    if default_volume is not None and not 0 <= float(default_volume) <= 100:
        errors[CONF_DEFAULT_VOLUME] = "invalid_volume"

    return errors, normalized_input


def _device_title(data: dict) -> str:
    return f"{data[CONF_NAME]} ({data[CONF_BOSE_IP]})"


def _preset_fields(data: dict, *, expert: bool) -> dict:
    selected: dict = {}
    for preset in PRESET_IDS:
        if preset_url_key(preset) in data:
            selected[preset_url_key(preset)] = data[preset_url_key(preset)]
        if expert and preset_volume_key(preset) in data:
            selected[preset_volume_key(preset)] = data[preset_volume_key(preset)]
    return selected


def _active_presets(data: dict) -> list[int]:
    return [
        preset
        for preset in PRESET_IDS
        if str(data.get(preset_url_key(preset)) or "").strip()
    ]


def _preset_summary(data: dict) -> str:
    active_presets = _active_presets(data)
    if not active_presets:
        return "Keine"

    labels: list[str] = []
    for preset in active_presets:
        url_value = str(data.get(preset_url_key(preset)) or "").strip()
        if url_value:
            labels.append(f"{preset}")
        else:
            labels.append(f"{preset} (ohne URL)")
    return ", ".join(labels)


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


async def _async_fetch_device_metadata(
    hass,
    *,
    host: str,
    fallback_name: str,
) -> dict[str, str]:
    metadata = {
        "device_id": host,
        "model": "",
        "friendly_name": fallback_name or host,
    }

    try:
        api = BoseSoundTouchApi(hass, host=host, device_name=fallback_name or host)
        info = await api.async_get_info()
    except Exception:
        return metadata

    metadata["device_id"] = str(info.get("device_id") or host)
    metadata["model"] = str(info.get("type") or "")
    metadata["friendly_name"] = str(info.get("name") or fallback_name or host)
    return metadata


async def _async_discover_bose_devices(
    hass,
    existing_devices: list[config_entries.ConfigSubentry | dict],
) -> list[dict[str, str]]:
    normalized_devices = _normalize_existing_devices(existing_devices)
    existing_ips = {str(device[CONF_BOSE_IP]) for device in normalized_devices if CONF_BOSE_IP in device}

    discovery_infos = await ssdp.async_get_discovery_info_by_st(hass, SSDP_MEDIA_RENDERER_ST)
    discovered: dict[str, dict[str, str]] = {}
    for discovery_info in discovery_infos:
        manufacturer = _ssdp_value(discovery_info, "manufacturer")
        friendly_name = _ssdp_value(discovery_info, "friendlyName", "friendly_name")
        if "bose" not in manufacturer.casefold() and "soundtouch" not in friendly_name.casefold():
            continue

        location = _ssdp_value(discovery_info, "ssdp_location", "location")
        host = urlparse(location).hostname
        if not host or host in existing_ips:
            continue

        try:
            ip_address(host)
        except ValueError:
            continue

        metadata = await _async_fetch_device_metadata(
            hass,
            host=host,
            fallback_name=friendly_name or host,
        )
        device_id = str(metadata["device_id"] or _ssdp_value(discovery_info, "udn") or host)
        device_name = str(metadata["friendly_name"] or friendly_name or host)
        model = str(metadata["model"] or "")
        label_parts = [device_name]
        if model:
            label_parts.append(model)
        label_parts.append(host)
        discovered[device_id] = {
            "device_id": device_id,
            CONF_NAME: device_name,
            CONF_BOSE_IP: host,
            "model": model,
            "label": " | ".join(label_parts),
        }

    return sorted(discovered.values(), key=lambda item: item["label"].casefold())


async def _async_provision_device_presets(hass, device_data: dict) -> None:
    bose_ip = str(device_data.get(CONF_BOSE_IP) or "").strip()
    device_name = str(device_data.get(CONF_NAME) or bose_ip)
    if not bose_ip:
        return
    api = BoseSoundTouchApi(hass, host=bose_ip, device_name=device_name)
    for preset_id in PRESET_IDS:
        url = str(device_data.get(preset_url_key(preset_id)) or "").strip()
        if not url:
            continue
        try:
            await api.async_store_preset(preset_id, url, f"Preset {preset_id}")
            _LOGGER.debug("Stored preset %s on %s during setup", preset_id, bose_ip)
        except Exception as err:
            _LOGGER.warning("Could not store preset %s on %s during setup: %s", preset_id, bose_ip, err)


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
            return self.async_create_entry(title="Bose SoundTouch LocalControl", data=user_input)

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
        self._discovered_devices: list[dict[str, str]] = []
        self._setup_method = MANUAL_SETUP_METHOD
        self._setup_mode = SETUP_MODE_QUICK
        self._selected_device_metadata: dict[str, str] = {}

    @property
    def _is_expert_mode(self) -> bool:
        return self._setup_mode == SETUP_MODE_EXPERT

    def _device_defaults(self, entry: config_entries.ConfigEntry, subentry=None) -> dict:
        base: dict[str, Any] = {
            ATTR_ROUTING_MODE: ROUTING_MODE_NONE,
        }
        if subentry is not None:
            base.update(subentry.data)
            base[ATTR_ROUTING_MODE] = _routing_mode_from_data(subentry.data)
        return base

    @staticmethod
    def _basic_fields(data: dict) -> dict:
        return {
            key: data[key]
            for key in (CONF_NAME, CONF_BOSE_IP)
            if key in data
        }

    @staticmethod
    def _routing_fields(data: dict) -> dict:
        selected = {ATTR_ROUTING_MODE: str(data.get(ATTR_ROUTING_MODE) or ROUTING_MODE_NONE)}
        if CONF_MA_PLAYER in data:
            selected[CONF_MA_PLAYER] = data[CONF_MA_PLAYER]
        return selected

    @staticmethod
    def _advanced_fields(data: dict) -> dict:
        selected: dict = {}
        if CONF_DEFAULT_VOLUME in data:
            selected[CONF_DEFAULT_VOLUME] = data[CONF_DEFAULT_VOLUME]
        return selected

    def _discover_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(ATTR_DISCOVERED_DEVICE): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=device["device_id"],
                                label=device["label"],
                            )
                            for device in self._discovered_devices
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_NAME): selector.TextSelector(),
            }
        )

    def _summary_placeholders(self) -> dict[str, str]:
        metadata = self._selected_device_metadata
        routing_mode = str(self._pending_user_input.get(ATTR_ROUTING_MODE) or ROUTING_MODE_NONE)
        routing_target = str(self._pending_user_input.get(CONF_MA_PLAYER) or "").strip()
        active_presets = _active_presets(self._pending_user_input)

        if routing_mode == ROUTING_MODE_PLAYER and routing_target:
            routing_status = "Preset-Weiterleitung an einen anderen Player"
            routing_target_text = routing_target
        elif routing_mode == ROUTING_MODE_DIRECT:
            routing_status = "Direkte Wiedergabe auf Bose via UPNP"
            routing_target_text = "Bose-Geraet direkt"
        else:
            routing_status = "Nur Bose-Player anlegen"
            routing_target_text = "Kein Routingziel"

        notes: list[str] = []
        if routing_mode not in (ROUTING_MODE_PLAYER, ROUTING_MODE_DIRECT):
            notes.append("Preset-Routing bleibt zunaechst deaktiviert.")
        if active_presets:
            notes.append("Presets werden automatisch auf dem Bose-Geraet gespeichert.")
        else:
            notes.append("Es sind noch keine Presets konfiguriert.")
        if self._is_expert_mode:
            notes.append("Expertenmodus aktiv.")
        else:
            notes.append("Quick-Setup aktiv.")

        return {
            "device_name": str(self._pending_user_input.get(CONF_NAME) or "-"),
            "bose_ip": str(self._pending_user_input.get(CONF_BOSE_IP) or "-"),
            "model": str(metadata.get("model") or "-"),
            "device_id": str(metadata.get("device_id") or "-"),
            "routing_status": routing_status,
            "routing_target": routing_target_text,
            "active_presets": _preset_summary(self._pending_user_input),
            "notes": " ".join(notes),
        }

    async def _async_process_device_input(
        self,
        entry: config_entries.ConfigEntry,
        user_input: dict,
        *,
        current_name: str | None = None,
        current_ip: str | None = None,
    ) -> tuple[dict[str, str], dict, dict[str, str]]:
        errors, normalized_input = _validate_device_input(
            user_input,
            list(entry.subentries.values()),
            current_name=current_name,
            current_ip=current_ip,
        )
        if errors:
            return errors, normalized_input, {}

        if not await _async_validate_device_connection(normalized_input[CONF_BOSE_IP]):
            return {"base": "cannot_connect"}, normalized_input, {}

        metadata = await _async_fetch_device_metadata(
            self.hass,
            host=str(normalized_input[CONF_BOSE_IP]),
            fallback_name=str(normalized_input.get(CONF_NAME) or ""),
        )
        if metadata.get("friendly_name") and not str(normalized_input.get(CONF_NAME) or "").strip():
            normalized_input[CONF_NAME] = metadata["friendly_name"]

        return {}, normalized_input, metadata

    def _show_user_start(self, *, errors: dict[str, str] | None = None) -> FlowResult:
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                device_start_schema(),
                {
                    ATTR_SETUP_METHOD: self._setup_method,
                    ATTR_SETUP_MODE: self._setup_mode,
                },
            ),
            errors=errors or {},
        )

    def _show_manual(self, *, errors: dict[str, str] | None = None) -> FlowResult:
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(
                device_basic_schema(),
                self._basic_fields(self._pending_user_input),
            ),
            errors=errors or {},
        )

    def _show_discover(self, *, errors: dict[str, str] | None = None) -> FlowResult:
        return self.async_show_form(
            step_id="discover",
            data_schema=self.add_suggested_values_to_schema(
                self._discover_schema(),
                {
                    ATTR_DISCOVERED_DEVICE: str(self._pending_user_input.get(ATTR_DISCOVERED_DEVICE) or ""),
                    CONF_NAME: str(self._pending_user_input.get(CONF_NAME) or ""),
                },
            ),
            errors=errors or {},
        )

    def _show_routing(self, *, step_id: str = "routing", errors: dict[str, str] | None = None) -> FlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                routing_schema(),
                self._routing_fields(self._pending_user_input),
            ),
            errors=errors or {},
        )

    def _show_presets(self, *, step_id: str = "presets", errors: dict[str, str] | None = None) -> FlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                preset_schema(expert=self._is_expert_mode),
                _preset_fields(self._pending_user_input, expert=self._is_expert_mode),
            ),
            errors=errors or {},
        )

    def _show_advanced(self, *, step_id: str = "advanced", errors: dict[str, str] | None = None) -> FlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                advanced_schema(),
                self._advanced_fields(self._pending_user_input),
            ),
            errors=errors or {},
        )

    def _show_summary(self, *, step_id: str) -> FlowResult:
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({}),
            errors={},
            description_placeholders=self._summary_placeholders(),
        )

    def _route_validation_errors(
        self,
        *,
        errors: dict[str, str],
        normalized_input: dict,
        manual_step_id: str,
        routing_step_id: str,
        presets_step_id: str,
        advanced_step_id: str,
    ) -> FlowResult:
        self._pending_user_input = normalized_input

        device_errors = {key: value for key, value in errors.items() if key in DEVICE_KEYS or key == "base"}
        routing_errors = {key: value for key, value in errors.items() if key in ROUTING_KEYS or key == "base"}
        preset_keys = {
            key
            for preset in PRESET_IDS
            for key in (
                preset_url_key(preset),
                preset_volume_key(preset),
            )
        }
        preset_errors = {key: value for key, value in errors.items() if key in preset_keys or key == "base"}
        advanced_errors = {key: value for key, value in errors.items() if key in ADVANCED_KEYS or key == "base"}

        if device_errors:
            if manual_step_id == "reconfigure_device":
                return self.async_show_form(
                    step_id="reconfigure_device",
                    data_schema=self.add_suggested_values_to_schema(
                        device_basic_schema(),
                        self._basic_fields(self._pending_user_input),
                    ),
                    errors=device_errors,
                )
            if self._setup_method == DISCOVERY_SETUP_METHOD:
                return self._show_discover(errors=device_errors)
            return self._show_manual(errors=device_errors)
        if routing_errors:
            return self._show_routing(step_id=routing_step_id, errors=routing_errors)
        if preset_errors:
            return self._show_presets(step_id=presets_step_id, errors=preset_errors)
        if advanced_errors and self._is_expert_mode:
            return self._show_advanced(step_id=advanced_step_id, errors=advanced_errors)

        if self._setup_method == DISCOVERY_SETUP_METHOD:
            return self._show_discover(errors={"base": "discovery_failed"})
        return self._show_manual(errors={"base": "cannot_connect"})

    async def async_step_user(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._setup_method = str(user_input[ATTR_SETUP_METHOD])
            self._setup_mode = str(user_input[ATTR_SETUP_MODE])
            self._pending_user_input = {
                ATTR_SETUP_METHOD: self._setup_method,
                ATTR_SETUP_MODE: self._setup_mode,
            }
            self._selected_device_metadata = {}
            if self._setup_method == DISCOVERY_SETUP_METHOD:
                return await self.async_step_discover()
            return await self.async_step_manual()

        self._pending_user_input = {}
        self._selected_device_metadata = {}
        return self._show_user_start()

    async def async_step_discover(self, user_input=None) -> FlowResult:
        entry = self._get_entry()
        self._setup_method = DISCOVERY_SETUP_METHOD

        if user_input is not None:
            selected = next(
                (
                    device
                    for device in self._discovered_devices
                    if device["device_id"] == user_input[ATTR_DISCOVERED_DEVICE]
                ),
                None,
            )
            if selected is None:
                return self._show_discover(errors={"base": "discovery_failed"})

            custom_name = str(user_input.get(CONF_NAME) or "").strip()
            self._pending_user_input.update(
                {
                    ATTR_DISCOVERED_DEVICE: selected["device_id"],
                    CONF_NAME: custom_name or selected[CONF_NAME],
                    CONF_BOSE_IP: selected[CONF_BOSE_IP],
                }
            )
            self._selected_device_metadata = {
                "device_id": str(selected.get("device_id") or ""),
                "model": str(selected.get("model") or ""),
                "friendly_name": str(selected.get(CONF_NAME) or ""),
            }
            return await self.async_step_routing()

        try:
            self._discovered_devices = await _async_discover_bose_devices(
                self.hass,
                list(entry.subentries.values()),
            )
        except Exception:
            _LOGGER.exception("Bose SSDP discovery failed")
            return self._show_user_start(errors={"base": "discovery_failed"})

        if not self._discovered_devices:
            return self._show_user_start(errors={"base": "no_devices_discovered"})

        return self._show_discover()

    async def async_step_manual(self, user_input=None) -> FlowResult:
        self._setup_method = MANUAL_SETUP_METHOD
        if user_input is not None:
            self._pending_user_input.update(user_input)
            return await self.async_step_routing()

        return self._show_manual()

    async def async_step_routing(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._pending_user_input.update(user_input)
            if str(user_input.get(ATTR_ROUTING_MODE)) == ROUTING_MODE_PLAYER:
                return await self.async_step_routing_player()
            self._pending_user_input.pop(CONF_MA_PLAYER, None)
            return await self.async_step_presets()

        if ATTR_ROUTING_MODE not in self._pending_user_input:
            self._pending_user_input[ATTR_ROUTING_MODE] = _routing_mode_from_data(self._pending_user_input)
        return self._show_routing()

    async def async_step_routing_player(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not str(user_input.get(CONF_MA_PLAYER) or "").strip():
                errors[CONF_MA_PLAYER] = "target_player_required"
            else:
                self._pending_user_input.update(user_input)
                return await self.async_step_presets()
        return self.async_show_form(
            step_id="routing_player",
            data_schema=self.add_suggested_values_to_schema(
                routing_player_schema(),
                {CONF_MA_PLAYER: self._pending_user_input.get(CONF_MA_PLAYER)},
            ),
            errors=errors,
        )

    async def async_step_presets(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._pending_user_input.update(user_input)
            if self._is_expert_mode:
                return await self.async_step_advanced()
            return await self.async_step_summary()

        return self._show_presets()

    async def async_step_advanced(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._pending_user_input.update(user_input)
            return await self.async_step_summary()

        return self._show_advanced()

    async def async_step_summary(self, user_input=None) -> FlowResult:
        entry = self._get_entry()

        errors, normalized_input, metadata = await self._async_process_device_input(
            entry,
            self._pending_user_input,
        )
        if errors:
            return self._route_validation_errors(
                errors=errors,
                normalized_input=normalized_input,
                manual_step_id="manual",
                routing_step_id="routing",
                presets_step_id="presets",
                advanced_step_id="advanced",
            )

        self._pending_user_input = normalized_input
        if metadata:
            self._selected_device_metadata = metadata

        if user_input is not None:
            final_data = _finalize_device_data(self._pending_user_input)
            await _async_provision_device_presets(self.hass, final_data)
            return self.async_create_entry(
                title=_device_title(final_data),
                data=final_data,
            )

        return self._show_summary(step_id="summary")

    async def async_step_reconfigure(self, user_input=None) -> FlowResult:
        subentry = self._get_reconfigure_subentry()
        self._reconfigure_subentry = subentry

        if user_input is not None:
            self._setup_mode = str(user_input[ATTR_SETUP_MODE])
            self._pending_user_input = self._device_defaults(self._get_entry(), subentry)
            self._pending_user_input[ATTR_SETUP_MODE] = self._setup_mode
            self._selected_device_metadata = await _async_fetch_device_metadata(
                self.hass,
                host=str(self._pending_user_input[CONF_BOSE_IP]),
                fallback_name=str(self._pending_user_input[CONF_NAME]),
            )
            return await self.async_step_reconfigure_device()

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                reconfigure_start_schema(),
                {ATTR_SETUP_MODE: self._setup_mode},
            ),
            errors={},
        )

    async def async_step_reconfigure_device(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._pending_user_input.update(user_input)
            return await self.async_step_reconfigure_routing()

        return self.async_show_form(
            step_id="reconfigure_device",
            data_schema=self.add_suggested_values_to_schema(
                device_basic_schema(),
                self._basic_fields(self._pending_user_input),
            ),
            errors={},
        )

    async def async_step_reconfigure_routing(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._pending_user_input.update(user_input)
            if str(user_input.get(ATTR_ROUTING_MODE)) == ROUTING_MODE_PLAYER:
                return await self.async_step_reconfigure_routing_player()
            self._pending_user_input.pop(CONF_MA_PLAYER, None)
            return await self.async_step_reconfigure_presets()

        return self._show_routing(step_id="reconfigure_routing")

    async def async_step_reconfigure_routing_player(self, user_input=None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not str(user_input.get(CONF_MA_PLAYER) or "").strip():
                errors[CONF_MA_PLAYER] = "target_player_required"
            else:
                self._pending_user_input.update(user_input)
                return await self.async_step_reconfigure_presets()
        return self.async_show_form(
            step_id="reconfigure_routing_player",
            data_schema=self.add_suggested_values_to_schema(
                routing_player_schema(),
                {CONF_MA_PLAYER: self._pending_user_input.get(CONF_MA_PLAYER)},
            ),
            errors=errors,
        )

    async def async_step_reconfigure_presets(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._pending_user_input.update(user_input)
            if self._is_expert_mode:
                return await self.async_step_reconfigure_advanced()
            return await self.async_step_reconfigure_summary()

        return self._show_presets(step_id="reconfigure_presets")

    async def async_step_reconfigure_advanced(self, user_input=None) -> FlowResult:
        if user_input is not None:
            self._pending_user_input.update(user_input)
            return await self.async_step_reconfigure_summary()

        return self._show_advanced(step_id="reconfigure_advanced")

    async def async_step_reconfigure_summary(self, user_input=None) -> FlowResult:
        entry = self._get_entry()
        subentry = self._reconfigure_subentry or self._get_reconfigure_subentry()

        errors, normalized_input, metadata = await self._async_process_device_input(
            entry,
            self._pending_user_input,
            current_name=subentry.data[CONF_NAME],
            current_ip=subentry.data[CONF_BOSE_IP],
        )
        if errors:
            return self._route_validation_errors(
                errors=errors,
                normalized_input=normalized_input,
                manual_step_id="reconfigure_device",
                routing_step_id="reconfigure_routing",
                presets_step_id="reconfigure_presets",
                advanced_step_id="reconfigure_advanced",
            )

        self._pending_user_input = normalized_input
        if metadata:
            self._selected_device_metadata = metadata

        if user_input is not None:
            final_data = _finalize_device_data(self._pending_user_input)
            await _async_provision_device_presets(self.hass, final_data)
            self.hass.config_entries.async_update_subentry(
                entry,
                subentry,
                data=final_data,
                title=_device_title(final_data),
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigure_successful")

        return self._show_summary(step_id="reconfigure_summary")
