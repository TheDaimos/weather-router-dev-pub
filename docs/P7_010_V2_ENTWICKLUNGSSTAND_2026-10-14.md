# P7-010 – Öffentlicher Entwicklungsstand der mehrteiligen Rasterauflösung

**Datum:** 14.10.2026  
**Entwicklungszweig:** `feature/p7-010-raster-contract-2026-10-14`  
**Status:** Entwicklungsfunktion – **nicht** im privaten Auslieferungszweig aktiv, nicht in Home Assistant realabgenommen.

## Ziel

WeatherRouter darf künftig beliebig viele weitere regionale und großräumige
Quellen aufnehmen. Die Auswahl muss räumlich passend, zeitlich möglichst
kohärent und ausdrücklich providerneutral bleiben. Ein winziger regionaler
Kartenecken-Treffer darf niemals das globale Bild verdrängen. Bei ausreichender
Quelle bleiben großräumige Informationen erhalten; zusätzliche regionale
Informationen werden geografisch begrenzt ergänzt.

Gleiche Aufnahmezeit garantiert noch keine gleiche Messgröße: Einheit,
Messverfahren, Herkunft, Zeitbezug und Legende bleiben **pro Quelle**
unabhängig. Unbekannte Abdeckung oder unbekannte Messzeiten sind nicht
gleichbedeutend mit Regenfreiheit.

## Experimental WebSocket – nur V2

Neuer optionaler Befehl `weather_router/consumer/resolve_mosaic` mit
`contract_version: 2`, allein für `weather.precipitation.layer`.
Der bestehende Consumer-V1-Endpunkt `weather_router/consumer/resolve`
und dessen Einzelwinner-Verhalten bleiben unangetastet.

Beispiel für eine **synthetische Anfrage**, keine aktive
Produktanweisung und keine echten Wetterdaten:

```json
{
  "id": 201,
  "type": "weather_router/consumer/resolve_mosaic",
  "contract_version": 2,
  "capability": "weather.precipitation.layer",
  "context": {
    "type": "bbox",
    "west": -90,
    "south": 15,
    "east": 8,
    "north": 56,
    "focus": {"latitude": 21, "longitude": -76}
  },
  "time": {
    "mode": "latest_coherent",
    "max_data_age_seconds": 900,
    "max_time_delta_seconds": 180
  },
  "limits": {
    "max_layers": 3,
    "max_tile_requests": 24
  }
}
```

*Zeitwerte sind vorläufige, für Niederschlagsdarstellung ausdrücklich
konfigurierbare Versuchsparameter, kein allgemeingültiger Wettergrenzwert.*

## Sicherheits- und Lastgrenzen

- Der Consumer liefert **keine** Wunsch-Provider-IDs, interne Zugriffsrechte
  oder Auswahlprioritäten. Die Kandidaten stammen ausschließlich aus
  WeatherRouters eigenem Capability- und Providerkatalog.
- Router/Fachbereich/Provider müssen aktiviert sein. Bei vorhandenen
  Consumer-Profilen gelten diese weiter ausschließlich einschränkend.
- Nur Rasterkandidaten mit vom Provider gelieferten und validierten
  maschinenlesbaren Abdeckungen sind zulässig; keine Länderliste und
  kein unbelegter Welt-Fallback.
- Vorprüfung begrenzt auf 12 Coverage-Kontakte bei höchstens drei
  parallelen Prüfungen und einer einzelnen Zeitgrenze.
- Die eigentliche Mehrquellenabfrage arbeitet mit begrenzter Zahl an
  Quellen und gleichzeitigen Abrufen, begrenzten Zeitfenstern und
  Kachel-/Quellenbudget. Noch nicht verfügbare oder zu alte Bilder
  scheiden aus; unbekannte Bildzeiten werden nicht aus Abrufzeiten
  erfunden.
- Der Verarbeitungsbaustein wählt nach Möglichkeit zeitnähere verfügbare
  Bilder/Frames. Wesentliche Zeitunterschiede werden kenntlich gemacht.
- Mehrere Quellen werden **als getrennte, geografisch begrenzte Ebenen**
  zurückgegeben, nicht zu erfundenen Niederschlagsmesswerten vermischt.

## Bereits implementierte öffentliche Bausteine

