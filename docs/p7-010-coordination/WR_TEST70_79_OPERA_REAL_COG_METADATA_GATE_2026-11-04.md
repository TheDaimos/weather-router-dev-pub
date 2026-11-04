# TEST70-79 – OPERA-CoG-Metadaten im echten Downloadpfad prüfen

**Datum:** 2026-11-04; **Repository:** `TheDaimos/weather-router-dev-pub` (öffentlich); **Branch:** `feature/p7-010-global-concurrency-2026-10-16`.

## Umsetzung
- `df85c7f1ae690e0e4d6256740430b6c5f2f47c00`: Unmittelbar nach dem erfolgreichen OPERA-CoG-Download führt `OperaSourceMonitor._inspect_raster` im HA-Executor eine echte `rasterio.open`-Prüfung durch und verwendet den bestehenden `check_opera_raster`-Vertrag (Produkt, UTC, Format, LAEA, Rastergröße, Bänder, NoData). Der Status unterscheidet `native_raster_reader_unavailable`, `raster_metadata_rejected` und `metadata_checked_quality_palette_unverified`. Der Frame wird ausdrücklich **nicht** als qualitäts-/palettenverifiziert freigegeben.
- `af4519d957a3e6a53c7885d7f867dbafd3f376dd`: Admin-WebSocket `weather_router/opera_status` stellt `source_monitor.last_metadata_check` bereit.
- `85cd163cc6e51cdbd0682639177ab96fc56e2d7c`: Regression überprüft Aufruf und Diagnose, kein Frame-Promote.

## Technische Grenzen
Das Vorhandensein von `rasterio` ist auf HA DEV VM109 nicht bestätigt. `quality1` und Farbpalette sind im öffentlichen Freigabevertrag weiterhin `unverified`; `ready_for_public_tiles` bleibt `False`. Kein synthetisches Bestehen von Qualität, keine HTTP-Freigabe, kein unautorisierter Consumer-V2-Pfad.

## CI
Öffentliche CI auf Commit `85cd163cc6e51cdbd0682639177ab96fc56e2d7c`: `41924488691` und `41924481108` Python, `41924480970` Frame Cache, `41924480876` 900-Audit, `41924480738` API-Monitor. Beim Dokumentieren noch laufend, kein PASS behauptet.

## Freigabestand
**Nicht installieren als fertige OPERA-Funktion**; HA DEV 109 Realtest noch offen. Wissenschaftlicher TEST69-Nachweis bereits abgeschlossen und wird nicht wiederholt. PROD 101 unverändert.

**Private GitHub Actions verboten; nur öffentliche CI.** Realtest-/Diagnose-Exporte ausschließlich `TheDaimos/Project-Log-And-Export@main`.
