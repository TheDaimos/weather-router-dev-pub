# WR-OPERA-PUBLIC-DEV-03 – Serverseitige OPERA-Registry und atomare Generationen

**Datum:** 29.10.2026  
**Repository:** `TheDaimos/weather-router-dev-pub` (**PUBLIC**)  
**Entwicklungsbranch:** `feature/p7-010-global-concurrency-2026-10-16`  
**Ausgangs-HEAD:** `2c6dd686a1dc6166a46f6b9aa752b8558c1f1a4b`  
**Vollständig regressionsgeprüfter Codecommit:** `e6e2e2e0cfe4a66d4e0b8374b30e0e77a1fb2ee4`  
**Freigabe:** TECHNISCHE TEILREGRESSION BESTANDEN; HA-REALABNAHME UND WISSENSCHAFTLICHE FREIGABE GESPERRT.

## Implementierter tatsächlicher öffentlicher Code

1. `custom_components/weather_router/opera_runtime.py` **neu**: `OperaRuntime` mit genau einer `ImmutableFrameCache`-Instanz und einer `RateTileRegistry`. Produktgetrennte aktive Generationen, unveränderliche `PreparedCycle`-Referenzen, serverseitige Synchronisierung mit `RLock`.
2. `OperaRuntime.prepare()`: Erst Prüfung von zulässiger Produktklasse, Quellattribution und UTC-Messzeit, danach hash-verifizierte Frame-Admission in die **gemeinsame** vorhandene Cache-Instanz, anschließend vorbereitete Registrierung. **Noch keine aktive Veröffentlichung**.
3. `OperaRuntime.promote()` und `RateTileRegistry.promote()`: Synchronisierte Verifikation des vollständigen vorbereiteten Zyklus, Monotonie nach UTC-Zeitstempel, gleicher Timestamp nur bei gleichem Digest idempotent, keine ältere oder inkonsistente Generation. Verdrängte vorbereitete Rasterdateien dürfen nicht aktiviert werden. Erst danach atomarer Registry-Zeigerersatz.
4. `OperaRuntime.lookup()`: Fail-closed, solange die öffentliche Provider-/Dienstfreigabe deaktiviert ist; zusätzlicher UTC-Alterscheck. `enabled=False` und sämtliche Einzelservices standardmäßig False.
5. `utc_status()`: CURRENT, STALE, UNAVAILABLE aus dem fachlichen UTC-Quellzeitpunkt (Standard 1500s, max. 900–3600s, historische Schranke 3600s).
6. `custom_components/weather_router/__init__.py`: Im realen `async_setup()` wird eine einzelne servereigene `OperaRuntime` in `hass.data[DOMAIN]["opera_runtime"]` abgelegt. Wiederholter Setup-Aufruf erzeugt nicht jedes Mal eine zweite ungenutzte Cache-Instanz.
7. **Keine HTTP-Registrierung und keine automatische Dienstaktivierung.** Vorhandene `OperaTileView`-HTTP-Sicherheitsgates, Consumer V1 und bestehende wissenschaftliche Sperren bleiben unberührt. ACRR hat ausdrücklich **noch keine** eigenständige Rastervalidierung; `prepare(product="ACRR")` wird verweigert. RATE und DBZH werden als separate Metadatenklassen geführt, aber ihre wissenschaftliche Produktprüfung/Originaldaten-Rasterverarbeitung ist **nicht abgeschlossen**.

### Tatsächliche Commits

- `1c69be641a6095ee011fe235ff625e15ac11cf99`: öffentlicher OPERA Runtime/Registry-Code.
- `1566437e9cf60efb878991e728b9bce2634555d4`: serverseitige Einbindung in Home Assistant.
- `8faad2300192ab1625284713d323ccee04947d55`: doppelte Cache-Erstellung bei wiederholtem Setup verhindert.
- `991fb1471229051c11e4328ed6253795023c5240`: 9 verhaltensorientierte Runtime-Unit-Tests.
- `e6e2e2e0cfe4a66d4e0b8374b30e0e77a1fb2ee4`: öffentliche OPERA-CI erweitert.

## Tatsächlich ausgeführte öffentliche GitHub Actions

**Öffentlicher Repository-Status vor Ausführung:** `PUBLIC` nach GitHub-Metadaten bestätigt; keine privaten Quelltexte synchronisiert. Öffentliche Workflow-Datei inhaltlich kontrolliert. Commit auf öffentliches Feature-Branch; ausschließlich dort entstanden CI-Runs.

### OPERA-Fokus-CI
- URL: https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40909510075
- Run `40909510075`, Head `e6e2e2e0cfe4a66d4e0b8374b30e0e77a1fb2ee4`, `completed/success`.
- Python 3.12 Job `123573325284`: 6 Cachetests, 5 HTTP-Lease-Vertragsprüfungen und **9 tatsächliche Runtime-Verhaltenstests**, alle **20/20 PASS**.
- Python 3.13 Job `123573325054`: identisch, **20/20 PASS**.
- Insgesamt **40/40 Testausführungen**.

