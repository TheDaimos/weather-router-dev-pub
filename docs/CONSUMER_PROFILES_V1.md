# WeatherRouter – Consumer-Profile V1

Stand: **2026-10-01**

Status: **IMPLEMENTIERT · optionale deny-only Policy-Schicht der Consumer API V1**

Kanonischer Consumer-Vertrag: `docs/CONSUMER_API_V1.md`

Kanonische Themen-/Routing-Strategie: `docs/THEMEN_UND_ROUTING_STRATEGIE.md`

## 1. Zweck

Consumer-Profile sind eine **optionale, benutzerkonfigurierbare Policy-Schicht** über
der providerneutralen WeatherRouter-Consumer-API.

Sie lösen den Anwendungsfall, dass unterschiedliche Consumer fachlich nur einen
Ausschnitt der grundsätzlich verfügbaren WeatherRouter-Daten benötigen.

Beispiele:

- Gewitterradar interessiert sich für Gewitter, Blitz, Hagel, Tornado/Windhose,
  Starkregen, Sturm, Niederschlag, Radar und passende Warnungen.
- Aurora Borealis interessiert sich primär für Bewölkung, Sichtweite, Nebel,
  Niederschlag/Wetterzustand sowie passende Weltraum-/Sonnendaten; Erdbeben,
  Tsunami, Waldbrand oder Bevölkerungsschutz sind dort typischerweise irrelevant.

Profile ändern **nicht** das Grundprinzip der API: Ein Consumer fragt weiterhin
fachliche Capabilities an; WeatherRouter entscheidet weiterhin providerneutral,
welcher geeignete Provider die Capability liefert.

Ohne `profile_id` verhält sich die Consumer-API exakt wie bisher.

## P0-060 Referenztests

Für die Routing-Abnahme werden Profile bewusst als **Deny-only-Prüfung** verwendet.
Die verbindlichen Testprofile sind im Routing-Schlachtplan festgelegt. Sie prüfen
gezielt Provider-, Datenursprung-, Messmethoden- und Beobachtungsart-Ausschlüsse,
ohne Scoring oder Providerreihenfolge zu verändern.

Ein Profil-Ausschluss muss im Routingtrace über `profile_allowed`,
`candidate_policy` und einen konkreten `profile_*_filtered`-Grund
nachvollziehbar sein.

## 2. Harte Architekturregel: Profile dürfen nur einschränken

Die verbindliche Reihenfolge lautet:

```text
globale Routerfreigabe
→ globale Fachbereichsfreigabe
→ globale Providerfreigabe
→ Coverage / Health / Freshness / harte Requirements
→ Consumer-Profil als zusätzliche Einschränkung
→ konkrete Consumeranfrage
```

Ein Profil darf niemals:

- einen global deaktivierten Provider wieder aktivieren;
- einen global deaktivierten Fachbereich wieder aktivieren;
- harte Coverage-/Health-/Credential-Grenzen umgehen;
- direkte Providerwahl erzwingen;
- eine Provider-Reihenfolge oder Provider-Priorität definieren.

Ein global deaktivierter Provider bleibt eine harte No-Network-Grenze.

## 3. Providerregeln

Profile dürfen Provider **ausschließen**:

```json
{
  "excluded_providers": ["provider_x", "provider_y"]
}
```

Das ist bewusst eine Negativregel nur auf Provider-Ebene.

Zulässig:

- Provider global EIN, Profil schließt ihn für genau diesen Consumer aus.

Nicht zulässig:

- Provider global AUS, Profil schaltet ihn wieder ein.
- Profil sagt „Provider A zuerst, dann B“.
- Profil bindet eine Capability fest an einen Provider.

Damit bleibt die Trennung erhalten:

```text
Profil: Welche fachlichen Informationen darf dieser Consumer sehen?
Router: Woher werden diese Informationen bezogen?
Consumer: Wie werden die Daten dargestellt/verwendet?
```

Provider-Ausschlüsse sind insbesondere sinnvoll bei:

