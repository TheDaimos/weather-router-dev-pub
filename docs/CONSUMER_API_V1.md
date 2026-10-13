# WeatherRouter – Consumer API V1

Status: **IMPLEMENTIERT · read-only V1-Vertrag · Gewitterradar V4.11 real integriert · finaler Freeze nach laufender WR-0.10.86-Abnahme**

Stand: **2026-10-01**

Diese Datei ist die kanonische fachliche Beschreibung der aktuell implementierten
WeatherRouter-Consumer-API V1. Maschinenlesbare Verträge liegen unter
`contracts/consumer_v1/`. Bei Widersprüchen gilt: Runtime-Code → JSON-Schema →
dieses Dokument.

## Hazard-Taxonomie · Konvektive Gefahren

Die öffentlichen Hazard-IDs bleiben stabil. Zusätzlich zur ID kann ein Ereignistyp
einer fachlichen Gruppe zugeordnet sein. Konvektive Gefahren verwenden die Gruppe
`convective_hazards` mit dem übergeordneten Router-Fachbereich
`natural_hazards`.

Aktuell umfasst diese Gruppe unter anderem `severe_thunderstorm`, `tornado`,
`waterspout`, `hail`, `lightning`, `downburst` und `supercell`.
`downburst` und `supercell` sind additive Erweiterungen des V1-Katalogs; bestehende
Capability- und Ereignis-IDs werden dadurch nicht umbenannt.

Reine Blitzbeobachtungs-Capabilities unter `weather.lightning.*` bleiben Wetterdaten.
Die Naturgefahren-Hierarchie beschreibt Warn-/Gefahrensemantik und ersetzt nicht die
bestehende Capability-Domäne.

## 1. Grundprinzip

Consumer fragen **fachliche, providerneutrale Capabilities** an. Sie wählen keinen
Provider.

Richtig:

```text
weather.radar.precipitation
weather.precipitation.layer
weather.lightning.observed.events
weather.warning.official
```

Falsch:

```text
provider=dwd
provider=fmi
provider=<beliebige konkrete Quelle>
```

WeatherRouter entscheidet anhand globaler Routerfreigabe, Fachbereich, Providerfreigabe,
Profil, Kontext, Requirements und Laufzeitverfügbarkeit über den geeigneten Datenweg.

Provideridentität bleibt ausschließlich als Provenienz sichtbar.

## 1.1 Fachlicher Routing-Intent für flächigen Niederschlag

Seit WR 0.10.89 existiert additiv `weather.precipitation.layer`.

Die Capability bündelt geeignete Raster-Candidates, ohne deren Messmethode umzudeuten.
`resource.semantics` und `provenance.data_semantics` führen additiv:

```text
data_origin
measurement_method
observation_kind
quantity
unit
```

Radarreflektivität, Niederschlagsrate, Satellitenschätzung, Beobachtung und Modell
bleiben dadurch unterscheidbar. Bestehende spezialisierte IDs behalten ihre Semantik.

Die Candidate-Reihenfolge wird im Router-Core aus normalisierten Eigenschaften
berechnet. Profile dürfen Candidates nur ausschließen und keine Provider priorisieren.

### 1.1.1 Verbindlicher Darstellungsvertrag

`weather.precipitation.layer` ist ab WR 0.10.98 ausdrücklich ein **visueller
Raster-Intent** und keine einheitliche numerische Messgröße.

Garantiert:

- Resource-Typ `raster_tile`;
- maschinenlesbare Coverage vor Auswahl;
- normalisierte Candidate-Semantik mit `data_origin`,
  `measurement_method`, `observation_kind`, `quantity` und `unit`;
- Attribution;
- Legende mit öffentlicher URL;
- renderbare Austauschbarkeit als Kartenebene;
- Runtime-Zeitmodus `latest`.

Nicht garantiert:

- einheitliches Messverfahren;
- einheitliche physikalische Größe;
- einheitliche Einheit;
- einheitliche zeitliche Auflösung;
- einheitliche Beobachtungsart;
- numerische Austauschbarkeit zwischen Raster-Candidates.