### Vollständige öffentliche Haupt-CI
- URL: https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40909510179
- Run `40909510179`, gleicher Head, `completed/success`.
- Python 3.12 Job `123573324986`: 1588/1588 Haupttests PASS, 106/106 Vorprüfungen PASS, 2/2 Pixeltests PASS, Struktur-/Paketschecks PASS.
- Python 3.13 Job `123573325482`: identische 1588/1588 Haupttests PASS, 106/106 Vorprüfungen PASS, 2/2 Pixeltests PASS, Struktur-/Paketschecks PASS.
- Insgesamt **3176 bestandene Haupt-Testausführungen**. Fokus-CI enthält Wiederholungen; Ergebnisse **nicht** als einzigartige Tests addieren.
- Exitcodes: alle GitHub-CI-Jobs/Schritte success, Prozess-Exitcode 0 für bestandene Schritte.

## Nicht nachgewiesen oder offen

- **Kein OPERA-S3-Echtabruf, keine vollständige Originaldatenprüfung:** die Runtime hat bislang keine produktive Originaldatenerfassung oder ODIM/ACRR-Fachvalidierung. Ein synthetischer hash-geprüfter Frame allein ist keine OPERA-Messwertfreigabe.
- **Keine registrierte aktive OPERA-HTTP-Route**: kein aktueller Home-Assistant- oder Gewitterradar-Kachelabruf. Keine unbewiesene echte Verbraucherfreigabe.
- Kein persistentes Frame-Manifest und keine Crash-/Neustart-Recovery.
- Cache-Eviction und laufende Leser sind durch die bereits existierende Lease-Implementierung und neue Tests teilweise abgesichert; generationensichere Promotion ist ergänzend getestet. Noch keine echten S3-/HTTP-/Restart-Gesamtstresstests.
- `utc_status()` ist noch nicht vollständig mit Consumer-V2, HTTP und Administrationsoberfläche verknüpft.
- RATE, DBZH und ACRR sind fachlich noch nicht als drei vollständige Rasterpipelines umgesetzt; keine Wiedereinführung der zuvor bewusst zurückgestellten Discovery-Capabilities.
- Keine echte HA DEV VM 109 Installation oder Realabnahme. HA PROD VM 101 unverändert.
- Public-DEV-Versionierung nach vorhandener Architektur nicht eigenmächtig verändert; keine private Versionsnummer übernommen.

## WR-OPERA-PUBLIC-DEV-04 – verbindlicher Folgeauftrag

**Ausschließlich** `TheDaimos/weather-router-dev-pub@feature/p7-010-global-concurrency-2026-10-16`:
1. **P0:** Bereits jetzt beim HA-Setup angelegte öffentliche `OperaRuntime` in einen dauerhaften, reload-/unload-sicheren Serverlebenszyklus überführen; keine Frame-Cache-Leaks. Wissenschaftlich gesperrten HTTP-Zugriff nur als explizit deaktivierte/fail-closed Runtime-Komponente anbinden; nie automatisch freischalten.
2. **P0:** `OperaRuntime` mit eigener hashverifizierter, atomarer Persistenz des aktiven Generation-Manifests inklusive Integrity-/Time-/Provider-/Dienstprüfung bei Neustart ausstatten. Beschädigte Dateien/Stagingreste fail-closed. Tatsächliche Crash-/Recovery-/Parallelitäts-Laufzeittests.
3. **P0:** Einheitlichen UTC-Zustandsvertrag (CURRENT/STALE/UNAVAILABLE) in Registry, OPERA-HTTP und Consumer-V2 **vor jedem Response** erzwingen; keine Altersverlängerung durch Downloads. Tests zur Altersgrenzüberschreitung während Render-Worker.
4. **P1:** RATE, DBZH und ACRR jeweils über eigenständige OPERA-Originaldaten-, Produktsemantik-, Rasterprojektion- und Verifikationswege anbinden. Wissenschaftliche Sperren beibehalten; unregistrierte OPERA-Discovery nicht vorzeitig erneut öffentlich anbieten.
5. **P1:** Serverseitige OPERA-Admin-Status-WS, Ring-/Cache-/Cycle-Diagnose ohne Geheimnisse, angepasste Anzeige `6 · OPERA` integrieren.
6. **P1:** Verhaltensorientierte HTTP-Tests mit gemeinsamen Cache und zwei parallelen Lesern, Tokenwiderruf, Timeout, Cancel, Eviction, Registry-Pointer-Swap, Fehlrender und UTC-Ablauf ergänzen; Gesamt-CI unter Python 3.12/3.13 erneut ausführen.
7. **Sicherheit:** **GitHub Actions ausdrücklich erlaubt NUR in dem nachweislich PUBLIC Repository `TheDaimos/weather-router-dev-pub` nach Datenschutz-/Lizenzprüfung. GitHub Actions aus allen privaten Repositories AUSNAHMSLOS VERBOTEN**, einschließlich Push, PR, workflow_dispatch, workflow_call, automatische, manuelle und indirekte Ausführungen sowie Reruns. Private Repositories nur lesend für Bestands-/Regressionabgleich, keine Commits, keine Datenübernahme.
8. **Keine PROD-Änderungen**, keine ungenehmigten DEV-VM-Installationen. Diagnose- und Realtestexporte ausschließlich nach `TheDaimos/Project-Log-And-Export@main`. Aktuelle CI-Run-IDs und exakte Code-Commits nachweisen; keine wissenschaftliche Freigabe ohne Originaldatennachweis.

**Gesamtstatus: ÖFFENTLICHER CODEGETESTETER TEILERFOLG / OPERA-WISSENSCHAFTLICH UNVERIFIED/BLOCKED / HA DEV NICHT REAL ABGENOMMEN.**
