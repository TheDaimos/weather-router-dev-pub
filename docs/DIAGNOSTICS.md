# WeatherRouter – Routing- & Consumer-Diagnose

Stand: **2026-10-01**

Status: **WR 0.10.98 DEV · P0-080 Niederschlags-Intent fachlich eingefroren**

## Zweck

Die Routing- & Consumer-Diagnose ist das zentrale Werkzeug, um eine
`weather_router/consumer/resolve`-Entscheidung vollständig und providerneutral
nachzuvollziehen. Sie ist nicht auf DWD, Radar oder eine einzelne Datenklasse
zugeschnitten.

Sie gilt für heutige und zukünftige Ressourcen, darunter `value`, `raster_tile`,
`event_feed`, `hazard_feed`, `data_file`, `image_sequence`, `live_stream`,
`planetary_tile` und unbekannte spätere Ressourcentypen. Unbekannte Typen werden
diagnostisch generisch dargestellt, ohne fachliche Bedeutung zu erfinden.

> **Diagnose beobachtet und erklärt Routing. Diagnose entscheidet nicht anders als der
> Router und erzeugt im Live-Modus keine zusätzlichen Provideranfragen.**

## Drei getrennte Diagnosewerkzeuge

### Routing- & Consumer-Diagnose

Beobachtet echte Consumer-V1-Resolve-Vorgänge: Request, Kontext, Profil/Policy,
Candidates, Coverage, Fallback, finale Entscheidung, Resource-Zusammenfassung,
Freshness, deklarierte Netzwerkziele, providerseitige Cacheinformationen und
Routing-/Candidate-Dauern.

Schema: `weather_router.routing_diagnostic.v1`.

### Provider-Diagnose

Expliziter One-Shot-Test eines Providers bzw. aller Provider. Darf gezielt
Providerzugriffe auslösen und Provider-Probes/Exceptions erfassen.

### Browser-Ereignislog

Beobachtet Lab-/MapLibre-/Timeline-/Puffer-/Frontendzustände im Browser.

Die Werkzeuge ergänzen sich und werden nicht miteinander verwechselt.

## Laufzeitmodell

Jeder Consumer-Resolve erzeugt intern einen kleinen strukturierten Trace. Der
Ringpuffer hält maximal **50 Traces**.

- nur RAM, keine Persistenz;
- nach HA-Neustart verloren;
- keine Tile-Bilddaten;
- keine vollständigen Eventfeed-Kopien;
- keine unbegrenzten Tracebacks;
- große Listen/Dictionaries begrenzt;
- Ressourcen werden typabhängig zusammengefasst;
- admin-only Zugriff.

## WebSocket-Schnittstellen

Interne Diagnosebefehle, **nicht** Teil von Consumer API V1:

```text
weather_router/routing_diagnostics
weather_router/routing_diagnostics_clear
weather_router/routing_diagnostics_subscribe
```

Verlauf:

```json
{"type":"weather_router/routing_diagnostics","limit":20}
```

Einzeltrace:

```json
{"type":"weather_router/routing_diagnostics","trace_id":"rt-..."}
```

Ring leeren:

```json
{"type":"weather_router/routing_diagnostics_clear"}
```

Live:

```json
{"type":"weather_router/routing_diagnostics_subscribe"}
```

Die Live-Subscription beobachtet nur abgeschlossene Traces und startet keine
Providerabfragen.

## Diagnoseformat

Maschinenlesbare Diagnoseverträge:

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

Die Schemas beschreiben die Nutzlast der WeatherRouter-Befehle. Die von Home Assistant
auf Transportebene ergänzte WebSocket-`id` ist nicht Bestandteil der
WeatherRouter-Fachnutzlast.

Top-Level:

```text
meta
request
context
policy
profile
candidates
coverage
decision
resource
timeline
freshness
network
cache
performance
errors
```

Das Format ist intern/admin-only und bläht Consumer API V1 nicht auf.

## Request

Erfasst werden Trace-ID, Start/Ende, Consumer-Vertragsversion, aufrufender API-Pfad,
öffentliche Capability, Family, Phenomena, Resource-Typen, `context.type`,
`time.mode`, Requirements, Eventfilter, Profil-ID/-Revision und Gesamtdauer.

Unbekannte Phänomene werden nicht umgedeutet.

## Räumlicher Kontext

### point

Latitude, Longitude und `routing_uses=consumer_point`.

### bbox

- west/south/east/north;
- berechneter Mittelpunkt;
- Breite/Höhe in Grad;
- Datumsgrenzenüberquerung;
- grobe Ausdehnung in km;
- `routing_uses=consumer_bbox`.

