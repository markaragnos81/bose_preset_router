# Bose Preset Router

Benutzerdefinierte Home-Assistant-Integration fuer Bose-SoundTouch-Geraete mit lokalem `media_player`, Preset-Steuerung, Multiroom-Funktionen und integrierter Preset-Router-Logik.

Die Integration ist fuer Setups gedacht, in denen Bose-SoundTouch-Geraete nach dem Wegfall der Bose-Cloud-Dienste weiterhin lokal in Home Assistant nutzbar bleiben sollen. Neben der direkten Geraetesteuerung bleibt auch die urspruengliche Router-Idee erhalten: Bose-Presets koennen weiterhin als physische Preset-Fernbedienung fuer Music Assistant oder andere Home-Assistant-`media_player` dienen.

## Funktionen

- Lokaler Bose-SoundTouch-`media_player` pro Geraet
- Anzeige des aktuellen Bose-Wiedergabestatus ueber `now_playing`
- Direkte Preset-Steuerung in Home Assistant
  - per `play_preset`-Service
  - per Preset-`select`
  - per sechs Preset-Buttons pro Geraet
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
5. Suche in HACS nach `Bose Preset Router` und installiere die Integration.
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

## Dokumentation

- Funktionsuebersicht: [`docs/FUNCTIONS.md`](docs/FUNCTIONS.md)
- Veroeffentlichungs-Checkliste: [`docs/PUBLISHING.md`](docs/PUBLISHING.md)
- Changelog: [`CHANGELOG.md`](CHANGELOG.md)

## Lizenz

Dieses Repository verwendet die MIT-Lizenz. Details stehen in [`LICENSE`](LICENSE).
