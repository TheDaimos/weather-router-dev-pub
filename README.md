<div align="center">

<img src="assets/graphics/weather-router-brandmark/versions/v001/renditions/png/weather-router-brandmark_v001_512.png" width="250" alt="WeatherRouter Logo">

# WeatherRouter

### Fähigkeitsbasiertes Daten-, Gefahren- und Wetter-Routing für Home Assistant

**Optionale Home-Assistant-Integration · 38 Provider · 8 Fachbereiche · Punktdaten, Kartenebenen, Gefahrenfeeds und Medien · providerneutrale Consumer-Schnittstelle**

![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5?logo=home-assistant&logoColor=white)
![DEV Build](https://img.shields.io/badge/DEV%20Build-0.10.161-c9a45b)
![HA Baseline](https://img.shields.io/badge/HA%20Manifest-0.10.0-6b7280)
![API](https://img.shields.io/badge/API--Vertrag-1-c9a45b)
![Provider](https://img.shields.io/badge/Provider-38%20registriert%20%2F%2022%20Standard-00a8e8)
![Status](https://img.shields.io/badge/Status-Development%20Baseline-2ea44f)

</div>

---

> [!IMPORTANT]
> **V0.10 ist als reale Home-Assistant-Development-Baseline abgenommen, aber nicht öffentlich freigegeben.**  
> Dieses Repository ist die private Entwicklungs- und Validierungsbasis. Eine spätere öffentliche Auslieferung erfolgt erst aus einem ausdrücklich akzeptierten Stand.

<table>
<tr>
<td width="50%" valign="top">

### 🌦️ Was WeatherRouter macht

WeatherRouter stellt Wetterdaten **nach Fähigkeit** bereit, nicht nach einem einzigen global aktiven Wetteranbieter.

Dadurch können gleichzeitig beispielsweise:

- Punktwetter von Provider A,
- Niederschlagsradar von Provider B,
- Satellitendaten von Provider C,
- Wind- oder Wolkendaten von Provider D

verwendet werden.

</td>
<td width="50%" valign="top">

### 🧩 Was WeatherRouter nicht macht

WeatherRouter ersetzt keine Consumer-Anwendung.

**Gewitterradar, Aurora Borealis und weitere Consumer müssen ohne WeatherRouter vollständig funktionsfähig bleiben.**

WeatherRouter enthält keine Consumer-spezifische Produktlogik und koppelt Anwendungen nicht an einen bestimmten Provider.

</td>
</tr>
</table>

## Schnellnavigation

**[Aktueller Stand](#aktueller-stand)** · **[Provider](#provider-und-fähigkeiten)** · **[WeatherRouter Lab](#weatherrouter-lab)** · **[Schnittstellen](#schnittstellen)** · **[Netzwerk & Datenschutz](#netzwerk-und-datenschutz)** · **[Dokumentation](#projektdokumentation)** · **[KI-/Entwickler-Einstieg](#ki--und-entwickler-einstieg)**

---

# Aktueller Stand

Aktueller sichtbarer Entwicklungsstand: **WR 0.10.88 · DEV / Loader 91**.

Die implementierte Consumer API V1 umfasst **221 öffentliche Capabilities** über acht Router-Fachbereiche. Die vollständige fachliche Matrix steht in **[`docs/CURRENT_CAPABILITIES.md`](docs/CURRENT_CAPABILITIES.md)**.


Die aktuelle Linie **V0.10 TEST** ist die erste real installierte und abgenommene WeatherRouter-Basis.

Bestätigt sind unter anderem:

- native Home-Assistant-Custom-Integration `weather_router`;
- Config Flow und genau ein Config Entry;
- `select.weather_router_reference_location`;
- Bezugsstandorte aus `person.*` und `zone.*`, Standard `zone.home`;
- admin-only **WeatherRouter Lab**;
- MapLibre mit OpenFreeMap `Dark`, `Fiord`, `Positron`;
- Modus **Keine Basiskarte · nur Wetterlayer**;
- reale Open-Meteo-Punktdaten;
- reales RainViewer-Niederschlagsradar;
- Radar-Zeitverlauf mit Zurück/Vor, Neueste und Play/Pause;
- flackerarme Frame-Umschaltung über bestehende Rasterquelle;
- Config-Entry-Reload und kompletter Home-Assistant-Neustart;
- Diagnoseausgabe ohne vollständige private Koordinaten, Referenz-Entity-ID oder Provider-Secrets;
- Provider-Katalog ohne blockierende Dateizugriffe im Home-Assistant-Event-Loop;
- **38 registrierte Provider**, davon **22 standardmäßig aktiv** und **16 opt-in**;
- persistente **Router-Steuerung**: global Ein/Aus, Fachbereiche Ein/Aus, Provider Ein/Aus;
- deaktivierte Bereiche/Provider sind harte Netzwerkgrenzen und werden auch von Live-Diagnosen nicht still abgefragt;
- optionale öffentliche Warnquellen für Bevölkerungsschutz, öffentliche Sicherheit, globale Katastrophenlage, seismische Sonderereignisse und Luftfahrtwarnungen.

Der vollständige reale Prüfstand steht in **[`docs/V0_10_TEST.md`](docs/V0_10_TEST.md)**.

> [!NOTE]
> Produktversion und Schnittstellenvertrag sind absichtlich getrennt. V0.10.0 verwendet aktuell `API_CONTRACT_VERSION = 1`; eine Produktversion erzwingt keine gleichlautende API-Version.

> [!NOTE]
> **Consumer API V1** ist als providerneutrale read-only Runtime implementiert und wird von Gewitterradar V4.11 real für `weather.radar.precipitation` genutzt. Der endgültige V1-Freeze erfolgt erst nach Abschluss der laufenden WR-0.10.88-/Gewitterradar-Abnahme.
> Der kanonische Vertrag steht in **[`docs/CONSUMER_API_V1.md`](docs/CONSUMER_API_V1.md)**,
> die maschinenlesbaren Schemas unter **[`contracts/consumer_v1/`](contracts/consumer_v1/)**.
> Die Lab-/Diagnose-WebSockets bleiben ausdrücklich getrennt von der Consumer API. Die neue Routing-/Consumer-Diagnose ist unter **[`docs/DIAGNOSTICS.md`](docs/DIAGNOSTICS.md)** und **[`contracts/diagnostics/`](contracts/diagnostics/)** beschrieben.

---

# Provider und Fähigkeiten

<table>
<tr>
<th>Provider</th>
<th>Datentyp</th>
<th>Aktuell implementiert</th>
</tr>
<tr>
<td><strong>Open-Meteo</strong></td>
<td>Punktwerte · Modell</td>
<td>Temperatur, Wolken gesamt/tief/mittel/hoch, Niederschlag, Regen, Schauer, Schnee, Windgeschwindigkeit, Windrichtung, Böen, Sichtweite, WMO-Wettercode sowie globaler UV-/Clear-Sky-UV-Index und Tagesmaxima</td>
</tr>
<tr>
<td><strong>RainViewer</strong></td>
<td>räumliche Kartenebene · Beobachtung</td>
<td>Niederschlagsradar als Raster-Layer mit historischem Frame-Verlauf</td>
</tr>
<tr>
<td><strong>DWD</strong></td>
<td>räumliche Kartenebenen · Beobachtung / Vorhersage</td>
<td>Radar, RADOLAN, METEOSAT, Gewitter-/Blitzprodukte und ICON-Kartenfelder · Entwicklungsblock weitgehend real verprobt</td>
</tr>
<tr>
<td><strong>NASA GIBS</strong></td>
<td>räumliche Kartenebenen · Beobachtung</td>
<td>MODIS Terra sowie ausgewählte GOES-East/West-, Himawari-9- und IMERG-Produkte · MODIS-Basis real bestätigt, Multi-Service-Ausbau WR 0.10.25 im Realtest</td>
</tr>
<tr>
<td><strong>EUMETSAT EUMETView</strong></td>
<td>räumliche Kartenebene · Beobachtung</td>
<td>Meteosat European HRV RGB · Timeline/Puffer/Deckkraft/Basiskartenwechsel real bestätigt</td>
</tr>
<tr>
<td><strong>MET Norway</strong></td>
<td>Punktwerte · Modell</td>
<td>Locationforecast 2.0 direkt integriert; Geosatellite, Nowcast und Radar als weitere Dienste katalogisiert · Realtest WR 0.10.25 ausstehend</td>
</tr>
</table>

### Zusätzliche optionale Gefahrenabwehrquellen

WR 0.10.48 registriert außerdem acht bewusst **nicht automatisch aktivierte** Quellen:
GDACS, USGS Seismische Sonderereignisse, BBK/NINA MoWaS, BBK/NINA Polizeiwarnungen,
NINA/LHP Hochwasser, NINA KATWARN, NINA BIWAPP und NOAA/NWS Aviation Weather Center.

Ab **WR 0.10.68** kommen drei weitere opt-in Provider hinzu:

- **Copernicus GloFAS** · globale modellbasierte Hochwasser-/Hydrologieebenen;
- **MET Norway · Sonne & Mond** · weltweite Astronomie-Punktwerte;
- **Open-Meteo · Pollen** · CAMS-Europe-Pollenkonzentrationen für sechs Pollenarten; eigener Router-Fachbereich **Pollen**.

Mit WR 0.10.68 wuchs der damalige Katalog auf **33 Provider**. Die neuen Provider werden bei bestehenden
Installationen nicht automatisch aktiviert.

Sie bleiben fachlich getrennt von Wetterdaten. WeatherRouter übernimmt Quellsemantik und
Provenienz; eine Explosion wird beispielsweise nicht automatisch zum Anschlag, und eine
Luftfahrtwarnung nicht zur allgemeinen Bevölkerungswarnung.

WeatherRouter unterscheidet bewusst zwischen fachlicher Quelle und Darstellung:

```text
Open-Meteo / Wolken gesamt
→ source_class: model
→ render_mode: value
→ Punktwert für eine Koordinate

RainViewer / Niederschlagsradar
→ source_class: observation
→ render_mode: raster_tile
→ räumliche Kartenebene
```

Ein Punktwert wird nicht künstlich zu einer flächigen Wetterkarte hochinterpretiert.

---

# Router, Fachbereiche und Consumer-Profile

WeatherRouter besitzt aktuell acht Top-Level-Fachbereiche:

```text
Wetter
Pollen
Naturgefahren
Bevölkerungsschutz
Öffentliche Sicherheit
Luftfahrtwarnungen
Sonne & Weltraum
Biologische Gefahren & Wildtiere
```

Die Eligibility-Reihenfolge ist verbindlich:

```text
Router global
→ Fachbereich
→ Provider
→ Coverage / Health / Freshness / harte Anforderungen
→ optionales Consumer-Profil
→ konkrete Anfrage
```

Ein deaktivierter Router, Fachbereich oder Provider ist eine harte Netzwerkgrenze. Ein Consumer-Profil kann diese Freigaben nur weiter einschränken. Profile bieten Positivlisten für Fachbereiche, Familien, Phänomene, Capabilities, Ereignistypen und Warnstufen sowie deny-only Provider-Ausschlüsse. Sie dürfen weder global deaktivierte Quellen reaktivieren noch Providerprioritäten festlegen.

Pollen ist ein eigener Fachbereich. Die öffentlichen IDs lauten `pollen.*`; `weather.pollen.*` gehört nicht zum aktuellen Vertrag.

### Biologische Gefahren & Wildtiere

WR 0.10.71 ergänzt einen achten, opt-in Fachbereich für Wildtiere, toxische Arten und biologische Vorkommensdaten.

Der erste Provider **GBIF · Biologische Vorkommen** stellt **88 globale Vorkommensdichte-Layer** bereit, unter anderem für:

- Löwen, Pumas, Tiger, Leoparden, Jaguare, Bären und Wölfe;
- Krokodilartige einschließlich Nil- und Leistenkrokodil;
- Haie einschließlich Weißem Hai, Tigerhai und Bullenhai;
- Giftschlangen, Skorpione, Spinnen und marine Gifttiere;
- giftige Pflanzen, ausgewählte Giftpilze und biologische Vektoren.

Die Karten zeigen die **Dichte veröffentlichter Vorkommensnachweise**. Sie sind ausdrücklich **keine Populationsdichte und keine Gefahren-/Angriffswahrscheinlichkeit**.

Der Provider verwendet GBIF Species Match API v2 mit Catalogue of Life Extended Release (COL XR) sowie die Maps API über `api.gbif.org:443`. WR 0.10.73 ergänzt für homonyme Pflanzengattungen wie **Digitalis** und **Taxus** zusätzlich Rang-, Kingdom- und Autorenhinweise., ist standardmäßig deaktiviert und erzeugt ohne Aktivierung keinen Netzwerkverkehr.

Zusätzlich gibt es im Admin-Lab eine **freie GBIF-Taxonsuche**: Ein wissenschaftlicher Name oder höheres Taxon wird zur Laufzeit aufgelöst und als Vorkommensdichte-Layer dargestellt. Damit ist die Lab-Nutzung nicht auf die 88 Presets beschränkt.

Detail- und Quellenplan: **[`docs/BIOLOGICAL_HAZARDS_PLAN.md`](docs/BIOLOGICAL_HAZARDS_PLAN.md)**.

### Offizielle Blitzquellen · WR 0.10.76

WeatherRouter integriert vier eigenständige offizielle Blitzquellen:

- **FMI Lightning Open Data** · Ereignisse für Finnland/nördliches Europa;
- **EUMETSAT MTG Lightning Imager** · optische Total-Lightning-Raster für Europa/Afrika/Atlantik;
- **NOAA GOES-19/18 GLM** · offizielle LCFA-NetCDF-Dateien über NOAA NODD;
- **ECCC/MSC Lightning Density** · beobachtete Blitzdichte über Kanada.

Alle bleiben opt-in. Sie sind in der Gewitterradar-Profilvorlage bewusst **nicht**
automatisch freigeschaltet.

Quellenmatrix und Zugangsgates: **[`docs/LIGHTNING_SOURCES.md`](docs/LIGHTNING_SOURCES.md)**.

# WeatherRouter Lab

Das **WeatherRouter Lab** ist der interne Prüfstand der Integration.

Es enthält derzeit:

- **0 · Router-Steuerung** für globalen Router, Fachbereiche und einzelne Provider;
- Auswahl des Home-Assistant-Bezugsstandorts;
- Koordinaten und **Kartenstatus**;
- Kartenquelle und Kartenstil;
- **2 · Kartenebenen** mit Ein/Aus, Deckkraft und providerneutralen Rasterdaten;
- **4 · Punktwerte** für Wetter, Pollen sowie Sonne & Mond;
- Radar-Zeitverlauf;
- freie Diagnose-Matrix für Punktdaten;
- Rohdatenansicht für Entwicklungs- und Diagnosezwecke;
- einklappbare Hauptbereiche und Providergruppen;
- strukturierten lokalen Ereignislog mit kopierbarem JSON;
- goldenes Provider-`i` mit Diensten, Coverage, Stärken, Einschränkungen und Attribution.

Reine Frontendänderungen unter `custom_components/weather_router/frontend/` können nach Dateiaustausch normalerweise mit

```text
Strg + Shift + R
```

getestet werden. Änderungen an bereits importiertem Python-Code benötigen weiterhin einen kontrollierten Home-Assistant-Neustart.

Die Entwicklungsregeln dafür stehen in **[`docs/FRONTEND_DEV_RELOAD.md`](docs/FRONTEND_DEV_RELOAD.md)**.

---

## Gefahren- und Warnlogik

WeatherRouter führt Warnungen und Ereignisse in einer gemeinsamen, aber semantisch getrennten Taxonomie. Dazu gehören unter anderem schwere Gewitter, Tornado/Windhose, Wasserhose, Hagel, Starkregen, Sturm/Orkan, Blitz, Hochwasser, Sturzflut, Oberflächenüberflutung, Mure/Schlammstrom, Deichbruch, Dammbruch, Gletschersee-Ausbruch, Eisstau-Hochwasser, tropische Wirbelstürme, Erdbeben, Vulkanaktivität, Tsunami, Bevölkerungsschutz, öffentliche Sicherheit und Luftfahrtwarnungen.

Quellmeldungen werden nicht eigenmächtig hochgestuft. `tsunami_potential` bleibt beispielsweise von einer amtlichen Tsunamiwarnung getrennt. Unbekannte Provider-Ereignistypen bleiben erhalten und werden nur auf einen sicheren generischen Typ zurückgeführt.

# Bezugsstandort

WeatherRouter besitzt einen konfigurierbaren **Default-/Test-/Diagnosekontext**.

Aktuell werden automatisch angeboten:

```text
person.*
zone.*
```

Standard:

```text
zone.home
```

Der Bezugsstandort ist **keine globale Position für alle späteren Consumer**. Gewitterradar, Aurora oder andere Anwendungen müssen ihren eigenen Punkt beziehungsweise später ihren eigenen Viewport übergeben können.

---

# Schnittstellen

Der aktuelle V0.10-Prüfstand besitzt unter anderem diese internen bzw. administrativen WebSocket-Wege:

```text
weather_router/routing_settings
weather_router/routing_settings_update
weather_router/providers
weather_router/diagnostic_query
weather_router/map_layer
weather_router/hazard_feed
weather_router/provider_diagnostics
weather_router/all_provider_diagnostics
weather_router/routing_diagnostics
weather_router/routing_diagnostics_clear
weather_router/routing_diagnostics_subscribe
weather_router/consumer/discovery
weather_router/consumer/capabilities
weather_router/consumer/resolve
weather_router/consumer_profiles
weather_router/consumer_profile_upsert
weather_router/consumer_profile_delete
```

Dazu kommt der lokale Providervertrag mit:

```text
Provider
PointProvider
MapLayerProvider
CapabilityInfo
ProviderInfo
NetworkTargetInfo
```

Die Providerliste liegt datengetrieben unter:

```text
custom_components/weather_router/providers/registry.json
```

Ein **neuer, bisher nicht importierter Provider**, der einen bestehenden Vertrag erfüllt, kann im Entwicklungsbetrieb über Providerdatei + Registry ergänzt und anschließend im Lab neu entdeckt werden. Bereits importierter Python-Code wird bewusst nicht mit `importlib.reload()` zwangsgeladen.

Die exakten Request-/Response-Strukturen, Fehlercodes und Providerverträge stehen in **[`docs/INTERFACES.md`](docs/INTERFACES.md)**.

> [!WARNING]
> Die derzeitigen WebSocket-Befehle sind ein interner Entwicklungs-/Diagnosevertrag. Die spätere öffentliche Consumer-Schnittstelle für Gewitterradar/Aurora ist noch nicht freigegeben.

---

# Netzwerk und Datenschutz

Providerzugriffe bleiben serverseitig in Home Assistant. Provider dokumentieren ihre Netzwerkziele strukturiert über `network_targets()`.

Aktuell unter anderem:

```text
Open-Meteo   → api.open-meteo.com:443
RainViewer   → api.rainviewer.com:443
DWD          → maps.dwd.de:443 (+ dokumentiertes Backup)
NASA GIBS    → gibs.earthdata.nasa.gov:443
EUMETView    → view.eumetsat.int:443
MET Norway   → api.met.no:443
GloFAS       → ows.globalfloods.eu:443
FMI Lightning → opendata.fmi.fi:443
MTG-LI        → view.eumetsat.int:443
GOES GLM      → noaa-goes19/noaa-goes18 S3:443
ECCC Lightning→ geo.weather.gc.ca:443
GBIF         → api.gbif.org:443
Pollen       → air-quality-api.open-meteo.com:443
```

Der konkrete RainViewer-Tile-Host wird dynamisch aus den Provider-Metadaten ermittelt.

WeatherRouter soll Firewall-/Proxy-/DNS-Anforderungen **sichtbar machen**, aber keine Firewall, keinen Proxy und kein DNS automatisch verändern.

Diagnosedaten dürfen keine vollständigen privaten Koordinaten, Provider-Secrets oder unnötige Identifikatoren ausgeben.

Mehr dazu: **[`docs/NETWORK_FIREWALL_TRANSPARENCY.md`](docs/NETWORK_FIREWALL_TRANSPARENCY.md)**.

---

# Branding und Hilfe

WeatherRouter besitzt zwei bewusst getrennte Grafikrollen:

- **Emblem** — vollständige Präsentationsgrafik mit eigenem dunklen Rahmen/Hintergrund;
- **Brandmark** — freigestellte transparente Variante für Integration, Lab und kompaktere UI-Flächen.

Die kanonischen Grafikdateien liegen versioniert unter:

```text
assets/graphics/
```

Runtime-Kopien für die Integration liegen unter:

```text
custom_components/weather_router/frontend/assets/branding/
```

Die Branding-Regeln stehen in **[`docs/BRANDING.md`](docs/BRANDING.md)**.

> [!NOTE]
> Die Textstruktur, Manifestdateien und Checksummen für die transparente Brandmark sind bereits vorbereitet. Die Binärdateien selbst müssen vor dem Main-Merge noch exakt an den dokumentierten Pfaden importiert werden.

Zusätzlich enthält die Integration eine eigenständige HTML-Erklärseite:

```text
/weather_router_static/weather-router-help.html
```

Sie ist für den direkten Aufruf innerhalb einer laufenden Home-Assistant-Instanz gedacht und erklärt Zweck, Datenwege, Provider, Datenschutz und Entwicklungsstatus mit prominentem WeatherRouter-Branding.

---

# Projektdokumentation

WeatherRouter wird nicht nur über Quellcode dokumentiert. Architektur, Schnittstellen, Regressionsregeln, Tests und Entscheidungen werden dauerhaft im Repository gehalten.

Der zentrale Dokumentationseinstieg ist:

**[`docs/DOCUMENTATION.md`](docs/DOCUMENTATION.md)**

Besonders wichtig:

- [`docs/AI_CONTEXT.md`](docs/AI_CONTEXT.md) — kompakter, verifizierbarer Einstieg für KI/Codex und neue Entwickler;
- [`docs/ARCHITEKTUR.md`](docs/ARCHITEKTUR.md) — Architektur und Grenzen;
- [`docs/INTEGRATION_CONTRACT.md`](docs/INTEGRATION_CONTRACT.md) — optionale Consumer-Beziehung;
- [`docs/DIAGNOSTICS.md`](docs/DIAGNOSTICS.md) — Routing-/Consumer-Diagnose, Decision Trace, Coverage, Live-Modus und Export;
- [`docs/INTERFACES.md`](docs/INTERFACES.md) — tatsächlich implementierte technische Schnittstellen;
- [`docs/PROVIDER_ADAPTERS.md`](docs/PROVIDER_ADAPTERS.md) — Providervertrag und Erweiterungsablauf;
- [`docs/PROVIDER_NASA_GIBS.md`](docs/PROVIDER_NASA_GIBS.md) — NASA-GIBS-Adapter und Realtest-Gate;
- [`docs/PROVIDER_EUMETVIEW.md`](docs/PROVIDER_EUMETVIEW.md) — EUMETView-Adapter und Realtest-Gate;
- [`docs/RASTER_BUFFER_ENGINE.md`](docs/RASTER_BUFFER_ENGINE.md) — generische Raster-/Timeline-/Puffer-Engine und HAR-Abnahme;
- [`docs/NETWORK_FIREWALL_TRANSPARENCY.md`](docs/NETWORK_FIREWALL_TRANSPARENCY.md) — Netzwerktransparenz;
- [`docs/REGRESSIONSREGELN.md`](docs/REGRESSIONSREGELN.md) — Eigenschaften, die nicht still brechen dürfen;
- [`docs/V0_10_TEST.md`](docs/V0_10_TEST.md) — reale V0.10-Abnahme;
- [`docs/RELEASE_NOTES.md`](docs/RELEASE_NOTES.md) — kuratierte Release-/Entwicklungsnotizen und aktuelle Freigabegrenzen;
- [`docs/ENTSCHEIDUNGEN.md`](docs/ENTSCHEIDUNGEN.md) — dauerhafte Projektentscheidungen;
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — geplante und noch nicht freigegebene Arbeit.

---

# KI- und Entwickler-Einstieg

Für eine neue KI-/Codex-Sitzung gilt als kurzer Einstieg:

```text
1. AGENTS.md
2. docs/AI_CONTEXT.md
3. docs/BASELINE_STATUS.md
4. docs/INTERFACES.md
5. für Providerarbeit: docs/PROVIDER_ADAPTERS.md
6. für UI/Lab: docs/FRONTEND_DEV_RELOAD.md
7. danach erst die betroffenen Quelldateien
```

Implementierungsfakten werden aus dem aktuellen Repository verifiziert. Chat-Erinnerungen oder ältere Übergaben überschreiben keinen aktuelleren Quellstand.

---

# Projektgrenzen

Dieses Repository besitzt die konkrete WeatherRouter-Implementierung und WeatherRouter-spezifische Entscheidungen.

Projektneutrales, wiederverwendbares Wissen bleibt kanonisch in:

```text
TheDaimos/home-assistant-dev-toolkit
└── knowledge/weather/
```

Globale Projekt-/Arbeitsregeln bleiben in:

```text
TheDaimos/project-defaults
```

Consumer wie Gewitterradar oder Aurora dürfen zur Laufzeit **nicht** von privaten Zentral-Repositories abhängen.

---

# Entwicklungsstatus

**V0.10 ist eine real abgenommene Development-Baseline.**

Sie ist ausdrücklich **keine öffentliche Releasefreigabe**. Neue Provider, Consumer-Schnittstellen, automatisches Routing/Fallback und öffentliche Auslieferung werden jeweils als eigene, ausdrücklich freigegebene Entwicklungsblöcke behandelt.
