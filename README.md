# Bose SoundTouch LocalControl

Benutzerdefinierte Home-Assistant-Integration fuer Bose-SoundTouch-Geraete mit lokalem `media_player`, Preset-Steuerung, Multiroom-Funktionen und integrierter Preset-Router-Logik.

Die Integration ist fuer Setups gedacht, in denen Bose-SoundTouch-Geraete nach dem Wegfall der Bose-Cloud-Dienste weiterhin lokal in Home Assistant nutzbar bleiben sollen. Neben der direkten Geraetesteuerung bleibt auch die urspruengliche Router-Idee erhalten: Bose-Presets koennen weiterhin als physische Preset-Fernbedienung fuer Music Assistant oder andere Home-Assistant-`media_player` dienen.

## Wichtig Fuer Nutzer Von `0.4.3`

Wenn du per HACS direkt von `0.4.3` auf `0.4.13` springst, aendert sich nicht nur das Branding, sondern auch der fachliche Umfang der Integration deutlich.

Seit `0.4.4+` ist aus dem frueheren Preset-Router eine deutlich umfassendere lokale Bose-SoundTouch-Integration geworden:

- Bose-Geraete werden als eigene `media_player`-Entities in Home Assistant angelegt
- Presets koennen direkt in Home Assistant gesteuert werden
- Bose-Quellen, Presets und Status werden lokal aus der SoundTouch-API gelesen
- Multiroom-/Zonenfunktionen sind vorbereitet
- Discovery und Geraete-Setup wurden erweitert
- Die urspruengliche Router-Funktion fuer Music Assistant bleibt erhalten

Kurz gesagt:

- `0.4.3` war noch stark auf Routing fokussiert
- `0.4.13` ist eine lokale Bose-SoundTouch-Integration mit integriertem Preset-Routing

## Was Sich Seit `0.4.3` Geaendert Hat

### Neue Bose-Entities

Pro Bose-Geraet werden jetzt mehrere Home-Assistant-Entities angelegt:

- ein eigener Bose-`media_player`
- ein Preset-`select`
- sechs Preset-`button`-Entities
- sechs Preset-`binary_sensor`-Entities fuer den aktiven Preset-Status

### Direkte Bose-Steuerung

Der Bose-`media_player` unterstuetzt jetzt unter anderem:

- Ein- und Ausschalten
- Play, Pause und Stop
- Vor und Zurueck
- Lautstaerke und Mute
- Quellen-Auswahl
- Preset-Auswahl
- `browse_media` fuer Presets, Quellen und Zonen

### Verbesserte Router-Architektur

Die Router-Funktion ist weiterhin da, arbeitet jetzt aber auf derselben SoundTouch-Basis wie der Bose-`media_player`. Das bedeutet:

- Bose-Preset-Tastendruecke werden lokal erkannt
- die Weitergabe an Music Assistant oder andere `media_player` bleibt moeglich
- Bose-Status und Routing greifen auf dieselbe lokale Geraeteschicht zu

### Setup Und Discovery

Das Setup ist nicht mehr nur eine reine Preset-Konfiguration. Die Integration fuehrt dich jetzt durch:

- Geraeteerkennung per SSDP
- manuelles Hinzufuegen per Bose-IP
- Anlegen eines echten Bose-Geraets in Home Assistant
- Preset-Zuordnung und Zielplayer-Konfiguration

## Update-Hinweise Fuer Bestehende Installationen

Wenn du von `0.4.3` kommst, sind diese Punkte wichtig:

1. Nach dem Update Home Assistant einmal komplett neu starten.
2. Die Integration danach einmal oeffnen und pruefen, ob Bose-Geraete und Entities sauber angelegt wurden.
3. Falls alte doppelte Bose-Geraete sichtbar sind, die Integration einmal neu laden und veraltete Altgeraete im Zweifel manuell entfernen.
4. Falls dein Routing bisher ueber Music Assistant lief, pruefe den hinterlegten Zielplayer pro Bose-Geraet.
5. Wenn Bose-Preset-Bestaetigungen zu streng sind, pruefe die Optionen fuer strenge oder tolerante Bose-Bestaetigung.

## Empfohlener Erster Check Nach Dem Update

Nach dem Update auf `0.4.13` solltest du kurz diese Punkte pruefen:

- Der Bose-`media_player` ist vorhanden und verfuegbar
- Preset-`select` und Preset-Buttons sind vorhanden
- Die neuen Preset-Statussensoren wechseln beim Umschalten korrekt
- `media_title`, `media_artist`, Cover und Quelle werden sinnvoll angezeigt
- `turn_off` funktioniert auf deinem Bose ueber `standby`
- Das Routing an Music Assistant funktioniert weiterhin wie erwartet

