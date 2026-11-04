# WR TEST70-74 – Öffentliche OPERA-S3-Quellensuche mit WR-Gültigkeit

Datum: 2026-11-04 · Entwicklung ausschließlich `TheDaimos/weather-router-dev-pub@feature/p7-010-global-concurrency-2026-10-16`.

## Bestätigte Basis
Öffentliche CI auf `498d36a75bb3b40bee646c221cea9f205b64b8c5`: `41913677690` und `41913666975` Python SUCCESS, `41913667133` API-Monitor SUCCESS.

## Implementiert
- `4f9b084c4970426457e18d27b693cfb81f2e830d`: `opera_source_monitor.parse_catalog` entfernt die feste 900-Sekunden-Ausschlussgrenze. Die Quelle erhält stattdessen eine explizite serverseitige `max_age_seconds`-Angabe und lehnt fehlende/ungültige Werte ab.
- `54a0944296a70d1df32f574341078594cbda905f`: Regression für 20 Minuten alten, mit WR=1500 Sekunden zulässigen OPERA-RATE-S3-Schlüssel; WR=900 verwirft denselben Schlüssel; fehlende Servergültigkeit wird abgewiesen.
- `323649f1f42291d142edcd6a2cef338d5637e4ab`: Live-Source-Monitor liest die Option `opera_preview_validity_seconds` aus dem HA-WR-Config-Entry; die Prüfung wird bei jedem Discovery-Abruf neu ausgeführt. Bei fehlendem Config-Entry fail-closed.

## Öffentliche Prüfungen auf letztem Source-Commit
`41914261792` OPERA Frame Cache SUCCESS; `41914261589` API Monitor SUCCESS. Python Public DEV `41914261819`, `41914266704` zum Erstellungszeitpunkt noch in_progress. Frühere Zwischen-Commits haben erwartungsgemäß fehlende Testparameter aufgedeckt, maßgeblich ist nur der aktuelle Source-Commit.

## Keine Installationsfreigabe
Die OPERA-Monitor-Implementierung kennzeichnet Downloads weiterhin ausdrücklich `downloaded_unverified_raster`; weder Providerregistrierung noch abgesicherter authentifizierter HTTP-Transport und validierter Frame-Promotion-Pfad sind end-to-end aktiv. GR/WR-HA-DEV-Abnahme nicht erfolgt. PROD VM101 nicht verändern; TEST69 nicht wiederholen.

**Keine privaten GitHub Actions – ausschließlich öffentliche Actions im Public-Repo.** Diagnose-/Realtest-Exporte ausschließlich `TheDaimos/Project-Log-And-Export@main`.