Ein Consumer darf daher die ausgewählte Rasterebene direkt darstellen, muss aber
`resource.semantics`, Legende, Attribution und Candidate-Zeitachse respektieren.
Insbesondere dürfen Radarreflektivität, Niederschlagsrate und 1-h-Akkumulation nicht
als identische Zahlenwerte interpretiert oder miteinander verrechnet werden.

Die maschinenlesbare Beschreibung steht im Capability-Katalog unter
`intent_contract` und wird bei erfolgreichem Resolve zusätzlich als
`intent_contract` zurückgegeben. Zeitachsen bleiben candidate-spezifisch. Wenn ein
Provider Frame-Arten wie `observation`, `estimate` oder `forecast` ausweist,
werden sie als `timeline.frames[].kind` erhalten.

## 2. Transport

Transport ist Home Assistants authentifizierter WebSocket-Kanal.

Implementierte read-only Consumerbefehle:

```text
weather_router/consumer/discovery
weather_router/consumer/capabilities
weather_router/consumer/resolve
```

Vertragsname:

```text
weather_router.consumer
```

Aktuelle Vertragsversion:

```text
1
```

Die Consumer-Vertragsversion ist unabhängig von der WeatherRouter-Produktversion.

## 3. Discovery

Request:

```json
{
  "type": "weather_router/consumer/discovery"
}
```

Response:

```json
{
  "schema": "weather_router.consumer.discovery.v1",
  "contract": {
    "name": "weather_router.consumer",
    "supported_versions": [1],
    "preferred_version": 1
  },
  "router": {
    "ready": true,
    "enabled": true,
    "integration_version": "0.10.0",
    "status": "ready"
  },
  "domains": [
    {"id": "weather", "enabled": true}
  ]
}
```

Discovery führt keinen Provider-Netzwerkabruf aus.

Consumerzustände:

```text
PRESENT
→ COMPATIBLE
→ READY
→ CAPABLE(konkrete Anfrage)
```

Bedeutung:

- PRESENT: WebSocket-Befehl erreichbar.
- COMPATIBLE: gemeinsame Vertragsversion vorhanden.
- READY: Router geladen und betriebsbereit.
- CAPABLE: konkrete Capability kann für Kontext/Requirements tatsächlich aufgelöst werden.

Ein Consumer muss ohne WeatherRouter vollständig weiter funktionieren.

## 4. Fachbereiche

Aktuell:

```text
weather
pollen
natural_hazards
civil_protection
security
aviation
space
biological_hazards
```

Ein deaktivierter Fachbereich ist eine harte Eligibility- und Netzwerkgrenze.

## 5. Capability-Katalog

Request:

```json
{
  "type": "weather_router/consumer/capabilities",
  "contract_version": 1
}
```

Optional:

```json
{
  "filter": {
    "domains": ["weather"],
    "families": ["radar", "lightning"],
    "phenomena": ["precipitation", "thunderstorm"],
    "resource_types": ["raster_tile", "event_feed"],
    "available_only": true
  },
  "profile_id": "gewitterradar"
}
```

Innerhalb einer Filtergruppe gilt ODER, zwischen Filtergruppen UND.

Der Katalog enthält aktuell **222 öffentliche Capabilities**. Consumer dürfen diese Zahl
nicht hart verdrahten.

Jeder Eintrag enthält mindestens:

```text
id
domain
name
enabled
available
resource_types
spatial_contexts
time_modes
family
phenomena
source_classes
resolution_strategy
availability_basis
```

Wichtig:

- `enabled`: mindestens ein Kandidat überlebt globale Eligibility und optionales Profil.
- `available`: mindestens ein Kandidat besitzt einen implementierten Ressourcenadapter.
- `available=true` garantiert noch keine konkrete regionale/zeitliche Auflösung.
- Consumer verwenden `family` und `phenomena`; sie analysieren Capability-IDs nicht per Stringheuristik.
- unbekannte additive Response-Felder müssen ignoriert werden.

## 6. Aktuelle Lightning-Capabilities

Providerneutral vorhanden:

```text
weather.lightning.density
weather.lightning.satellite.mtg_li.accumulated_flashes
weather.lightning.satellite.glm_east.lcfa
weather.lightning.satellite.glm_west.lcfa
weather.lightning.observed.density
weather.lightning.observed.events
weather.lightning.observed.nearest_distance
weather.lightning.observed.nearest_azimuth
```

Consumer dürfen aus diesen IDs keine konkrete Providerbindung ableiten.

## 7. Resolve

Minimaler Request:

```json
{
  "type": "weather_router/consumer/resolve",
  "contract_version": 1,
  "capability": "weather.radar.precipitation",
  "context": {
    "type": "bbox",
    "west": 5.0,
    "south": 47.0,
    "east": 16.0,
    "north": 56.0
  },
  "time": {
    "mode": "latest"
  }
}
```

Optionale Felder:

```text
requirements
event_filter
profile_id
```

Es gibt bewusst **kein** `provider`-Feld.

## 8. Räumlicher Kontext

### global

```json
{"type":"global"}
```

Keine weiteren Felder erlaubt.

### point

```json
{
  "type":"point",
  "latitude":52.52,
  "longitude":13.405
}
```

Latitude: -90..90, Longitude: -180..180.

### bbox

```json
{
  "type":"bbox",
  "west":5.0,
  "south":47.0,
  "east":16.0,
  "north":56.0
}
```

`south <= north`. Dateline-Überquerung ist durch `west > east` zulässig.

WeatherRouter verwendet **niemals still** den HA-Bezugsstandort für Consumerrequests.

### 8.1 Maschinenlesbare Raster-Coverage

Für `raster_tile` bedeutet „Endpoint erreichbar“ nicht automatisch „räumlich
geeignet“. Vor der eigentlichen Ressourcenauflösung kann ein Rasterprovider deshalb
eine maschinenlesbare Coverage über den internen Vertrag
`async_get_coverage(hass, capability_id)` liefern.

Der Resolve-Ablauf ist:

```text
globale Routerfreigabe
→ Fachbereich/Provider aktiv
→ Consumer-Profil
→ Resource-Type/Requirements
→ räumliche Maschinen-Coverage
→ erst danach async_get_map_layer()
```

Unterstützte Coverageformen:

```json
{"scope":"global"}
```

oder

```json
{
  "scope":"bbox",
  "bbox":{"west":2.0,"south":46.0,"east":17.0,"north":56.0},
  "source":"wms_get_capabilities",
  "layer":"<konkreter Layer>"
}
```

Regeln:

- bei `bbox` genügt eine echte räumliche Überlappung; vollständig außerhalb →
  `outside_coverage`;
- bei `point` wird Punkt-in-Coverage geprüft;
- bei `global` ist eine regionale BBox **nicht** ausreichend;
- `west > east` wird als Antimeridian-/Datumsgrenzen-BBox behandelt;
- Freitextfelder wie `CapabilityInfo.coverage` oder `ProviderInfo.coverage` sind
  ausschließlich Anzeige-/Dokumentationsmetadaten und werden nicht geparst;
- nach `outside_coverage` versucht der Resolver den nächsten ansonsten geeigneten
  Kandidaten;
- sind alle auflösbaren Kandidaten räumlich ungeeignet, lautet der fachliche Zustand
  `status=unavailable / code=outside_coverage`;
- existiert bereits vor der räumlichen Prüfung grundsätzlich kein aktivierter/passender
  Kandidat, bleibt `no_eligible_provider` bzw. `requirements_not_met` maßgeblich.

DWD ist die erste layerbezogene Umsetzung. Für Radar, RADOLAN, Meteosat, NowCastMIX
und ICON/ICON-EU wird die Coverage des **konkret verwendeten WMS-Layers** aus
GetCapabilities gelesen. Derselbe bereits vorhandene DWD-Capabilities-Cache wird
wiederverwendet; ein Karten-`moveend` erzeugt dadurch keinen zusätzlichen
GetCapabilities-Abruf pro Consumer-Resolve.

Consumer API V1 bleibt unverändert: Gewitterradar sendet weiterhin nur öffentliche
Capability, `context`, `time` und Requirements. Providerwahl und Coverage bleiben
WeatherRouter-Aufgabe.

## 9. Zeitkontext

