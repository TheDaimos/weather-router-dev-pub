# WR TEST70-69 – Public-Only OPERA Runtime: serverseitige Gültigkeit und echte Release-Sperren

Datum: 04.11.2026 · Entwicklung **nur** `TheDaimos/weather-router-dev-pub@feature/p7-010-global-concurrency-2026-10-16`. Keine privaten Actions, keine privaten Commits.

## Umgesetzt und tatsächlich committet
- `6bbf2c1d86b23a54bc0c8655b5606baeda03cac7`: `raster_mosaic_service.resolve_mosaic_snapshot` verwendet nur `server_max_data_age_seconds` als autoritativen Wert, überschreibt die Client-Angabe und scheitert bei fehlender Serverkonfiguration kontrolliert.
- `21c6a85acc4b2a2a5d56ee0ff7eac8c36a223bc1`: Public Consumer V2 Handler übergibt die serverseitige Gültigkeit, statt beim fehlenden Client-Wert einen KeyError auszulösen.
- `1ad397d7ea93c58ac5548a033c8aab24b434a3f5`, `b8af151ef51eb5226803b393a4e0ae67483bf0f8`, `04ccd9b15dc981b765d74272c62bd1952e1a79ed`: HA OptionsFlow für `opera_preview_validity_seconds` (Standard 1500, konfigurierbar 1–3600), zentral deklarierte Option und Nutzung im V2 Handler.
- `5440f0c5fa5623da45ceebbcbad1d30ed68aa037` / `25c6c743183488e4407378dcb2da2326c5832ef2` / `cb7a9443a7011a744e0666d3c45ed676056eb2ae`: isolierte Public-Tests und Handler-Harness an den echten WR-Konfigurationsvertrag angepasst.
- `d7282e2ba149bd44bced798fa16cf6edb0eeb178`: separate Python-Regression für Client-Alter=2 vs WR=1650, fehlendes Client-Alter vs WR=1500 und Fail-Closed ohne WR-Konfiguration.

## Belegte CI
Öffentliche Public DEV Python-CI `41893255475`, `41893268418`, `41893529124`, `41893540612` = SUCCESS. Öffentlicher API-Monitor `41893529245` = SUCCESS. Die neue Regression auf Commit `d7282e2...` läuft in `41893697387`, bei Berichterstellung noch nicht abgeschlossen. Frühe Commits der Anpassungsserie waren rot; ausschließlich der jeweils letzte vollständige CI-Stand zählt.

## Release-Gap: OPERA ist kein vollständiger Consumer-Provider im aktuellen Public-Stand
Quellenprüfung auf dem öffentlichen Branch:
- `custom_components/weather_router/providers/registry.json`: kein OPERA-Eintrag.
- `custom_components/weather_router/consumer_capability_map.json`: keine OPERA-Consumer-Capability.
- `custom_components/weather_router/consumer_raster_mosaic_api.py` arbeitet mit `_candidates` aus dem Consumer-Katalog; damit ist eine vollständige OPERA-Auswahl auf diesem öffentlichen Stand nicht nachgewiesen.
- `opera_runtime.py`, `opera_tile_http.py`, `opera_source_monitor.py` existieren öffentlich, aber das beweist allein keine durchgängige Bereitstellung.
- Verbindlich bleiben Provider-Registrierung, Ringpuffer-Cycle-Bridge, token-geschützter Tile-Transport, WR-gesteuertes `times.valid_until`, Seamless Tile Handover, verifizierte Assets und gemeinsame GR/WR DEV-Realtests.

## Updateentscheidung
**Noch keine HA DEV-/PROD-Installationsfreigabe.** Die nachgewiesenen Python-Tests betreffen Teilverträge. Weder die vollständige OPERA-Consumer-Runtime noch die neuen HA-OptionsFlow-Realtests sind dadurch abgenommen. Kein PROD VM101-Eingriff. Kein TEST69-Retest.

**Private GitHub Actions ausdrücklich verboten.** CI nur in Public-Repository. Alle Diagnose-/Realtest-Exporte ausschließlich `TheDaimos/Project-Log-And-Export@main`.
