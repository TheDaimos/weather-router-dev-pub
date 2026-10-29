# WR-OPERA-PUBLIC-DEV-05 – Crash-Recovery, UTC und OPERA-Adminstatus

**Datum:** 2026-10-29  
**Repository:** `TheDaimos/weather-router-dev-pub` (**PUBLIC**, vor Änderungen geprüft)  
**Branch:** `feature/p7-010-global-concurrency-2026-10-16`  
**Ausgangs-HEAD:** `167d0d97a8f4fbc1902885c5922ef18f80c62cf1`  
**Geprüfter Codecommit:** `e9424a08e62aa9cba8ee91549e184de872ac73e3`  
**Gesamtstatus:** öffentliche CI SUCCESS; wissenschaftliche OPERA-Freigabe UNVERIFIED/BLOCKED, HA DEV nicht abgenommen.

## 1. Tatsächliche Umsetzung

### OPERA-Administrations-WebSocket / Frontend

- `custom_components/weather_router/websocket_api.py`: Neuer `@websocket_api.require_admin`-geschützter WebSocket-Befehl `weather_router/opera_status`; wird durch das vorhandene `async_register()` registriert. Bei fehlender Runtime werden ausdrücklich deaktivierte und nicht freigegebene Zustände ausgegeben. Bei vorhandener Runtime verwendet er die **tatsächliche** `runtime.status()`-Diagnose und ergänzt `scientific_status="UNVERIFIED/BLOCKED"`. Keine lokalen Dateipfade/Token.
- `custom_components/weather_router/frontend/weather-router-lab.js`: Neuer aufklappbarer Lab-Bereich **`6 · OPERA`** mit manuell ausgelöstem Admin-WebSocket-Abruf; tatsächliche Provider-/Produktzustände, Generationen, UTC-Messzeit, Datenalter, Status, Cache-Framezahl/-Bytes, Reader-Leases, letzte Promotion/Fehler. HTTP und Consumer V2 bleiben als gesperrt markiert. Frontend-Newline-Darstellung nach GitHub-Readback korrigiert.
- **Noch nicht umgesetzt:** persistente Speicherbelegung im WebSocket-Ergebnis, echter Admin-WebSocket-End-to-End-Test unter Home Assistant, tatsächliche VM109-Frontendabnahme. Die bestehenden WebSocket-Decorators erlauben nur Adminzugriff, ein Live-HA-Test fehlt.

### Persistenz und Crash-Recovery

- `custom_components/weather_router/opera_cycle_store.py`: Die persistente Journalprüfung verhindert nun die **Zurückschreibung einer älteren Generation nach Runtime-Neustart**, selbst wenn die neue In-Memory-Registry leer ist; identische Generation mit anderem SHA-256 wird ebenfalls abgewiesen.
- `tests/test_opera_cycle_journal.py`: Neuer tatsächlicher Neustart-Laufzeittest `test_restart_cannot_replace_newer_persisted_cycle`; er führt `OperaRuntime.prepare()` und `promote()` aus und prüft das unveränderte persistierte Manifest sowie fehlende unerlaubte Registry-Aktivierung.
- Weiterhin vorhanden: atomare Bytes-`fsync`-`os.replace`-Journaldaten, hashgeprüfte reine Metadaten-Recovery; keine automatische wissenschaftliche Zulassung.
- **Offen:** dedizierte Prozessabsturz-Injektionsprüfungen an jedem `fsync`-/`os.replace`-Zwischenpunkt, parallele externe Schreibprozesse/Dateisperre, begrenzte Dateibereinigung und persistente Speicherkontingentierung. Diese Punkte wurden nicht als erledigt ausgegeben.

### UTC, HTTP und Consumer V2

- Die in P04 bestehende `utc_status()`-Klassifikation wird weiterhin durch die Runtime und die Statusanzeige genutzt. Nach Neustart wird aus dem UTC-**Messzeitpunkt** und nicht aus dem Downloadzeitpunkt gerechnet.
- Bestehende HTTP-Preflight-/Final-Authorization bleibt **strenger bei 900 Sekunden** und wurde bewusst nicht gelockert.
- **Offen:** einheitlicher konfigurierbarer 1500-s-Vertrag für HTTP und Consumer V2, echter asynchroner HTTP-Test mit Altersgrenzüberschreitung während Rendering, Registry/HTTP-Gesamtintegration. Die echte OPERA-HTTP-Route bleibt unregistriert/fail-closed.

### RATE / DBZH / ACRR

- Weiterhin getrennte Produktverträge, RATE und DBZH als noch nicht wissenschaftlich freigegebene Entwicklungszweige, ACRR weiterhin BLOCKED wegen fehlender eigener vollständiger Raster-/Originaldatenprüfung.
- Keine ungeprüfte Produktkonvertierung, keine Reaktivierung der unvollständigen Consumer-Discovery-Verträge.

## 2. Public CI – tatsächlich ausgeführt

**Sichtbarkeit vor Änderungen und Ausführung bestätigt:** `TheDaimos/weather-router-dev-pub` ist PUBLIC. **Keine GitHub Actions aus irgendeinem privaten Repository** angefordert oder gestartet.

**Exakter Codecommit:** `e9424a08e62aa9cba8ee91549e184de872ac73e3`.

**OPERA-Fokus-CI** https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40931585971 – **completed / success**
- Python 3.12, Job `123651108320`: Cache 6/6, HTTP-Lease-Quellcodevertrag 5/5, echte Runtime-Tests 10/10, echte Journal-Tests 10/10, insgesamt **31/31 PASS**.
- Python 3.13, Job `123651108745`: identische **31/31 PASS**.
- Gesamt: **62/62 Testausführungen** (enthält fünf statische HTTP-Vertragsprüfungen je Python-Version).