Aktuell implementiert:

```json
{"mode":"latest"}
```

**Nur `latest` ist derzeit Runtime-Vertrag.**

`at` und `range` sind zukünftige additive Erweiterungen und werden aktuell als
`requirements_not_met` zurückgegeben. Consumer dürfen sie bis zur ausdrücklichen
Freigabe nicht senden.

## 10. Harte Requirements

Optional:

```json
{
  "requirements": {
    "resource_types": ["raster_tile"],
    "source_classes": ["observation"],
    "max_age_seconds": 900,
    "timeline_required": true
  }
}
```

Unterstützt:

- `resource_types`: nichtleere Stringliste;
- `source_classes`: nichtleere Stringliste;
- `max_age_seconds`: Integer >= 0;
- `timeline_required`: Boolean.

Requirements sind Constraints, keine Scores. Kein Kandidat erfüllt sie → strukturierte
Nichtverfügbarkeit.

## 11. Event-Filter

Für Hazard-Capabilities:

```json
{
  "event_filter": {
    "hazard_types": [
      "severe_thunderstorm",
      "tornado",
      "waterspout",
      "hail",
      "heavy_rain",
      "windstorm",
      "lightning"
    ],
    "severities": ["moderate", "severe", "extreme"]
  }
}
```

Erlaubte Werte werden aus dem Capability-Katalog /
`consumer_hazard_event_types.json` bezogen.

Der Filter wirkt nach der Provider-Normalisierung und ist keine Providerwahl.

Kein Treffer ist kein Fehler: ein Hazard-Feed kann `status=ready` und
`event_count=0` liefern.

## 12. Consumer-Profile

Optional:

```json
"profile_id": "gewitterradar"
```

Profile sind **deny-only**.

Sie dürfen:

- Domains einschränken;
- Familien einschränken;
- Phänomene einschränken;
- Capabilities einschränken;
- Hazard-Typen/Severity einschränken;
- Provider ausschließen.

Sie dürfen niemals:

- global deaktivierte Domains/Provider aktivieren;
- Provider priorisieren;
- Provider fest auswählen;
- Coverage-/Health-/Requirement-Grenzen umgehen.

Ohne `profile_id` gilt die normale Consumer-API unverändert.

Wird ein Profil angewandt, enthält die Antwort:

```json
{
  "profile": {
    "id": "gewitterradar",
    "name": "Gewitterradar",
    "revision": 1,
    "applied": true
  }
}
```

## 13. Resource-Typen

Aktuell öffentlich modelliert:

```text
value
raster_tile
hazard_feed
event_feed
image_sequence
live_stream
planetary_tile
data_file
```

Die jeweiligen Payload-Verträge stehen unter:

```text
contracts/consumer_v1/resources/
```

### value

Normalisierte Punktwerte.

### raster_tile

Kachel-/WMS-Descriptor mit Attribution und optionaler Timeline.

### hazard_feed

Normalisierte Gefahren-/Warnereignisse mit Hazard-Semantik und Provenienz.

### event_feed

Nicht-warnende Beobachtungsereignisse, z. B. beobachtete Blitzereignisse.

### image_sequence

Zeitlich geordnete Bilder/Frames.

### live_stream

Livestream-Descriptor.

### planetary_tile

Nicht-irdische Kachelquelle mit Body-/Projektionskontext.

### data_file

Original-/Datendatei. Sie darf nicht als normalisierter Punktwert ausgegeben werden,
solange kein fachlich korrekter Decoder existiert.

## 14. Erfolgreiche Resolve-Antwort

Grundform:

```json
{
  "schema": "weather_router.consumer.resolution.v1",
  "contract_version": 1,
  "status": "ready",
  "capability": "weather.radar.precipitation",
  "resource": {
    "type": "raster_tile",
    "payload": {}
  },
  "provenance": {
    "provider_id": "example",
    "provider_name": "Example",
    "source_class": "observation",
    "attribution": "..."
  },
  "freshness": {
    "data_time": "2026-09-29T11:20:00Z",
    "fetched_at": "2026-09-29T11:21:00Z",
    "age_seconds": 60,
    "stale": null
  },
  "profile": null,
  "routing": {
    "reason_code": "eligible_candidate",
    "fallback_available": true,
    "degraded": false,
    "candidate_count": 2,
    "selected_index": 0,
    "profile_excluded_candidates": 0
  }
}
```

