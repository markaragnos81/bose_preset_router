# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

- No unreleased changes yet.

## [0.3.3] - 2026-04-10

### Fixed

- Removed invalid global `reconfigure` translation keys from `strings.json` and `translations/en.json`
- Added an explicit `CONFIG_SCHEMA` to satisfy Home Assistant validation for `async_setup`
- Adjusted the Hassfest workflow to validate the integration from a generated `custom_components/bose_preset_router` path
- Updated GitHub Actions checkout steps to `actions/checkout@v5` to avoid the Node.js 20 deprecation warning

## [0.3.2] - 2026-04-10

### Fixed

- Accepted Bose `now_playing` handoffs via UPNP as well as AirPlay after Music Assistant playback changes
- Tightened Bose-side handoff verification so unchanged metadata no longer counts as a successful transfer
- Returned early when Bose preset confirmation fails instead of continuing the routing pipeline
- Aligned manager startup with the synchronous `async_start()` implementation in `__init__.py`

### Changed

- Updated the README to describe Bose-side verification more accurately for both AirPlay and UPNP handoffs

## [0.3.1] - 2026-04-04

### Added

- MIT license for the public repository
- Local Home Assistant brand assets in `brand/`
- Project changelog and release workflow documentation

### Changed

- Updated `manifest.json` links to the real GitHub repository
- Reduced branding asset sizes for repository and UI use
- Cleaned up outdated publishing notes in the README

## [0.3.0] - 2026-04-04

### Added

- Initial public release of the Bose Preset Router integration
- Config flow for Bose device and preset mapping setup
- Bose preset detection over the SoundTouch websocket
- Stream routing to a target Home Assistant or Music Assistant player
- Retry and verification logic for media handoff
- Optional notifications and verbose logging
- German and English translations
