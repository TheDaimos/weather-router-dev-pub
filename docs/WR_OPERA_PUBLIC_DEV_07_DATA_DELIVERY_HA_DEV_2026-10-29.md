# WR-OPERA-PUBLIC-DEV-07 – Live-OPERA-S3-Quellmonitor und HA-DEV-Vorbereitung

**Datum:** 29.10.2026  
**Repository:** `TheDaimos/weather-router-dev-pub`, GitHub-Sichtbarkeit ausdrücklich PUBLIC bestätigt.  
**Branch:** `feature/p7-010-global-concurrency-2026-10-16`  
**Ausgangs-HEAD:** `1c62c35a50e62332bb887ed6769eb89c7ea1ca22`  
**Letzter mit vollständiger öffentlicher Haupt-CI geprüfter Codecommit:** `71cacee7f380b7211d9f41b05db54a3d547619d3`  
**DEV-Version:** `0.10.163` / Loader `166`; HA-Manifest-Vertragsbasis bleibt `0.10.0`.  
**Status:** **ABRUFPFAD CODEGETESTET / END-TO-END-KACHELN NICHT NACHGEWIESEN / SCIENCE UNVERIFIED-BLOCKED**.

## 1. Tatsächlich geänderte öffentliche Implementierung

### OPERA-S3-Quelle

Neu `custom_components/weather_router/opera_source_monitor.py`:
- Nutzt den vorhandenen authentifizierungsfreien öffentlichen CloudFerro-S3-Bucket `openradar-24h` mit einem bounded, TLS-gesicherten S3-ListObjectsV2-Katalogabruf. Begrenzung der XML-Liste auf 512 KiB, Fehler bei unvollständiger/trunkierter Liste, keine allgemeinen Host-URLs, kein offener Proxy.
- Parse-Sperren für ausschließlich strukturkonforme `YYYY/MM/DD/OPERA/COMP/OPERA@YYYYMMDDTHHMM@0@RATE|DBZH.tiff`-Schlüssel mit übereinstimmendem Datum und maximal 900 s Alter zum Anfragezeitpunkt. Der Objektname **belegt nicht** bereits die tatsächlich gültige ODIM/COG-Messzeit.
- Priorität RATE; DBZH besitzt einen getrennten Produktzweig, bleibt aber aufgrund fehlender eigenständiger wissenschaftlicher Freigabe noch deaktiviert; ACRR mangels spezialisierter Raster- und Akkumulationssemantik gesperrt.
- Für tatsächlich gelistete neue CoGs wird der bereits vorhandene `OperaCogFetch` verwendet (TLS, Antwortcode, Typ, Content-Length, TIFF-Magic, erneute Zeitprüfung und SHA-256-Admission in denselben Runtime-Cache). Bereits aufgenommene Generationen werden nicht laufend erneut abgerufen.
- Der Monitor führt **keine wissenschaftlich unvalidierten CoGs** in die aktive `RateTileRegistry`, in Consumer V2 oder in die HTTP-Kachelansicht über.
- 60-s-Monitorzyklus, begrenzte gleichzeitige Downloads und sichere Stop-Funktion; ein aktiver Netzwerkfehler führt nicht zu fiktiven Bildern.

### Aktivierung ohne zweiten globalen Schalter

- `custom_components/weather_router/__init__.py` bindet die Runtime beim HA-Config-Entry-Setup an die vorhandenen Optionen `router_enabled`, `enabled_domains` und `enabled_providers`.
- Nur bei **Router AN + Wetterbereich AN + Provider-ID `opera` aktiviert** startet ein einzelner Quellmonitor. Beim Unload wird dieser gestoppt und die Runtime samt Cache ordnungsgemäß geschlossen.
- `websocket_api.py` lässt den rein quellenbezogenen opt-in-Eintrag `opera` im bestehenden `weather_router/routing_settings_update` zu, ohne ihn als Consumer-V1-Provider mit unbewiesenen Capabilities zu publizieren. Der bestehende Routing-Updatehandler synchronisiert den Start/Stop dynamisch.
- Keine zusätzliche globale Vorschau-Aktivierung.

### Admin und manuelle Prüfung

- Neuer Admin-Only-WebSocket `weather_router/opera_refresh` führt **denselben** regulären S3-Abrufprozess einmalig aus (keine zweite Testpipeline).
- `weather_router/opera_status` ergänzt `source_monitor`: laufend, letzter erfolgreicher CoG-Eingang, zuletzt erkannter Objektname, aktive Downloads und letzter Verfügbarkeits-/Sperrgrund.
- `frontend/weather-router-lab.js`: Menü `6 · OPERA` enthält Provider aktivieren/deaktivieren, Live-Status und „Jetzt aktualisieren“, sowie die echten S3-Monitorwerte. Provideränderung erfolgt über die bereits bestehende Routing-WebSocket-Schnittstelle.
- Keine Zugangsdaten, vollständigen lokalen Dateien oder Credentials in dieser Diagnose.

### Version und Dokumentation

