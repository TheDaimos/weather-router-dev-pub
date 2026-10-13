# WeatherRouter Consumer Contract V1 · Implementierter Vertragskandidat

Diese Dateien sind die maschinenlesbaren Verträge der **implementierten WeatherRouter-Consumer-API V1**.

Die Runtime ist implementiert und intern testbar. Der Vertrag ist noch **nicht endgültig eingefroren**, bis die erste externe Consumer-Abnahme – zunächst Gewitterradar – erfolgreich abgeschlossen ist.

Aktuell:

- `discovery.response.schema.json`
- `capabilities.request.schema.json`
- `capabilities.response.schema.json`
- `resolve.request.schema.json`
- `resolve.response.schema.json`
- `capability-map.draft.json`
- `hazard-event-types.v1.json`
- `consumer-profile.schema.json`
- `resources/value.schema.json`
- `resources/raster_tile.schema.json`
- `resources/hazard_feed.schema.json`
- `resources/event_feed.schema.json`
- `resources/image_sequence.schema.json`
- `resources/live_stream.schema.json`
- `resources/planetary_tile.schema.json`
- `resources/data_file.schema.json`

Kanonische fachliche Beschreibung:

```text
docs/CONSUMER_API_V1.md
```

Grundregeln:

- Requests werden streng validiert;
- Responses dürfen später additive Felder erhalten;
- Consumer müssen unbekannte Response-Felder ignorieren;
- Provideridentität ist Provenienz, kein Auswahlparameter;
- erwartbare Nichtverfügbarkeit wird als fachlicher `status=unavailable`-Zustand
  modelliert;
- Breaking Changes benötigen eine neue Contract-Major-Version.

Die Resource-Payloads für `value`, `raster_tile`, `hazard_feed`, `event_feed`,
`image_sequence`, `live_stream`, `planetary_tile` und `data_file` besitzen
jeweils eigene Schemas. `resolve.response.schema.json` bindet sie abhängig
vom jeweiligen Resource-Typ ein.

Öffentliche Capabilities können additiv ein `intent_contract` veröffentlichen.
Der Referenzintent `weather.precipitation.layer` nutzt dies, um die
**darstellerische Raster-Austauschbarkeit** maschinenlesbar von einer ausdrücklich
**nicht garantierten numerischen Austauschbarkeit** zu trennen.

Für Raster-Zeitachsen bleiben `default_index`, `current_index` und optionale
`frames[].kind`-Angaben erhalten. Dadurch können Beobachtung, Schätzung und
Vorhersage auch in einer gemeinsamen visuellen Ebene unterscheidbar bleiben.


Die Capability-Map ist bewusst **kein Public-Requestschema**, sondern die Router-interne
Übersetzung interner Provider-Capabilities in öffentliche providerneutrale Capability-IDs.
Bis zum ersten Consumer-Realtest sind nur additive oder klar fehlerkorrigierende Anpassungen vorgesehen.


## Feinfilter im Capability-Katalog

Der Capability-Katalog unterstützt zusätzlich providerneutrale Filter für:

- Fachbereich;
- Familie/Ebene;
- Wetterphänomen;
- Resource-Typ;
- nur aktuell auflösbare Capabilities.

Aktuelle Wetterphänomene:

```text
temperature
dew_point
humidity
pressure
rain
precipitation
snow
wind
clouds
visibility
fog
thunderstorm
lightning
uv
weather_condition
```

Die Filtermetadaten sind ausdrücklich Teil des Public-Vertrags. Consumer sollen
diese Felder verwenden und **nicht** Capability-IDs per Stringanalyse zerlegen.


## Ereignisfilter

Gefahrenfeeds können im Resolve-Request zusätzlich über `event_filter` nach
normalisiertem Ereignistyp und Warnstufe gefiltert werden. Der zentrale Typkatalog
steht in `hazard-event-types.v1.json`; die jeweils für eine Public Capability
zulässigen Typen stehen im Capability-Katalog unter `event_filter_options`.

Ein Ereignisfilter wirkt erst auf die normalisierten Ereignisse und ist ausdrücklich
**keine Providerwahl**.


## Optionale Consumer-Profile

`profile_id` ist eine additive optionale Policy-Schicht für
`consumer/capabilities` und `consumer/resolve`. Profile dürfen nur einschränken.
Provider können profilspezifisch ausgeschlossen, aber niemals priorisiert oder trotz
globaler Deaktivierung wieder zugelassen werden.

Kanonische Regeln: `docs/CONSUMER_PROFILES_V1.md`.


## Aktueller Runtime-Stand

- Transport: authentifizierter Home-Assistant-WebSocket;
- Befehle: `consumer/discovery`, `consumer/capabilities`, `consumer/resolve`;
- Vertragsversion: `1`;
- 8 Fachbereiche;
- 221 öffentliche Capabilities;
- 8 öffentliche Lightning-Capabilities;
- aktuelle Zeitsemantik: ausschließlich `time.mode=latest`;
- keine Providerwahl im Consumerrequest;
- optionale deny-only Consumer-Profile;
- erwartbare Nichtverfügbarkeit als `status=unavailable`, nicht als Transportfehler.

Kanonische Beschreibung: `docs/CONSUMER_API_V1.md`.


## Diagnoseverträge sind getrennt

Die admin-only Routing-/Consumer-Diagnose ist **nicht** Teil des öffentlichen
Consumer-V1-Vertrags. Ihre maschinenlesbaren WebSocket-/Trace-Schemas liegen unter:

```text
contracts/diagnostics/
```

Ein Consumer darf diese internen Diagnose-Endpunkte nicht als Produkt-API verwenden.
