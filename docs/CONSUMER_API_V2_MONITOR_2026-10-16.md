# WeatherRouter – Consumer API V2 und universeller API-Monitor

**Entwicklungsstand:** 16.10.2026 · zusammenhängender V1/V2-Integrationskandidat. Vor produktiver Verwendung HA-Realabnahme erforderlich.

## Architektur

Consumer API V1 (`weather_router/consumer/resolve`) bleibt mit `contract_version: 1` unverändert nutzbar. V2 wird zusätzlich als `weather_router/consumer/resolve_mosaic`, `contract_version: 2`, registriert. Beide Befehle sind lesend. WeatherRouter speichert keine Orte, und die vom Verbraucher gelieferte `consumer_id` ist nur Diagnosemetadatum, keine Autorisierung. Profil-/Providerberechtigungen werden weiterhin serverseitig bewertet.

Die Mehrquellen-Auswahl nutzt tatsächliche Abdeckung, zeitliche Gültigkeit, fachliche Eignung und begrenzte Quellenkontakte. Eine regional passende Quelle darf keine globale Darstellung verdrängen, wenn sie nur eine kleine Randfläche des angeforderten Viewports abdeckt.

### V2-Anfrage

```json
{
  "type": "weather_router/consumer/resolve_mosaic",
  "contract_version": 2,
  "capability": "weather.precipitation.layer",
  "consumer_id": "gewitterradar",
  "correlation_id": "gr-example-request-001",
  "context": {"type":"bbox","west":-85,"south":18,"east":-73,"north":25},
  "time": {"mode":"latest_coherent","max_data_age_seconds":3600},
  "limits": {"max_layers":4,"max_tile_requests":64}
}
```

`consumer_id` (maximal 96 Zeichen), `correlation_id` (maximal 128 Zeichen) sowie `profile_id` sind optional. Fehlende Consumer-Kennungen bleiben zulässig. V1 unterstützt dieselben optionalen Herkunfts-/Korrelationsfelder ohne Änderung des bisherigen Antwortformats.

Die Anzahl verfügbarer Mosaikquellen beträgt maximal zwölf Quellenkontakte pro Anfrage; gleichzeitig höchstens drei Coverage- und drei Rasterkontakte je Eventloop sowie zwei V2-Auflösungen. `max_layers` und `max_tile_requests` sind getrennte Grenzen. Der tatsächliche Renderer muss das Kachelbudget zusätzlich selbst einhalten. Ein Fehler einzelner Provider führt grundsätzlich zur kontrollierten Degradierung, nicht zum Verwerfen aller anderen geeigneten Daten.

### Technischer V2-Rückfall

Technische Fehler wie `mosaic_busy`, `router_not_ready` oder `mosaic_temporarily_unavailable` dürfen vom Consumer unter Wahrung derselben Korrelationskennung gezielt in eine V1-Anfrage überführt werden. `no_data` ist **kein** generischer technischer Ausfall. WeatherRouter protokolliert zwei Aufrufe, erkennt aber nicht eigenständig eine absichtlich ausgeführte Fallback-Kette. Gewitterradar muss diese Entscheidung selbst markieren.

## API-Monitor in WeatherRouter Lab

Der Bereich `API-Monitor · Consumer V1 / V2` erscheint in den Diagnosewerkzeugen. Der Recorder läuft nur im Speicher, ist nach dem Start standardmäßig AUS und muss durch den HA-Administrator ausdrücklich gestartet werden. Nach Stop/Unload werden die Einträge verworfen, nach HA-Neustart ist er erneut AUS.

**Harte Obergrenzen:** 250 Einträge, 512 KiB, maximale Lebensdauer 3600 Sekunden, höchstens 8192 Bytes pro Eintrag. Eine laufende Aufzeichnung darf die eigentliche Consumer-Antwort nicht verändern. Es werden keine Binär-/Rasterdaten oder vollständigen Providerantworten gespeichert. Standardmäßig werden Koordinaten verborgen; Zugangsdaten, signierte URLs und große Textwerte werden bereinigt. Die Consumer-Kennung ist nicht vertrauenswürdig; die separate HA-Verbindungskennung dient nur zur technischen Zuordnung.

Administratoren stehen folgende WebSocket-Befehle zur Verfügung:

- `weather_router/api_monitor/status` – Aufzeichnungszustand und Grenzen
- `weather_router/api_monitor/configure` – `enabled` boolesch; optional `clear` und `allow_locations`
- `weather_router/api_monitor/query` – begrenzte, gefilterte Abfrage und JSON-Snapshot

Filter: `api_version`, `consumer`, `command`, `capability`, `provider`, `result`, `correlation_id`, `request_id`, `session_id`, `since`, `until`, `min_duration_ms`, `max_duration_ms`, `search`. Filter werden kombiniert. Zeiten werden als UTC-ISO-8601 übermittelt.

Das Exportformat heißt `weather_router.api_monitor.v1` und enthält die Felder `captured_at`, `recording`, `session_id`, `record_count`, `entries` und `buffer_bytes`. Jede Anfrage besitzt zusätzlich eine serverseitige `request_id`.

Der Monitor bietet Zwischenablage, lokalen JSON-Export und Export2Git. Der Git-Export verwendet **ausschließlich** den vorhandenen administrativen Befehl `weather_router/log_git_export` und dessen abgesichertes privates Diagnosearchiv. Ausführungen in öffentliche Quellen-Repositories sind zu verhindern. Für Archiv-Exporte muss die vorhandene Git-Konfiguration vollständig eingerichtet sein.

## Prüfumfang und Grenzen

Automatisierte Pub-Dev-Prüfungen umfassen Python 3.12/3.13, Python-Regressionssuite, JS-Syntax, P7-010-Vertrags-/Serviceprüfungen, Testaufzeichnungen, Datenschutz und Speichergrenzen. Das ist **keine HA-Realabnahme**. Insbesondere sind echte Kartenbudgets im Gewitterradar-Renderer, laufende GR-Fallback-Korrelation, Netzwerkausfälle und der Kuba/Deutschland/DWD-Fall in HA getrennt zu prüfen. Bei einem fehlgeschlagenen technischen Prüfschritt erfolgt keine DRA-Freigabe.

E-078 ist nicht Bestandteil dieser Änderung. Es dürfen keine vertraulichen privaten Erweiterungen in die öffentliche Prüfumgebung gelangen.
