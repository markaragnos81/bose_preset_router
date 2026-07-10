# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning.

## [0.7.15] - 2026-07-10

### Fixed

- Jedes Bose-Geraet erschien doppelt in Einstellungen > Geraete: einmal korrekt unter seinem Config-Untereintrag, einmal zusaetzlich unter "Geraete, die nicht zu einem Untereintrag gehoeren". Ursache: `media_player.py` und `select.py` haben alle Entities in einem einzigen `async_add_entities(...)`-Aufruf ohne `config_subentry_id` hinzugefuegt, wodurch HA sie nur mit dem Config-Entry als Ganzes statt mit dem jeweiligen Geraete-Untereintrag verknuepft hat. Entities werden jetzt pro Coordinator einzeln mit dem passenden `config_subentry_id` hinzugefuegt. Bereits bestehende doppelte "kein Untereintrag"-Eintraege aus frueheren Starts muessen einmalig manuell in Einstellungen > Geraete geloescht werden (Klick auf das Geraet unter "Geraete, die nicht zu einem Untereintrag gehoeren" > Loeschen) -- das automatisierte Fix verhindert nur neue Duplikate.

## [0.7.14] - 2026-07-10

### Fixed

- Ein ueber die HA-Geraeteseite deaktiviertes Bose-Geraet wurde weiterhin unbegrenzt per HTTP gepollt und per WebSocket verbunden, was fortlaufend Verbindungsfehler ins Log schrieb (z.B. "Cannot connect to host ..."). Deaktivierte Geraete (device_registry disabled_by gesetzt) werden jetzt beim Setup uebersprungen: kein Coordinator-Polling, keine WebSocket-Verbindungsversuche mehr. Betrifft nur den Start; ein reaktiviertes Geraet braucht wie ueblich einen Reload/Neustart, um wieder aufgenommen zu werden.

## [0.7.13] - 2026-07-05

### Fixed

- Home Assistant meldete einen blockierenden Aufruf im Event-Loop aus `airplay.py` (`AirPlay: ... stream_file`). Ursache ist ein internes, synchrones `time.sleep(0.1)` in pyatvs RAOP-Icecast-Reader, das nicht ueber unseren eigenen Code steuerbar ist. Die komplette pyatv-Verbindungs-/Stream-Lebensdauer laeuft jetzt in einem dedizierten Hintergrund-Thread mit eigenem Event-Loop, vollstaendig isoliert vom Haupt-Loop von Home Assistant, damit dieses blockierende Verhalten HA nicht mehr betrifft. Das oeffentliche Interface von `AirPlayPlayer` (play/stop/is_playing/set_on_ended) ist unveraendert.

## [0.7.12] - 2026-07-05

### Fixed

- Ein Geraet, das ausserhalb von Home Assistant ausgeschaltet wurde (Bose-App, physische Taste), wurde nach einem HA-Neustart faelschlich per AirPlay-Resume wieder eingeschaltet, weil `async_resume_airplay_devices()` blind auf den zuletzt gespeicherten Preset vertraute, ohne den tatsaechlichen Standby-Status des Geraets zu pruefen. Vor dem Resume wird jetzt der echte Bose-Status abgefragt; steht das Geraet auf STANDBY, wird der Resume uebersprungen und der veraltete Eintrag geloescht.

## [0.7.11] - 2026-07-03

### Fixed

- Radio-Metadaten (Sendername, Titel, Cover) konnten nach einem AirPlay-Resume oder Preset-Wechsel an einer stale UPNP-ContentItem-Meldung von Bose haengenbleiben, obwohl der eigene RAOP-Stream bereits korrekt lief. `_resolve_icy_url()` bevorzugt jetzt bei verifiziert laufender AirPlay-Session immer die eigene `active_stream_url`, bevor Bose's gemeldete `location` ausgewertet wird.

## [0.7.10] - 2026-07-03

### Changed

- Radio-Metadaten laufen jetzt ueber einen eigenen laufenden Stream-Tracker statt nur ueber punktuelle ICY-Abfragen beim Polling. Das trennt Senderdaten sauberer von Trackdaten und aktualisiert Titelwechsel robuster.

### Added

- Best-effort Cover-Art-Anreicherung fuer echte `Artist - Title`-Treffer aus ICY-Metadaten.
- Zusaeztliche Diagnose-Attribute am `media_player` fuer die StreamTitle-Klassifikation (`title_classification`, `title_decision_reason`, `is_station_branding`), damit problematische Sender leichter live analysiert werden koennen.

## [0.6.16] - 2026-06-28

### Changed