Providerfelder sind Provenienz. Consumer dürfen ihre Fachlogik nicht an
`provider_id` koppeln.

Bei räumlich geprüften Rasterressourcen kann `provenance` zusätzlich
`spatial_coverage` enthalten. Dieses additive Feld beschreibt die für die Auswahl
verwendete Maschinen-Coverage und ändert den V1-Vertrag nicht.

## 15. Aggregation

Die Capability-Map kennt:

```text
single
aggregate
```

Aktuell sind 218 Capabilities `single` und 3 `aggregate`.

`aggregate` ist aktuell auf `hazard_feed` begrenzt. Alle geeigneten Quellen werden
abgerufen, Ereignisse zusammengeführt und behalten jeweils eigene Provenienz.

Aktuell aggregate:

```text
weather.warning.official
natural_hazards.tsunami.warnings
civil_protection.warning.official
```

Es erfolgt derzeit bewusst keine automatische Ereignisdeduplizierung zwischen Behörden.

## 16. Freshness

Antworten unterscheiden:

```text
data_time
fetched_at
age_seconds
stale
```

Fehlt eine belastbare Datenzeit, wird sie nicht erfunden.

`max_age_seconds` kann nur erfüllt werden, wenn eine belastbare Datenzeit existiert.

## 17. Routing-Reason-Codes

Aktuell:

```text
only_eligible_candidate
eligible_candidate
fallback_after_failure
fallback_after_rate_limit
aggregate_eligible_sources
```

Consumer sollen Reason-Codes anzeigen/diagnostisch verwenden, aber keine
Providerprioritätslogik daraus ableiten.

## 18. Fachliche Nichtverfügbarkeit

Erwartbare Nichtverfügbarkeit ist **kein WebSocket-Fehler**:

```json
{
  "schema": "weather_router.consumer.resolution.v1",
  "contract_version": 1,
  "status": "unavailable",
  "capability": "weather.radar.precipitation",
  "unavailable": {
    "code": "outside_coverage",
    "retryable": false,
    "message": "..."
  }
}
```

Aktuell relevante Codes:

```text
router_not_ready
router_disabled
domain_disabled
capability_not_supported
no_eligible_provider
outside_coverage
temporarily_unavailable
rate_limited
credentials_required
requirements_not_met
source_stale
profile_not_available
profile_filtered
```

Consumer behandeln `status=unavailable` als normalen Betriebszustand und degradieren
kontrolliert.

## 19. WebSocket-/Vertragsfehler

Transport-/Requestfehler bleiben für echte Vertragsverletzungen reserviert, u. a.:

```text
unsupported_contract_version
consumer_contract_invalid
invalid_consumer_filter
invalid_capability
invalid_consumer_request
profile_not_available
```

Consumer dürfen App-Kernfunktionen dadurch nicht beschädigen.

## 20. Sicherheit

Consumer API V1:

- gibt keine Provider-Credentials aus;
- gibt keine Git-/Diagnose-Tokens aus;
- gibt keine internen `hass.data`-Strukturen aus;
- verwendet keine implizite Home-/Personenposition;
- liefert direkte URLs nur secret-frei;
- trennt read-only Consumerzugriff von administrativer Router-/Profilkonfiguration.

## 21. Kompatibilitätsregeln

Für Consumer verbindlich:

1. zuerst Discovery ausführen;
2. Vertragsversion statt Produktversion prüfen;
3. unbekannte additive Response-Felder ignorieren;
4. Capability-Verfügbarkeit dynamisch aus Katalog/Resolve bestimmen;
5. keine Provider-ID in Consumerfachlogik;
6. keine feste Zahl von Capabilities/Providern annehmen;
7. `status=unavailable` nicht als Exception behandeln;
8. WeatherRouter immer optional behandeln;
9. nur ausdrücklich dokumentierte Zeitmodi verwenden;
10. Resource-Typ prüfen, bevor Payload interpretiert wird;
11. Provenienz/Attribution erhalten;
12. bei `degraded=true` Ergebnis weiterhin nutzbar, aber sichtbar degradiert behandeln.

