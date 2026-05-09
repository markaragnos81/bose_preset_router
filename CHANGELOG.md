# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [Unreleased]

- No unreleased changes yet.

## [0.4.14] - 2026-05-09

### Changed

- Erweitere die README deutlich fuer Nutzer, die per HACS direkt von `0.4.3` auf die neue lokale SoundTouch-Architektur aktualisieren, inklusive Update-Hinweisen, Funktionsueberblick und Migrationskontext

## [0.4.13] - 2026-05-09

### Added

- Fuegte zusaetzliche `binary_sensor`-Entities fuer `Preset 1` bis `Preset 6` hinzu, damit in Home Assistant sichtbar und fuer Dashboards nutzbar ist, welches Bose-Preset aktuell aktiv ist

## [0.4.12] - 2026-05-09

### Changed

- Ersetzte die lokalen Brand-Assets durch die neuen hellen und dunklen `icon`-/`logo`-Varianten im `brand/`-Ordner, wie von der aktuellen Home-Assistant- und HACS-Dokumentation fuer Custom Integrations vorgesehen

## [0.4.11] - 2026-05-09

### Changed

- Ergaenzte fuer Cover und Radiometadaten einen Fallback auf den konfigurierten Ziel-Player, damit bei Music-Assistant-Weitergabe fehlende Bose-Artworks besser aus der eigentlichen Wiedergabequelle uebernommen werden koennen

## [0.4.10] - 2026-05-09

### Changed

- Priorisierte in der Player-Darstellung echte `now_playing`-Metadaten wie Track, Artist und Album vor reinen Quellenlabels wie `AIRPLAY`, damit die Home-Assistant-Media-Karte die laufenden Inhalte sinnvoller anzeigt

## [0.4.9] - 2026-05-09

### Fixed

- Korrigierte einen fehlenden `callback`-Import in `__init__.py`, der den Config-Flow mit `Invalid handler specified` blockierte

## [0.4.8] - 2026-05-09

### Fixed

- Fuegte eine automatische Bereinigung fuer alte Bose-Device-Registry-Eintraege hinzu, damit fruehere Duplikate ohne stabilen Subentry-Identifier beim Setup von der Config Entry geloest werden koennen
- Aktivierte die manuelle Geraeteloeschung fuer veraltete Bose-Registry-Eintraege im Home-Assistant-UI, damit verbliebene Altgeraete gezielt entfernt werden koennen

## [0.4.7] - 2026-05-09

### Fixed

- Schaltete `turn_off` fuer SoundTouch-Geraete auf den lokal verifizierten `GET /standby`-Pfad um, nachdem das bisherige XML-POST auf deinem Bose mit `400 Bad Request` scheiterte

## [0.4.6] - 2026-05-09

### Fixed

- Stellte die Device-Registry-Identifikation fuer Bose-Geraete auf einen stabilen, subentry-basierten Identifier um, damit Home Assistant nicht mehr zwischen IP- und Bose-Device-ID wechselt und dadurch doppelte Geraeteeintraege erzeugt
- Liess alle Bose-Entities konsistent an demselben stabilen Geraet haengen, statt bei spaeter verfuegbaren Bose-Metadaten ein zweites Device zu erzeugen

## [0.4.5] - 2026-05-09

### Fixed

- Haertete den Entry-Unload gegen teilweise oder fehlgeschlagene Plattform-Loads ab, damit Reloads nicht mehr mit `Config entry was never loaded!` scheitern
- Stellte den internen Update-Listener auf das offizielle Home-Assistant-Reload fuer Config Entries um, statt den Entry manuell zu entladen und neu aufzubauen

## [0.4.4] - 2026-05-09

### Changed

- Machte den Music-Assistant-Zielplayer im Bose-Geraete-Setup optional, damit das Bose-Geraet zuerst sauber als Home-Assistant-Entity angelegt werden kann
- Liess die Preset-Router-Logik bewusst beim bestehenden Music-Assistant-/Media-Player-Routing und entfernte den zwischenzeitlich ausprobierten direkten lokalen Stream-Pfad wieder

### Fixed

- Verknuepfte Bose-Geraete explizit mit ihrem Config-Subentry, damit die erzeugten Entities im Home-Assistant-UI sauber unter dem passenden Untereintrag erscheinen
- Bereinigte die Haupt-`media_player`-Benennung, damit keine doppelt zusammengesetzten Entity-Namen entstehen
- Behandelte optionale SoundTouch-Endpunkte wie `zone` und `sources` toleranter, damit einzelne nicht unterstuetzte Bose-Endpunkte den gesamten Player nicht auf `nicht verfuegbar` ziehen

## [0.4.3] - 2026-05-09

### Fixed

- Sortierte die `manifest.json` wieder Hassfest-konform, damit die Integration in CI nicht mehr an der Manifest-Reihenfolge scheitert
- Fuegte den Root-Titel in `strings.json` hinzu, damit die Home-Assistant-Stringdefinitionen auf dem aktuellen Erwartungsstand liegen

## [0.4.2] - 2026-05-09

### Changed

- Stellte das sichtbare Branding auf `Bose SoundTouch LocalControl` um, ohne den technischen Integrations-Domainnamen zu aendern
- Aktualisierte README, HACS-Metadaten und die Benutzeroberflaechen-Titel auf den neuen Produktnamen
- Ersetzte das bisherige, zu nah am Bose-Original orientierte Branding durch ein eigenstaendiges Icon- und Logo-Set

## [0.4.1] - 2026-05-09

### Changed

- Ueberarbeitete die deutschsprachige Projektbeschreibung und README fuer den neuen Stand als lokale Bose-SoundTouch-Integration mit `media_player`, Preset-Steuerung, Discovery und Multiroom-Funktionen
- Erhoehte die Version nach dem Dokumentations- und Beschreibungspolishing auf `0.4.1`

## [0.4.0] - 2026-05-09

### Added

- Neue lokale SoundTouch-Grundlage mit gemeinsamer Bose-API, Geraete-Koordinatoren und einer ersten vollwertigen `media_player`-Implementierung
- Home-Assistant-Steuerung fuer Bose-Presets ueber `play_preset`, Preset-`select`-Entities und sechs Preset-Buttons pro Geraet
- Bose-Quellen-Browsing und Quellen-Auswahl im `media_player`
- Bose-Multiroom-Services zum Erstellen von Zonen sowie zum Hinzufuegen, Entfernen und Leeren von Mitgliedern
- Discovery-unterstuetztes Geraete-Setup ueber Home-Assistant-SSDP mit anschliessender Bose-API-Pruefung

### Changed

- Integrierte die urspruengliche Preset-Router-Logik in die neue SoundTouch-Architektur, so dass Routing und direkte Geraetesteuerung dieselbe Bose-Zustandsbasis verwenden

## [0.3.6] - 2026-04-10

### Fixed

- Resolved preset device handoff mismatches by resolving websocket events to configured devices via Bose IP before falling back to the device name
- Added configurable Bose preset confirmation behavior so strict confirmation can be disabled and tolerant confirmation can be enabled for speakers with inconsistent `now_playing` metadata

## [0.3.5] - 2026-04-10

### Fixed

- Avoided a `KeyError` when Home Assistant unloads a config entry that is no longer present in `hass.data`
- Hardened setup/unload bookkeeping by always initializing the domain store before registering a manager

## [0.3.4] - 2026-04-10

### Fixed

- Sorted `manifest.json` keys to match Hassfest requirements
- Added the required `entry_type` for the `device` config subentry translations
- Changed the Hassfest workflow to validate only the generated `custom_components` layout, avoiding duplicate root-level integration detection

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