- später kostenpflichtigen Diensten;
- stark eingeschränkten kostenlosen Kontingenten;
- unzuverlässigen oder fachlich falschen Antworten;
- Lizenz-/Nutzungsgrenzen eines bestimmten Consumers;
- bewusstem Schutz eines kleinen API-Kontingents.

## 3.1 Candidate-Klassen restriktiv ausschließen

Zusätzlich zum Provider-Ausschluss dürfen Profile normalisierte Candidate-Eigenschaften
ausschließlich **deny-only** filtern:

```json
{
  "excluded_data_origins": ["satellite", "model"],
  "excluded_measurement_methods": ["radar_reflectivity"],
  "excluded_observation_kinds": ["forecast"]
}
```

So kann ein Consumer z. B. Satellit, Modell oder Nowcast ausschließen, ohne konkrete
Provider zu kennen. Diese Felder definieren weder Präferenz noch Reihenfolge; das
Scoring bleibt vollständig im WeatherRouter-Core.

## 4. Profilfelder

Erste Profilstruktur:

```text
id
name
description
enabled
revision

allowed_domains
allowed_families
allowed_phenomena
allowed_capabilities
allowed_hazard_types
allowed_severities

excluded_providers
excluded_data_origins
excluded_measurement_methods
excluded_observation_kinds
```

Alle `allowed_*`-Felder sind optionale Positivlisten. Nicht gesetzte Felder
schränken auf dieser Ebene nicht ein.

Positivlisten sind für fachliche Auswahl bewusst sicherer als Verbotslisten:
Neue Capabilities oder neue Ereignistypen sollen nicht plötzlich in einem eng
definierten Consumer erscheinen, nur weil niemand sie nachträglich verboten hat.

Mehrere gesetzte Profilregeln wirken gemeinsam als Einschränkungen.

## 5. Ereignisfilter

Der bestehende direkte `event_filter` bleibt vollständig erhalten.

Ein Profil kann zusätzlich dauerhafte erlaubte Ereignistypen und Schweregrade
festlegen. Bei einem Consumerrequest werden direkter Requestfilter und Profil
geschnitten.

Beispiel:

```text
Profil erlaubt: Gewitter, Hagel, Tornado
Request verlangt: Gewitter, Starkregen
Ergebnis: Gewitter
```

Ist die Schnittmenge leer, wird die Anfrage als `profile_filtered` abgelehnt.
WeatherRouter erweitert einen Request niemals über das Profil hinaus.

## 6. Profilidentität in Requests

Profile sind optional:

```json
{
  "type": "weather_router/consumer/resolve",
  "contract_version": 1,
  "profile_id": "aurora_borealis",
  "capability": "weather.point.cloud_cover",
  "context": {
    "type": "point",
    "latitude": 52.52,
    "longitude": 13.405
  },
  "time": {"mode": "latest"}
}
```

Ohne `profile_id` gilt der normale, ungefilterte Consumer-Vertrag.

Eine automatische versteckte Zuordnung „Consumer X bekommt immer Profil Y“ ist für
V1 bewusst **nicht** Teil des Vertrags. Eine spätere optionale Standardzuordnung darf
nur eingeführt werden, wenn die tatsächlich angewandte Profil-ID in der Antwort
transparent bleibt.

## 7. Transparenz

Wird ein Profil angewandt, enthält die Public Response:

```json
{
  "profile": {
    "id": "aurora_borealis",
    "name": "Aurora Borealis",
    "revision": 3,
    "applied": true
  }
}
```

Routingdiagnosen dürfen außerdem die Zahl profilspezifisch ausgeschlossener
Providerkandidaten ausweisen.

Ein Profil gibt keine Credentials oder geheimen Providerparameter aus.

## 8. Beispielprofil Gewitterradar

Nicht normativ, aber als Zielbild:

