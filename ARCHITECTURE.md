# Bose Preset Router — Architecture & Status (as of v0.7.9)

This is a working-state reference doc, not user-facing documentation (see
`README.md` for that) and not a changelog (see `CHANGELOG.md`). It exists so
future work sessions can pick up the current architecture, the reasoning
behind it, and known open issues without re-deriving them.

## What this integration does

A Home Assistant custom integration that controls Bose SoundTouch speakers:
preset routing (physical button presses and dashboard/service triggers),
`media_player` entities, ICY stream metadata, station name/logo enrichment,
multi-room zones.

## Playback paths (routing modes)

Configured per device in the config flow, one of:

- **`airplay`** (recommended, default for new devices) — streams via
  AirPlay/RAOP using `pyatv`. **We are the active streamer**: pyatv connects
  to the speaker and pushes decoded audio over a live RAOP session. Falls
  back automatically to UPnP AVTransport if AirPlay discovery/connect fails.
- **`direct`** (UPnP AVTransport, legacy/fallback) — Bose fetches the stream
  URL itself via SOAP `SetAVTransportURI`/`Play` on port 8091. Bose owns the
  playback state for this path.
- **`player`** — forwards to another HA `media_player` (e.g. Music
  Assistant, an `apple_tv` HomePod entity) via `media_player.play_media`.
- **`none`** — Bose player entity only, no preset routing.

### Why AirPlay exists at all: the UPnP wedge

The UPnP AVTransport renderer on these speakers intermittently and
unpredictably "wedges": SOAP calls return HTTP 200, `ContentItem`/metadata
update, but `<playStatus>` never appears and no audio plays. This is a
firmware-level issue — four separate fix attempts (v0.6.24–v0.6.27) could
not resolve it in software; only a physical power-cycle clears it. The
reference project `gesellix/Bose-SoundTouch` has the same limitation with no
recovery mechanism.

Live-tested and proven (before building any of this): streaming via
`pyatv`'s RAOP protocol works even while the UPnP renderer is wedged on the
same device — AirPlay is a structurally independent playback pipeline in the
speaker's firmware. This is why AirPlay became the new default/recommended
path (v0.7.0) rather than trying a fifth UPnP fix.

## Key architectural principle: who is "the source of truth"?

This is the single most important design decision in the AirPlay code, and
it took real live-testing (not assumption) to land on.

- **UPnP mode**: Bose fetches the URL and plays it independently — Bose's own
  `now_playing` really is authoritative. No changes needed here.
- **AirPlay mode**: WE (via `pyatv`) actively decode and push audio. Bose is
  a *passive receiver*. Its own `now_playing` self-report for AirPlay has
  been repeatedly proven stale/unreliable in live testing:
  - `ContentItem` for AirPlay never has a `location` field.
  - `source` can stay `"UPNP"` (echoing a stale prior ContentItem from a
    physical preset press, which *always* stores with `source="UPNP"`
    regardless of routing mode) even while correct AirPlay audio is playing.
  - Observed directly: entity showed `media_title: RADIO BOB - Livestream
    National`, `source: Preset 2: Regiocast`, `active_preset: 2` while
    Preset 1 (Radio21) was actually and correctly playing.

  The fix (v0.7.9, prompted directly by the user asking "why does Music
  Assistant get this right but we don't?") mirrors how Music Assistant
  works: MA doesn't poll the downstream device for "what's playing" because
  MA itself is the active streamer and owns that state. Same principle here,
  but grounded in something *verifiable*, not blind trust of "what we last
  asked to play" (which could itself go stale if the RAOP session silently
  dies in the background — this was explicitly rejected by the user as
  "klingt nach raten" / "sounds like guessing").

  Concretely: `AirPlayPlayer.is_playing` checks the live `asyncio.Task`
  state of our own stream. `coordinator.active_preset` is only trusted when
  `is_playing` is also true. `set_on_ended()` fires a callback the moment the
  stream task dies unprompted, clearing `active_preset`/`active_stream_url`
  immediately rather than waiting for the next poll to notice a mismatch.

## Files

