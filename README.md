# Bose Preset Router

Benutzerdefinierte Home-Assistant-Integration, die Preset-Tastendruecke von Bose SoundTouch-Geraeten erkennt und jedes Preset an einen Music-Assistant-Zielplayer weiterleitet.

Die Integration ist fuer Setups gedacht, in denen ein Bose SoundTouch als physische Preset-Fernbedienung dient, waehrend die eigentliche Wiedergabe von Music Assistant uebernommen wird.

## Funktionen

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

1. Die Integration oeffnet zu jedem konfigurierten Bose-SoundTouch-Geraet eine Websocket-Verbindung auf Port `8080`.
2. Bei einem erkannten Preset-Tastendruck werden Preset-Nummer und Bose-Metadaten ausgelesen.
3. Die konfigurierte Stream-URL wird per `media_player.play_media` an den ausgewaehlten Home-Assistant- bzw. Music-Assistant-Player uebergeben.
4. Die Uebergabe wird auf zwei Wegen geprueft:
   - ueber den Zielplayer-Zustand in Home Assistant
   - ueber den Bose-`now_playing`-Endpunkt auf Port `8090`, inklusive erfolgreicher AirPlay-Uebergabe mit Metadaten
5. Wenn die Verifikation fehlschlaegt, wird die Wiedergabe gemaess der konfigurierten Retry-Einstellungen erneut versucht.

## Voraussetzungen

- Home Assistant mit Unterstuetzung fuer Custom Integrations
- Ein Bose-SoundTouch-Geraet, das im lokalen Netzwerk erreichbar ist
- Music Assistant oder ein anderer kompatibler Home-Assistant-`media_player`
- Netzwerkzugriff von Home Assistant auf:
  - Bose-Websocket: `ws://<bose_ip>:8080/`
  - Bose-Statusendpunkt: `http://<bose_ip>:8090/now_playing`

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

Standardwerte fuer die Verifikation:

- `3` Versuche
- `1.5` Sekunden zwischen den Pruefungen

### Geraetekonfiguration

Die Geraetekonfiguration ist in mehrere Schritte aufgeteilt:

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

## Dienst

Die Integration stellt einen Test-Dienst bereit:

```yaml
service: bose_preset_router.trigger_preset
data:
  device: Wohnzimmer Bose
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
- bei der Bose-seitigen AirPlay-Uebergabe

## HACS-Hinweise

Dieses Repository ist fuer HACS als Custom Repository vorbereitet, ueber [`hacs.json`](hacs.json).

Das aktuelle Layout bleibt im Repository-Root und verwendet:

```json
"content_in_root": true
```

## Dokumentation

- Funktionsuebersicht: [`docs/FUNCTIONS.md`](docs/FUNCTIONS.md)
- Veroeffentlichungs-Checkliste: [`docs/PUBLISHING.md`](docs/PUBLISHING.md)

## Lizenz

Dieses Repository verwendet die MIT-Lizenz. Details stehen in [`LICENSE`](LICENSE).