```json
{
  "id": "gewitterradar",
  "name": "Gewitterradar",
  "enabled": true,
  "allowed_domains": ["weather", "natural_hazards"],
  "allowed_families": [
    "warning",
    "convection",
    "lightning",
    "radar",
    "nowcast",
    "point",
    "satellite"
  ],
  "allowed_phenomena": [
    "thunderstorm",
    "precipitation",
    "rain",
    "wind",
    "clouds"
  ],
  "allowed_hazard_types": [
    "severe_thunderstorm",
    "tornado",
    "waterspout",
    "hail",
    "downburst",
    "supercell",
    "heavy_rain",
    "windstorm",
    "lightning",
    "flash_flood",
    "flood"
  ],
  "excluded_providers": []
}
```

Das Profil darf später angepasst werden, ohne Gewitterradar selbst mit
Providerspezifika zu koppeln.

## 9. Beispielprofil Aurora Borealis

Nicht normativ, aber als Zielbild:

```json
{
  "id": "aurora_borealis",
  "name": "Aurora Borealis",
  "enabled": true,
  "allowed_domains": ["weather", "space"],
  "allowed_families": ["point", "satellite", "solar"],
  "allowed_phenomena": [
    "clouds",
    "visibility",
    "fog",
    "precipitation",
    "weather_condition"
  ],
  "excluded_providers": []
}
```

Damit bleiben z. B. Erdbeben/Tsunami/Waldbrand außerhalb des Profils, während
Wolken/Sichtbedingungen und Sonnen-/Weltraumdaten nutzbar bleiben.

Langfristig sinnvolle zusätzliche providerneutrale WeatherRouter-Capabilities für
Aurora sind insbesondere:

- Sonnenwind;
- IMF/Bz;
- geomagnetische Indizes wie Kp;
- Aurora-Oval / Polarlichtaktivität;
- eine aus fachlich belastbaren Quellen abgeleitete Sichtbarkeits-/Beobachtungslage.

Diese werden bei Umsetzung **normale öffentliche Capabilities**, keine
Aurora-Sonderlogik im Router-Core.

## 10. Verwaltung

Profilverwaltung ist administrative WeatherRouter-Konfiguration.

Erste interne Admin-Befehle:

```text
weather_router/consumer_profiles
weather_router/consumer_profile_upsert
weather_router/consumer_profile_delete
```

Consumer selbst erhalten dadurch keinen Schreibzugriff auf Router- oder
Profilkonfiguration.

## 11. Erste Runtime-Grundlage ab WR 0.10.60 DEV

Implementiert:

- persistente Profile im Config Entry;
- strukturelle Profilvalidierung;
- Admin List/Upsert/Delete;
- optionales `profile_id` in Capability-Katalog und Resolve;
- Allowlist-Filter für Domain/Familie/Phänomen/Capability;
- Hazard-/Severity-Schnitt mit dem bestehenden `event_filter`;
- profilspezifische Provider-Ausschlüsse;
- Provider-Ausschlüsse wirken nur deny-only nach globaler Eligibility;
- Response nennt angewandtes Profil;
- keine Profilpflicht und keine automatische Consumerkopplung;
- keine Providerpriorität im Profil.

## 12. Erste Lab-Verwaltung ab WR 0.10.61 DEV

Implementiert:

- Profilwahl im bestehenden Consumer-API-Schnittstellentest;
- „Kein Profil“ bleibt der unveränderte Standardpfad;
- Anlage, vollständiges Ersetzen und Löschen persistenter Profile;
- editierbare Positivlisten für Fachbereiche, Familien, Wetterthemen,
  öffentliche Capabilities, Ereignistypen und Warnstufen;
- alle registrierten Provider werden als **Ausschluss-Checkboxen** angeboten;
- global deaktivierte Provider werden sichtbar als „global aus“ gekennzeichnet; ein
  zusätzlicher Profilausschluss kann trotzdem gespeichert werden und bleibt bei
  späterer globaler Reaktivierung wirksam;
- Profile können ohne Löschen aktiviert/deaktiviert werden;
- bestehende Profil-IDs sind im Editor schreibgeschützt, damit ein versehentliches
  „Umbenennen“ nicht still ein zweites Profil erzeugt;
