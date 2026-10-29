# WR-OPERA-PUBLIC-DEV-01 – HTTP-Leserleases und öffentliche CI

**Datum:** 29.10.2026  
**Repository:** `TheDaimos/weather-router-dev-pub` (**PUBLIC**)  
**Entwicklungszweig:** `feature/p7-010-global-concurrency-2026-10-16`  
**Ausgangs-HEAD:** `a7a8c0aa2e37e55e0bd65a0664eb527b57ec9cbe`  
**Geprüfter Implementierungscommit:** `1fc2aeddfcb14794e992c7a75a516433999c9ad5`

## Verbindliche Repository-Grenze
Verbindliche Bestandsregel `docs/WR_PUBLIC_DEV_REPOSITORY_BOUNDARY_2026-10-29.md` gelesen. **Ausschließlich PUBLIC-DEV** wurde geändert. Kein Zugriff für Schreibaktionen auf das alte private Repository, kein privater Workflow gestartet, keine Migration von privatem Quellcode oder privater Konfiguration.

## Vorhandene CI (P01)
Workflow `.github/workflows/opera-frame-cache-regression.yml` war bereits am Ausgangsstand erfolgreich: Run **40902279670 – success**. Die allgemeine Public-DEV-CI am Ausgangsstand meldete dagegen bei Run **40902289700 – failure**, Python-Testschritt in beiden Matrixjobs. Diese Ergebnisse sind getrennte Prüfungen.

## Tatsächlich implementiert (P02)
`custom_components/weather_router/opera_tile_http.py`:
- Neue optionale Abhängigkeit `frame_cache`. Ohne vorhandenen Frame-Cache wird vor einem Renderauftrag **503/fail closed** zurückgegeben.
- Die öffentlich bereits implementierte `ImmutableFrameCache.lease()` wird nach erfolgreicher Berechtigungs-/Altersprüfung und vor Executor-Start erworben.
- Renderer nutzt ausschließlich den **gepinnten** Frame-Pfad, Digest und Frame-Nachweis.
- Bei Fehlern während Lease-Erwerb und Start des Executors werden Lease und Slot aufgeräumt.
- Eine `done_callback` am tatsächlich laufenden Executor-Task gibt die Lease nach dessen Abschluss frei. Timeout-/Cancellation der HTTP-Anfrage führt nicht zu einer verfrühten Freigabe. Gleichzeitig wird der begrenzte Render-Semaphor-Slot beim Worker-Ende freigegeben.
- Bestehende Sicherheitsgates für User, Provider, Produkt, Qualität, Orientierung und Altersprüfung wurden nicht absichtlich abgeschwächt.
- **Noch nötig:** Konkrete produktive Registrierung des HTTP-Views mit dem tatsächlich zuständigen Cache-Objekt sowie echte asynchrone HTTP- und Home-Assistant-Laufzeittests. Bis dahin nicht als end-to-end freigegeben betrachten.

## Tests (P04/P05)
`tests/test_opera_http_lease_contract.py` umfasst **5 Quellcode/AST-Prüfungen des tatsächlichen öffentlichen HTTP-Moduls** (Reihenfolge, Callback-Lease-Aufgabe, Timeout-Verhalten, Fail-Closed ohne Cache, angepinnter Frame). Das ist kein synthetisches Alternativmodell, aber auch kein vollständiger HA-HTTP-Integrationstest.

Öffentlichen Workflow so erweitert, dass nach Änderungen an HTTP/Tests zusätzlich `py_compile`, bestehende 6 Cache-Unit-Tests und die 5 HTTP-Vertragsprüfungen unter Python 3.12 und 3.13 laufen.

**Echte öffentliche GitHub-Actions-Ausführung:**
- Repository: `TheDaimos/weather-router-dev-pub`, Sichtbarkeit PUBLIC bestätigt.
- Run-ID: **40904908929**, Head: `1fc2aeddfcb14794e992c7a75a516433999c9ad5`
- Workflow: OPERA Public Frame Cache Regression, **completed/success**.
- Python 3.12, Job **123556896954**: 6/6 Cache-Tests + 5/5 HTTP-Vertragsprüfungen = **11/11 PASS**.
- Python 3.13, Job **123556896632**: 6/6 Cache-Tests + 5/5 HTTP-Vertragsprüfungen = **11/11 PASS**.
- Gesamt **22 erfolgreiche Testausführungen, keine Fehlschläge**, `py_compile` erfolgreich.
- GitHub-Run: https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40904908929