Breaking Changes an einem akzeptierten V1-Vertrag benötigen neue Major-Version oder
ausdrückliche kompatible Migrationsentscheidung.

## 22. Gewitterradar-Integrationsregel

Gewitterradar soll ausschließlich über diese Consumer-API angebunden werden.

Verboten:

- direkte Imports aus WeatherRouter-Pythonmodulen;
- Zugriff auf WeatherRouter-`hass.data`;
- direkte Nutzung interner Provider-Capability-IDs;
- Providerfestverdrahtung;
- direkte Abhängigkeit von einem installierten WeatherRouter.

Empfohlener Ablauf:

```text
Gewitterradar startet
→ WeatherRouter discovery versuchen
→ fehlt: Gewitterradar normal weiter
→ Contract V1 kompatibel?
→ ready?
→ capabilities abfragen
→ benötigte Capability dynamisch anbieten
→ resolve mit eigenem Punkt/BBox und latest
→ resource.type prüfen
→ payload rendern
→ provenance/attribution erhalten
→ unavailable/Fehler kontrolliert degradieren
```

Ein optionales `profile_id=gewitterradar` darf genutzt werden, wenn das Profil vorhanden
und bewusst aktiviert ist. Gewitterradar darf die Existenz dieses Profils nicht als
Voraussetzung für seine Kernfunktion behandeln.

## 23. Vollständige Resource-Payload-Regeln

Consumer prüfen immer zuerst `resource.type` und interpretieren `resource.payload`
ausschließlich gemäß dem passenden Vertrag.

### 23.1 value

Pflicht:

```json
{
  "values": {
    "<public-capability-id>": {
      "value": 17.2
    }
  }
}
```

Je Wert optional:

```text
unit: string|null
data_time: ISO-8601|null
field: string|null
```

`value` darf Zahl, String, Boolean oder null sein.

### 23.2 raster_tile

Pflicht:

```text
tile_url: string
tile_size: integer >= 1
max_zoom: number >= 0
```

Optional:

```text
min_zoom
default_opacity (0..1|null)
attribution
timeline
legend
```

Timeline:

```json
{
  "mode": "frames",
  "default": null,
  "loop": true,
  "frames": [
    {
      "time": "2026-09-29T11:20:00Z",
      "tile_url": "https://..."
    }
  ]
}
```

`timeline.mode` ist `frames` oder `time_dimension`.

Legend:

```json
{
  "url": "https://...",
  "title": "..."
}
```

### 23.3 hazard_feed

Pflicht:

```json
{
  "events": []
}
```

Jedes normalisierte Ereignis benötigt mindestens:

```text
id
hazard_type
headline
source_semantics
```

Weitere mögliche Felder:

```text
event
severity
urgency
certainty
status
message_type
sent
effective
onset
expires
ends
area_desc
geometry
description
instruction
response
parameters
source_event_id
source_ref
provenance
```

Ereignisprovenienz enthält mindestens:

```text
provider_id
provider_name
source_class
attribution
```

Feed-Metadaten können enthalten:

```text
event_count
source_count
unfiltered_event_count
matched_source_count
filtered
event_filter
```

### 23.4 event_feed

Pflicht:

```json
{
  "events": [],
  "event_count": 0
}
```

Jedes Ereignis benötigt:

```text
id
event_type
observed_at
```

Optional:

```text
latitude
longitude
distance_km
azimuth_deg
source_distance_km
source_azimuth_deg
status
region
source_semantics
provenance
```

Zusätzlich kann `window_seconds` den vom Provider gelieferten Ereigniszeitraum
beschreiben.

Für beobachtete Blitze ist dies der zentrale nicht-warnende Ereignistyp.

### 23.5 image_sequence

Pflicht:

```text
georeferenced: boolean
frames: array
```

Jeder Frame benötigt:

```text
time: ISO-8601
url: string
```

Optional pro Frame:

```text
content_type
width
height
extent {west,south,east,north}
```

Feedweit optional:

```text
default_index
loop
```

### 23.6 live_stream

Pflicht:

```text
url
transport
```

`transport`:

```text
direct
weather_router_proxy
```

Optional:

```text
content_type
title
attribution
```

### 23.7 planetary_tile

Pflicht:

```text
body
tile_url
min_zoom
max_zoom
```

Optional:

```text
tile_size
crs
attribution
```

Consumer dürfen Planetenkacheln nicht als normale Erdkarte behandeln, wenn Body/CRS
dies nicht zulassen.

### 23.8 data_file

Pflicht:

```text
format
url
transport
```

`transport`:

```text
direct
weather_router_proxy
```

Optional:

```text
content_type
size_bytes
data_time
```

Ein `data_file` ist keine Zusage, dass der Consumer das Format dekodieren kann.
Consumer dürfen z. B. GRIB2/NetCDF nicht als gerenderten Layer behandeln, solange kein
eigener kompatibler Decoder vorhanden ist.

## 24. Maschinenlesbare Verträge

Öffentliche Consumer-V1-Verträge:

```text
contracts/consumer_v1/discovery.response.schema.json
contracts/consumer_v1/capabilities.request.schema.json
contracts/consumer_v1/capabilities.response.schema.json
contracts/consumer_v1/resolve.request.schema.json
contracts/consumer_v1/resolve.response.schema.json
contracts/consumer_v1/consumer-profile.schema.json
contracts/consumer_v1/hazard-event-types.v1.json
contracts/consumer_v1/resources/*.schema.json
```

Runtime-Implementierung:

```text
custom_components/weather_router/consumer_api.py
custom_components/weather_router/consumer_profiles.py
custom_components/weather_router/consumer_capability_map.json
custom_components/weather_router/consumer_hazard_event_types.json
```

Davon getrennte interne/admin-only Diagnoseverträge:

```text
contracts/diagnostics/README.md
contracts/diagnostics/routing_diagnostic.v1.schema.json
contracts/diagnostics/routing_diagnostics.request.schema.json
contracts/diagnostics/routing_diagnostics.index.v1.schema.json
contracts/diagnostics/routing_diagnostics_clear.request.schema.json
contracts/diagnostics/routing_diagnostics_clear.response.schema.json
contracts/diagnostics/routing_diagnostics_subscribe.request.schema.json
contracts/diagnostics/routing_diagnostic.event.v1.schema.json
```

Diese Dateien gehören nicht zur Public Consumer API V1.

## 25. Freigabestatus

Die API ist implementiert und wird von **Gewitterradar V4.11 real und providerneutral**
für `weather.radar.precipitation` verwendet. Damit ist der erste externe
Consumer-Ende-zu-Ende-Pfad erreicht.

Der Vertrag bleibt während der laufenden WR-0.10.86-/Gewitterradar-Abnahme bewusst
noch ein V1-Vertrag vor dem endgültigen Freeze. Zulässig sind nur **additive oder
fehlerkorrigierende** Anpassungen; keine unnötige Consumerkopplung und keine stillen
semantischen Änderungen.

Die neue Routing-/Consumer-Diagnose ist ausdrücklich **keine Erweiterung der Public
Consumer API**. Ihre admin-only WebSocket-Verträge liegen getrennt unter
`contracts/diagnostics/` und sind in `docs/DIAGNOSTICS.md` dokumentiert.


### Providerneutrale Routing-Intents

Echte Fallback-Ketten verwenden einen fachlichen Intent statt einer messmethodenspezifischen Capability. Für flächigen Niederschlag ist `weather.precipitation.layer` der Referenz-Intent. Er kann Radar-, Satelliten- und Modellkandidaten enthalten, ohne deren physikalische Bedeutung gleichzusetzen.

`weather.radar.precipitation` bleibt absichtlich radar-spezifisch. Ein Consumer, der provider- und messmethodenübergreifenden Fallback benötigt, soll deshalb `weather.precipitation.layer` anfordern. Herkunft, Messmethode, Beobachtungsart, physikalische Größe und Einheit bleiben Candidate-Metadaten und werden in Routing und Diagnose sichtbar gehalten.