### global

`global=true` und `routing_uses=global`.

Consumer-Kontext und WeatherRouter-Referenzposition bleiben strikt getrennt.
Der Trace weist `implicit_reference_location_used=false` aus.

## Coverage-Diagnose

Bei Maschinen-Coverage werden sichtbar:

- machine coverage vorhanden;
- scope;
- echte Provider-BBox;
- Provider-Metadatenquelle;
- `bbox_source`;
- Layer und CRS;
- WMS GetCapabilities ja/nein;
- EX_GeographicBoundingBox ja/nein;
- CRS:84-Fallback ja/nein;
- LatLonBoundingBox-Fallback ja/nein;
- providerseitiges Cachealter/TTL/Hit soweit instrumentiert;
- Consumer-Mittelpunkt innerhalb ja/nein;
- BBox-Schnitt ja/nein;
- ungefähre Überlappung in Prozent der Consumer-BBox;
- Consumer-BBox vollständig innerhalb;
- Provider-Coverage vollständig innerhalb Consumer-BBox;
- Antimeridian-Behandlung;
- finaler Coverage-Status.

Die Prozentzahl ist **Diagnose**, keine neue Routingregel.

Aktuell bleibt E-072 unverändert:

```text
bbox → echte geometrische Schnittmenge
point → Punkt-in-Coverage
global → regionale Coverage reicht nicht
```

Mittelpunkt- oder Mindestüberlappungsregeln werden erst nach realen Diagnoseexports
separat entschieden.

## DWD

DWD ist die erste vollständig instrumentierte WMS-Coverage.

Priorität der geografischen Metadaten:

1. konkrete Named-Layer-Coverage im bestehenden DWD-Sammel-GetCapabilities;
2. falls dort keine verwertbare Layer-BBox vorhanden ist: DWDs **layerbezogener
   GeoServer-GetCapabilities-Dienst**;
3. innerhalb des gefundenen Layers:
   `EX_GeographicBoundingBox` → `BoundingBox/CRS:84` →
   `LatLonBoundingBox`.

Es wird **keine** pauschale Deutschland-BBox als Routinggrundlage fest eingebaut.

Der Layer-Fallback besitzt einen eigenen 300-Sekunden-Cache je Layer. Dadurch erzeugt
ein Karten-`moveend` nach dem ersten Resolve keine neue GetCapabilities-Anfrage pro
Bewegung.

Zusätzliche Diagnosefelder:

- `coverage_metadata_scope = aggregate_wms | layer_specific_wms`;
- `aggregate_coverage_missing`;
- `endpoint_host`;
- konkrete `bbox_source`;
- Cache hit/age/TTL.

WR 0.10.88 entstand aus dem realen Kuba-Trace
`rt-b76ed022a33b4f15`: korrekte `consumer_bbox`, DWD nicht selected, aber bisher
`coverage_error / ValueError` und dadurch falsches `temporarily_unavailable`.

Coverage-Ausnahmen enthalten nun zusätzlich eine redigierte `error_message`, damit
ein Metadatenfehler im nächsten Trace nicht nur als Exceptiontyp sichtbar ist.

## Kandidatenmatrix und Decision Trace

Jeder gemappte Candidate besitzt feste Reihenfolge und getrennte Checks:

```text
router_enabled
domain_enabled
provider_enabled
profile_allowed
resource_implemented
context_supported
resource_type
source_class
coverage
```

Dazu Provider/Capability, Resource-Typ, Source Class, attempted, Dauer, Result und
Reason. Ein vor Coverage ausgeschlossener Candidate wird nicht fälschlich als
Coverage-Fehler dargestellt.

Die finale Entscheidung enthält Status, Code, Selected Provider/Capability/Index,
Fallback Count und Reason Code. Diagnose führt keine neue Providerpriorität ein.

## Ressourcen

### raster_tile

Keine vollständige Tile-URL im Ring. Gespeichert werden nur Scheme/Host/Port,
Pfadsegmentanzahl, nicht geheime Query-Key-Namen, Template-Tokens, Zoom/Tile/Opacity,
Attribution, Legendenmetadaten und Timeline-Summary.

### value

Anzahl, Einheit, Datenzeit und Zustand `present/null/invalid`. Der Messwert wird nicht
unnötig dupliziert.

### event_feed / hazard_feed

Eventanzahl, ungefilterte Anzahl, Source Count, Filter, Ereignistypen, Severities und
Geometrieanzahl; keine vollständige zweite Eventliste.

### data_file / image_sequence / live_stream / planetary_tile

Kleine typbezogene Metadaten und sichere URL-Zusammenfassungen; keine Medieninhalte.

