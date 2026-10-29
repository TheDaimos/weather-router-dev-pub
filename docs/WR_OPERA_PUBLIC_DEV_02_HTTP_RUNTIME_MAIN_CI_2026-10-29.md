# WR-OPERA-PUBLIC-DEV-02 – HTTP-Laufzeitregression und reparierte öffentliche Haupt-CI

**Datum:** 29.10.2026
**Repository:** `TheDaimos/weather-router-dev-pub` (**PUBLIC**)
**Branch:** `feature/p7-010-global-concurrency-2026-10-16`
**Ausgangs-HEAD:** `f06d411738fdbd614fc8f464f1fd92d68e5e4976`
**Letzter vollständig erfolgreicher Quellstand:** `d3662b981b9ea807ca72e100d7650d526af103fd`
**Freigabe:** PUBLIC CI BESTANDEN; OPERA REAL-/WISSENSCHAFTSFREIGABE GESPERRT.

## P02-01 – Fehlgeschlagene Haupt-CI tatsächlich repariert

Historischer Run `40902289700` meldete unter Python 3.12/3.13 `1573` Tests, `36 failures`, `2 errors`. Die aktuellen früheren Runs enthielten außerdem HTTP-Testfehler, weil die bereits eingeführte Cache-Abhängigkeit nicht in die vorhandenen Testinstanzen injiziert war.

**Fehlerursache A (Testintegration):** `tests/test_opera_tile_http.py` erzeugte die tatsächliche `OperaTileView` weiterhin ohne `frame_cache`. Der Handler verweigerte daher zu Recht fail-closed mit HTTP 503. Die bestehenden positiven HTTP-Tests reichen jetzt denselben `ImmutableFrameCache` hinein, der die zugehörige `VerifiedFrame` erzeugt. Produktives Fail-Closed-Gate wurde nicht abgeschwächt.

**Fehlerursache B (Consumer-Vertrag):** Die öffentliche `consumer_capability_map.json` und `contracts/consumer_v1/capability-map.draft.json` bewarben OPERA als 39. Provider mit zwei Discovery-Capabilities und 229 Public-Routen, obwohl die öffentliche Provider-Registry noch keinen ausführbaren OPERA-Provider dafür enthält und die eingefrorenen V1-Verträge auf 38 Provider, 280 interne Capabilities und 227 Public-Routen ausgelegt sind. Fehlende Topic-, Utility-, Audit- und Zeitverträge verursachten daher breite Querschnittsfehler. Die beiden **nicht vollständig registrierten** Discovery-Einträge wurden ausschließlich aus dem aktiven V1-Consumer-Katalog zurückgestellt; keine OPERA-Quelldateien oder Tests gelöscht. Die zugehörigen `candidate_semantics`- und `provider_time_contracts.v1.json`-Einträge wurden synchronisiert. V1-Katalog und Contract-Datei sind wieder identisch; der dokumentierte Git-Blob-SHA des Gewitterradar-V1-Vertrags stimmt mit der Datei überein.

Ein OPERA-Discovery-Dienst darf erst nach vollständiger registrierter Provider-Implementierung und belegten Topic-/Time-/Utility-/Coverage-/Semantikverträgen erneut als Public-V1-Funktion erscheinen. Diese Korrektur ist keine Freigabe für Pixel-/Warnbereitstellung.

## P02-02 – HTTP-View und serverseitiger Cache

`opera_tile_http.py` unterstützt bereits die in PUBLIC-DEV-01 implementierte `frame_cache`-Injection und hält eine echte Cache-Leserlease bis zum Render-Worker-Ende.

**Befund:** Die öffentliche `custom_components/weather_router/__init__.py` hat derzeit **keine OPERA-HTTP-View-Registrierung und keine aktive OPERA-Provider-Registry**. Es gibt somit keinen gültigen servereigenen registrierten OPERA-Cache, der ohne weitere Providerimplementierung in der Integration angeschlossen werden könnte. Die HTTP-View bleibt bewusst unregistriert und damit fail-closed. Die Cache-Identität ist nun in den Laufzeittests geprüft, aber noch nicht in einer tatsächlichen HA-Integration. Keine zweite Cache-Instanz im Produktivcode als Behelf eingeführt.

## P02-03 – Tatsächliche asynchrone HTTP-Tests

`tests/test_opera_tile_http.py` verwendet die reale öffentliche `OperaTileView.get()`-Implementierung mit nur minimalen HA-Stubklassen. Der Test `test_http_executor_keeps_evicted_frame_until_worker_finished` wurde neu hinzugefügt:
- Blockierter tatsächlicher HTTP-Executor-Renderauftrag mit angepinnter `VerifiedFrame`.
- Aufnahme vier weiterer Quellframes in die echte `ImmutableFrameCache`-Instanz, wodurch die im HTTP-Worker verwendete alte Frame-Generation aus dem Cache-Katalog verdrängt wird.
- Feststellung: die aktive Rasterdatei bleibt trotz Eviction auf Disk.
- Erst nach Freigabe und tatsächlichem Render-Worker-Ende wird die zur Löschung vorgemerkte Datei entfernt.

Vorhandene öffentliche verhaltensorientierte HTTP-Tests behandeln zusätzlich Authentifizierung, Berechtigungswiderruf, Wartebudget, Deadline, Client-Cancellation und wissenschaftliche Sperren. Nicht alle P02-HTTP-01–10-Szenarien sind bereits als eigene vollständige neue Regressionstests implementiert; insbesondere echter Registry-Pointer-Swap und Zeitablauf während Worker-Rendering bleiben offen.