- `const.py` DEV_BUILD_VERSION `0.10.163`, DEV_LOADER_REV `0.10-loader-166`.
- `weather-router-lab.js`, `weather-router-lab-dev-loader.js`, `__init__.py` Frontend-Cache-Revision und `weather-router-help.html` abgeglichen.
- `tests/test_f7_l05_dev_candidate.py` behält alle bisherigen strengen Versionskonsistenztests, mit aktualisiertem erwarteten DEV-Build. `manifest.json` bleibt gemäß bestehendem akzeptierten Vertrag `0.10.0`, nachdem die öffentliche CI einen unzulässigen Basisversionswechsel festgestellt hatte.

## 2. Tests und öffentliche CI

Neu `tests/test_opera_source_monitor.py` mit fünf tatsächlichen Tests des öffentlich implementierten Katalogparsers und der Quellmonitor-Steuerung: Schlüssel-/Datum-/Produktfilter, unvollständige Listenantwort, veraltete/verdächtige Objekte, kein Netzabruf bei deaktiviertem Provider, deduplizierter Fetch-Start ohne frühzeitige Registry-Veröffentlichung. **Die Testquelle ist XML-/Fetcher-Simulation; kein echter aktueller S3-Dateidownload wurde ausgeführt.**

**Fokus-CI:** https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40937276809  
Geprüfter früherer Codecommit `fc5847182b0f81b772f070e4b3f67b104f288f1e`, Status SUCCESS. Python 3.12 und 3.13 jeweils 6 Cache + 5 HTTP-Vertragsprüfungen + 10 Runtime + 12 Journal + 5 neue Source-Monitor-Tests = **38/38 pro Version, 76/76 Fokustest-Ausführungen**. Die neueste finale Codeänderung ist im Haupt-CI, nicht erneut im Fokus-CI geprüft; dessen zuletzt mit Fokus-CI verifizierter SHA muss unterschieden werden.

**Vollständige Haupt-CI:** https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40938118590  
Geprüfter Codecommit `71cacee7f380b7211d9f41b05db54a3d547619d3`, **completed/success**.
- Python 3.12, Job `123673977195`: **1607/1607 Haupttests**, 106/106 Vorprüfungen, 2/2 Pixeltests, Struktur-/Paketkontrolle erfolgreich.
- Python 3.13, Job `123673977775`: **1607/1607 Haupttests**, 106/106 Vorprüfungen, 2/2 Pixeltests, Struktur-/Paketkontrolle erfolgreich.
- Haupttests insgesamt **3214 erfolgreiche Testausführungen**, nicht als 3214 einzigartige Tests interpretieren.

**Fehlersuche:** Ein Zwischen-Run am DEV-0.10.163-Stand schlug ausschließlich an zwei Vertragsprüfungen fehl: erwartete Version im bestehenden F7-Test und veraltete öffentliche HTML-Hilfeseite. Diese wurden synchronisiert. Der nächste Lauf scheiterte an der unveränderlichen `manifest.json`-Basis `0.10.0`; dieser Vertragswert wurde wiederhergestellt. Keine Tests entfernt, keine Sicherheitsgates gelockert.

## 3. Originaldaten, wissenschaftliche Grenzen, Consumer V2

Die offizielle Dokumentation von EUMETNET bestätigt: OPERA-Komposite RATE, DBZH und ACRR liegen öffentlich als ODIM-HDF5 und CoG vor; RATE und DBZH sind wissenschaftlich eigenständige Produkte, ACRR benötigt insbesondere eine separate Akkumulationszeitzuordnung. Quelle: https://eumetnet.github.io/openradardata-documentation/2-ORD-API-discovering-and-accessing-data/

**In diesem Arbeitsschritt tatsächlich erfolgreiche aktuelle OPERA-Dateidownloads: 0 nachgewiesen.**
**Tatsächlich fachlich geprüfte Original-ODIM/CoG-Messwert-Raster: 0.**
**Über Consumer V2 tatsächlich ausgelieferte OPERA-Raster: 0.**
**Über Home-Assistant-HTTP tatsächlich ausgelieferte OPERA-PNG-Kacheln: 0.**
**Durch Gewitterradar tatsächlich sichtbare OPERA-Kacheln: 0 nachgewiesen.**

`OperaProductContract.check_opera_raster()` endet weiterhin ausdrücklich mit `ready_for_public_tiles=False`, weil Qualität/Pixelsemantik nicht freigegeben sind. Die bestehende HA-ABI-Prüfung klassifiziert native Rasterio/GDAL-Verfügbarkeit auf HA OS als nicht nachgewiesen. Die Public-DEV-Laufzeit installiert weiterhin keine Native-Dependencies automatisch. **Keine falsche technische oder wissenschaftliche Freigabe.**

## 4. HA-DEV-109-Testfähigkeit

