# WR-OPERA-PUBLIC-DEV-04 – Persistenz, HA-Lebenszyklus und UTC-Sperrlogik

**Datum:** 29.10.2026
**Repository:** `TheDaimos/weather-router-dev-pub` – bestätigte Sichtbarkeit **PUBLIC**
**Branch:** `feature/p7-010-global-concurrency-2026-10-16`
**Ausgangs-HEAD:** `32324a3021fee4a4bd39f8b841846912a73ad3d4`
**Letzter erfolgreich geprüfter Codecommit:** `6b3df3f7ab1e8d6a163422b65769ffbf41d78e77`
**Freigabe:** ÖFFENTLICHE CI ERFOLGREICH / HA DEV NICHT ABGENOMMEN / WISSENSCHAFTLICH UNVERIFIED-BLOCKED

## 1. Tatsächlich implementierte Quellcodeänderungen

### P04-01 – Config-Entry-Lebenszyklus / Cache
- `custom_components/weather_router/__init__.py`: Serverseigene `OperaRuntime` wird bei `async_setup_entry()` erzeugt, nicht mehr beim globalen `async_setup()`. Wiederholter Setup-Aufruf erzeugt keine weitere Cache-Instanz. `async_unload_entry()` entfernt und schließt die Runtime nach erfolgreichem Platform-Unload. Re-Setup erzeugt eine neue Runtime. Erstmalige Konstruktion wird über `hass.async_add_executor_job` ausgeführt, um Dateisystemarbeit aus dem HA-Eventloop fernzuhalten.
- Persistenter lokaler Speicherpfad: `hass.config.path(".storage", "weather_router_opera_cycles")`. Keine Ablage privater Messdaten in GitHub.
- `opera_frame_cache.py`: `close(defer=True)` verweigert neue Cache-Lookups/-Admissions, hält laufende Leserleases bis zum tatsächlichen Worker-Ende und entfernt den Cache-Ordner erst bei Freigabe der letzten Lease. Ursprüngliches `close()` ohne Defer kann bei aktiven Lesern weiterhin mit `active_readers` abbrechen.
- `opera_runtime.py`: `close()` setzt Dienste auf False, revokiert die Registry und verwendet den defer-basierten Cache-Abbau.

### P04-02 – Atomarer persistenter Zyklus-Journal
- Neu `opera_cycle_store.py`: `CycleJournal` mit atomar umbenannten Dateikopien und `active.json`-Manifest; Dateidaten und Manifest werden vor Veröffentlichung `fsync`-gesichert. Manifestfelder: Produkt, UTC-Messzeit, Generation, SHA-256, Dateigröße, relativer Dateiname, Attribution, Integrity-/Publication-Status. Begrenzung Quellframe auf 12 MiB, hexadezimale Digest-Prüfung, keine absoluten Pfade im Manifest, Hash-Neuberechnung bei Inspektion.
- `OperaRuntime.promote()`: Prüfung gegen ältere und gleichzeitige widersprüchliche Radarzyklen, Journal-Commit **vor** Veröffentlichung des neuen Registry-Pointers; Journalfehler verweigern die Promotion. Das bisherige gültige Registry-Objekt bleibt bei Validierungsfehler erhalten.
- `CycleJournal.inspect()` verweigert beschädigte Manifeste, fehlende/umgeschriebene Dateien und inkonsistente Identitäten. `recover_metadata()` liest nur Daten und meldet UTC-Status: `authorized=False`, **keine** automatische Runtime-/HTTP-/Consumer-Freischaltung nach Neustart.
- Einschränkungen: Journal ist noch **kein vollständiges Crash-Recovery veröffentlichbarer Rastergenerationen**, da das Wiederherstellen bewusst *niemals* wissenschaftliche Palette-/Raster-/Qualitätsfreigaben rekonstruiert. Ein Stromausfall zwischen Journal- und Registry-Commit kann einen zwar validierten, aber **nicht freigegebenen** Journalstand hinterlassen; er wird beim Neustart nur als Metadaten sichtbar und nicht ausgeliefert. Alte Journaldateien/Stagingreste werden noch nicht langfristig volumenbegrenzt bereinigt.

