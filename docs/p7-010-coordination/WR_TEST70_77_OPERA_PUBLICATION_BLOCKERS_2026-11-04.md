# WR TEST70-77 – Echte OPERA-Publikationssperren im öffentlichen Runtime-Status

Datum: 2026-11-04. Repository: `TheDaimos/weather-router-dev-pub`, Branch `feature/p7-010-global-concurrency-2026-10-16`.

## Quellenbefund
- `opera_source_monitor.OperaSourceMonitor.check_once` setzt nach Datenabruf `downloaded_unverified_raster` und registriert keinen neuen, geprüften OPERA-Radarframe für Consumer V2.
- `opera_product_contract.CheckedRaster.ready_for_public_tiles` ist ausdrücklich immer `False`: Der Produktvertrag validiert Rahmen/Metadaten, aber behauptet keine geprüfte Qualität/Palette.
- `opera_runtime.OperaRuntime.status` meldet `http_enabled=False`, `consumer_v2_approved=False`; die tatsächliche HA-Endpunktregistrierung und Providerzulassung fehlen.
- Grün bestandene öffentliche Quellcode-CI ist deshalb kein Nachweis sichtbarer OPERA-Niederschlagspixel in HA DEV 109.

## Änderungen
- `011df84410101f9e362886b0f10da38c894c6917`: `status().products[product].publication_blockers` mit den eindeutigen Gründen `provider_disabled`, `product_service_disabled`, `no_promoted_frame`, `quality_not_verified`, `geometry_not_verified`, `palette_not_verified`, `frame_not_current`. Zusätzlich `frame_verified` – ohne neue Freigabe.
- `e84b7b78227cad56db4d1f0db7dc5bb1be5b1dc1`: Regression prüft deaktivierten Provider, fehlenden Frame und alle drei Prüfsperren an synthetischem Frame.
- `weather_router/opera_status` im bestehenden WebSocket-Modul liest bereits `runtime.status()`; die zusätzlichen Gründe sind somit in der dafür vorgesehenen Diagnose verfügbar, sofern die öffentliche Version wirklich installiert wird.

## Öffentliche CI
Auf `e84b7b782...`: OPERA Frame Cache `41923295305` SUCCESS, WR API monitor `41923295200` SUCCESS, 900-s Audit `41923295197` SUCCESS. Python-Workflows `41923295089` und `41923307626` zum Berichtszeitpunkt in Arbeit; keine grüne Gesamt-CI vorwegnehmen.

## Noch ausstehend
Es fehlt ein realer, unabhängig geprüfter OPERA-Frame-Promote-Pfad einschließlich echter Produkt-Qualitätswerte und Palette, Provider-Registry samt Consumer-V2-Capability, authentifizierte Tile-HTTP-Aktivierung und ein HA DEV 109 Realtest. Kein Bypass dieser Freigaben. Bei bestehendem Export2Git meldete HA DEV WR 0.10.285, während die öffentliche DEV-Codeversion 0.10.164 ist; kein identischer Installationsstand nachgewiesen.

**Private GitHub Actions verboten – nur öffentliche CI im Public-Repo.** PROD VM101 unverändert. Diagnostik-/Realtest-Exporte ausschließlich nach `TheDaimos/Project-Log-And-Export@main`. Keine Wiederholung bereits abgeschlossener wissenschaftlicher TEST69-Prüfungen.
