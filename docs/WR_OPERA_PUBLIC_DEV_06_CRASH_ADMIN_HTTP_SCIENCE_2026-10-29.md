# WR-OPERA-PUBLIC-DEV-06 – Journal-Serialisierung, HTTP-UTC-Laufzeittest und öffentliche CI

**Datum:** 29.10.2026  
**Repository:** `TheDaimos/weather-router-dev-pub` (**PUBLIC**, geprüft)  
**Branch:** `feature/p7-010-global-concurrency-2026-10-16`  
**Ausgangs-HEAD:** `b7a5cc9680c6f186c6f2e3c4927e879ca2ebcdac`  
**Erfolgreich geprüfter Codecommit:** `b608e4a99a8091d64c1f2a9e6bb53775704b03fc`  
**Freigabe:** technisch teilimplementiert, HA DEV VM109 nicht real abgenommen, OPERA wissenschaftlich **UNVERIFIED/BLOCKED**.

## 1. Tatsächliche Quellcodeänderungen

### Persistenz und konkurrierende Writer

`custom_components/weather_router/opera_cycle_store.py`:
- `CycleJournal` verwendet nun für jede `commit()`-Transaktion eine Linux-`fcntl.flock`-Sperre auf `.journal.lock`, um parallele Journal-Writerprozesse an derselben Verzeichniswurzel zu serialisieren.
- Konfigurierbarer Konstruktorparameter `max_disk_bytes`, validiert im Bereich 24–256 MiB (Standard 32 MiB), begrenzt die zugelassenen aktiven Daten plus neue Frame-Kopie. Die physische Belegung wird zusätzlich per `disk_usage()` gemessen.
- `cleanup()` und transaktionsinterne Bereinigung entfernen nur an erkennbaren Dateinamen identifizierbare, **nicht** vom gültigen Manifest referenzierte Journal-Kopien und unvollständige Stagingreste; das aktive Manifest wird vor Löschung vollständig geprüft. HTTP-Cachedateien werden nicht berührt.
- Alte Crash-Sperren bleiben: Hash und Dateigröße werden bei `inspect()` erneut kontrolliert, jüngere Journalgenerationen dürfen nach Neustart nicht durch ältere ersetzt werden, Recovery liefert niemals eine wissenschaftliche Berechtigung.
- **Grenzen:** Das Quota berücksichtigt insbesondere die belegten Nutzdaten; es ist noch kein garantierter physischer Maximalwert aller temporären Metadaten und Crash-Artefakte. `fcntl.flock` ist Linux-spezifisch; ein echter Multiprozess-Crash-Stresstest fehlt. Die tatsächlichen `fsync`-/`os.replace`-Prozessabbrüche an allen sieben Phasen wurden **nicht** simuliert. Keine Recovery-Freigabe.

`custom_components/weather_router/opera_runtime.py`:
- `status()` liefert `persistent_bytes` und `journal_present` aus der tatsächlichen servereigenen Journal-Instanz.

`custom_components/weather_router/frontend/weather-router-lab.js`:
- Admin-Menü `6 · OPERA` zeigt nun die gemessene persistente Belegung oder ausdrücklich `nicht verfügbar` an, statt 0 Bytes zu erfinden.

### HTTP/UTC

`tests/test_opera_tile_http.py`:
- Neuer verhaltensorientierter asynchroner Test `test_utc_expiry_during_actual_async_render_is_denied` startet die **tatsächliche öffentliche `OperaTileView.get()`**, blockiert ihren echten Executor-Ablauf bei gepinntem Frame, verschiebt die kontrollierte UTC-Uhr von 899 auf 901 Sekunden und prüft, dass **HTTP 403** vor der Pixelantwort erfolgt. Die eigentliche Renderfunktion ist kontrolliert simuliert, nicht der HTTP-Handler.
- Die bestehende strengere HTTP-Altersgrenze `900 s` wurde **nicht** gelockert. Eine zentralisierte 1500-s-Policy über Consumer V2, Runtime, Registry und HTTP bleibt offen.
- Bereits vorhandene Timeout-, Client-Cancellation-, Readerlease-, Eviction- und Berechtigungs-Laufzeittests wurden nicht entfernt.