Unbekannte spätere Ressourcentypen fallen auf eine neutrale Schlüsselübersicht zurück.

## Timeline / Freshness

Timeline-Summary: Framezahl, erster/letzter Frame, Default-/Current-Index soweit
vorhanden, Loop, Frameabstände, Duplikate und ungültige Zeitwerte.

Freshness übernimmt nur belastbare Datenzeit/Alter/Stale-Information. Fehlende Werte
werden nicht erfunden.

## Netzwerk

Normale Routing-Traces speichern ausschließlich deklarierte `network_targets()`.

```text
instrumentation = declared_targets_only
observed_call_count = null
```

Reale HTTP-Status-/Netzzeiten bleiben Provider-Probes vorbehalten, solange sie nicht
zentral zuverlässig instrumentiert sind.

## Cache

Es werden nur providerseitig gemeldete Cachemetadaten gespeichert. DWD WMS ist
instrumentiert; andere Provider werden nicht künstlich als Hit/Miss klassifiziert.

## Performance

Gemessen: Gesamtzeit, instrumentierte Stage-Zeiten, Candidate-Dauer, Provider geprüft
und Provider kontaktiert. Nicht zuverlässig messbare RAM-/Netzwerkwerte bleiben
`null` bzw. ausdrücklich nicht instrumentiert.

## Providerstatus

Die Providerdiagnose kann aus dem begrenzten Ring Attempt-/Selected-Zähler, letzten
beobachteten Erfolg/Fehler sowie `observed_success`, `degraded` oder `unknown`
anzeigen. Das ist kein erfundener universeller Health-Check.

## Lab-Cockpit

Schaltfläche:

```text
🧭 Routing & Consumer-Diagnose
```

Kompakte Akkordeons:

A Anfrage · B Räumlicher Kontext · C Zeit · D Profil/Policy · E Kandidatenmatrix ·
F Coverage · G Providerentscheidung · H Resource · I Timeline · J Freshness ·
K Netzwerk · L Cache · M Performance · N Fehler/Fallback · O Letzte Entscheidungen ·
P Rohdaten · Q Export.

## WR 0.10.98 · Niederschlags-Intent-Vertrag

Routing-Traces führen den additiven `intent_contract` im Policy-Block. Für
`weather.precipitation.layer` kann damit direkt geprüft werden, dass der Intent
visuell austauschbar, aber nicht numerisch austauschbar ist.

Raster-Zeitachsen zeigen zusätzlich:
- `default`;
- `default_index`;
- `current_index`;
- vorhandene `frame_kinds`.

Die Resource-Zusammenfassung zeigt außerdem den verwendeten Legend-Style. Dadurch
sind Legende, Zeitsemantik und Darstellungsvertrag im Git-Export nachvollziehbar.

## WR 0.10.97 · Source-Stale-Probe

Der erste reale Source-Stale-Test zeigte, dass der Zielcandidate vor Erreichen der
Stale-Simulation bereits mit `requirements_not_met` abbrechen konnte. Die Probe
wird deshalb nun direkt nach dem echten Provider-Resource-Abruf ausgelöst und erst
danach würde die normale Raster-Normalisierung folgen.

Resource-Ausfall und Rate-Limit waren bereits real erfolgreich.

## WR 0.10.96 · P0-070 Fehlerprobe

Die Routing-Diagnose kann für den nächsten manuellen Resolve eine kurzlebige,
admin-only Fehlerprobe aktivieren. Unterstützt werden temporäre Resource-
Nichtverfügbarkeit, Rate Limit und Source-Stale. Die Probe ist pro Admin-Benutzer
isoliert und wird beim nächsten Resolve verbraucht oder nach 120 Sekunden verworfen.

Bei den Rasterproben für Resource-Ausfall und Rate Limit läuft die reale
Coverage-Prüfung zuerst durch. Dadurch kann der Trace belegen, dass Coverage
vorhanden war und erst der anschließende Resource-Schritt scheiterte.

## WR 0.10.95 · P0-060-Testprofile und Mobile

Die Routing-Diagnose kann die fünf reservierten P0-060-Testprofile jetzt selbst
persistent anlegen bzw. aktualisieren. Damit entfällt die manuelle Anlage über den
separaten Consumer-Profil-Editor.

Für Mobilgeräte wird die Diagnose als Vollbildansicht dargestellt. Bedienelemente
verwenden größere Touchziele; die Schnellaktionen im Kopf sind horizontal scrollbar.
Die Kandidatenmatrix wird auf kleinen Displays als Candidate-Karten dargestellt,
während die Desktop-Tabelle unverändert erhalten bleibt.

