# WR TEST70-70 – Öffentliche Consumer-V2-OPERA-Providerauswahl ohne stillen Fallback

**Datum:** 2026-11-04. **Entwicklung:** ausschließlich `TheDaimos/weather-router-dev-pub@feature/p7-010-global-concurrency-2026-10-16`.

## Nachgewiesener Ausgangsstand
Öffentliche Runs `41908336321` und `41908327450` sowie API-Monitor `41908327353` erfolgreich auf `65a08811b053560b06b94260e755621fb637bb7f`.

Die zuvor implementierte Prüfung auf einen vorhandenen OPERA-Kandidaten war nicht hinreichend: Bei vorhandener OPERA-Kandidaten-ID konnten anschließend auch Raster anderer freigegebener Anbieter zur Auflösung gelangen.

## Implementiert
- `4d8ced5f780072972a00de51676f0db437a2f4b4`: Bei `source_request.provider_id=opera` wählt die Consumer-V2-Kandidatenauswahl **nur OPERA**. Falls nach den Core-, Profil-, Raster-, Geographic- und Feature-Prüfungen keine autorisierte OPERA-Kandidatur verbleibt, antwortet der Handler fail-closed mit `requested_provider_unavailable`. Automatische Providerwahl ohne `source_request` bleibt unverändert.
- `bb61d15d2616269cba3cea163fe86fbd78399937`: WebSocket-Harness mit tatsächlich zugelassenem simulierten OPERA-Kandidaten, konkurrierender Weltquelle und Prüfung, dass ausschließlich OPERA-Kachelebene geliefert und die andere Quelle niemals kontaktiert wird.
- Public CI automatisch angestoßen: Python `41908614112`, API Monitor `41908614257`. Bei Berichtserstellung noch **kein** abschließender Ergebnisnachweis für diesen Commit.

## Verbleibende echte Lücke
Ein erfolgreiches synthetisches OPERA-Routing ist **keine** vollständige Live-Anbindung. Der Public-Provider-Registry `providers/registry.json` und der Consumer-Capability-Map fehlt weiterhin die freigegebene OPERA-Providerdefinition. Der vorhandene Source-Monitor bezeichnet heruntergeladene CoGs ausdrücklich `downloaded_unverified_raster`, statt sie zu promoten. Die HTTP-Tile-View ist als inaktiv dokumentiert; `OperaRuntime.status` meldet `http_enabled=false` und `consumer_v2_approved=false`. Vor einer Aktivierung müssen native Raster-, wissenschaftliche Qualitäts-, Palette- und Berechtigungsfreigaben **angeschlossen** sein. Kein experimentelles Umgehen der Sperren.

**Updatefreigabe GR/WR: NEIN.** Für HA DEV 109 fehlen Live-E2E, vollständige OPERA-Bridge, Artefaktparität und tatsächliche Geräteabnahme. PROD VM101 unverändert, TEST69 nicht wiederholen. **Private GitHub Actions ausdrücklich verboten; öffentliche Actions ausschließlich in Public-Repositories.** Diagnose-/Realtest-Exporte nur nach `TheDaimos/Project-Log-And-Export@main`.