### Vorhandenes Admin-WebSocket

Die bestehende Admin-Only-Schnittstelle `weather_router/opera_status` wird weiterhin verwendet, aber **neue verhaltensorientierte WebSocket-Admin-/Nichtadmin-Tests** wurden in diesem Abschnitt **nicht** implementiert. Keine HA-Realabnahme; zugehörige Adminrolle ist über den bestehenden `require_admin`-Decorator geschützt.

### RATE/DBZH/ACRR, Consumer V2

Keine neue wissenschaftliche Originaldaten-Verifikation vorgenommen. Produktwege bleiben getrennt und gesperrt; ACRR ohne gesicherte Produktpipeline. Keine Reaktivierung der vorzeitig zurückgestellten OPERA-Discovery-Capabilities, keine aktive HTTP-Route und keine Consumer-V2-OPERA-Freigabe. Keine heimliche Veröffentlichung privater Quellen.

## 2. Testfehler, Korrektur und CI-Ergebnisse

Die erste Erweiterung führte zur OPERA-CI **`40934329388`: FAILURE** unter Python 3.12/3.13 im neuen Test `test_journal_orphan_cleanup_preserves_live_generation`. Ursache: das neue Journal-Dateimuster war falsch escaped und erkannte verwaiste Dateien nicht. Korrektur in `b608e4a99a8091d64c1f2a9e6bb53775704b03fc` mit eindeutigen Ziffernklassen. Kein Test entfernt.

**Öffentliche OPERA-CI – SUCCESS:**  
https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40934475372
- Head `b608e4a99a8091d64c1f2a9e6bb53775704b03fc`; Python 3.12, Job `123661258172`: Cache 6/6, HTTP-Quellcodevertrag 5/5, Runtime 10/10, Journal 12/12 = **33/33 PASS**.
- Python 3.13, Job `123661258821`: identische **33/33 PASS**.
- **66/66 Fokustest-Ausführungen**, Workflow abgeschlossen/success.

**Vollständige öffentliche Haupt-CI – SUCCESS:**  
https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40934475398
- Head wie oben; Python 3.12, Job `123661258482`: **1602/1602 Haupttests**, 106/106 Vorprüfungen, 2/2 Pixeltests, Provider-Struktur/Paket OK.
- Python 3.13, Job `123661259050`: identische **1602/1602 Haupttests**, 106/106 Vorprüfungen, 2/2 Pixeltests, Struktur/Paket OK.
- **3204/3204 Haupttest-Ausführungen**; alle gemeldeten CI-Jobs/Schritte erfolgreich; Fokus-Tests sind nicht als zusätzliche eindeutige Testfälle zu zählen.
- Die neue asynchrone HTTP-Alterstestprüfung ist Teil der vollständigen Hauptsuite.
- Kein echter Home-Assistant-, Browser- oder Originaldaten-Abnahmelauf.

## 3. Commits und Quellcode-Readback

- `ff461fd9e2dede11c0d0ecd1e76ce21fa3c5f682`: Cross-process-Lock, Quota und Journaldatenbereinigung.
- `d42b89a86d8029c3a08c26baba70d1b0c92dd4e8`: gemessene Runtime-Persistenzbelegung.
- `04a4e823bd663d5b7c34cb73c84ad0aa4d9e7edc`: Verhaltenstests Orphan-Cleanup und konkurrierende Writer.
- `b90f185f21437c8ddeb2f3b1c40afe2eb36d684d`: echter asynchroner HTTP-Expiry-Test.
- `fb11939b070f72450e46e22254b54877c445cdb6`: Frontend-Persistenzbelegung.
- `b608e4a99a8091d64c1f2a9e6bb53775704b03fc`: Journal-Dateimusterfehler behoben, **CI-geprüfter Codecommit**.

## 4. WR-OPERA-PUBLIC-DEV-07 – priorisierter Entwicklungsauftrag

