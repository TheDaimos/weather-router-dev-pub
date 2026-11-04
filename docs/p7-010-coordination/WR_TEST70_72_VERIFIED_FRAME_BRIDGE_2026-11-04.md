# WR TEST70-72 – Verifizierte OPERA-Frame-Übergabe im Public-Repo

Datum: 04.11.2026. Entwicklungszweig: `TheDaimos/weather-router-dev-pub@feature/p7-010-global-concurrency-2026-10-16`.

## Öffentliche Ausgangsprüfungen
`41909112925`, `41909104523` (Python Public DEV) und `41909104634` (API-Monitor) sind SUCCESS auf dem vorherigen geprüften Stand.

## Umsetzung
- Commit `bc7c491becf752e3065c5e172a8c2e0a2b8b562c`: OPERA-Runtime-Test um den positiven Fall erweitert: verifizierter, promoteter RATE-Frame unter WR-Gültigkeit 1650 Sekunden, Ablehnung nach 1651 Sekunden, Ablehnung nach Deaktivierung und vor der Promotion.
- Commit `bf6f81cb830ed3ebdf3053337133fe89aa91a285`: `OperaRuntime.consumer_registration(product, now, max_age_seconds)` liefert die interne unveränderliche Frame-Registrierung ausschließlich nach `consumer_ready` und erneutem aktiven Generationenvergleich. Keine öffentliche URL, kein eigenständiges HTTP-Recht.
- Commit `9e7bce839d07c3031eb56226d6561e2d209f4303`: Regression prüft den Rückgabewert und dessen Widerruf nach Ablauf.

## Verifizierte Zwischenergebnisse
Auf Commit `bc7c491...`: `41911131728` und `41911122737` Python Public DEV SUCCESS; `41911122909` OPERA Frame Cache SUCCESS; `41911122773` API-Monitor SUCCESS.

## Freigabestatus
Neue CI auf `9e7bce839...`: `41911205886` (Python), `41911205811` (OPERA Frame Cache), `41911205869` (API-Monitor) zum Erstellungszeitpunkt noch nicht bestätigt.

**Noch nicht freigegeben:** Öffentliche OPERA-Source-Monitor-Raster sind weiterhin unverified; keine ausgebildete produktive Verifier-Palette-/Scientific-Promotion-Brücke, keine vollständig autorisierte Provider-Capability und kein registrierter authentifizierter Tile-Endpunkt. Der neue interne Getter ist ausdrücklich **kein** Umgehen dieser Sperren. HA DEV VM109 noch nicht real abgenommen; PROD VM101 unverändert. TEST69 nicht wiederholen.

**Private GitHub Actions verboten; nur öffentliche Actions.** Diagnose-/Realtest-Exporte ausschließlich `TheDaimos/Project-Log-And-Export@main`.
