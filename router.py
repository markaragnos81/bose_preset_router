from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import unquote, urlsplit

import websockets
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .api import BoseSoundTouchApi
from .const import (
    CONF_BOSE_IP,
    CONF_DEBUG_LOGGING,
    CONF_DEBOUNCE_SECONDS,
    CONF_DEFAULT_VOLUME,
    CONF_MA_PLAYER,
    CONF_NAME,
    CONF_NOTIFY_ON_PRESS,
    CONF_PLAYBACK_VERIFY_ATTEMPTS,
    CONF_PLAYBACK_VERIFY_DELAY_SECONDS,
    CONF_ROUTING_MODE,
    CONF_STRICT_BOSE_CONFIRMATION,
    CONF_TOLERANT_BOSE_CONFIRMATION,
    DATA_COORDINATORS,
    DOMAIN,
    DEFAULT_PLAYBACK_VERIFY_ATTEMPTS,
    DEFAULT_PLAYBACK_VERIFY_DELAY_SECONDS,
    DEFAULT_STRICT_BOSE_CONFIRMATION,
    DEFAULT_TOLERANT_BOSE_CONFIRMATION,
    PRESET_IDS,
    ROUTING_MODE_AIRPLAY,
    ROUTING_MODE_DIRECT,
    ROUTING_MODE_NONE,
    WS_PORT,
    default_preset_url_key,
    preset_enabled_key,
    preset_url_key,
    preset_volume_key,
)

_LOGGER = logging.getLogger(__name__)

PRESET_RE = re.compile(r'<preset id="(\d+)">')
ITEM_RE = re.compile(r"<itemName>(.*?)</itemName>")
PLAYING_STATES = {"playing", "buffering"}
PASSIVE_BOSE_HANDOFF_RECHECK_REASONS = {
    "airplay_without_metadata",
    "airplay_metadata_unchanged",
    "bose_now_playing_unavailable",
    "upnp_without_metadata",
    "upnp_metadata_unchanged",
}


