# WR TEST70-78 – OPERA-Quellenaufnahme von Freigabe getrennt

**Repository:** `TheDaimos/weather-router-dev-pub` · **Branch:** `feature/p7-010-global-concurrency-2026-10-16` · **Datum:** 04.11.2026

## Konkreter Codebefund
`OperaSourceMonitor.check_once` ruft `OperaCogFetch.fetch` auf, übernimmt das Ergebnis aber **nicht** als freigegebenen Frame. Stattdessen wird `last_reason=downloaded_unverified_raster` gesetzt. Weder `OperaRuntime.prepare` noch `OperaRuntime.promote` wird für diesen Download aufgerufen. `CheckedRaster.ready_for_public_tiles` liefert ausdrücklich `False`. Die Runtime meldet weiterhin `http_enabled=False` und `consumer_v2_approved=False`. Die OPERA-Verbindung nach GR ist somit noch nicht vollständig.

## Änderungen
- `08858dc7ae352dcac8cd713d8429905b9f86b1e7`: getrennte Anzahl heruntergeladener, unbestätigter Originale und letztes Produkt im Source-Monitor; keine falsche Promotionszählung.
- `f2737964467ac8b8ce054e48723928c592ad9826`: Admin-WebSocket `weather_router/opera_status` gibt `downloaded_unverified_count`, `last_downloaded_product` und `publication_stage=download_only_unverified` zurück.
- `c4224a66ebb19fec62ff344de59c6c1a9ef4d6c9`: Regression fordert, dass genau ein Download als unverified erfasst wird und die Registry dabei unverändert leer bleibt.

## Freigabe
**Keine OPERA-End-to-End-Installationsfreigabe.** Die vollständige produktive Prüfung von Rastermetadaten, Qualität, Palette, Freigabe, Provider-Capability und authentifiziertem HTTP-Transport bleibt offen. Abgeschlossene wissenschaftliche Prüfungen nicht erneut durchführen. Die neuen Zähler verbessern die Lokalisierung der Stufe, ersetzen aber **keine** funktionierende Übertragung bis GR.

Alle CI ausschließlich öffentlich, **keine privaten GitHub Actions**. PROD VM101 unverändert. Exporte ausschließlich `TheDaimos/Project-Log-And-Export@main`.