## WR 0.10.93 · Candidate-Einheiten

Die normalisierte Candidate-Einheit wird nun im JSON-Trace, in der Kandidatenmatrix, in der Kompaktdiagnose und in der CSV ausgegeben. Damit ist der letzte technisch fehlende Pflichtbestandteil aus P0-050 D umgesetzt.

## WR 0.10.92 · P0-050 Coverage-Härtung

Der reale Ozean-Trace zeigte, dass RainViewer ohne maschinenlesbare Coverage wegen
der bisherigen Rückwärtskompatibilitätsregel als räumlich geeignet behandelt wurde.
Für den gemeinsamen Intent `weather.precipitation.layer` ist das nicht ausreichend.

Ab WR 0.10.92:

- der gemeinsame Niederschlags-Rasterintent setzt `coverage_policy=required`;
- Raster-Candidates ohne maschinenlesbare Coverage werden mit
  `machine_coverage_required` ausgeschlossen;
- spezialisierte Public-Capabilities behalten die bisherige
  Rückwärtskompatibilitätssemantik;
- NASA GIBS stellt Layer-Coverage aus seinem realen WMS-GetCapabilities bereit;
- der Diagnose-Trace zeigt den zusätzlichen Check `coverage_declared`;
- jeder neue Routingtrace trägt `meta.build_version` und
  `meta.loader_revision`, damit Git-Exporte den tatsächlich getesteten
  WeatherRouter-Build eindeutig belegen;
- die Header-Schnellaktionen zeigen Exportstatus und laufenden Git-Export direkt im
  Kopf des Diagnosefensters.

Damit wird ein global erreichbarer Endpunkt ausdrücklich nicht als globale
fachliche Coverage interpretiert.

## Bedienverbesserungen ab WR 0.10.91

Die Routing-Diagnose behält den Zustand der manuellen Testanfrage über Neurendern,
Aktualisieren und Tracewechsel hinweg. Insbesondere darf eine zuvor gewählte BBox nicht
stillschweigend auf die Deutschland-Standardwerte zurückfallen.

Zusätzlich:

- stabile, rein visuelle Capability-Nummern auf Basis der deterministisch sortierten
  Public-Capability-Liste;
- Suchfeld nach Nummer, Name oder Capability-ID;
- Schaltfläche **Kontext aus Trace übernehmen**;
- Export-/Kopieraktionen zusätzlich direkt im Kopf der Routing-Diagnose;
- Provider-Diagnose, Routing-Diagnose und Protokolle werden als gemeinsamer
  **Diagnose & Protokolle**-Bereich gruppiert;
- bestehende Diagnose- und Exportfunktionen bleiben erhalten.

Die Nummern sind ausschließlich UI-Hilfen und niemals Bestandteil des
Consumer-Vertrags oder einer Capability-ID.

## Manuelle Testanfrage

Unterstützt Capability, `global/point/bbox`, Resource-Type, Source-Class,
`max_age_seconds`, Timeline-Requirement und optionales Profil.

Presets: Deutschland, Europa, USA, Kuba/Karibik, Puntland/Somalia, Australien, Japan,
Antimeridian, Nordpol, Südpol.

**Aktuellen Kartenausschnitt testen** übernimmt MapLibre-`getBounds()`,
`getCenter()` und `getZoom()` als Diagnosekontext.

## Vergleichsmodus

Zwei Traces werden auf Provider-/Status-/Resource-Wechsel, Candidates Added/Removed,
Coverage-Änderung und Laufzeitdifferenz verglichen.

## Export

WR 0.10.87 verwendet für alle Diagnoseexporte denselben gehärteten Clientpfad:

- **Diagnose kopieren** und **JSON kopieren** zeigen Erfolg/Fehler direkt in Q;
- **Routingreport herunterladen** erzeugt einen angehängten temporären Downloadlink;
- **Kandidaten CSV** verwendet denselben robusten Downloadpfad;
- **Nach Git übertragen** prüft zuerst den vorhandenen WeatherRouter-Git-Status;
- fehlt die Einrichtung, öffnet sich derselbe Git-Konfigurationsdialog wie unter
  **Protokolle & Logs**;
- nach erfolgreicher Konfiguration wird der ausstehende Routingtrace automatisch
  weiterexportiert;
- während eines Exportvorgangs sind die Exportbuttons deaktiviert;
- Erfolg/Fehler bleibt direkt bei **Q · Export** sichtbar;
- nach erfolgreichem Git-Export wird **Letzten Git-Export öffnen** angeboten;
- der Git-Export unterstützt `weather_router.routing_diagnostic.v1`;
- Routingdiagnose-Dateinamen verwenden Capability und Trace-Zeit statt
  `wr-unknown`.