- Preset-Setup-Seite aufgeteilt: der "Globale Standards verwenden"-Schalter erscheint jetzt auf einer eigenen Seite. Bei Aktivierung wird die URL-Eingabe übersprungen; bei Deaktivierung folgt eine separate Seite mit allen 6 URL-Feldern. Verhindert das Abschneiden von Preset 6 durch die HA-Formular-Feldgrenze.
- Zwei weitere Umlauts-Fehler in config_flow.py behoben ("zunaechst" → "zunächst", "Geraet" → "Gerät")

## [0.6.15] - 2026-06-28

### Fixed

- Bose SoundTouch lehnt HTTPS-URLs in AVTransport und storePreset ab (Fehler 402 "No URI supplied"). `https://`-URLs werden jetzt automatisch auf `http://` herabgestuft, bevor sie an den Bose gesendet werden — sowohl beim AVTransport-Play als auch beim Preset-Speichern.

## [0.6.14] - 2026-06-28

### Fixed

- Umlaute und Sonderzeichen in allen deutschen UI-Texten korrigiert (ä, ö, ü, ß statt ae, oe, ue, ss)
- Reconfigure-Dialog zeigt jetzt in der Beschreibung einen Hinweis "Weiter → Standard-Stream-URLs", damit klar ist, dass nach OK ein zweiter Schritt mit den globalen Preset-URLs folgt

## [0.6.13] - 2026-06-28

### Changed

- Direkt-Routing (UPNP): Playback laeuft jetzt ueber UPnP AVTransport (`SetAVTransportURI` + `Play`) statt ueber `storePreset` + Tastendruck. Das entspricht dem Vorgehen von Music Assistant und funktioniert zuverlaessig auch dann, wenn der Bose den Stream-Hostnamen per DNS nicht selbst aufloesen kann (z.B. `.lan`-Adressen die nur im lokalen Custom-DNS bekannt sind).

## [0.6.12] - 2026-06-28

### Fixed

- Hotfix: `config_subentry_id` aus den Entity-`device_info`-Dicts entfernt — das Feld wird von dieser HA-Version nicht unterstuetzt und verhinderte, dass Entities ueberhaupt angelegt wurden ("Error adding entity None")

## [0.6.11] - 2026-06-28

### Changed

- Geraete-Preset-Setup auf eine einzige kompakte Seite zusammengefasst (statt zwei Seiten fuer Presets 1–3 und 4–6)
- Neuer Schalter "Globale Standard-URLs verwenden" auf der Preset-Seite: bei aktiviertem Schalter werden keine geraetespezifischen URLs gespeichert und die globalen Standards greifen automatisch
- Per-Preset-Lautstaerken (Expertenmodus) in den "Erweiterten Optionen"-Schritt verschoben
- Zusammenfassung zeigt jetzt "6 Presets (globale Standards)" statt "Keine", wenn der Schalter aktiv ist
- Behebt verwaiste Geraete-Eintraege unter "keine Untereintrag" durch Ergaenzung von `config_subentry_id` in den Entity-Geraetemeldungen

## [0.6.10] - 2026-06-28

### Fixed

- Direkt-Routing (UPNP): physischer Tastendruck auf dem Bose loeste `async_select_preset` ein zweites Mal aus (doppelter Tastendruck). Bei `reason=websocket` wird jetzt fruehzeitig zurueckgekehrt, da der Bose das Preset bereits selbst gewaehlt hat.

## [0.6.9] - 2026-06-28

### Changed

- Alle Setup-Seiten auf kompakte Einzelseiten ohne Scrollen umgestellt:
  - Globale Einstellungen: "Allgemein" (7 Felder) + "Standard-Presets" (6 URL-Felder) als separate Schritte
  - Geraete-Presets: aufgeteilt in "Presets 1–3" und "Presets 4–6"

## [0.6.8] - 2026-06-28

### Added

- Globale Standard-Stream-URLs fuer Presets 1–6 in den Haupteinstellungen der Integration. Die URLs gelten fuer alle Bose-Geraete und werden pro Geraet durch eine eigene URL ueberschrieben. Praktisch, um dieselben Streams nicht fuer jedes Geraet einzeln einzutragen.

## [0.6.7] - 2026-06-28

### Changed

- Routing-Setup in zwei separate Schritte aufgeteilt: erst Routing-Modus waehlen, dann — nur bei Modus "Weiterleitung" — Zielplayer auswaehlen. Das Zielplayer-Dropdown erscheint damit nicht mehr unnoetig bei "Nur Bose-Player" oder "Direkt via UPNP".

## [0.6.6] - 2026-06-28