## Welche Version Ist Fuer Was Relevant

- `0.4.4`:
  erster groesserer Umbau Richtung echte Bose-Integration
- `0.4.5` bis `0.4.9`:
  Stabilisierung von Reload, Device-Registry, Config-Flow und Bose-spezifischen Eigenheiten
- `0.4.10` und `0.4.11`:
  bessere Darstellung von Titeln, Radiometadaten und Cover
- `0.4.12`:
  neue offizielle Brand-Assets fuer HA/HACS
- `0.4.13`:
  sichtbarer aktiver Preset-Status ueber `binary_sensor`

## Funktionen

- Lokaler Bose-SoundTouch-`media_player` pro Geraet
- Anzeige des aktuellen Bose-Wiedergabestatus ueber `now_playing`
- Direkte Preset-Steuerung in Home Assistant
  - per `play_preset`-Service
  - per Preset-`select`
  - per sechs Preset-Buttons pro Geraet
  - per sechs Preset-Statussensoren zur Anzeige des aktuell aktiven Presets
- Quellen-Browsing und Quellen-Auswahl im `media_player`
- Multiroom-/Zonen-Services fuer Bose-SoundTouch-Geraete
- Discovery-unterstuetztes Setup ueber SSDP und lokale Bose-API-Pruefung
- Erkennt Bose-Preset-Tastendruecke ueber den SoundTouch-Websocket auf Port `8080`
- Unterstuetzt mehrere Bose-Geraete innerhalb einer Integration
- Ordnet die Presets `1` bis `6` individuellen Stream-URLs zu
- Startet die Wiedergabe auf einem ausgewaehlten Music-Assistant- bzw. Home-Assistant-`media_player`
- Optionale Standardlautstaerke und Preset-spezifische Lautstaerke
- Entprellung fuer wiederholte Tastendruecke
- Verifikation der Stream-Uebergabe mit Retry-Logik
- Zusaetzliche Bose-seitige Pruefung ueber `http://<bose_ip>:8090/now_playing`
- Optionale persistente Benachrichtigungen zur Fehlersuche
- Deutsche und englische Uebersetzungen

## So Funktioniert Es

1. Die Integration baut pro Bose-SoundTouch-Geraet eine lokale SoundTouch-Verbindung auf.
2. Statusdaten wie `info`, `now_playing`, `presets` und `sources` werden ueber die lokale Bose-API auf Port `8090` gelesen.
3. Ein `media_player` pro Geraet bildet Wiedergabe, Quellen, Presets und weitere Bose-Informationen in Home Assistant ab.
4. Zusaetzlich wird pro Geraet ein Websocket auf Port `8080` geoeffnet, damit Preset-Tastendruecke und Statusaenderungen schnell erkannt werden.
5. Wenn die Router-Funktion genutzt wird, leitet die Integration erkannte Bose-Presets an einen ausgewaehlten Home-Assistant- bzw. Music-Assistant-Player weiter.
6. Die Uebergabe wird ueber den Zielplayer-Zustand in Home Assistant und optional ueber Bose-`now_playing` verifiziert.

## Voraussetzungen

- Home Assistant mit Unterstuetzung fuer Custom Integrations
- Ein Bose-SoundTouch-Geraet, das im lokalen Netzwerk erreichbar ist
- Optional: Music Assistant oder ein anderer kompatibler Home-Assistant-`media_player` fuer die Router-Funktion
- Netzwerkzugriff von Home Assistant auf:
  - Bose-Websocket: `ws://<bose_ip>:8080/`
  - Bose-SoundTouch-API: `http://<bose_ip>:8090/`

## Installation

### HACS Custom Repository

1. Oeffne HACS in Home Assistant.
2. Oeffne das Menue und waehle `Custom repositories`.
3. Fuege die URL deines GitHub-Repositories hinzu.
4. Kategorie: `Integration`.
5. Suche in HACS nach `Bose SoundTouch LocalControl` und installiere die Integration.
6. Starte Home Assistant neu.
7. Fuege die Integration unter `Einstellungen -> Geraete & Dienste` hinzu.

### Manuelle Installation

1. Kopiere diesen Ordner nach:

```text
custom_components/bose_preset_router
```

2. Starte Home Assistant neu.
3. Fuege die Integration unter `Einstellungen -> Geraete & Dienste` hinzu.

## Konfiguration

### Hauptkonfiguration