## P02-04/P02-05 – Generationen und Datenalter

Die bestehende `ImmutableFrameCache`-Lease verhindert die vorzeitige physische Löschung aktiv gelesener Frames. Vollständig atomare Generationenveröffentlichung, persistente active-Stamp-Wiederherstellung, fachlich vollständige RATE-/DBZH-/ACRR-Rasterzyklen sowie konsistente HTTP/Consumer-V2-Alterszustände sind weiter offen. Keine wissenschaftlichen Gates geöffnet.

## Tatsächlich durchgeführte öffentliche Linux-CI

- **Repository-Sichtbarkeit:** PUBLIC bestätigt.
- **Workflow:** WeatherRouter Public DEV - Pruefung
- **Run-ID:** `40906539602`; Head `d3662b981b9ea807ca72e100d7650d526af103fd`
- **Status/Conclusion:** `completed / success`
- **Python 3.12, Job-ID 123562733531:** zusätzliche Vorprüfung 106/106 PASS, Pixeltest 2/2 PASS, Haupt-`unittest discover` **1579/1579 PASS**, Struktur- und Paketprüfung erfolgreich.
- **Python 3.13, Job-ID 123562734142:** zusätzliche Vorprüfung 106/106 PASS, Pixeltest 2/2 PASS, Haupt-`unittest discover` **1579/1579 PASS**, Struktur- und Paketprüfung erfolgreich.
- **Summe Hauptregression:** 3158 bestandene Testausführungen (zwei Python-Versionen). Vorprüfungen sind separat und können inhaltlich mit der Hauptsuite überlappen.
- **Exitcode:** GitHub-Jobs und Workflow `success` (Prüfschritte Exitcode 0).
- Öffentlicher Link: https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40906539602

Andere, frühere Fehlruns gehören zu abweichenden Commits. Der Bericht selbst erzeugt einen neueren Dokumentations-Commit; dessen etwaige CI ist gesondert zu beurteilen.

## Nachweisbare Commitkette

- `69e2787497c6aaf059ca44929545cb1756523241`: bestehende echte HTTP-Laufzeittests erhalten gemeinsame Cache-Instanz.
- `1c784ec117a9e01fbc5bad233e414c2f223c3d08`, `c80f0b5e3eb20b6da576935dce91edf743fb0bff`: unregistrierte OPERA-Discovery im öffentlichen Consumer-V1-Vertrag zurückgestellt.
- `952eea98e43f3a5ab05073b22647874afb834365`: tatsächlicher asynchroner HTTP-Eviction-Test.
- `0414cf87b2991c2ead6e9dee84cc89ef87179c7d`: Zeitvertragsinventar bereinigt.
- `c40ed7247dfea6dec45fb13dabec56d11dd1a9bf`, `d3662b981b9ea807ca72e100d7650d526af103fd`: nicht registrierte Discovery-Pilotsemantik bereinigt; Quell- und Contract-Map wieder identisch.
- GitHub-Run `40906539602` bestätigt den finalen **Codezustand**.

## P02-06 – Offene Arbeitspakete / WR-OPERA-PUBLIC-DEV-03

**Ausschließlich** `TheDaimos/weather-router-dev-pub@feature/p7-010-global-concurrency-2026-10-16`:
1. Einen unabhängigen, wissenschaftlich weiterhin gesperrten OPERA-Provider samt servereigenem `RateTileRegistry`, derselben `ImmutableFrameCache`-Instanz und *deaktivierter* HTTP-View-Bereitstellung integrieren. Erst nach realem HA-/CI-Nachweis Zugriff freischalten; keine doppelte Cacheverwaltung.
2. Echte asynchrone HTTP-Tests erweitern für zwei parallele Leser, Timeout plus Eviction, Clientabbruch plus Eviction, Fehler plus Lease-Freigabe, Grenzübertritt der UTC-Altersgrenze und atomaren Registry-Wechsel. Die eigentliche `OperaTileView.get()` ausführen.
3. Atomare Frame-Promotion nach vollständig geprüfter Rastervorbereitung, monotone Zykluskennungen und sichere Leserleases im tatsächlich öffentlichen Runtime-Code verbinden; Crash-/Recovery-Fälle testen.
4. Produktspezifische RATE, DBZH, ACRR-Pfade getrennt entwickeln und wissenschaftliche Sperren erhalten. Erst danach unter vollständigen Contracts die OPERA-Discovery-Capabilities wieder öffentlich registrieren.
5. UTC-Messzeit-basierte Alters- und Datenverfügbarkeitszustände konsistent in Consumer-V2, HTTP und OPERA-Admin-UI einführen.
6. Öffentliche Haupt-CI und gezielte OPERA-HTTP-CI an jedem Implementierungsstand in PUBLIC ausführen, echte Run-IDs/Commits dokumentieren; HA DEV VM109 erst später kontrolliert realtesten.
7. **GitHub Actions im öffentlichen Repository ausdrücklich erlaubt**, nach bestätigter Sichtbarkeit/Datenschutz/Lizenz. **GitHub Actions in allen privaten Repositories ABSOLUT VERBOTEN** (Push, PR, Dispatch, automatisch, indirekt, Rerun). Private Repos nur lesend, keine Schreiboperationen. Keine PROD-Änderungen; Exportdaten ausschließlich `TheDaimos/Project-Log-And-Export@main`.

**Gesamtfreigabe: HA DEV NICHT REAL ABGENOMMEN; WISSENSCHAFTLICH UNVERIFIED/BLOCKED.**
