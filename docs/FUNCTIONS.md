# Function Overview

## Purpose

`Bose Preset Router` bridges physical Bose SoundTouch preset buttons with Home Assistant and Music Assistant playback.

Instead of letting the Bose speaker keep the original preset source locally, the integration can treat the preset press as a trigger and start a configured stream on another player.

## Functional Blocks

### 1. Bose websocket listener

- Connects to the Bose SoundTouch websocket on port `8080`
- Listens for `nowSelectionUpdated` events
- Extracts the preset number and Bose metadata from incoming XML-like payloads

### 2. Device mapping

Each configured Bose speaker contains:

- Bose IP address
- Target `media_player`
- Optional default volume
- Six possible preset mappings

Each preset mapping contains:

- enabled / disabled state
- stream URL
- optional per-preset volume override

### 3. Debounce protection

The integration suppresses duplicate preset triggers that happen within the configured debounce window.

This helps with repeated websocket events or accidental double presses.

### 4. Stream routing

When a valid preset is triggered:

- the target volume is optionally adjusted
- `media_player.play_media` is called with the configured stream URL

### 5. Verification and retry logic

After playback is requested, the integration verifies the handoff:

- via Home Assistant player state
- via Bose `now_playing` on port `8090`

If the handoff is not confirmed, playback is retried according to the configured settings.

### 6. Bose-side handoff confirmation

The Bose `now_playing` endpoint is used to confirm that the speaker has transitioned into an `AIRPLAY` playback state with metadata such as:

- track
- artist
- album
- item name
- station name

### 7. Notifications and logs

Optional persistent notifications can be shown in Home Assistant.

Detailed logs help identify:

- preset detection success
- Bose preset confirmation
- Home Assistant player confirmation
- Bose AirPlay handoff confirmation
- final handoff failure after retries

## User-Facing Configuration

### Global settings

- notifications on preset press
- debug logging
- debounce timing
- retry count
- retry delay

### Per device settings

- Bose IP
- target player
- default volume
- per-preset enable flag
- per-preset URL
- per-preset volume