- `raster_mosaic_contract.py` – V2-Anfrageprüfung.
- `raster_mosaic_adapter.py` – nur geprüfte, öffentliche V1-Normalisierung.
- `raster_mosaic_policy.py` – deterministische räumliche und zeitliche
  Quellen-/Bilderauswahl.
- `raster_mosaic_service.py` – asynchrone, ressourcenbegrenzte Zusammenstellung.
- `consumer_raster_mosaic_api.py` – experimenteller, separat registrierter
  V2-WebSocket-Endpunkt; bestehende V1-Befehle unverändert.
- `tests/test_p7_010_raster_mosaic_*.py` – synthetische Testfälle für
  Quellenwahl, Zeitfenster, Anbieterabschaltung, Sicherheit, Fehlerausfälle,
  begrenzte Parallelität und den tatsächlichen Handler-Kontrollfluss.

## Noch offene Abnahmegrenzen

- Keine echte HA-Installation oder End-zu-End-Providerprüfung des
  experimentellen WebSocket-Endpunkts. Die isolierte Handler-Prüfung
  benutzt kontrollierte Anbieter-Stellvertreter, keine reale HA-Laufzeit.
- Die Coverage-BBOX allein beweist keine vollständige Pixelversorgung;
  Polygon-/Pixelmasken, echte Lücken, Kachelserverfehler und tatsächliche
  geographische Komposition sind gesondert zu prüfen.
- Das maximal zugelassene **Kachelbudget** begrenzt bereits die mindestens
  benötigte Zahl gleichzeitiger Ebenen, ist aber noch **nicht** als
  tatsächlicher Gesamtzähler aller Kachelanforderungen an einem produktiven
  Kartenrenderer angeschlossen. Der Consumer muss dies später durchsetzen.
- Kein aktiver Gewitterradar-V2-Renderer, keine DRA-Installation, kein
  iPad-Lasttest, keine validierte Bildinhaltsanalyse.
- Erweiterte zeitliche Gültigkeitsarten, prognostische Daten und
  fachliche Grenzwerte je Capability sind erst nach eigener Abnahme
  freizugeben. Die Rückgabe bleibt konservativ `partial` oder
  `unavailable`, bis echte vollständige Pixelabdeckung belegt ist.

## Prüf- und Veröffentlichungsstrategie

Aus GitHub-Minutenkontingent-Gründen erfolgen öffentlich zulässige
Entwicklungsprüfungen in diesem **öffentlichen Entwicklungszweig**.
Für ein vollständiges Nachholregister aller nicht gestarteten privaten
Actions werden **keine privaten Commit- oder Runnerdaten veröffentlicht**.
Das Register wird ausschließlich im privaten Repository gepflegt.

Eine erfolgreiche CI prüft Code und synthetische Abläufe. Sie ersetzt
**nicht** die private Home-Assistant-/DRA-Produktabnahme und bedeutet keine
Veröffentlichungsfreigabe für andere private Inhalte.

## Ergänzung: Quellengetreue Rasterparameter und echte Provider-Abdeckung

Am 14.10.2026 wurden V2-Schema, reiner Adapter und Auswahllogik um
quellenspezifische Darstellungsparameter erweitert:
`render.tile_size` (128/256/512 Pixel), `render.min_zoom`,
`render.max_zoom` und `render.opacity`. Die Parameter werden aus
den bereits öffentlich normalisierten V1-Quelldaten übernommen und
auf gültige Werte geprüft. Gewitterradars isolierter
`src/p7-010/raster-compositor.js` kann dadurch native Quellkacheln
in die richtige Zielkachelgröße umrechnen, lokale Zoomgrenzen beachten
und Deckkraft je Quelle unabhängig einsetzen. Die Werte werden
**nicht** in eine gemeinsame meteorologische Messskala umgerechnet.

Die öffentliche GitHub-Prüfung [38631643647](https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/38631643647)
lief auf Commit `e59ee9c526dfb07ab185175f60b23e349330ff28`
erfolgreich mit Python 3.12 und 3.13. Die tatsächliche
Anbieter-Bestandsprüfung [38632252752](https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/38632252752)
bestätigt ebenfalls die öffentlichen Tests für die aktuelle
`weather.precipitation.layer`-Capability-Zuordnung.