### P04-03 – UTC und Diagnose
- Die bereits vorhandene `utc_status()` klassifiziert nach UTC-**Messzeit**, nicht Download-Zeit, zu CURRENT/STALE/UNAVAILABLE. Standard 1500 s, erlaubte 900–3600 s, historische Obergrenze 3600 s.
- `OperaRuntime.status()` neu: getrennte Dienstzustände RATE/DBZH/ACRR, aktuelle Generationen, Messzeit, Sekundenalter, UTC-Status, reale Cache-Frames/Bytes/Readerleases, letzte Promotion, letzter Fehler sowie `http_enabled=False`, `consumer_v2_approved=False`. Keine lokalen Dateipfade oder Geheimnisse.
- **Noch offen**: Diese Statuswerte sind noch nicht als echte Admin-WebSocket-Schnittstelle mit `6 · OPERA` verbunden. `OperaTileView` nutzt derzeit weiterhin den bisherigen strengeren 900-s-Preflight; es erfolgt keine automatische Freigabe und die 1500-s-Policy ist noch **nicht** durchgehend über V2/HTTP/UI integriert. Dies darf nicht als abgeschlossen gelten.

### P04-04 / P04-06
- Separate Produktidentität RATE vs. DBZH durch Registry/Journal erhalten. ACRR ist mangels wissenschaftlich verifizierter eigener Pipeline weiterhin explizit BLOCKED.
- Bestehende echte asynchrone HTTP-Lease-Tests weiter vorhanden; neuer verhaltensorientierter Test `test_close_during_lease_preserves_file_until_release` prüft das Unload-/Readerlease-Verhalten der echten Runtime und des Caches.
- Weiter offen: vollständige echte HTTP-Gleichzeitigkeit mit Registry-Swap, über Rendering ablaufender Messzeit, Wiederanlauf unter aktiven Workern und S3-/Originaldatenprüfung auf HA DEV 109.

## 2. Neue Verhaltenstests und Fehlersuche

- Neu `tests/test_opera_cycle_journal.py`: 9 Tests zur dauerhaften Promotion, reiner Metadaten-Recovery, unterbrochenem Staging, temporären Manifestresten, beschädigtem Manifest, fehlender Datei, verändertem Hash, veralteter/deaktivierter Quelle, Rollback und zwei getrennten Produktgenerationen.
- Erweiterung `tests/test_opera_runtime_atomic.py`: 10 Tests einschließlich Schließen bei aktiver Readerlease.
- OPERA-CI-Workflow auf Python 3.12 und 3.13 einschließlich neuer Journaltests erweitert.
- Erste öffentliche OPERA-CI `40918950988` scheiterte: 7 Recovery-Testfehler in beiden Matrixjobs, Ursache: `inspect()` verglich Dateinamen ohne `.bin`-Endung. Fehler konkret im Quellcode korrigiert, keine Tests entfernt.
- **Erfolgreiche Wiederholung:** OPERA-CI **Run 40919153933**, Codecommit `86d7d33a45cb998712ce584e56ba0cc5f6932e8d`, `completed/success`. Python 3.12 und 3.13 jeweils 6/6 Cache + 5/5 HTTP-Struktur-/Vertragsprüfungen + 10/10 echte Runtime-Tests + 9/9 echte Journal-Tests = **30/30 pro Version**, **60/60 Testausführungen**.
- **Öffentliche Haupt-CI:** Run **40919311386**, Head `6b3df3f7ab1e8d6a163422b65769ffbf41d78e77`, `completed/success`. Python 3.12, Job 123607913896: **1598/1598 Haupttests**, 106/106 Vorprüfungen, 2/2 Pixeltests, Struktur-/Paketschecks OK. Python 3.13, Job 123607914241: identisch. **3196/3196 Haupt-Testausführungen** über beide Python-Versionen.
- Links: https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40919153933 und https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/40919311386
- Die öffentliche Haupt-CI läuft nach Bericht-Commit eventuell erneut. Dieser Bericht darf den nachfolgenden Dokumentations-Commit nicht ungeprüft als erfolgreich deklarieren.

## 3. Commitkette des Codefortschritts

- `86d6c552ee0f670b2fe18c619262065744f2eb82`: persistenter, atomar geschriebener OPERA-CycleJournal.
- `7bdbdd200ddedf7b028bdee621aecc1e336ed999`, `7cb7bb798c613da984f3465e96422578a2f89f53`: Journal-Anbindung / Monotonie vor Manifestwechsel / Runtime-Diagnose.
- `3f21c69693d15b878c8252db919d178ffcd134da`: Crash-/Corruption-/Hash-Tests.
- `3fe500413080e08d19f98f34bb86af597eb44482`, `e79fc87a1fd0403ed8ddb5204e6ffadc5a8acdbb`: Deferred Cache-/Runtime-Close.
- `6ee8415d35ca89226d26e2511ac224552d14bbb0`, `3b63f801799f9e0028756d7c30f05de0bccf5e31`: reale Readerlease/Close-Tests.
- `ab801d21eb2f34a4e02e9686654c1dbc2d12c6d5`: öffentliche Fokus-CI erweitert.
- `7f9a0436503232f45e5a65f3d413c5ff26d5f986`: Config-Entry-Reload/Unload.
- `86d7d33a45cb998712ce584e56ba0cc5f6932e8d`: im OPERA-CI-Fehlerlauf gefundener Dateinamenfehler behoben.
- `6b3df3f7ab1e8d6a163422b65769ffbf41d78e77`: HA-Storage-Pfad angeschlossen, vollständig grüne Haupt-CI.