## Geänderte Dateien / Commits
- `opera_tile_http.py` – `bd2cead03aedc2342f2521750da72be93ea6e5e1`.
- `tests/test_opera_http_lease_contract.py` – `1d8ea1e649f130870ba3e800d840c9b30d77d9df`.
- `.github/workflows/opera-frame-cache-regression.yml` – `1fc2aeddfcb14794e992c7a75a516433999c9ad5`.

## Ungeprüft / offen
1. Realer `OperaTileView`-HTTP-Handler mit einer produktiven Registrierung des **gleichen** Caches, Authentifizierung, echten Rendering-Workern und Request-Cancellation/Timeout.
2. Atomare Publisher-/Registry-Generationswechsel einschließlich zweier paralleler Reader und Cache-Eviction unter Last.
3. Persistenz aktiver Radarzyklen, Hash/Crash-Recovery, Neustart.
4. UTC-Altersvertrag durch S3, Ring, Registry, V2, HTTP und UI.
5. Produktspezifische DBZH- und ACRR-Verarbeitung und vollständige Consumer-V2-End-to-End-Anbindung.
6. Vollständige OPERA-Adminanzeige; echte Home Assistant DEV VM109-Abnahme.
7. Allgemeiner öffentlicher Python-Testfehler aus Run 40902289700 getrennt analysieren und korrigieren.

## WR-OPERA-PUBLIC-DEV-02 – sofort ausführbarer Entwicklungsauftrag
**Nur** `TheDaimos/weather-router-dev-pub@feature/p7-010-global-concurrency-2026-10-16`.
1. Das öffentliche HTTP-View an die tatsächliche servereigene Cache-/Registry-Instanz anschließen, sodass das neue `frame_cache`-Argument im laufenden Prozess übergeben wird; bei fehlendem Cache weiterhin fail closed.
2. Echte asynchrone HTTP-Tests des öffentlichen Views mit Executor-Task, blockiertem Worker, Eviction, zwei parallelen Lesern, Timeout und Client-Cancellation bauen und auf Ubuntu/Python 3.12/3.13 über **öffentliche** GitHub Actions ausführen.
3. Erlaubte, wissenschaftlich blockierte Radarzyklen strikt zweiphasig vorbereiten, atomar registrieren und mit monotonic timestamp und getrennten Produktgenerationen absichern. Aktive Dateien mit Leserleases schützen.
4. Crash-Recovery, UTC-Messzeit-Altersvertrag, getrennte DBZH/ACRR-Pipelines und Consumer-V2-Verträge weiter integrieren.
5. Fehlgeschlagene öffentliche Haupt-CI am aktuellen HEAD untersuchen, Fehler im öffentlichen Code beheben, vollständige öffentliche CI und zielgerichtete OPERA-CI laufen lassen.
6. Bericht und exakte Run-IDs/Commits verifizieren, wissenschaftlichen Status UNVERIFIED/BLOCKED belassen, VM109 nicht ungeprüft installieren.
7. **GitHub Actions im öffentlichen Repository ausdrücklich ERLAUBT** (nach Sichtbarkeits-, Datenschutz- und Lizenzkontrolle). **GitHub Actions in sämtlichen privaten Repositories ABSOLUT VERBOTEN**, einschließlich Push, PR, Dispatch, indirekt und automatisch. Das alte private Repository nur für lesende Bestands-/Gesamtprüfungen; dort keine Commits, keine Synchronisierung privater Daten.
8. Keine PROD-Änderungen. Exporte ausschließlich nach `TheDaimos/Project-Log-And-Export@main`.

**Gesamtfreigabe: NICHT ABGENOMMEN.**