class BosePresetRouterManager:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._tasks: list[asyncio.Task] = []
        self._stop_event = asyncio.Event()
        self._last_trigger: dict[str, float] = {}

    def _option(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    @property
    def notify_on_press(self) -> bool:
        return bool(self._option(CONF_NOTIFY_ON_PRESS, False))

    @property
    def debug_logging(self) -> bool:
        return bool(self._option(CONF_DEBUG_LOGGING, False))

    @property
    def debounce_seconds(self) -> float:
        return float(self._option(CONF_DEBOUNCE_SECONDS, 2.0))

    @property
    def playback_verify_attempts(self) -> int:
        return int(self._option(CONF_PLAYBACK_VERIFY_ATTEMPTS, DEFAULT_PLAYBACK_VERIFY_ATTEMPTS))

    @property
    def playback_verify_delay_seconds(self) -> float:
        return float(self._option(CONF_PLAYBACK_VERIFY_DELAY_SECONDS, DEFAULT_PLAYBACK_VERIFY_DELAY_SECONDS))

    @property
    def strict_bose_confirmation(self) -> bool:
        return bool(self._option(CONF_STRICT_BOSE_CONFIRMATION, DEFAULT_STRICT_BOSE_CONFIRMATION))

    @property
    def tolerant_bose_confirmation(self) -> bool:
        return bool(self._option(CONF_TOLERANT_BOSE_CONFIRMATION, DEFAULT_TOLERANT_BOSE_CONFIRMATION))

    @property
    def devices(self) -> list[dict[str, Any]]:
        return [
            sub.data
            for sub in self.entry.subentries.values()
            if sub.subentry_type == "device"
        ]

    def _preset_config(self, device: dict[str, Any], preset: int) -> dict[str, Any]:
        stream_url = str(device.get(preset_url_key(preset)) or "").strip() or None
        if not stream_url:
            stream_url = str(self.entry.data.get(default_preset_url_key(preset)) or "").strip() or None
        enabled_key = preset_enabled_key(preset)
        if enabled_key in device:
            enabled = bool(device[enabled_key])
        else:
            enabled = bool(stream_url)
        return {
            "enabled": enabled,
            "stream_url": stream_url,
            "volume": device.get(
                preset_volume_key(preset),
                device.get(CONF_DEFAULT_VOLUME),
            ),
        }

    def _resolve_device(
        self,
        *,
        device_name: str,
        bose_ip: str | None = None,
    ) -> dict[str, Any] | None:
        if bose_ip:
            device = next(
                (d for d in self.devices if d.get(CONF_BOSE_IP) == bose_ip),
                None,
            )
            if device is not None:
                return device

            _LOGGER.warning(
                "No configured device matches Bose IP %s for device name %s",
                bose_ip,
                device_name,
            )

        device = next((d for d in self.devices if d[CONF_NAME] == device_name), None)
        if device is not None:
            return device

        normalized_name = device_name.casefold()
        device = next(
            (d for d in self.devices if str(d.get(CONF_NAME, "")).casefold() == normalized_name),
            None,
        )
        if device is not None:
            return device

        # Partial match: search term is a substring of the configured name (case-insensitive).
        # Allows short names like "Büro" to match "Bose Soundtouch 20 - Büro".
        matches = [d for d in self.devices if normalized_name in str(d.get(CONF_NAME, "")).casefold()]
        if len(matches) == 1:
            _LOGGER.debug(
                "Resolved device %r via partial name match → %r",
                device_name,
                matches[0].get(CONF_NAME),
            )
            return matches[0]
        if len(matches) > 1:
            _LOGGER.warning(
                "Ambiguous partial device name %r matches %s — skipping",
                device_name,
                [d.get(CONF_NAME) for d in matches],
            )
        return None

    def _get_coordinator(self, bose_ip: str):
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        coordinators = entry_data.get(DATA_COORDINATORS, {})
        return next(
            (coordinator for coordinator in coordinators.values() if coordinator.bose_ip == bose_ip),
            None,
        )

    def _soundtouch_api(self, *, bose_ip: str, device_name: str) -> BoseSoundTouchApi:
        coordinator = self._get_coordinator(bose_ip)
        return coordinator.api if coordinator is not None else BoseSoundTouchApi(self.hass, host=bose_ip, device_name=device_name)

    def _log_stage(
        self,
        level: int,
        stage: str,
        *,
        device_name: str,
        preset: int,
        ma_player: str,
        detail: str,
        attempt: int | None = None,
        total_attempts: int | None = None,
    ) -> None:
        attempt_info = ""
        if attempt is not None and total_attempts is not None:
            attempt_info = f" attempt={attempt}/{total_attempts}"

        _LOGGER.log(
            level,
            "Preset pipeline stage=%s device=%s preset=%s player=%s%s detail=%s",
            stage,
            device_name,
            preset,
            ma_player,
            attempt_info,
            detail,
        )

    @staticmethod
    def _normalize_stream_identifier(value: str | None) -> str:
        if not value:
            return ""

        parsed = urlsplit(unquote(str(value).strip()))
        path = parsed.path.rstrip("/")
        return parsed._replace(path=path, fragment="", query="").geturl().casefold()

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return str(value or "").strip().casefold()

    def _playback_matches_target(
        self,
        state,
        stream_url: str,
        item_name: str | None,
    ) -> tuple[bool, str]:
        if state is None:
            return False, "state_unavailable"

        attrs = state.attributes
        expected_stream = self._normalize_stream_identifier(stream_url)
        current_stream = self._normalize_stream_identifier(attrs.get("media_content_id"))
        if expected_stream and current_stream == expected_stream:
            return True, "media_content_id"

        expected_name = self._normalize_text(item_name)
        if expected_name:
            for attr_name in ("media_title", "media_channel", "media_album_name"):
                if self._normalize_text(attrs.get(attr_name)) == expected_name:
                    return True, attr_name

        return False, "no_match"

    def _playback_started_since_request(self, previous_state, current_state) -> bool:
        if current_state is None or current_state.state not in PLAYING_STATES:
            return False

        if previous_state is None:
            return True

        previous_attrs = previous_state.attributes
        current_attrs = current_state.attributes
        return (
            previous_state.state != current_state.state
            or previous_attrs.get("media_content_id") != current_attrs.get("media_content_id")
            or previous_attrs.get("media_title") != current_attrs.get("media_title")
            or previous_attrs.get("media_channel") != current_attrs.get("media_channel")
        )

    async def _async_send_play_media(
        self,
        *,
        device_name: str,
        preset: int,
        ma_player: str,
        stream_url: str,
        target_volume: Any,
        item_name: str | None,
    ) -> None:
        try:
            await self.hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": ma_player,
                    "media_content_id": stream_url,
                    "media_content_type": "music",
                },
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.error(
                "Playback failed for device=%s preset=%s player=%s volume=%s url=%s item=%s: %s",
                device_name,
                preset,
                ma_player,
                target_volume if target_volume is not None else "unchanged",
                stream_url,
                item_name or "-",
                err,
            )
            raise

    async def _async_verify_playback(
        self,
        *,
        ma_player: str,
        stream_url: str,
        item_name: str | None,
        previous_state,
    ) -> tuple[bool, str]:
        await asyncio.sleep(self.playback_verify_delay_seconds)

        current_state = self.hass.states.get(ma_player)
        matches_target, match_reason = self._playback_matches_target(
            current_state,
            stream_url,
            item_name,
        )
        if matches_target:
            return True, match_reason

        if self._playback_started_since_request(previous_state, current_state):
            return True, "state_transition"

        return False, match_reason

    async def _async_fetch_bose_now_playing(self, bose_ip: str) -> dict[str, str] | None:
        try:
            device = next(
                (candidate for candidate in self.devices if candidate.get(CONF_BOSE_IP) == bose_ip),
                None,
            )
            api = self._soundtouch_api(
                bose_ip=bose_ip,
                device_name=str(device.get(CONF_NAME, bose_ip)) if device else bose_ip,
            )
            state = await api.async_get_now_playing()
        except Exception as err:
            _LOGGER.warning("Failed to fetch Bose now_playing from %s: %s", bose_ip, err)
            return None

        return {
            "source": str(state.get("source", "")),
            "source_account": str(state.get("source_account", "")),
            "item_name": str(state.get("item_name", "")),
            "track": str(state.get("track", "")),
            "artist": str(state.get("artist", "")),
            "album": str(state.get("album", "")),
            "station_name": str(state.get("station_name", "")),
            "location": str(state.get("location", "")),
            "source_type": str(state.get("source_type", "")),
        }

    async def _async_confirm_bose_preset(
        self,
        *,
        bose_ip: str,
        device_name: str,
        preset: int,
        item_name: str | None,
    ) -> tuple[bool, str]:
        state = await self._async_fetch_bose_now_playing(bose_ip)
        if state is None:
            return False, "now_playing_unavailable"

        expected_name = self._normalize_text(item_name)
        candidate_values = (
            state.get("item_name"),
            state.get("track"),
            state.get("station_name"),
        )
        if expected_name and any(
            self._normalize_text(value) == expected_name for value in candidate_values
        ):
            return True, "item_name"

        location = state.get("location", "")
        if location.endswith(f"/presets/{preset}") or location.endswith(f"preset/{preset}"):
            return True, "location"

        if self.tolerant_bose_confirmation:
            if f"/presets/{preset}" in location or f"preset/{preset}" in location:
                return True, "location_contains_preset"

            if self._bose_now_playing_has_metadata(state):
                return True, "tolerant_metadata"

        if self.debug_logging:
            _LOGGER.debug(
                "Bose now_playing did not confirm preset for device=%s preset=%s source=%s location=%s item=%s track=%s station=%s",
                device_name,
                preset,
                state.get("source", "-"),
                location or "-",
                state.get("item_name", "-"),
                state.get("track", "-"),
                state.get("station_name", "-"),
            )
        return False, "no_bose_match"

    def _bose_now_playing_has_metadata(self, state: dict[str, str] | None) -> bool:
        if not state:
            return False

        return any(
            self._normalize_text(state.get(field))
            for field in ("item_name", "track", "artist", "album", "station_name")
        )

    def _should_passively_recheck_bose_handoff(self, reason: str) -> bool:
        return reason in PASSIVE_BOSE_HANDOFF_RECHECK_REASONS

    def _bose_now_playing_transitioned(
        self,
        previous_state: dict[str, str] | None,
        current_state: dict[str, str],
    ) -> bool:
        if previous_state is None:
            return True

        tracked_fields = (
            "source",
            "source_account",
            "item_name",
            "track",
            "artist",
            "album",
            "station_name",
            "location",
            "source_type",
        )
        return any(
            self._normalize_text(previous_state.get(field))
            != self._normalize_text(current_state.get(field))
            for field in tracked_fields
        )

    async def _async_verify_bose_stream_handoff(
        self,
        *,
        bose_ip: str,
        previous_state: dict[str, str] | None,
    ) -> tuple[bool, str]:
        current_state = await self._async_fetch_bose_now_playing(bose_ip)
        if current_state is None:
            return False, "bose_now_playing_unavailable"

        current_source = self._normalize_text(current_state.get("source"))
        metadata_present = self._bose_now_playing_has_metadata(current_state)

        if current_source not in {"airplay", "upnp"}:
            return False, f"source={current_state.get('source', '-') or '-'}"

        if not metadata_present:
            return False, f"{current_source}_without_metadata"

        if previous_state is None:
            return True, f"{current_source}_metadata"

        if self._bose_now_playing_transitioned(previous_state, current_state):
            return True, f"{current_source}_metadata_changed"

        return False, f"{current_source}_metadata_unchanged"

    @staticmethod
    def _parse_now_playing_update(message: str) -> dict[str, Any] | None:
        """Parse a nowPlayingUpdated WS message into a now_playing dict."""
        try:
            root = ET.fromstring(message)
            np_el = root.find(".//nowPlayingUpdated/nowPlaying")
            if np_el is None:
                return None
            content_item = np_el.find("ContentItem")
            return {
                "source": np_el.get("source", ""),
                "source_account": np_el.get("sourceAccount", ""),
                "device_id": np_el.get("deviceID", ""),
                "item_name": np_el.findtext("ContentItem/itemName", default=""),
                "track": np_el.findtext("track", default=""),
                "artist": np_el.findtext("artist", default=""),
                "album": np_el.findtext("album", default=""),
                "station_name": np_el.findtext("stationName", default=""),
                "play_status": np_el.findtext("playStatus", default=""),
                "description": np_el.findtext("description", default=""),
                "image": np_el.findtext("art", default=""),
                "location": content_item.get("location", "") if content_item is not None else "",
                "source_type": content_item.get("source", "") if content_item is not None else "",
            }
        except ET.ParseError:
            return None

    def async_start(self) -> None:
        self._stop_event.clear()
        self._tasks.clear()

        for device in self.devices:
            name = device[CONF_NAME]
            task = self.entry.async_create_background_task(
                self.hass,
                self._device_loop(device),
                f"{DOMAIN}_{name}_device_loop",
            )
            self._tasks.append(task)

    async def async_stop(self) -> None:
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def async_resume_airplay_devices(self) -> None:
        """Replay whatever was last playing via AirPlay on each device, if anything.

        Called once at startup after coordinators/websocket loops are live. Only
        applies to AIRPLAY-mode devices — UPnP-mode speakers keep playing across a
        restart on their own and don't need this.
        """
        for device in self.devices:
            if str(device.get(CONF_ROUTING_MODE) or "") != ROUTING_MODE_AIRPLAY:
                continue
            bose_ip = device[CONF_BOSE_IP]
            coordinator = self._get_coordinator(bose_ip)
            if coordinator is None:
                continue
            preset = coordinator.airplay_resume_store.get(bose_ip)
            if preset is None:
                continue
            _LOGGER.info(
                "Resuming AirPlay preset %s for device=%s after restart", preset, device[CONF_NAME]
            )
            await self.async_handle_preset(device[CONF_NAME], preset, reason="resume", bose_ip=bose_ip)
        self._tasks.clear()

    async def _device_loop(self, device: dict[str, Any]) -> None:
        name = device[CONF_NAME]
        bose_ip = device[CONF_BOSE_IP]
        url = f"ws://{bose_ip}:{WS_PORT}/"

        while not self._stop_event.is_set():
            try:
                _LOGGER.info("Connecting to Bose websocket for %s (%s)", name, bose_ip)
                async with websockets.connect(url, subprotocols=["gabbo"]) as ws:
                    _LOGGER.info("Connected to Bose websocket for %s", name)

                    async for message in ws:
                        if not isinstance(message, str):
                            continue

                        if self.debug_logging:
                            _LOGGER.debug("Raw websocket message for %s: %s", name, message)

                        coordinator = self._get_coordinator(bose_ip)

                        if coordinator is not None and "nowPlayingUpdated" in message:
                            now_playing = self._parse_now_playing_update(message)
                            if now_playing is not None:
                                self.hass.async_create_task(coordinator.push_now_playing(now_playing))
                            else:
                                self.hass.async_create_task(coordinator.async_request_refresh())
                        elif coordinator is not None:
                            self.hass.async_create_task(coordinator.async_request_refresh())

                        if "nowSelectionUpdated" not in message or "<preset id=" not in message:
                            continue

                        match = PRESET_RE.search(message)
                        if not match:
                            continue

                        preset = int(match.group(1))
                        if preset not in PRESET_IDS:
                            continue

                        if coordinator is not None:
                            coordinator.active_preset = preset
                            if coordinator.data is not None:
                                coordinator.async_set_updated_data(coordinator.data)

                        item_name_match = ITEM_RE.search(message)
                        item_name = item_name_match.group(1) if item_name_match else None

                        await self.async_handle_preset(
                            device_name=name,
                            preset=preset,
                            reason="websocket",
                            item_name=item_name,
                            bose_ip=bose_ip,
                        )

            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.warning(
                    "Websocket error for %s (%s): %s",
                    name,
                    bose_ip,
                    err,
                )
                await asyncio.sleep(3)

    async def async_handle_preset(
        self,
        device_name: str,
        preset: int,
        reason: str = "unknown",
        item_name: str | None = None,
        bose_ip: str | None = None,
    ) -> None:
        device = self._resolve_device(device_name=device_name, bose_ip=bose_ip)
        if not device:
            _LOGGER.warning(
                "Unknown device in preset handler: name=%s bose_ip=%s",
                device_name,
                bose_ip or "-",
            )
            return

        debounce_key = f"{device_name}:{preset}"
        now = time.monotonic()
        last = self._last_trigger.get(debounce_key, 0.0)

        if now - last < self.debounce_seconds:
            if self.debug_logging:
                _LOGGER.debug("Debounced %s preset %s", device_name, preset)
            return

        self._last_trigger[debounce_key] = now

        preset_config = self._preset_config(device, preset)
        stream_url = preset_config["stream_url"]
        ma_player = str(device.get(CONF_MA_PLAYER) or "").strip()
        target_volume = preset_config["volume"]
        target_label = ma_player or "(not configured)"

        if not preset_config["enabled"]:
            _LOGGER.info(
                "Preset %s for device %s is disabled; ignoring trigger from %s",
                preset,
                device_name,
                reason,
            )
            return

        if not stream_url:
            _LOGGER.warning("No stream configured for %s preset %s", device_name, preset)
            return

        routing_mode = str(device.get(CONF_ROUTING_MODE) or ROUTING_MODE_NONE)
        if routing_mode == ROUTING_MODE_DIRECT:
            coordinator = self._get_coordinator(device[CONF_BOSE_IP])
            if coordinator is None:
                _LOGGER.warning("No coordinator for direct routing: device=%s", device_name)
                return
            stream_url = coordinator._resolve_preset_url(preset)
            if not stream_url:
                _LOGGER.warning("Direct routing: no URL configured for device=%s preset=%s", device_name, preset)
                return
            if target_volume is not None:
                try:
                    await coordinator.api.async_set_volume(int(target_volume))
                except Exception as err:
                    _LOGGER.warning("Failed to set volume for direct routing: %s", err)

            # Playback is done purely via UPnP AVTransport (SetAVTransportURI+Play), which
            # is what actually starts streaming. Station metadata (title/art) is carried in
            # the DIDL we send, and active_preset is derived from the now_playing location.
            # We deliberately do NOT send the native PRESET key first: that kicks off the
            # speaker's own preset machinery for a UPNP-source ContentItem, which on some
            # units wedges the renderer (accepts commands with HTTP 200 but never streams).
            # This mirrors the reference bridge, which plays with AVTransport only.
            pre_state = await self._async_fetch_bose_now_playing(device[CONF_BOSE_IP])
            pre_source = str((pre_state or {}).get("source") or "").upper()

            if reason != "websocket":
                # Service/dashboard trigger: wake the speaker first if it is asleep.
                # POWER toggles power, so only send it when actually in standby.
                _LOGGER.info("Direct routing (service): device=%s preset=%s url=%s", device_name, preset, stream_url)
                try:
                    if pre_source in {"STANDBY", ""}:
                        await coordinator.api.async_power_on()
                        await asyncio.sleep(1.5)
                except Exception as err:
                    _LOGGER.warning(
                        "Direct routing: power-on check failed for %s preset=%s: %s", device_name, preset, err
                    )
            else:
                _LOGGER.debug("Direct routing (physical): device=%s preset=%s starting stream", device_name, preset)

            try:
                meta = coordinator.get_station_meta(stream_url)
                await coordinator.api.async_play_upnp_stream(
                    stream_url,
                    station_name=meta.get("name", ""),
                    station_favicon=meta.get("favicon", ""),
                )
            except Exception as err:
                _LOGGER.warning(
                    "Direct routing: AVTransport play failed for %s preset=%s: %s", device_name, preset, err
                )
                await coordinator.async_request_refresh()
                return

            # Diagnostics only (no recovery attempt — testing showed standby/power-cycle
            # and preset-reselect do not free a wedged renderer, only a physical power
            # cycle does). Log enough context to spot a pattern across occurrences.
            await asyncio.sleep(self.playback_verify_delay_seconds)
            post_state = await self._async_fetch_bose_now_playing(device[CONF_BOSE_IP])
            post_status = str((post_state or {}).get("source") or "")
            playing = False
            try:
                np_raw = await coordinator.api._async_get_text("now_playing")
                playing = "<playStatus>" in np_raw
            except Exception:
                pass
            if not playing:
                _LOGGER.warning(
                    "Direct routing: renderer did not report playStatus after AVTransport "
                    "device=%s preset=%s pre_source=%s post_source=%s url=%s "
                    "(SOAP accepted but speaker never started streaming — known wedge state, "
                    "requires physical power cycle to clear)",
                    device_name, preset, pre_source or "-", post_status or "-", stream_url,
                )

            await coordinator.async_request_refresh()
            return

        elif routing_mode == ROUTING_MODE_AIRPLAY:
            coordinator = self._get_coordinator(device[CONF_BOSE_IP])
            if coordinator is None:
                _LOGGER.warning("No coordinator for AirPlay routing: device=%s", device_name)
                return
            stream_url = coordinator._resolve_preset_url(preset)
            if not stream_url:
                _LOGGER.warning("AirPlay routing: no URL configured for device=%s preset=%s", device_name, preset)
                return
            if target_volume is not None:
                try:
                    await coordinator.api.async_set_volume(int(target_volume))
                except Exception as err:
                    _LOGGER.warning("Failed to set volume for AirPlay routing: %s", err)

            # Pass the speaker's actual current volume into the new AirPlay session so
            # pyatv preserves it instead of defaulting to a device-reported
            # "initialVolume" or its own ~33% fallback on every fresh connection —
            # otherwise volume audibly resets on every preset/replay.
            volume_percent: float | None = float(target_volume) if target_volume is not None else None
            if volume_percent is None:
                try:
                    current_volume = await coordinator.api.async_get_volume()
                    volume_percent = float(current_volume.get("actual", 0))
                except Exception as err:
                    _LOGGER.debug("AirPlay routing: could not read current volume for %s: %s", device_name, err)

            pre_state = await self._async_fetch_bose_now_playing(device[CONF_BOSE_IP])
            pre_source = str((pre_state or {}).get("source") or "").upper()

            if reason != "websocket":
                _LOGGER.info(
                    "AirPlay routing (%s): device=%s preset=%s url=%s", reason, device_name, preset, stream_url
                )
                try:
                    if pre_source in {"STANDBY", ""}:
                        await coordinator.api.async_power_on()
                        await asyncio.sleep(1.5)
                except Exception as err:
                    _LOGGER.warning(
                        "AirPlay routing: power-on check failed for %s preset=%s: %s", device_name, preset, err
                    )
            else:
                _LOGGER.debug("AirPlay routing (physical): device=%s preset=%s starting stream", device_name, preset)

            meta = coordinator.get_station_meta(stream_url)
            try:
                started = await coordinator.airplay_player.play(
                    stream_url,
                    title=meta.get("name", "") or (item_name or ""),
                    artist="Bose Preset Router",
                    album=meta.get("name", "") or "AirPlay",
                    volume_percent=volume_percent,
                )
            except Exception as err:
                _LOGGER.warning("AirPlay routing: play failed for %s preset=%s: %s", device_name, preset, err)
                await coordinator.async_request_refresh()
                return

            if not started:
                _LOGGER.warning(
                    "AirPlay routing: could not start stream for %s preset=%s (no discovered target or connect failure)",
                    device_name, preset,
                )
                await coordinator.async_request_refresh()
                return

            # AirPlay's ContentItem carries no location/item_name for media_player.py
            # to reverse-match against stored presets (unlike UPnP), so record which
            # preset we just started directly — router.py is the one source of truth
            # for what it told the speaker to play.
            coordinator.active_preset = preset
            if coordinator.data is not None:
                coordinator.async_set_updated_data(coordinator.data)

            # Remember this so a future HA restart can resume playback: AirPlay is a
            # live push connection (pyatv decodes and streams audio itself), unlike
            # UPnP where the speaker fetches the URL independently and keeps playing
            # across a restart. Without this, the speaker just goes silent on restart.
            try:
                await coordinator.airplay_resume_store.async_set(device[CONF_BOSE_IP], preset)
            except Exception as err:
                _LOGGER.debug("AirPlay routing: could not persist resume state for %s: %s", device_name, err)

            # Lightweight sanity check only — unlike the UPnP branch's wedge diagnostic,
            # a missing AIRPLAY source here just means the RAOP handshake is still in
            # progress or genuinely failed, not a known unrecoverable device state.
            await asyncio.sleep(self.playback_verify_delay_seconds)
            post_state = await self._async_fetch_bose_now_playing(device[CONF_BOSE_IP])
            post_source = str((post_state or {}).get("source") or "").upper()
            if post_source != "AIRPLAY":
                _LOGGER.info(
                    "AirPlay routing: source is %s (not yet AIRPLAY) for device=%s preset=%s shortly after play start",
                    post_source or "-", device_name, preset,
                )

            await coordinator.async_request_refresh()
            return

        if not ma_player:
            _LOGGER.warning(
                "No target media player configured for device=%s preset=%s; Bose device entity was created but routing is disabled until a player is assigned",
                device_name,
                preset,
            )
            self._log_stage(
                logging.WARNING,
                "routing_skipped",
                device_name=device_name,
                preset=preset,
                ma_player=target_label,
                detail="no_target_player_configured",
            )
            return

        _LOGGER.info(
            "Routing device=%s preset=%s reason=%s item=%s player=%s volume=%s url=%s",
            device_name,
            preset,
            reason,
            item_name,
            target_label,
            target_volume if target_volume is not None else "unchanged",
            stream_url,
        )
        self._log_stage(
            logging.INFO,
            "preset_detected",
            device_name=device_name,
            preset=preset,
            ma_player=target_label,
            detail=f"reason={reason} item={item_name or '-'}",
        )

        bose_verified, bose_reason = await self._async_confirm_bose_preset(
            bose_ip=device[CONF_BOSE_IP],
            device_name=device_name,
            preset=preset,
            item_name=item_name,
        )
        self._log_stage(
            logging.DEBUG
            if bose_verified and self.debug_logging
            else logging.WARNING if not bose_verified else logging.INFO,
            "bose_preset_confirmation",
            device_name=device_name,
            preset=preset,
            ma_player=target_label,
            detail=f"verified={bose_verified} via={bose_reason}",
        )
        if not bose_verified and self.strict_bose_confirmation:
            return

        if self.notify_on_press:
            persistent_notification.async_create(
                self.hass,
                title="Bose Preset erkannt",
                message=(
                    f"Bose device: {device_name}\n"
                    f"Preset: {preset}\n"
                    f"Item: {item_name or '-'}\n"
                    f"Bose confirm: {'yes' if bose_verified else 'no'} ({bose_reason})\n"
                    f"Target player: {target_label}\n"
                    f"Volume: {target_volume if target_volume is not None else 'unchanged'}\n"
                    f"URL: {stream_url}"
                ),
                notification_id=f"{DOMAIN}_{device_name}_{preset}",
            )

        if target_volume is not None:
            try:
                await self.hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {
                        "entity_id": ma_player,
                        "volume_level": float(target_volume) / 100,
                    },
                    blocking=True,
                )
            except HomeAssistantError as err:
                _LOGGER.error(
                    "Failed to set volume for device=%s preset=%s player=%s volume=%s: %s",
                    device_name,
                    preset,
                    target_label,
                    target_volume,
                    err,
                )
                raise

        previous_state = self.hass.states.get(ma_player)
        previous_bose_state = await self._async_fetch_bose_now_playing(device[CONF_BOSE_IP])
        verification_reason = "not_checked"

        for attempt in range(1, self.playback_verify_attempts + 1):
            self._log_stage(
                logging.INFO,
                "play_media_send",
                device_name=device_name,
                preset=preset,
                ma_player=target_label,
                attempt=attempt,
                total_attempts=self.playback_verify_attempts,
                detail=f"url={stream_url}",
            )
            await self._async_send_play_media(
                device_name=device_name,
                preset=preset,
                ma_player=ma_player,
                stream_url=stream_url,
                target_volume=target_volume,
                item_name=item_name,
            )

            verified, verification_reason = await self._async_verify_playback(
                ma_player=ma_player,
                stream_url=stream_url,
                item_name=item_name,
                previous_state=previous_state,
            )
            if verified:
                self._log_stage(
                    logging.INFO,
                    "player_verification_ok",
                    device_name=device_name,
                    preset=preset,
                    ma_player=target_label,
                    attempt=attempt,
                    total_attempts=self.playback_verify_attempts,
                    detail=f"via={verification_reason}",
                )
                bose_handoff_verified, bose_handoff_reason = await self._async_verify_bose_stream_handoff(
                    bose_ip=device[CONF_BOSE_IP],
                    previous_state=previous_bose_state,
                )
                if (
                    not bose_handoff_verified
                    and attempt < self.playback_verify_attempts
                    and self._should_passively_recheck_bose_handoff(bose_handoff_reason)
                ):
                    self._log_stage(
                        logging.INFO,
                        "bose_handoff_recheck",
                        device_name=device_name,
                        preset=preset,
                        ma_player=target_label,
                        attempt=attempt,
                        total_attempts=self.playback_verify_attempts,
                        detail=f"waiting_for_settle via={bose_handoff_reason}",
                    )
                    await asyncio.sleep(self.playback_verify_delay_seconds)
                    bose_handoff_verified, bose_handoff_reason = await self._async_verify_bose_stream_handoff(
                        bose_ip=device[CONF_BOSE_IP],
                        previous_state=previous_bose_state,
                    )

                if not bose_handoff_verified:
                    self._log_stage(
                        logging.WARNING,
                        "bose_handoff_failed",
                        device_name=device_name,
                        preset=preset,
                        ma_player=target_label,
                        attempt=attempt,
                        total_attempts=self.playback_verify_attempts,
                        detail=f"via={bose_handoff_reason}",
                    )
                    verification_reason = f"{verification_reason}+{bose_handoff_reason}"
                    continue

                self._log_stage(
                    logging.DEBUG if self.debug_logging else logging.INFO,
                    "handoff_complete",
                    device_name=device_name,
                    preset=preset,
                    ma_player=target_label,
                    attempt=attempt,
                    total_attempts=self.playback_verify_attempts,
                    detail=f"via={verification_reason}+{bose_handoff_reason}",
                )
                return

            self._log_stage(
                logging.WARNING,
                "player_verification_failed",
                device_name=device_name,
                preset=preset,
                ma_player=target_label,
                attempt=attempt,
                total_attempts=self.playback_verify_attempts,
                detail=f"via={verification_reason}",
            )

        self._log_stage(
            logging.ERROR,
            "handoff_failed",
            device_name=device_name,
            preset=preset,
            ma_player=target_label,
            attempt=self.playback_verify_attempts,
            total_attempts=self.playback_verify_attempts,
            detail=f"final_reason={verification_reason}",
        )
        if self.notify_on_press:
            persistent_notification.async_create(
                self.hass,
                title="Bose SoundTouch LocalControl Warnung",
                message=(
                    f"Die Stream-Uebergabe konnte nicht bestaetigt werden.\n"
                    f"Bose device: {device_name}\n"
                    f"Preset: {preset}\n"
                    f"Target player: {target_label}\n"
                    f"URL: {stream_url}"
                ),
                notification_id=f"{DOMAIN}_{device_name}_{preset}_verification_failed",
            )
