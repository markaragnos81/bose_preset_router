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
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
    DEFAULT_PLAYBACK_VERIFY_ATTEMPTS,
    DEFAULT_PLAYBACK_VERIFY_DELAY_SECONDS,
    DOMAIN,
    PRESET_IDS,
    WS_PORT,
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

    @property
    def notify_on_press(self) -> bool:
        return self.entry.options.get(
            CONF_NOTIFY_ON_PRESS,
            self.entry.data.get(CONF_NOTIFY_ON_PRESS, False),
        )

    @property
    def debug_logging(self) -> bool:
        return self.entry.options.get(
            CONF_DEBUG_LOGGING,
            self.entry.data.get(CONF_DEBUG_LOGGING, False),
        )

    @property
    def debounce_seconds(self) -> float:
        return float(
            self.entry.options.get(
                CONF_DEBOUNCE_SECONDS,
                self.entry.data.get(CONF_DEBOUNCE_SECONDS, 2.0),
            )
        )

    @property
    def playback_verify_attempts(self) -> int:
        return int(
            self.entry.options.get(
                CONF_PLAYBACK_VERIFY_ATTEMPTS,
                self.entry.data.get(
                    CONF_PLAYBACK_VERIFY_ATTEMPTS,
                    DEFAULT_PLAYBACK_VERIFY_ATTEMPTS,
                ),
            )
        )

    @property
    def playback_verify_delay_seconds(self) -> float:
        return float(
            self.entry.options.get(
                CONF_PLAYBACK_VERIFY_DELAY_SECONDS,
                self.entry.data.get(
                    CONF_PLAYBACK_VERIFY_DELAY_SECONDS,
                    DEFAULT_PLAYBACK_VERIFY_DELAY_SECONDS,
                ),
            )
        )

    @property
    def devices(self) -> list[dict[str, Any]]:
        return [
            sub.data
            for sub in self.entry.subentries.values()
            if sub.subentry_type == "device"
        ]

    def _preset_config(self, device: dict[str, Any], preset: int) -> dict[str, Any]:
        return {
            "enabled": bool(device.get(preset_enabled_key(preset), True)),
            "stream_url": device.get(preset_url_key(preset)),
            "volume": device.get(
                preset_volume_key(preset),
                device.get(CONF_DEFAULT_VOLUME),
            ),
        }

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
        session = async_get_clientsession(self.hass)
        url = f"http://{bose_ip}:8090/now_playing"

        try:
            async with session.get(url, timeout=5) as response:
                response.raise_for_status()
                payload = await response.text()
        except Exception as err:
            _LOGGER.warning("Failed to fetch Bose now_playing from %s: %s", bose_ip, err)
            return None

        try:
            root = ET.fromstring(payload)
        except ET.ParseError as err:
            _LOGGER.warning("Invalid Bose now_playing XML from %s: %s", bose_ip, err)
            return None

        content_item = root.find("ContentItem")
        return {
            "source": root.attrib.get("source", ""),
            "source_account": root.attrib.get("sourceAccount", ""),
            "item_name": root.findtext("itemName", default=""),
            "track": root.findtext("track", default=""),
            "artist": root.findtext("artist", default=""),
            "album": root.findtext("album", default=""),
            "station_name": root.findtext("stationName", default=""),
            "location": (
                content_item.attrib.get("location", "")
                if content_item is not None
                else ""
            ),
            "source_type": (
                content_item.attrib.get("source", "")
                if content_item is not None
                else ""
            ),
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

                        if "nowSelectionUpdated" not in message or "<preset id=" not in message:
                            continue

                        match = PRESET_RE.search(message)
                        if not match:
                            continue

                        preset = int(match.group(1))
                        if preset not in PRESET_IDS:
                            continue

                        item_name_match = ITEM_RE.search(message)
                        item_name = item_name_match.group(1) if item_name_match else None

                        await self.async_handle_preset(
                            device_name=name,
                            preset=preset,
                            reason="websocket",
                            item_name=item_name,
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
    ) -> None:
        device = next((d for d in self.devices if d[CONF_NAME] == device_name), None)
        if not device:
            _LOGGER.warning("Unknown device name in preset handler: %s", device_name)
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
        ma_player = device[CONF_MA_PLAYER]
        target_volume = preset_config["volume"]

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

        _LOGGER.info(
            "Routing device=%s preset=%s reason=%s item=%s player=%s volume=%s url=%s",
            device_name,
            preset,
            reason,
            item_name,
            ma_player,
            target_volume if target_volume is not None else "unchanged",
            stream_url,
        )
        self._log_stage(
            logging.INFO,
            "preset_detected",
            device_name=device_name,
            preset=preset,
            ma_player=ma_player,
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
            ma_player=ma_player,
            detail=f"verified={bose_verified} via={bose_reason}",
        )
        if not bose_verified:
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
                    f"Target player: {ma_player}\n"
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
                    ma_player,
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
                ma_player=ma_player,
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
                    ma_player=ma_player,
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
                        ma_player=ma_player,
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
                        ma_player=ma_player,
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
                    ma_player=ma_player,
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
                ma_player=ma_player,
                attempt=attempt,
                total_attempts=self.playback_verify_attempts,
                detail=f"via={verification_reason}",
            )

        self._log_stage(
            logging.ERROR,
            "handoff_failed",
            device_name=device_name,
            preset=preset,
            ma_player=ma_player,
            attempt=self.playback_verify_attempts,
            total_attempts=self.playback_verify_attempts,
            detail=f"final_reason={verification_reason}",
        )
        if self.notify_on_press:
            persistent_notification.async_create(
                self.hass,
                title="Bose Preset Router Warnung",
                message=(
                    f"Die Stream-Uebergabe konnte nicht bestaetigt werden.\n"
                    f"Bose device: {device_name}\n"
                    f"Preset: {preset}\n"
                    f"Target player: {ma_player}\n"
                    f"URL: {stream_url}"
                ),
                notification_id=f"{DOMAIN}_{device_name}_{preset}_verification_failed",
            )
