# TEST70-76 – Versionsidentitäten und repositoryweite 900-Sekunden-Prüfung

Datum: 04.11.2026. WR public branch `feature/p7-010-global-concurrency-2026-10-16`; GR public branch `deploy/dev`. Keine privaten GitHub Actions.

## Versionierung
- Gewitterradar: `manifest.json.version=0.25.44`; Frontend-Versionen `4.11.135`, `integrationVersion=0.25.44`, DRA `dra-deployment-provenance.json.productVersion=4.11.135`, unverändert und übereinstimmend.
- WeatherRouter Public: vor Korrektur `DEV_BUILD_VERSION=0.10.164`, aber `manifest.json.version=0.10.0` und `INTEGRATION_VERSION=0.10.0`. Beides auf `0.10.164` korrigiert (Commits `657b06090a61597f378c1a054289cf6c65fa7269`, `e7108df23aa1b96fd4a3fe94a61284f5aeaa3186`). Loader weiterhin `0.10-loader-167`.
- Das Export2Git auf HA DEV meldete `0.10.285`. Diese laufende Installation ist NICHT mit Public-Codeversion `0.10.164` gleichzusetzen. Kein Upgrade/Release ohne eindeutigen Build- und Loader-Nachweis.

## Technische Korrekturen im öffentlichen WR
- `opera_runtime.utc_status`: die bisherige 900-s-Untergrenze für konfigurierbare Gültigkeit und Veraltet-Ab entfällt.
- `opera_cog_tiles.authorize_current`: keine 900-s-Hardcap; explizite serverseitige `max_age_seconds` erforderlich.
- `opera_tile_security.frame_id/tile_cache_key`: keine `MAX_FRAME_AGE=900`; explizite WR-Gültigkeit und UTC-Konsistenz erforderlich.
- `opera_cog_fetch.object_url/fetch` und `opera_source_monitor`: serverseitige Gültigkeit wird vor und nach Netzwerkkontakt weitergereicht; keine heimliche Rückkehr zum 900-s-Default.
- In den Regressionstests 1650-s-Ablauf korrekt nach Download und Rendering simulieren (zuletzt `5c7a9c001b835691ffe1b8cde46bf51965072d24`).

## CI-Audit
- GR repositoryweiter Audit `41921527402`: SUCCESS; technische Zeitgrenzen werden von CSS font-weight, 900px oder ms-UI-Timern getrennt.
- WR sourceweiter Audit `41921498018`: SUCCESS, neueste Prüfserie `41921637747` bei Berichterstellung offen.
- WR Python-CI war vor letztem Fix rot: der CoG-Postdownloadtest erwartete noch 901 s statt WR 1650 s. Neue Public Python-CI `41921637894` und `41921647346` gestartet; Ergebnis nicht vorwegnehmen.
- GR Integrations-, Frontend- und Settings-CI des neuen Audit-Commits laufen separat.

## Offene Freigabebedingungen
Grüne Vertrags-/Audit-CI ist nicht gleich HA DEV OPERA-End-to-End. OPERA-Frame-Promotion, aktiv autorisierte Provider- und Tile-Auslieferung, `valid_until`, installierte Artefaktparität und real sichtbarer Niederschlag weiterhin nicht nachgewiesen. Keine Wiederholung von TEST69. PROD VM101 nicht ändern.

**Keine privaten GitHub Actions** – ausschließlich öffentliche Repositories. Exporte ausschließlich `TheDaimos/Project-Log-And-Export@main`.