- Gewitterradar- und Aurora-Borealis-Vorlage als editierbare Startpunkte;
- Capability-Katalog und Resolve-Test senden die ausgewählte `profile_id`;
- die Oberfläche weist ausdrücklich darauf hin, dass Profile global deaktivierte
  Provider niemals aktivieren und keine Providerpriorität festlegen dürfen.

Die beiden Vorlagen sind keine fest verdrahtete Consumer-Produktlogik. Sie schreiben
nur normale, benutzeränderbare Profilfelder.

Noch offen:

- komfortablere Mehrfachauswahl statt CSV-Eingaben für alle fachlichen Positivlisten;
- Validierung/Erklärung unbekannter fachlicher IDs direkt im Frontend;
- optionale spätere Consumer→Standardprofil-Zuordnung;
- Contract-/Realtest mit Gewitterradar und Aurora;
- zusätzliche Weltraum-/Aurora-Capabilities.


### UI-Stand ab WR 0.10.67

Fachbereiche, Familien/Ebenen, Wetterthemen, Ereignistypen und Warnstufen werden als
responsive Mehrfachauswahl mit explizitem **einschränken**-Schalter angeboten.
Schalter AUS bedeutet „keine zusätzliche Einschränkung“. Schalter EIN erfordert
mindestens einen ausgewählten Wert. Der Editor bezieht seine Auswahlmöglichkeiten aus
einem ungefilterten Basiskatalog, damit restriktive Profile später wieder erweitert
werden können. Die explizite Capability-Positivliste bleibt als Expertenfeld textuell.

## 13. Fachbereiche und aktuelle Profilreichweite · WR 0.10.70

Profile können aktuell die acht Router-Fachbereiche einschränken:

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

**Pollen** ist eigener Fachbereich und darf nicht als `weather.pollen.*` modelliert werden. Ein Profil kann Pollen auf Fachbereichs-, Phänomen-, Familien- oder Capability-Ebene einschränken.

Die deny-only-Regel bleibt unverändert: Profilregeln werden immer **nach** globaler Router-/Fachbereichs-/Provider-Eligibility angewandt und können deaktivierte Pfade nicht wieder aktivieren.

Der aktuelle Consumer-Katalog enthält 221 Capabilities; die Profiloberfläche verwendet einen ungefilterten Basiskatalog, damit auch restriktive Profile später wieder erweitert werden können.

### Vorlage Biologische Gefahren

WR 0.10.71 ergänzt eine editierbare Profilvorlage für biologische Daten:

- `allowed_domains = ["biological_hazards"]`;
- Familie `biological_occurrence_density`;
- Themen u. a. Wildtiere, Prädatoren, Krokodilartige, marine Arten, giftige Tiere, Schlangen, toxische Arten, Giftpflanzen, Giftpilze und biologische Vektoren.

Die Vorlage verändert weder globale Eligibility noch Providerprioritäten. Ist der Fachbereich oder GBIF global aus, bleibt er unabhängig vom Profil aus.

Das maschinenlesbare Profilschema erlaubt jetzt sowohl `pollen` als auch `biological_hazards`; damit ist eine ältere Schema-/Runtime-Abweichung für Pollen ebenfalls korrigiert.


### Gewitterradar · neue Blitzquellen standardmäßig ausgeschlossen

Die Gewitterradar-Profilvorlage schaltet die neuen WeatherRouter-Blitzfamilien
**nicht automatisch frei**.

Nicht Bestandteil der Vorlage sind insbesondere:

```text
lightning_observation
lightning_density
lightning_satellite
phenomenon: lightning
```

WeatherRouter kann die Quellen im Lab und in Diagnosen unabhängig testen. Eine Nutzung
durch Gewitterradar wird erst nach separater Abnahme bewusst in dessen Profil
freigeschaltet. Das schützt die bestehende Consumerlogik und erhält die vollständige
Unabhängigkeit von WeatherRouter.