- Benachrichtigung anzeigen, wenn ein Preset gedrueckt wird
- Ausfuehrliches Logging aktivieren
- Wiederholte Tastendruecke fuer eine konfigurierbare Zeit ignorieren
- Anzahl der Wiederholungsversuche fuer die Verifikation der Stream-Uebergabe festlegen
- Wartezeit zwischen den Verifikationsrunden festlegen
- Bose-Preset-Bestaetigung streng oder tolerant auswerten

Standardwerte fuer die Verifikation:

- `3` Versuche
- `1.5` Sekunden zwischen den Pruefungen

### Geraetekonfiguration

Die Geraetekonfiguration ist in mehrere Schritte aufgeteilt:

- Geraet automatisch im Netzwerk finden oder manuell anlegen
- Basisdaten des Lautsprechers
- Presets `1` bis `3`
- Presets `4` bis `6`

Pro Bose-Geraet koennen folgende Werte konfiguriert werden:

- Name des Lautsprechers
- Bose-IP-Adresse
- Zielplayer fuer Music Assistant
- Optionale Standardlautstaerke
- Pro Preset:
  - Aktiviert oder deaktiviert
  - Stream-URL
  - Optionale Preset-Lautstaerke

## Home-Assistant-Funktionen

### Bose als `media_player`

Pro Bose-Geraet wird ein eigener `media_player` angelegt. Darueber sind unter anderem moeglich:

- Wiedergabe starten, pausieren und stoppen
- Lautstaerke setzen und stummschalten
- Quellen auswaehlen
- Presets auswaehlen
- Quellen und Presets ueber `browse_media` durchsuchen

### Presets in Home Assistant

Die Bose-Presets koennen in Home Assistant direkt ausgeloest werden:

- ueber den Service `bose_preset_router.play_preset`
- ueber ein Preset-`select` pro Geraet
- ueber sechs Preset-Buttons pro Geraet

Zusaetzlich stellt die Integration sechs `binary_sensor`-Entities pro Geraet bereit, damit in Dashboards sichtbar ist, welches Preset aktuell aktiv ist:

- `binary_sensor.<geraet>_preset_1_aktiv`
- `binary_sensor.<geraet>_preset_2_aktiv`
- `binary_sensor.<geraet>_preset_3_aktiv`
- `binary_sensor.<geraet>_preset_4_aktiv`
- `binary_sensor.<geraet>_preset_5_aktiv`
- `binary_sensor.<geraet>_preset_6_aktiv`

### Multiroom / Zonen

Fuer Bose-Multiroom-Zonen stehen Services bereit:

- `bose_preset_router.create_zone`
- `bose_preset_router.add_zone_members`
- `bose_preset_router.remove_zone_members`
- `bose_preset_router.clear_zone`

## Dienste

### Router-Test

Die Integration stellt einen Test-Dienst bereit:

```yaml
service: bose_preset_router.trigger_preset
data:
  device: Wohnzimmer Bose
  preset: 1
```

### Bose-Preset direkt ausloesen

```yaml
service: bose_preset_router.play_preset
data:
  device: Bose-Portable
  preset: 1
```

## Logging Und Verifikation

Die Integration protokolliert die Routing-Pipeline in klar getrennten Stufen, unter anderem:

- `preset_detected`
- `bose_preset_confirmation`
- `play_media_send`
- `player_verification_ok`
- `player_verification_failed`
- `bose_handoff_failed`
- `handoff_complete`
- `handoff_failed`

Damit laesst sich leichter erkennen, ob ein Fehler aufgetreten ist:

- bei der Preset-Erkennung am Bose
- beim `play_media`-Aufruf
- bei der Pruefung des Home-Assistant-Playerzustands
- bei der Bose-seitigen Stream-Uebergabe, etwa per AirPlay oder UPNP

## HACS-Hinweise

Dieses Repository ist fuer HACS als Custom Repository vorbereitet, ueber [`hacs.json`](hacs.json).

Das aktuelle Layout bleibt im Repository-Root und verwendet:

```json
"content_in_root": true
```

Fuer HACS-Releases gilt:

- die Integration liegt absichtlich im Repository-Root
- Versionen werden ueber `manifest.json` gepflegt
- fuer HACS sichtbare Versionen werden als Git-Tags wie `v0.4.14` veroeffentlicht

## Dokumentation

- Funktionsuebersicht: [`docs/FUNCTIONS.md`](docs/FUNCTIONS.md)
- Veroeffentlichungs-Checkliste: [`docs/PUBLISHING.md`](docs/PUBLISHING.md)
- Changelog: [`CHANGELOG.md`](CHANGELOG.md)

## Lizenz

Dieses Repository verwendet die MIT-Lizenz. Details stehen in [`LICENSE`](LICENSE).