### Fixed

- Verwaiste Geraete (Subentry wurde geloescht) koennen jetzt im HA UI geloescht werden

## [0.6.5] - 2026-06-28

### Added

- Neuer Routing-Modus `direct`: Presets werden direkt per UPNP auf dem Bose-Geraet abgespielt, ohne Music Assistant oder einen anderen Zielplayer. Lautstaerke wird dabei ebenfalls direkt am Bose-Geraet gesetzt. Der Modus ist im Geraete-Setup unter "Routing" als dritte Option waehlbar.

## [0.6.4] - 2026-06-28

### Changed

- Binary-Sensor-Platform entfernt — redundant, da der aktive Preset jetzt ueber das Attribut \`active_preset\` am \`media_player\` abgerufen werden kann

## [0.6.3] - 2026-06-28

### Fixed

- `active_preset` und Binary Sensors liefern jetzt zuverlaessig den aktiven Preset: statt der fragilen `now_playing`-Matching-Logik wird der Wert direkt vom Router beim `nowSelectionUpdated`-WebSocket-Event gesetzt und zurueckgesetzt wenn der Bose in Standby geht

## [0.6.2] - 2026-06-28

### Added

- Neues Attribut `active_preset` am `media_player`: gibt die aktuell aktive Preset-Nummer als Integer zurueck (z.B. `5`), oder `null` wenn kein Preset aktiv ist — direkt nutzbar in Automationen ohne Binary Sensors

## [0.6.1] - 2026-06-28

### Changed

- Button-Platform entfernt — die sechs Preset-Button-Entities waren redundant mit dem `play_preset`-Service und koennen daher entfallen
- Media-Player-Entity um vollstaendige Metadaten erweitert: `media_track`-Property sowie zusaetzliche Attribute `track`, `description`, `location`, `play_status`, `model`, `network_type` und `account`

## [0.6.0] - 2026-06-28

### Added

- Neue Methode `async_store_preset()` in der Bose-API: schreibt Presets per `/storePreset` mit `source="UPNP"` direkt auf das Geraet, funktioniert ohne Bose-Account und nach dem Cloud-Shutdown
- Auto-Provisioning beim Start: der Coordinator schreibt beim HA-Start alle konfigurierten Preset-URLs automatisch auf das Bose-Geraet, damit physische Tasten zuverlaessig erkannt werden
- Auto-Provisioning beim Setup/Reconfigure: Presets werden nach der Bestaetigungsseite sofort auf das Geraet geschrieben

### Changed

- Setup-Dialog: `preset_N_enabled`-Checkbox entfernt — eine eingetragene URL genuegt, um ein Preset zu aktivieren
- Router: leitet `enabled` jetzt aus der URL-Praesenz ab; ein explizit gesetztes `preset_N_enabled: false` wirkt weiterhin als Override (Backward Compatibility)
- Beschreibungstexte im Setup-Dialog erklaeren jetzt das Auto-Provisioning

## [0.5.2] - 2026-06-14

### Fixed

- HA-Deprecation-Warnung behoben: `add_update_listener`-Muster entfernt, das ab HA 2026.12 nicht mehr unterstuetzt wird

## [0.5.1] - 2026-05-10

### Changed

- Entfernte die dunklen Brand-Assets `dark_icon.png` und `dark_logo.png`, so dass nur noch das helle Logo-Set fuer die Integration verwendet wird

## [0.5.0] - 2026-05-10

### Changed

- Ueberarbeitete den kompletten Bose-Geraete-Setup-Dialog mit Quick- und Expertenmodus, separaten Schritten fuer Geraet, Routing, Presets, erweiterte Optionen und Zusammenfassung
- Trennt die reine Bose-Geraeteanlage jetzt klarer von der optionalen Preset-Weiterleitung an Music Assistant oder andere Home-Assistant-Player
- Ersetzt die bisherigen zwei Preset-Unterseiten durch eine gemeinsame Preset-Uebersicht fuer alle sechs Presets
- Fuegt vor dem Speichern eine echte Zusammenfassung mit Geraet, Modell, Bose-ID, Routingziel, aktiven Presets und Hinweisen hinzu

### Fixed

- Reparierte die Bose-Autodiscovery fuer aktuelle Home-Assistant-SSDP-Objekte, indem der Config-Flow nicht mehr von Dictionary-Zugriffen auf `SsdpServiceInfo` ausgeht
- Faengt SSDP-Discovery-Fehler im Setup-Dialog jetzt sauber ab, so dass statt `Unknown error occurred` ein normaler Formularfehler angezeigt wird

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