Die serverseitige Redaction/Größenbegrenzung bleibt unverändert.

## Datenschutz / Security

Zentrale Redaction entfernt/entschärft API-Key-/Token-/Secret-Queryparameter,
Authorization/Bearer, Cookies, URL-Userinfo und entsprechend benannte verschachtelte
Secretfelder. Ressourcen-URLs werden im Routing-Ring grundsätzlich zusammengefasst.

Explizite Consumer-Koordinaten/BBoxen dürfen im admin-only, flüchtigen Routingtrace
sichtbar sein, weil sie für Coverage-Debugging notwendig sind. Es werden keine
`zone.home`-/Trackerkoordinaten als stiller Ersatz ergänzt.

Home-Assistant-ConfigEntry-Diagnostics bleiben separat und enthalten keine exakten
privaten Referenzkoordinaten.

## ConfigEntry Diagnostics V2

Schema:

```text
weather_router.config_entry_diagnostics.v2
```

Secret-safe enthalten: Manifest-/WR-/Loader-Version, Diagnose-/Consumervertrag,
Provider-/Enabled-/Extension-/Domain-/Capability-/Profilanzahl, Router enabled,
Runtime ready, Routing-Ringgröße, Statussummen, letzter erfolgreicher Resolve und
Fehlerklassen. Provider-Caches werden dafür nicht extra gepollt.

## Abnahmegrenze

Automatisierte Tests prüfen Syntax, Redaction, Schema, Resource-Summaries,
Decision/Coverage Trace, point/bbox/global/Antimeridian, Fallback-/Statuscodes,
Timeline, Netzwerkzielmetadaten, Cache-Hit/Miss und die Invariante, dass Diagnose die
Coverageentscheidung nicht verändert.

Erst DRA/HA-Realtest beweist WebSocket-Registration, Live-Subscription,
Desktop/Tablet/Mobile, echte DWD-Coveragewerte, Gewitterradar Deutschland ↔
Somalia/Kuba und reale Exportpfade.


## Candidate-Semantik · WR 0.10.89

Der Decision Trace führt je Candidate zusätzlich:

- `data_origin`;
- `measurement_method`;
- `observation_kind`;
- `quantity`;
- `routing_score`;
- Check `candidate_policy`.

Damit ist sichtbar, **warum** ein Candidate fachlich einsortiert und gegebenenfalls
durch das Consumer-Profil ausgeschlossen wurde. Der Kandidaten-CSV-Export enthält
dieselben Semantikfelder.

Das Scoring ist providerneutral; die Provider-ID ist kein Scorebestandteil.


## P1 normalisierte Candidate-Semantik

Seit dem P1-Routing-Grundgerüst trägt **jeder Core-Candidate** im Routingtrace die
vollständige normalisierte Semantik. Die Diagnose ist damit nicht mehr auf
Provider-/Capability-Namen und einzelne Laufzeitwerte angewiesen.

Pro Candidate werden ausgegeben:

- `intent` – angefragte öffentliche Capability bzw. gemeinsamer Routing-Intent;
- `topics` – fachliche Topic-Zuordnung(en);
- `provider_id` / `capability_id`;
- `resource_type`;
- `data_origin`;
- `measurement_method`;
- `observation_kind`;
- `quantity` und `unit`;
- `time_semantics`;
- `coverage_semantics`;
- Candidate-spezifische `freshness`, sobald Provider-Daten vorliegen;
- `routing_score`;
- Eligibility-/Policy-/Coverage-Prüfungen;
- `result`, Ausschluss-/Fehlergrund und Laufzeit.

Die statische Coverage-Semantik und die tatsächliche Runtime-Coverage bleiben
bewusst getrennt. Insbesondere gilt weiterhin:

> Technische Endpoint-Erreichbarkeit ist kein fachlicher Coverage-Beweis.

Die UI zeigt die normalisierten Felder sowohl in der Desktop-Kandidatenmatrix als
auch in der mobilen Candidate-Karte. JSON-Export enthält den vollständigen Trace;
der Kandidaten-CSV-Export enthält Intent, Topics, Resource-Typ, physikalische und
Quellsemantik, Zeit-/Coverage-Vertrag, Freshness, Score und Ergebnisgrund.

Die Diagnose darf die Semantik **nicht neu herleiten**. Quelle ist ausschließlich
der normalisierte Runtime-/Consumer-Vertrag. Damit sind Diagnose, Routingentscheidung
und Audit auf derselben fachlichen Grundlage.
