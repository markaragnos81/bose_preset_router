from __future__ import annotations

import asyncio
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .coordinator import BoseSoundTouchCoordinator
from .const import (
    ATTR_DEVICE,
    ATTR_MASTER,
    ATTR_MEMBERS,
    ATTR_PRESET,
    DATA_COORDINATORS,
    DATA_MANAGER,
    DOMAIN,
    PLATFORMS,
    SERVICE_ADD_ZONE_MEMBERS,
    SERVICE_CLEAR_ZONE,
    SERVICE_CREATE_ZONE,
    SERVICE_PLAY_PRESET,
    SERVICE_REMOVE_ZONE_MEMBERS,
    SERVICE_TRIGGER_PRESET,
)
from .router import BosePresetRouterManager

_LOGGER = logging.getLogger(__name__)
DATA_LOADED_PLATFORMS = "loaded_platforms"

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE): str,
        vol.Required(ATTR_PRESET): vol.All(vol.Coerce(int), vol.Range(min=1, max=6)),
    }
)
ZONE_CREATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MASTER): str,
        vol.Required(ATTR_MEMBERS): vol.All([str], vol.Length(min=1)),
    }
)
ZONE_UPDATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MASTER): str,
        vol.Required(ATTR_MEMBERS): vol.All([str], vol.Length(min=1)),
    }
)
ZONE_CLEAR_SCHEMA = vol.Schema({vol.Required(ATTR_MASTER): str})


def _entry_data(hass: HomeAssistant, entry_id: str | None = None) -> dict:
    domain_data = hass.data.get(DOMAIN, {})
    if entry_id is not None:
        entry_data = domain_data.get(entry_id)
        if entry_data is None:
            raise HomeAssistantError(f"Config entry {entry_id} is not loaded")
        return entry_data

    first_entry_id = next(iter(domain_data), None)
    if first_entry_id is None:
        raise HomeAssistantError("No Bose Preset Router config entry loaded")
    return domain_data[first_entry_id]


def _coordinators_by_name(hass: HomeAssistant) -> dict[str, BoseSoundTouchCoordinator]:
    entry_data = _entry_data(hass)
    coordinators: dict[str, BoseSoundTouchCoordinator] = entry_data[DATA_COORDINATORS]
    return {coordinator.device_name.casefold(): coordinator for coordinator in coordinators.values()}


def _resolve_coordinator(hass: HomeAssistant, device_name: str) -> BoseSoundTouchCoordinator:
    coordinator = _coordinators_by_name(hass).get(device_name.casefold())
    if coordinator is None:
        raise HomeAssistantError(f"Unknown Bose device: {device_name}")
    return coordinator


def _coordinator_zone_member(coordinator: BoseSoundTouchCoordinator) -> dict[str, str]:
    return {
        "device_id": coordinator.device_id,
        "ip_address": coordinator.bose_ip,
    }


def _resolve_member_coordinators(
    hass: HomeAssistant,
    *,
    master: BoseSoundTouchCoordinator,
    member_names: list[str],
) -> list[BoseSoundTouchCoordinator]:
    members: list[BoseSoundTouchCoordinator] = []
    seen: set[str] = set()
    for member_name in member_names:
        coordinator = _resolve_coordinator(hass, member_name)
        if coordinator.device_id == master.device_id:
            raise HomeAssistantError("The master speaker cannot also be listed as a member")
        if coordinator.device_id in seen:
            continue
        seen.add(coordinator.device_id)
        members.append(coordinator)
    if not members:
        raise HomeAssistantError("At least one member speaker is required")
    return members