**Aktueller realer Adapterbestand:** Bei der fünf internen
Niederschlags-Rasterzuordnungen bietet RainViewer
`async_get_map_layer`, derzeit aber **keine**
`async_get_coverage`-Methode. Sein lesbarer Hinweis auf internationale
Radarabdeckung ersetzt keine verifizierte geographische Maschinen-Coverage.
Daher wird RainViewer vom experimentellen V2-WebSocket-Endpunkt noch
nicht als bestätigte Mehrquellenebene verwendet.
DWD und NASA GIBS stellen eine solche Methode bereit; das garantiert
trotzdem weder die Erreichbarkeit der WMS-Server noch lückenlose
gültige Rasterpixel auf der Weltkarte. Eine mögliche RainViewer-V2-
Anbindung muss erst eine fachlich belastbare maschinenlesbare
Räumlichkeitsgrundlage nachweisen.

**Unveränderte Produktgrenze:** Das ist ein geprüfter öffentlicher
Entwicklungsstand, kein per DRA ausgerolltes Gewitterradar-Mosaik.
P7-010-VIEWPORT-COVERAGE, CONSUMER-ADAPTER und HA bleiben bis
produktiver Anbindung, echten Wetterabrufen und gebündelter
Geräteabnahme offen.

## Ergänzung: Isolierte Consumer-Kette bis zur Leaflet-Kartenebene

**Stand 14.10.2026, weiterhin ohne DRA-/HA-Freigabe.**

Im getrennten Gewitterradar-Entwicklungszweig
`feature/p7-010-world-bbox-2026-10-14` stehen inzwischen reine
V2-Bausteine für:

- `raster-mosaic-consumer.js`: begrenzte V2-Consumer-Anfrage mit
  Bounding-Box und tatsächlichem Kartenfokus, V2-Antwortprüfung und
  **nicht destruktivem V1-Rückfall**, falls WeatherRouter V2 nicht
  erreichbar ist oder keine Quelle bereitsteht;
- `raster-mosaic-grid-layer.js`: isolierte Leaflet-`GridLayer` mit
  gemeinsamer Abrufbegrenzung und Canvas-Kacheln;
- `raster-mosaic-tile-loader.js`: URL-basierter, begrenzt paralleler
  Bildabruf mit Zeitgrenze und Abbruchsignal, regionaler Ausfall
  darf das verfügbare großräumige Bild nicht entfernen;
- `raster-tile-url.js`: korrekte XYZ- und
  `{bbox-epsg-3857}`-WMS-Ersetzung, auch bei wiederholten Weltkacheln
  und am Antimeridian;
- `raster-tile-clip.js` und `raster-compositor.js`:
  maschinenbestätigte geografische Zuschnitte, quelleneigene
  Kachelgröße, Zoombegrenzung und Deckkraft.

**Schnelle separate CI**, zusätzlich zur vollständigen vorhandenen
Gewitterradar-Frontend-Prüfung: [P7-010 Lauf 38633971874](https://github.com/TheDaimos/gewitterradar/actions/runs/38633971874),
**8 von 8 isolierten Prüfskripten SUCCESS**, aktueller dokumentierter
Commit `347b74059df19e7cb3420c6e80c57f1783f202f8`.
Die unter GitHub Actions vorhandene
`.github/workflows/p7-010-raster-isolated.yml` prüft künftig
alle P7-Module unabhängig von der zeitintensiven Browsergesamtprüfung.

**WeatherRouter public CI:** [Lauf 38632573180](https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/38632573180),
Python 3.12 + 3.13 **SUCCESS**, je 1.225 Python-Gesamttests
(einschließlich 61 expliziten P7-Rastertests), M2-Struktur,
JavaScript-Syntax, Git-Export sowie öffentliche Integrationspaket-
und SHA256-Prüfung mit 117 Dateien.

**Nicht abgenommen:** Es existiert noch keine produktive
Gewitterradar-Modulanbindung, kein realer V2-WebSocket-Abruf im Home
Assistant, keine tatsächliche WMS-/Bildserver-Rasterdarstellung auf
Android/Desktop/iPad und keine DRA-Auslieferung. Die vorhandene
Quelllücken- und Leistungsdiagnose ist deshalb weder grün noch
ersetzt sie eine Realabnahme. V1 bleibt unverändert verwendbar.