Die neue Version kann derzeit **nicht als bewiesen vollständig funktionsfähige OPERA-Datenversorgung auf HA DEV 109 freigegeben werden**. Für eine spätere kontrollierte Prüfung:
1. Erst Public-DEV-CI und native HA-OS-ABI/Installationsvorschau prüfen, keine PROD-Installation.
2. Nach ausdrücklicher kontrollierter Freigabe die DEV-Version `0.10.163` mit Loader `166` aus dem vorgesehenen Branch installieren.
3. Im Admin-Menü `6 · OPERA` den bestehenden OPERA-Provider aktivieren (Router und Wetterbereich müssen aktiviert sein), „Jetzt aktualisieren“ auslösen und den S3-Status sowie Verweigerungsgrund erfassen.
4. Kein Consumer-V2-/Gewitterradar-Realbild anfordern oder behaupten, bevor Originaldaten-/Qualitäts-/Geometrievalidierung sowie Rasterio-HA-ABI und tatsächliche HTTP-Registrierung nachgewiesen sind.
5. Fehlermeldungen und Tests ausschließlich nach `TheDaimos/Project-Log-And-Export@main` exportieren, sofern ein Export erfolgt.

Keine Installation wurde aus diesem Chat durchgeführt.

## 5. WR-OPERA-PUBLIC-DEV-08 – Priorisierter Folgeauftrag

**Repository/Branch:** Ausschließlich `TheDaimos/weather-router-dev-pub` (**PUBLIC**) / `feature/p7-010-global-concurrency-2026-10-16`.

1. **P0 – End-to-End RATE:** Aktuellen vollständigen öffentlichen OPERA-S3-ListObjects-/CoG- oder ODIM-HDF5-Datenweg mit tatsächlichen Originalen testen. S3-Rechte/Verzeichnisformat, Fallback an der UTC-Tagesgrenze, Objekt-Pagination, Quota und reale Datei-Hashes beweisen. Einen fachlich korrekten RATE-Originaldaten→Raster→CoG→Geo-Projektion→PNG-Nachweis mit Pixel-/Qualitätschecks, Quelldatum, NoData und wissenschaftlich korrektem Kartenbezug erbringen; keine fiktive Geometrie. Hierzu die offiziell vorhandenen validierten OPERA-Testoriginale rechtlich prüfen und verwenden.
2. **P0 – Consumer V2 / HTTP:** Die nachgewiesen geprüfte RATE-Rastergeneration unter bestehendem aktiven Provider und korrektem Profil über Consumer V2 abbilden, `OperaTileView` mit derselben Cache-Instanz registrieren und echte autorisierte HTTP-PNG-Kacheln ausliefern. Vor jeder Antwort Product/UTC/Scientific/Permission-Gates; keine offene Proxy-URL. Ohne Fachnachweis betreffende **RATE-Kacheln** blockieren, andere Produkte unabhängig halten.
3. **P0 – Monitoring:** Rate-Quelle auf tatsächlich vorhandenes Originalformat prüfen (S3-Dokumentation weist .h5 und CoG aus), Datei-Pagination sicher ausbauen, echte Fetch-Zeitpunkte und provider-scoped Fehlgründe liefern, kontrollierte Echtmonitor-Laufzeittests mit aktuellen Daten durchführen. Diensteinzeloptionen RATE/DBZH/ACRR im bestehenden Routermodell gezielt ergänzen, ohne neuen globalen Vorschau-Schalter; keine automatische Freigabe unvollständig validierter Produkte.
4. **P1 – DBZH/ACRR:** Beide Produktschienen mit eigenem ODIM/Raster/Geo/Quality/Time-Vertrag getrennt realisieren. DBZH nie automatisch in RATE umrechnen; ACRR muss die Zeitintervall-Semantik wissenschaftlich nachweisen.
5. **P1 – CI/HA:** Vollständige öffentliche Regression Python 3.12/3.13 plus echte S3-/Originaldaten-/HTTP-/Consumer-V2-Integrationstests, Versions-/Loader-/native ABI-Vertragsnachweis. Danach kontrollierte HA DEV VM109 Realabnahme mit Rollback und getrennter Wissenschaftsfreigabe; PROD VM101 unangetastet.
6. **Verbindliche Sicherheit:** GitHub Actions **ausschließlich im nachweislich öffentlichen `TheDaimos/weather-router-dev-pub`** nach Datenschutz-/Lizenzprüfung erlaubt. GitHub Actions in `TheDaimos/weather-router-dev` und **allen privaten Repositories absolut VERBOTEN**, einschl. Push, Pull Request, workflow_dispatch, workflow_call, automatische/indirekte/manuelle Trigger und Reruns. Private Repositories ausschließlich lesend, keine Commits und keine Übertragung vertraulicher Inhalte.
7. Diagnose- und Realtest-Exporte ausschließlich nach `TheDaimos/Project-Log-And-Export@main`. Keine Änderungen auf HA PROD VM 101 oder im Gewitterradar-Repository. Keine ungenehmigte Installation auf HA DEV VM109.

**Gesamtfreigabe: CI-GEPRÜFTER QUELLEN-INTAKE / VOLLSTÄNDIGE OPERA-KACHELVERSORGUNG WEITER GESPERRT.**