- **`airplay.py`** — `AirPlayDiscovery` (shared per-config-entry periodic
  mDNS/RAOP scan with its own long-lived `AsyncServiceBrowser`, result cache
  by IP, retry-on-miss for Wi-Fi roaming blips), `AirPlayPlayer` (owns the
  pyatv connection + stream task per device; `is_playing`, `set_on_ended()`),
  `AirPlayResumeStore` (HA `Store`-backed, persists "device X was playing
  preset N" across HA restarts, since a live RAOP session dies with HA).
- **`coordinator.py`** — `BoseSoundTouchCoordinator`: one per device. Holds
  `active_preset`, `active_stream_url` (AirPlay's own record of what it's
  streaming, since AirPlay's ContentItem has no `location` to key ICY
  lookups off of), `airplay_player`. Cross-checks `airplay_player.is_playing`
  on every poll and self-corrects if the stream actually died.
- **`router.py`** — `BosePresetRouterManager.async_handle_preset()`: the
  central dispatch for both physical button presses (via the WS listener,
  `reason="websocket"`) and service/dashboard calls. The `ROUTING_MODE_AIRPLAY`
  branch tries `airplay_player.play()`; on failure (discovery miss or
  connect failure) it falls back to the existing `async_play_upnp_stream()`
  AVTransport path so the speaker doesn't get stuck "selected but silent."
- **`media_player.py`** — `_current_preset` trusts `coordinator.active_preset`
  only when `airplay_player.is_playing` confirms it; falls through to the
  pre-existing UPnP location/item_name matching otherwise (covers both
  UPnP-mode devices and the AirPlay-fallback-to-UPnP case). `_station_name`
  checks `now_playing.track` (the one field Bose reliably echoes for
  AirPlay) and falls back to `coordinator.active_stream_url` for station
  metadata lookups when `location` is empty.
- **`config_flow.py`** — AirPlay is the first/default routing option, labeled
  "recommended." No changes needed to the step-branching logic (`async_step_routing`
  only special-cases `player` mode; AirPlay falls into the same branch as
  `direct`/`none`).
- **`__init__.py`** — starts one `AirPlayDiscovery` per config entry, injects
  it (plus a shared `AirPlayResumeStore`) into every coordinator, fires a
  fire-and-forget `manager.async_resume_airplay_devices()` background task on
  startup to replay whatever was playing via AirPlay before the last restart.

## Known environmental limitation (not a code bug)

**Wi-Fi mesh roaming causes AirPlay mDNS discovery gaps.** User's network:
FRITZ!Box 6591 + 3× FRITZ!Repeater 1200 AX mesh, same SSID. Unicast HTTP
control traffic survives AP roaming fine; multicast (mDNS/RAOP advertisement)
can silently drop because multicast group membership must be rebuilt on the
new AP. Confirmed independently (not just via HA) with a raw Python
`zeroconf.ServiceBrowser` from a separate machine showing the same gap.
FRITZ! mesh has no AP-pinning feature (unlike UniFi/eero), and LAN backhaul
isn't an option here. Mitigations already in place (v0.7.6): 20s scan
interval, 45s cache max-age, 3-attempt retry with 2s gaps on a cache miss.
When discovery still misses, the `direct`/UPnP fallback (v0.7.8) keeps the
speaker functional. Observed live fix: power-cycling the speaker, or
toggling AirPlay in the Bose/SoundTouch app, kicks it back onto mDNS.

## Known limitation: no live per-song metadata updates via AirPlay

`pyatv`'s `stream_file(url, metadata=...)` sets metadata once at stream
start; it does not update per song change. Richer metadata comes from the
pre-existing ICY-polling logic (`radio_browser.async_fetch_icy_meta`)
against the stream URL directly — independent of the playback path, and
already fixed in v0.7.9 to actually fire for AirPlay (previously it silently
never fired because the fetch condition required a `location` field AirPlay
never populates).

## Verification discipline (established practice in this project)

No automated test suite exists. All fixes in this project are verified live
against real devices — primarily `192.168.20.139` (Büro, Wi-Fi) and
`192.168.20.20` (Wohnzimmer, LAN) — by polling `/now_playing` directly
and/or checking the HA entity state and logs after each change, before
committing. Speculative "this should fix it" patches without live
verification are explicitly against the established working style for this
project.

## Version history highlights (see `CHANGELOG.md` / git log for full detail)

- **v0.6.19–v0.6.27**: ICY metadata, station names/logos, WebSocket
  real-time events, multiple UPnP-wedge fix attempts (none fully resolved
  the underlying firmware issue).
- **v0.7.0**: AirPlay (pyatv/RAOP) added as a new, selectable, recommended
  routing mode.
- **v0.7.1–v0.7.4**: AirPlay discovery reliability inside HA (shared
  zeroconf instance, persistent `AsyncServiceBrowser`, required no-op
  handler — a missing handler crashed the whole integration on startup in
  the v0.7.3 release, fixed in v0.7.4).
- **v0.7.5**: Fixed AirPlay volume resetting to loud on every replay (pyatv
  defaults to a 33% fallback unless explicitly told the speaker's current
  volume before `stream_file()`).
- **v0.7.6**: More resilient discovery for Wi-Fi roaming (faster scan
  interval, shorter cache, retry logic).
- **v0.7.7**: Fixed `active_preset` always being `null` for AirPlay; added
  resume-after-HA-restart via `AirPlayResumeStore`; fixed `turn_off`/
  `media_pause`/`media_stop` not actually ending the RAOP session.
- **v0.7.8**: UPnP AVTransport fallback when AirPlay discovery/connect fails
  (previously left the speaker "selected but silent").
- **v0.7.9**: AirPlay-mode devices verify `active_preset`/metadata against
  their own live pyatv stream state (`is_playing`) instead of trusting
  Bose's proven-unreliable `now_playing` self-report; fixed ICY metadata
  never refreshing for AirPlay; removed the hardcoded `"Bose Preset Router"`
  artist placeholder that caused display flicker. Live-verified against
  `.139`: AirPlay start correctly reports `active_preset`/`media_title`, and
  `media_stop` correctly clears `active_preset` back to `null` immediately.

## Open / possible future work

- No automated tests exist for this project — all verification is manual
  and live. Not currently planned to change (small single-user project).
- Real per-song metadata updates on the Bose display during AirPlay would
  require a periodic stream restart (audible glitch) — deliberately not
  implemented; current metadata comes from ICY polling instead.
- HomePod minis: already fully covered by the existing `player` routing mode
  via HA's own `apple_tv` integration (`media_player.homepod_*`) — no
  dedicated pyatv-based HomePod path was built, since HomePods need real
  AirPlay pairing/auth (unlike the old SoundTouch speakers) and building a
  parallel unauthenticated path risked conflicting with the existing
  `apple_tv` connection.