async def _async_refresh_zone_devices(
    touched: list[BoseSoundTouchCoordinator],
) -> None:
    unique: dict[str, BoseSoundTouchCoordinator] = {
        coordinator.device_id: coordinator for coordinator in touched
    }
    await asyncio.gather(*(coordinator.async_request_refresh() for coordinator in unique.values()))


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})

    async def handle_trigger_preset(call: ServiceCall) -> None:
        manager: BosePresetRouterManager = _entry_data(hass)[DATA_MANAGER]
        await manager.async_handle_preset(
            device_name=call.data[ATTR_DEVICE],
            preset=call.data[ATTR_PRESET],
            reason="manual_service",
        )

    async def handle_create_zone(call: ServiceCall) -> None:
        master = _resolve_coordinator(hass, call.data[ATTR_MASTER])
        members = _resolve_member_coordinators(
            hass,
            master=master,
            member_names=call.data[ATTR_MEMBERS],
        )
        zone_members = [_coordinator_zone_member(master), *(_coordinator_zone_member(member) for member in members)]
        await master.api.async_set_zone(
            master_device_id=master.device_id,
            members=zone_members,
        )
        await _async_refresh_zone_devices([master, *members])

    async def handle_add_zone_members(call: ServiceCall) -> None:
        master = _resolve_coordinator(hass, call.data[ATTR_MASTER])
        members = _resolve_member_coordinators(
            hass,
            master=master,
            member_names=call.data[ATTR_MEMBERS],
        )
        await master.api.async_add_zone_slaves(
            master_device_id=master.device_id,
            members=[_coordinator_zone_member(member) for member in members],
        )
        await _async_refresh_zone_devices([master, *members])

    async def handle_remove_zone_members(call: ServiceCall) -> None:
        master = _resolve_coordinator(hass, call.data[ATTR_MASTER])
        members = _resolve_member_coordinators(
            hass,
            master=master,
            member_names=call.data[ATTR_MEMBERS],
        )
        await master.api.async_remove_zone_slaves(
            master_device_id=master.device_id,
            members=[_coordinator_zone_member(member) for member in members],
        )
        await _async_refresh_zone_devices([master, *members])

    async def handle_clear_zone(call: ServiceCall) -> None:
        master = _resolve_coordinator(hass, call.data[ATTR_MASTER])
        current_zone_members = list(master.data.get("zone", {}).get("members", []) if master.data else [])
        removable_members = [
            member
            for member in current_zone_members
            if str(member.get("device_id") or "") != master.device_id
        ]
        if not removable_members:
            await master.async_request_refresh()
            return

        await master.api.async_remove_zone_slaves(
            master_device_id=master.device_id,
            members=[
                {
                    "device_id": str(member.get("device_id") or ""),
                    "ip_address": str(member.get("ip_address") or ""),
                }
                for member in removable_members
            ],
        )

        touched = [master]
        coordinators = _coordinators_by_name(hass)
        for member in removable_members:
            device_id = str(member.get("device_id") or "")
            match = next(
                (coordinator for coordinator in coordinators.values() if coordinator.device_id == device_id),
                None,
            )
            if match is not None:
                touched.append(match)
        await _async_refresh_zone_devices(touched)

    hass.services.async_register(
        DOMAIN,
        SERVICE_TRIGGER_PRESET,
        handle_trigger_preset,
        schema=SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PLAY_PRESET,
        handle_trigger_preset,
        schema=SERVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_ZONE,
        handle_create_zone,
        schema=ZONE_CREATE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_ZONE_MEMBERS,
        handle_add_zone_members,
        schema=ZONE_UPDATE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_ZONE_MEMBERS,
        handle_remove_zone_members,
        schema=ZONE_UPDATE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_ZONE,
        handle_clear_zone,
        schema=ZONE_CLEAR_SCHEMA,
    )
    return True


def _device_matches_coordinator(device_entry: dr.DeviceEntry, coordinator: BoseSoundTouchCoordinator) -> bool:
    configuration_url = str(device_entry.configuration_url or "")
    if configuration_url == f"http://{coordinator.bose_ip}:8090/info":
        return True
    return str(device_entry.name or "").casefold() == coordinator.device_name.casefold()


@callback
def _async_cleanup_stale_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinators: dict[str, BoseSoundTouchCoordinator],
) -> None:
    device_registry = dr.async_get(hass)
    current_identifiers = {
        (entry.domain, coordinator.registry_identifier) for coordinator in coordinators.values()
    }
    devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)

    for device_entry in devices:
        domain_identifiers = {
            identifier for identifier in device_entry.identifiers if identifier[0] == entry.domain
        }
        if domain_identifiers & current_identifiers:
            continue

        match = next(
            (
                coordinator
                for coordinator in coordinators.values()
                if _device_matches_coordinator(device_entry, coordinator)
            ),
            None,
        )
        if match is None:
            continue

        _LOGGER.info(
            "Detaching stale Bose device registry entry %s (%s) in favor of subentry %s",
            device_entry.name or "-",
            device_entry.id,
            match.subentry_id,
        )
        device_registry.async_update_device(
            device_entry.id,
            remove_config_entry_id=entry.entry_id,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    domain_data = hass.data.setdefault(DOMAIN, {})
    manager = BosePresetRouterManager(hass, entry)
    coordinators = {
        subentry_id: BoseSoundTouchCoordinator(
            hass,
            entry,
            subentry_id=subentry_id,
            device=subentry.data,
        )
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == "device"
    }

    for coordinator in coordinators.values():
        await coordinator.async_start()

    device_registry = dr.async_get(hass)
    for coordinator in coordinators.values():
        info = coordinator.data.get("info", {}) if coordinator.data else {}
        model = str(info.get("type") or "") or None
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=coordinator.subentry_id,
            identifiers={(entry.domain, coordinator.registry_identifier)},
            configuration_url=f"http://{coordinator.bose_ip}:8090/info",
            manufacturer="Bose",
            model=model,
            name=coordinator.device_name,
        )

    _async_cleanup_stale_devices(hass, entry, coordinators)

    manager.async_start()

    domain_data[entry.entry_id] = {
        DATA_MANAGER: manager,
        DATA_COORDINATORS: coordinators,
        DATA_LOADED_PLATFORMS: False,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    domain_data[entry.entry_id][DATA_LOADED_PLATFORMS] = True
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        return True

    manager: BosePresetRouterManager = entry_data[DATA_MANAGER]
    coordinators: dict[str, BoseSoundTouchCoordinator] = entry_data[DATA_COORDINATORS]
    unload_ok = True
    if entry_data.get(DATA_LOADED_PLATFORMS):
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    await asyncio.gather(
        manager.async_stop(),
        *(coordinator.async_stop() for coordinator in coordinators.values()),
    )
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok



async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    existing_subentry_ids = {se.subentry_id for se in config_entry.subentries.values()}
    domain_identifiers = {
        identifier[1] for identifier in device_entry.identifiers if identifier[0] == config_entry.domain
    }
    active_subentry_identifiers = {f"subentry:{sid}" for sid in existing_subentry_ids}
    return not domain_identifiers.intersection(active_subentry_identifiers)
