from __future__ import annotations

import json
import re
from typing import Any

from homeassistant.components.media_player import (
    BrowseError,
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MA_PLAYER, CONF_ROUTING_MODE, DATA_COORDINATORS, ROUTING_MODE_AIRPLAY
from .coordinator import BoseSoundTouchCoordinator
from .radio_browser import parse_icy_stream_title

PRESET_SOURCE_PREFIX = "Preset "
CONTENT_TYPE_LIBRARY = "library"
CONTENT_TYPE_MUSIC = "music"
CONTENT_TYPE_PRESET = "soundtouch_preset"
CONTENT_TYPE_SOURCE = "soundtouch_source"
CONTENT_TYPE_ZONE = "soundtouch_zone"
ROOT_BROWSE_ID = "root"
PRESETS_BROWSE_ID = "presets"
SOURCES_BROWSE_ID = "sources"
ZONE_BROWSE_ID = "zone"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[entry.domain][entry.entry_id]
    coordinators: dict[str, BoseSoundTouchCoordinator] = entry_data[DATA_COORDINATORS]
    async_add_entities(
        BoseSoundTouchMediaPlayer(coordinator_id, coordinator)
        for coordinator_id, coordinator in coordinators.items()
    )


class BoseSoundTouchMediaPlayer(
    CoordinatorEntity[BoseSoundTouchCoordinator],
    MediaPlayerEntity,
):
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_has_entity_name = True
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.PLAY_MEDIA
        | MediaPlayerEntityFeature.BROWSE_MEDIA
    )

    def __init__(self, coordinator_id: str, coordinator: BoseSoundTouchCoordinator) -> None:
        super().__init__(coordinator)
        self._coordinator_id = coordinator_id
        self._attr_name = None
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{coordinator_id}_media_player"

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data)

    @property
    def state(self) -> MediaPlayerState | str | None:
        if not self.coordinator.last_update_success and not self.coordinator.data:
            return STATE_UNAVAILABLE

        now_playing = self._data.get("now_playing", {})
        source = str(now_playing.get("source", "")).upper()
        play_status = str(now_playing.get("play_status", "")).upper()

        if source in {"STANDBY", ""}:
            return MediaPlayerState.OFF
        if play_status in {"PLAY_STATE", "BUFFERING_STATE"}:
            return MediaPlayerState.PLAYING
        if play_status in {"PAUSE_STATE"}:
            return MediaPlayerState.PAUSED
        if play_status in {"STOP_STATE"}:
            return MediaPlayerState.IDLE

        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        volume = self._data.get("volume", {})
        actual = volume.get("actual")
        if actual is None:
            return None
        return max(0.0, min(1.0, float(actual) / 100))

    @property
    def is_volume_muted(self) -> bool | None:
        volume = self._data.get("volume", {})
        muted = volume.get("muted")
        return bool(muted) if muted is not None else None

    @property
    def media_title(self) -> str | None:
        now_playing = self._data.get("now_playing", {})

        # Real current song from ICY (e.g. "Black Dog" from "Led Zeppelin - Black Dog")
        _, song_title = self._real_song
        if song_title:
            return song_title

        # No real song playing -> show the clean station name
        station = self._station_name
        if station:
            return station

        now_playing_title = self._now_playing_title(now_playing)
        if now_playing_title:
            return now_playing_title

        current_preset = self._current_preset
        if current_preset is not None:
            return str(current_preset.get("item_name") or "") or self._preset_label(current_preset)

        current_source = self._current_source_item
        if current_source is not None:
            return self._source_label(current_source) or None

        return None

    @staticmethod
    def _normalize_station(value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[!\-–—_.,/()']", " ", value.lower())).strip()

    @property
    def _station_name(self) -> str:
        """Best-known clean station name for the current stream."""
        now_playing = self._data.get("now_playing", {})
        name = (
            str(now_playing.get("station_name") or "").strip()
            or str(now_playing.get("item_name") or "").strip()
        )
        if not name:
            location = str(now_playing.get("location") or "").strip()
            if not location:
                # AirPlay's ContentItem never carries a location — fall back to
                # the URL we ourselves pushed via pyatv, if we're the one streaming.
                location = str(self.coordinator.active_stream_url or "").strip()
            if location:
                name = self.coordinator.get_station_meta(location).get("name", "")
        if not name:
            # The one field Bose reliably echoes back for AirPlay sessions is the
            # track title we pushed via pyatv's MediaMetadata.
            name = str(now_playing.get("track") or "").strip()
        if not name:
            icy = self._data.get("icy_meta", {})
            name = str(icy.get("icy_name") or "").strip()
        return name

    @property
    def _real_song(self) -> tuple[str, str]:
        """Return (artist, title) ONLY when the ICY StreamTitle is an actual song.

        Many stations broadcast only their own name in StreamTitle (e.g.
        'RADIO BOB - Rock Hits'). That is branding, not a song, so we must not
        split it into a fake artist/title. Returns ('', '') in that case.
        """
        icy = self._data.get("icy_meta", {})
        stream_title = str(icy.get("stream_title") or "").strip()
        if not stream_title:
            return "", ""

        norm_title = self._normalize_station(stream_title)
        station = self._station_name
        icy_name = str(icy.get("icy_name") or "").strip()
        # Treat as branding (not a song) if it matches the station name / icy-name
        if station and norm_title == self._normalize_station(station):
            return "", ""
        if icy_name and norm_title == self._normalize_station(icy_name):
            return "", ""

        return parse_icy_stream_title(stream_title)

    @property
    def media_artist(self) -> str | None:
        now_playing = self._data.get("now_playing", {})
        # Native artist from Bose (e.g. Spotify/TIDAL)
        native_artist = str(now_playing.get("artist") or "").strip()
        if native_artist:
            return native_artist
        # Real ICY stream artist (e.g. "Led Zeppelin"); empty when only station branding
        song_artist, _ = self._real_song
        return song_artist or None

    @property
    def media_album_name(self) -> str | None:
        now_playing = self._data.get("now_playing", {})
        # When a real song is playing, show the station name as the "album"
        song_artist, _ = self._real_song
        if song_artist:
            station = self._station_name
            if station:
                return station
        return (
            str(now_playing.get("album") or "")
            or self._target_player_attr("media_album_name")
            or None
        )

    @property
    def media_image_url(self) -> str | None:
        now_playing = self._data.get("now_playing", {})
        current_preset = self._current_preset

        # Station logo (radio.net) / favicon, cached in coordinator by stream URL
        location = str(now_playing.get("location") or "").strip()
        cached_favicon = ""
        if location:
            cached_favicon = self.coordinator.get_station_meta(location).get("favicon", "")

        # For UPNP radio, the cached logo is the best source — Bose only echoes back
        # the (possibly older/plainer) art we sent it via DIDL.
        source = str(now_playing.get("source") or "").upper()
        if source == "UPNP" and cached_favicon:
            return cached_favicon

        return (
            str(now_playing.get("image") or "").strip()
            or (str(current_preset.get("image") or "").strip() if current_preset is not None else "")
            or cached_favicon
            or self._target_player_attr("entity_picture")
            or self._target_player_attr("media_image_url")
            or None
        )

    @property
    def media_content_type(self) -> str | None:
        if self._has_rich_now_playing_metadata:
            return CONTENT_TYPE_MUSIC

        current_preset = self._current_preset
        if current_preset is not None:
            return CONTENT_TYPE_PRESET

        current_source = self._current_source_item
        if current_source is not None:
            return CONTENT_TYPE_SOURCE

        return None

    @property
    def media_content_id(self) -> str | None:
        current_preset = self._current_preset
        if current_preset is not None:
            return self._preset_content_id(current_preset)

        current_source = self._current_source_item
        if current_source is not None:
            return self._source_content_id(current_source)

        return None

    @property
    def media_track(self) -> str | None:
        now_playing = self._data.get("now_playing", {})
        return str(now_playing.get("track") or "").strip() or None

    @property
    def media_channel(self) -> str | None:
        now_playing = self._data.get("now_playing", {})
        return (
            str(now_playing.get("station_name") or "")
            or str(now_playing.get("album") or "")
            or self._target_player_attr("media_channel")
            or None
        )

    @property
    def source(self) -> str | None:
        current_preset = self._current_preset
        if current_preset is not None:
            return self._preset_label(current_preset)

        current_source = self._current_source_item
        if current_source is not None:
            return self._source_label(current_source)

        now_playing = self._data.get("now_playing", {})
        current_source_name = str(now_playing.get("source") or "")
        if not current_source_name:
            return None

        return current_source_name

    @property
    def _has_rich_now_playing_metadata(self) -> bool:
        now_playing = self._data.get("now_playing", {})
        return any(
            str(now_playing.get(field) or "").strip()
            for field in ("track", "item_name", "artist", "album", "station_name", "description")
        )

    def _target_player_attr(self, attr_name: str) -> str | None:
        target_entity_id = str(self.coordinator.device.get(CONF_MA_PLAYER) or "").strip()
        if not target_entity_id or self.hass is None:
            return None

        target_state = self.hass.states.get(target_entity_id)
        if target_state is None:
            return None

        value = target_state.attributes.get(attr_name)
        return str(value).strip() if value else None

    @property
    def source_list(self) -> list[str] | None:
        labels = [self._preset_label(preset) for preset in self._presets]

        seen: set[str] = set(labels)
        for source in self._sources:
            label = self._source_label(source)
            if label and label not in seen:
                seen.add(label)
                labels.append(label)
        return labels

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        now_playing = self._data.get("now_playing", {})
        zone = self._data.get("zone", {})
        info = self._data.get("info", {})
        return {
            "active_preset": self._current_preset.get("id") if self._current_preset is not None else None,
            "bose_ip": self.coordinator.bose_ip,
            "bose_source": now_playing.get("source"),
            "source_account": now_playing.get("source_account"),
            "source_type": now_playing.get("source_type"),
            "station_name": self._station_name or None,
            "track": now_playing.get("track"),
            "description": now_playing.get("description"),
            "location": now_playing.get("location"),
            "play_status": now_playing.get("play_status"),
            "device_id": info.get("device_id"),
            "model": info.get("type"),
            "network_type": info.get("network_type"),
            "account": info.get("account"),
            "presets_available": len(self._presets),
            "sources_available": len(self._sources),
            "zone_role": self._zone_role(),
            "zone_master_id": zone.get("master_id"),
            "zone_sender_ip": zone.get("sender_ip"),
            "zone_members": zone.get("members"),
            "zone_member_count": len(zone.get("members", [])),
        }

    @property
    def device_info(self) -> dict[str, Any]:
        info = self._data.get("info", {})
        model = str(info.get("type") or "") or None
        return {
            "identifiers": {(self.coordinator.entry.domain, self.coordinator.registry_identifier)},
            "name": self.coordinator.device_name,
            "manufacturer": "Bose",
            "model": model,
            "configuration_url": f"http://{self.coordinator.bose_ip}:8090/info",
        }

    @property
    def _presets(self) -> list[dict[str, Any]]:
        return list(self._data.get("presets", []))

    @property
    def _sources(self) -> list[dict[str, Any]]:
        return list(self._data.get("sources", []))

    @property
    def _device_id(self) -> str:
        info = self._data.get("info", {})
        return str(info.get("device_id") or self.coordinator.bose_ip)

    @property
    def _zone(self) -> dict[str, Any]:
        return dict(self._data.get("zone", {}))

    @property
    def _current_preset(self) -> dict[str, Any] | None:
        now_playing = self._data.get("now_playing", {})
        current_source = str(now_playing.get("source") or "")

        # AirPlay's ContentItem carries no location/item_name to reverse-match
        # against stored presets (unlike UPnP's provisioned ContentItem), and
        # Bose's own now_playing.source has proven stale/unreliable during an
        # AirPlay transition (observed showing "UPNP" or a stale prior preset
        # while the correct AirPlay audio was genuinely playing). We are the
        # streamer for AirPlay, so trust our own verified state instead: only
        # if the RAOP stream task we started is actually still alive right now
        # (not just "we once asked to play X", which could be stale if the
        # stream silently died — coordinator.airplay_player.is_playing checks
        # the live asyncio.Task, not a static flag).
        if self.coordinator.active_preset is not None and self.coordinator.airplay_player.is_playing:
            for preset in self._presets:
                if preset.get("id") == self.coordinator.active_preset:
                    return preset
            return None

        current_location = str(now_playing.get("location") or "")
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

    @property
    def _current_source_item(self) -> dict[str, Any] | None:
        now_playing = self._data.get("now_playing", {})
        current_source = str(now_playing.get("source") or "")
        current_source_account = str(now_playing.get("source_account") or "")
        for source in self._sources:
            if str(source.get("source") or "") != current_source:
                continue
            source_account = str(source.get("source_account") or "")
            if current_source_account and source_account and source_account != current_source_account:
                continue
            return source
        return None

    @staticmethod
    def _preset_label(preset: dict[str, Any]) -> str:
        preset_id = preset.get("id")
        item_name = str(preset.get("item_name") or "").strip()
        return f"{PRESET_SOURCE_PREFIX}{preset_id}: {item_name or 'Unnamed'}"

    @staticmethod
    def _source_label(source: dict[str, Any]) -> str:
        item_name = str(source.get("item_name") or "").strip()
        source_name = str(source.get("source") or "").strip()
        return item_name or source_name

    @staticmethod
    def _now_playing_title(now_playing: dict[str, Any]) -> str | None:
        return (
            str(now_playing.get("track") or "").strip()
            or str(now_playing.get("item_name") or "").strip()
            or str(now_playing.get("description") or "").strip()
            or None
        )

    @staticmethod
    def _preset_content_id(preset: dict[str, Any]) -> str:
        return json.dumps({"preset_id": int(preset.get("id", 0))}, sort_keys=True)

    @staticmethod
    def _source_content_id(source: dict[str, Any]) -> str:
        return json.dumps(
            {
                "source": str(source.get("source") or ""),
                "source_account": str(source.get("source_account") or ""),
                "item_name": str(source.get("item_name") or ""),
                "location": str(source.get("location") or ""),
            },
            sort_keys=True,
        )

    @staticmethod
    def _zone_member_label(member: dict[str, Any]) -> str:
        ip_address = str(member.get("ip_address") or "")
        mac_address = str(member.get("mac_address") or "")
        return ip_address or mac_address or "Unknown member"

    def _zone_role(self) -> str:
        zone = self._zone
        members = zone.get("members", [])
        master_id = str(zone.get("master_id") or "")
        if not members:
            return "standalone"
        if master_id and master_id == self._device_id:
            return "master"
        return "member"

    async def async_play_media(
        self,
        media_type: str,
        media_id: str,
        **kwargs: Any,
    ) -> None:
        if media_type == CONTENT_TYPE_PRESET:
            payload = json.loads(media_id)
            await self.coordinator.api.async_select_preset(int(payload["preset_id"]))
            await self.coordinator.async_request_refresh()
            return

        if media_type == CONTENT_TYPE_SOURCE:
            payload = json.loads(media_id)
            await self.coordinator.api.async_select_source(
                source=str(payload.get("source") or ""),
                source_account=str(payload.get("source_account") or ""),
                item_name=str(payload.get("item_name") or ""),
                location=str(payload.get("location") or ""),
            )
            await self.coordinator.async_request_refresh()
            return

        raise BrowseError(f"Unsupported media type: {media_type}")

    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        media_content_type = media_content_type or CONTENT_TYPE_LIBRARY
        media_content_id = media_content_id or ROOT_BROWSE_ID

        if media_content_type == CONTENT_TYPE_LIBRARY and media_content_id == ROOT_BROWSE_ID:
            return BrowseMedia(
                title=self.coordinator.device_name,
                media_class="directory",
                media_content_type=CONTENT_TYPE_LIBRARY,
                media_content_id=ROOT_BROWSE_ID,
                can_play=False,
                can_expand=True,
                children=[
                    BrowseMedia(
                        title="Presets",
                        media_class="directory",
                        media_content_type=CONTENT_TYPE_LIBRARY,
                        media_content_id=PRESETS_BROWSE_ID,
                        can_play=False,
                        can_expand=True,
                    ),
                    BrowseMedia(
                        title="Sources",
                        media_class="directory",
                        media_content_type=CONTENT_TYPE_LIBRARY,
                        media_content_id=SOURCES_BROWSE_ID,
                        can_play=False,
                        can_expand=True,
                    ),
                    BrowseMedia(
                        title="Zone",
                        media_class="directory",
                        media_content_type=CONTENT_TYPE_LIBRARY,
                        media_content_id=ZONE_BROWSE_ID,
                        can_play=False,
                        can_expand=True,
                    ),
                ],
            )

        if media_content_type == CONTENT_TYPE_LIBRARY and media_content_id == PRESETS_BROWSE_ID:
            return BrowseMedia(
                title="Presets",
                media_class="directory",
                media_content_type=CONTENT_TYPE_LIBRARY,
                media_content_id=PRESETS_BROWSE_ID,
                can_play=False,
                can_expand=True,
                children=[
                    BrowseMedia(
                        title=self._preset_label(preset),
                        media_class="music",
                        media_content_type=CONTENT_TYPE_PRESET,
                        media_content_id=self._preset_content_id(preset),
                        can_play=True,
                        can_expand=False,
                        thumbnail=str(preset.get("image") or "") or None,
                    )
                    for preset in self._presets
                ],
            )

        if media_content_type == CONTENT_TYPE_LIBRARY and media_content_id == SOURCES_BROWSE_ID:
            return BrowseMedia(
                title="Sources",
                media_class="directory",
                media_content_type=CONTENT_TYPE_LIBRARY,
                media_content_id=SOURCES_BROWSE_ID,
                can_play=False,
                can_expand=True,
                children=[
                    BrowseMedia(
                        title=self._source_label(source),
                        media_class="channel",
                        media_content_type=CONTENT_TYPE_SOURCE,
                        media_content_id=self._source_content_id(source),
                        can_play=True,
                        can_expand=False,
                    )
                    for source in self._sources
                ],
            )

        if media_content_type == CONTENT_TYPE_LIBRARY and media_content_id == ZONE_BROWSE_ID:
            members = self._zone.get("members", [])
            return BrowseMedia(
                title="Zone",
                media_class="directory",
                media_content_type=CONTENT_TYPE_LIBRARY,
                media_content_id=ZONE_BROWSE_ID,
                can_play=False,
                can_expand=True,
                children=[
                    BrowseMedia(
                        title=f"Role: {self._zone_role()}",
                        media_class="directory",
                        media_content_type=CONTENT_TYPE_ZONE,
                        media_content_id="zone-role",
                        can_play=False,
                        can_expand=False,
                    ),
                    BrowseMedia(
                        title=f"Master: {str(self._zone.get('master_id') or '-')}",
                        media_class="directory",
                        media_content_type=CONTENT_TYPE_ZONE,
                        media_content_id="zone-master",
                        can_play=False,
                        can_expand=False,
                    ),
                    *[
                        BrowseMedia(
                            title=self._zone_member_label(member),
                            media_class="directory",
                            media_content_type=CONTENT_TYPE_ZONE,
                            media_content_id=f"zone-member-{index}",
                            can_play=False,
                            can_expand=False,
                        )
                        for index, member in enumerate(members, start=1)
                    ],
                ],
            )

        raise BrowseError(
            f"Unknown browse request: type={media_content_type} id={media_content_id}"
        )

    @property
    def _is_airplay_mode(self) -> bool:
        return str(self.coordinator.device.get(CONF_ROUTING_MODE) or "") == ROUTING_MODE_AIRPLAY

    async def _async_stop_airplay_if_active(self) -> None:
        """Actually end the RAOP session and forget the resume state.

        Bose's own stop/standby controls do not close an active AirPlay session
        (verified live: the speaker stays on source=AIRPLAY after a plain
        userPlayControl STOP) — only tearing down our own pyatv connection does.
        Also clears the persisted resume-on-restart preset, since this is an
        explicit user stop, not an interruption to recover from.
        """
        if not self._is_airplay_mode:
            return
        await self.coordinator.airplay_player.stop()
        try:
            await self.coordinator.airplay_resume_store.async_clear(self.coordinator.bose_ip)
        except Exception:
            pass

    async def async_turn_on(self) -> None:
        await self.coordinator.api.async_power_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self._async_stop_airplay_if_active()
        await self.coordinator.api.async_standby()
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        await self.coordinator.api.async_play()
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        await self._async_stop_airplay_if_active()
        await self.coordinator.api.async_pause()
        await self.coordinator.async_request_refresh()

    async def async_media_stop(self) -> None:
        await self._async_stop_airplay_if_active()
        await self.coordinator.api.async_stop()
        await self.coordinator.async_request_refresh()

    async def async_media_next_track(self) -> None:
        await self.coordinator.api.async_next_track()
        await self.coordinator.async_request_refresh()

    async def async_media_previous_track(self) -> None:
        await self.coordinator.api.async_previous_track()
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        await self.coordinator.api.async_set_volume(round(max(0.0, min(1.0, volume)) * 100))
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        await self.coordinator.api.async_set_muted(mute)
        await self.coordinator.async_request_refresh()

    async def async_select_source(self, source: str) -> None:
        source = source.strip()
        for preset in self._presets:
            if self._preset_label(preset) == source:
                await self.async_play_media(CONTENT_TYPE_PRESET, self._preset_content_id(preset))
                return

        for source_item in self._sources:
            label = self._source_label(source_item)
            if label != source:
                continue

            await self.async_play_media(CONTENT_TYPE_SOURCE, self._source_content_id(source_item))
            return

        raise ValueError(f"Unknown SoundTouch source selection: {source}")