**Öffentliche Haupt-CI** https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40931585996 – **completed / success**
- Python 3.12, Job `123651108373`: **1599/1599 Haupttests**, 106/106 Vorprüfungen, 2/2 Pixeltests, Struktur- und Paketprüfung erfolgreich.
- Python 3.13, Job `123651108492`: identische **1599/1599 Haupttests**, 106/106 Vorprüfungen, 2/2 Pixeltests, Struktur- und Paketprüfung erfolgreich.
- Gesamt: **3198 bestandene Haupt-Testausführungen** (die Vorprüfungen/OPERA-Fokustests nicht als neue einzigartige Tests hinzuaddieren).

**Exitcodes:** alle genannten GitHub-Jobs/Workflow-Schritte `success` (keine fehlgeschlagenen Jobs).

## 3. Commits und Readback

- `76fc9ca01504f6445f1f92ee4b63dcc02991d806`: Admin-WebSocket.
- `fbdb768bb40f60b9a593d7ee5cea2f87e7ccb5fc`: Frontend `6 · OPERA`.
- `643549f8bf1d5939ad5a77a8b5daa004d3c431b2`: Zeilenformatierung korrigiert.
- `35300a72723e3b859d40bab3ce73d1116253109d`: Journal-Rollback-Schutz.
- `e9424a08e62aa9cba8ee91549e184de872ac73e3`: echter Restart-Rollback-Test und CI-bestätigter Codecommit.

Wesentliche Codeänderungen wurden nach Erstellung über GitHub `fetch_file` zurückgelesen. CI-Freigabe gilt nur für den genannten Codecommit, nicht automatisch für einen folgenden Dokumentationscommit.

## 4. WR-OPERA-PUBLIC-DEV-06 – priorisierter Folgeauftrag

**Repository:** Ausschließlich `TheDaimos/weather-router-dev-pub` (**PUBLIC**), Branch `feature/p7-010-global-concurrency-2026-10-16`. Zuerst diesen Bericht, tatsächlichen HEAD und CI-Runs prüfen.

**P0 – Crash-Konsistenz:** `CycleJournal` mit strikter serialisierter Manifest-/Datei-Transaktion bei parallelen Writerprozessen, Quota, sicherer und readerfester Bereinigung verwaister Journaldateien ausstatten. In Tests Crash nach unvollständigem Framewrite, Frame-fsync, Manifest-fsync, Manifest-replace sowie Journal-Commit vor Registry-Pointer-Swap durch tatsächliche Fault-Injection simulieren. Nur hashgeprüfte aktuelle UTC-Metadaten recovern, niemals implizit wissenschaftlich freigeben.

**P0 – OPERA-Admin:** `weather_router/opera_status` mit echten HA-WebSocket-Admin-/Nichtadmin-Tests verifizieren; `6 · OPERA` inklusive persistenter Bytebelegung, Journal-/Ringstatus, aktuellen Messzeiten und konkreten Fehlersignalen erweitern. Keine Platzhalter als reale Werte. Keine Secrets/Pfade in Diagnosen.

**P0 – UTC/HTTP:** Eine gemeinsame Alters-Policy in Runtime, Registry, HTTP vor **jeder tatsächlichen Antwort** und Consumer API V2 schließen. Die bisher strengere HTTP-900-s-Grenze erst nach vollständigen Vertrags-/Laufzeitprüfungen kontrolliert ändern. Einen echten `OperaTileView.get()`-Test mit einem während des Renderns ablaufenden UTC-Zyklus sowie Parallel-Reader, Client-Cancel, Eviction und Pointer-Swap ausführen.

**P1 – OPERA-Fachdaten:** RATE, DBZH und ACRR als separat wissenschaftlich validierte Produktpfade auf öffentlichen zulässig verbreiteten ODIM-Originaldaten weiterentwickeln. Keine DBZH->RATE- oder ACRR->RATE-Implizitumrechnung, Provider-/Consumer-Discovery erst nach Vollvertrag.

**P1 – CI/Realabnahme:** Nach echtem Codefortschritt vollständige öffentliche CI Python 3.12 und 3.13 sowie OPERA- und WebSocket-/Frontendtests ausführen; SHA, Run-IDs, fehlgeschlagene und korrigierte Tests dokumentieren. HA DEV VM 109 nur kontrolliert und ausdrücklich, PROD VM 101 niemals verändern.

**ABSOLUTE GITHUB ACTIONS SICHERHEIT:** GitHub Actions **ausschließlich im nachweislich PUBLIC Repository `TheDaimos/weather-router-dev-pub` erlaubt**, nach Sichtbarkeits-, Lizenz- und Datenschutzprüfung. In `TheDaimos/weather-router-dev` und **allen anderen privaten Repositories absolut VERBOTEN** – Push, PR, Workflow-Dispatch, Workflow-Call, automatische, indirekte, manuelle Ausführung sowie Reruns. Private Repositories ausschließlich lesend, keine privaten Commits und keine Migration privater Inhalte.

**Exportziel:** Diagnosen und Realtestexporte ausschließlich `TheDaimos/Project-Log-And-Export@main`. Keine Änderungen in Gewitterradar/PROD und keine ungenehmigte HA DEV Installation. Keine wissenschaftliche Freigabe ohne Originaldatenbeleg.

**Status: CI-GEPRÜFTE TEILIMPLEMENTIERUNG / OPERA UNVERIFIED-BLOCKED / HA DEV NICHT REAL ABGENOMMEN.**