## 4. Grenzen der Freigabe

Kein echter OPERA-Raster-Originaldatennachweis für RATE, DBZH oder ACRR. Keine aktive OPERA-HTTP-Route oder Consumer-V2-Rasterfreigabe. Keine kontrollierte HA DEV VM109 Installation und keine PROD-Eingriffe. Kein privater GitHub-Workflow oder Commit. Gesamtstatus wissenschaftlich **UNVERIFIED/BLOCKED**.

## WR-OPERA-PUBLIC-DEV-05 – verbindlicher priorisierter Folgeauftrag

**Repository:** Nur `TheDaimos/weather-router-dev-pub` (**PUBLIC**), Branch `feature/p7-010-global-concurrency-2026-10-16`. Zuerst diesen Bericht, aktuellen HEAD und beide CI-Runs lesen.

1. **P0:** Journal und HA-Lebenszyklus mit echten HA-Setup-/Unload-/Reload-Tests prüfen, einschließlich aktiver Executor-Worker und der Persistenzpfadbindung. Absturzfälle zwischen Datei-`fsync`, Manifest-`os.replace` und Registry-Pointer-Swap simulieren. Begrenzte sichere Entfernung verwaister Dateikopien/Stagingreste implementieren; Cache-/Manifest-Versions- und Integrity-Vertrag gegen Mehrfachzugriffe absichern.
2. **P0:** Verbindlichen UTC-Messzeitvertrag 1500 s (konfigurierbar 900–3600 s, absolute Obergrenze 3600 s) in `OperaRuntime`, der HTTP-View vor **jeder Antwort**, Consumer API V2 und Adminstatus vereinheitlichen. Einen tatsächlich ausgeführten asynchronen HTTP-Test für Überschreiten der Altersgrenze **während** des Renderns hinzufügen. Bisherige strengere HTTP-900-s-Sperre nicht ohne Vertrag und Test absichtlich lockern.
3. **P0:** Servereigenes OPERA-Admin-WebSocket-Statuskommando und Anzeige `6 · OPERA` mit tatsächlichen Runtimewerten einbinden (Dienststatus, Datenalter, Generationen, Ring-/Cache-Bytes und Reader, letzte Promotion/Fehler). Admin-Only, keine geheimen Pfade. Wissenschaftlich gesperrte HTTP-View nur deaktiviert/fail-closed anbinden.
4. **P1:** RATE-/DBZH-/ACRR-Originaldatenprüfung und getrennte wissenschaftliche Rasterverifikation implementieren; keine Konvertierung DBZH→RATE oder ACRR→RATE ohne nachgewiesene Fachprüfung. Provider-/Consumer-V2-End-to-End nur nach geprüften Contracts und bewusstem Opt-in weiter integrieren.
5. **P1:** Vollständige öffentliche Haupt- und Fokus-CI auf dem neuen Codecommit tatsächlich ausführen, Run-IDs, Python 3.12/3.13, Testzahlen und Exitcodes dokumentieren. HA DEV VM 109 nicht ohne Abnahme installieren; PROD VM 101 niemals verändern.
6. **ABSOLUTE SICHERHEIT:** GitHub Actions **nur** im zuvor überprüften öffentlichen Repository `TheDaimos/weather-router-dev-pub` erlaubt. In **allen privaten Repositories ausnahmslos VERBOTEN**: Push, Pull Requests, Workflow-Dispatch, Workflow-Call, automatische/indirekte/manuelle Trigger und Reruns. Private Repositories ausschließlich für nötige lesende Bestandsprüfungen; **keine privaten Commits, keine private Entwicklung, keine Übertragung vertraulicher Inhalte ins Public-Repo.**
7. **Exporte:** Diagnosen und Realtestexporte ausschließlich `TheDaimos/Project-Log-And-Export@main`. Keine neue Linux-Testumgebung, keine unkontrollierte DEV-Installation, keine wissenschaftliche Freigabe ohne Originaldatenbelege.

**Status:** FUNKTIONALE TEILIMPLEMENTIERUNG / ÖFFENTLICHE CI ERFOLGREICH / HA DEV NICHT REAL ABGENOMMEN / OPERA-WISSENSCHAFTLICH BLOCKED.