**Repository:** Ausschließlich `TheDaimos/weather-router-dev-pub`, Sichtbarkeit **PUBLIC**, Branch `feature/p7-010-global-concurrency-2026-10-16`. Zuerst diesen Bericht, aktuellen HEAD und die beiden erfolgreichen GitHub-CI-Runs lesen.

1. **P0 Crash-Injection:** Tatsächliche Prozessunterbrechungen in `CycleJournal._atomic_bytes()` an sieben geforderten Punkten (Frame-Write, Frame-fsync, Manifest-Write, Manifest-fsync, Manifest-Replace sowie Journal-Commit vs. Registry-Swap) mit realen `multiprocessing`- bzw. subprocess-Fault-Injection-Tests. Endzustände und unbegrenzte temporäre Dateien sicher aufräumen. Cross-process Lock-Tests nicht mit reiner Thread-Simulation ersetzen.
2. **P0 HTTP/UTC:** Einheitlichen, konfigurierbaren UTC-Vertrag an tatsächlichem Consumer API V2 und HTTP-Sicherheitsgates implementieren; 900-s-Preflight ohne verifizierten gemeinsamen Vertrag nicht einfach öffnen. Echte `OperaTileView.get()`-Tests für zwei parallele Leser, Pointer-Swap, Cache-Eviction, Timeout, Cancel und die Messzeitgrenze in Kombination ausführen.
3. **P0 Admin-WebSocket:** Echte öffentliche WebSocket-Integrationstests der bestehenden `weather_router/opera_status`-Implementierung einschließlich Admin/Nichtadmin, Runtime missing/reload, absichtlicher Datenschutzproben. Status-UI-Tests für `6 · OPERA` mit tatsächlichen Backendwerten; keine erfundenen Messwerte. Weiteres echtes Diagnosefeld `persistent_bytes` bleibt zu prüfen.
4. **P1 Originaldaten:** RATE, DBZH, ACRR getrennt wissenschaftlich anhand zulässiger öffentlicher ODIM-Originale einschließlich Geometrie, Orientierungs-Pixelpositionen, Qualitäts-, NoData- und Zeitinformationen auswerten. Keine vertraulichen Dateien oder private Quelltexte veröffentlichen. Ohne Beleg Wissenschaftssperre strikt erhalten.
5. **P1 Consumer V2:** Passive OPERA-Gen-Referenzierung durch echte öffentliche Consumer-V2-Verträge vorbereiten, aber bis zur Originaldatenfreigabe fail-closed.
6. **P1 Regression:** Die **öffentliche** Haupt- und Fokus-CI unter Python 3.12/3.13 erneut für den neuen Codecommit nachweisen; SHA, Run-IDs, Testanzahlen, Fehler und Korrekturen dokumentieren. Keine HA DEV VM109-Installation ohne separate kontrollierte Abnahme; PROD VM101 und Gewitterradar unverändert.
7. **Sicherheitsregel (ausnahmslos):** GitHub Actions **ausschließlich** in dem vorher nachweislich öffentlichen Repository `TheDaimos/weather-router-dev-pub` nach Sichtbarkeits-/Lizenz-/Datenschutzprüfung **ERLAUBT**. GitHub Actions in **sämtlichen privaten Repositories ABSOLUT VERBOTEN**, einschließlich Push/PR/Dispatch/Workflow-Calls/indirekter/automatischer/manueller Trigger und Reruns. Private Repositories ausschließlich lesend für Bestandsprüfungen, keine privaten Commits und keinerlei unkontrollierte Übernahme privater Inhalte.
8. **Exporte:** Diagnosen/Realtestdaten ausschließlich in `TheDaimos/Project-Log-And-Export@main`, keine weitere Linux-Testinfrastruktur, keine scientific- oder produktive Radarfreigabe ohne Originaldatenbeleg.

**Gesamtstatus: CODE/CI-GEPRÜFTE TEILIMPLEMENTIERUNG / SCIENTIFIC UNVERIFIED-BLOCKED / HA DEV NICHT REAL ABGENOMMEN.**
