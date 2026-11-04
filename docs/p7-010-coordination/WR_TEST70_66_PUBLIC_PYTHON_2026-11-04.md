# WR TEST70-66 — Python-CI ausschließlich im öffentlichen Repository

Datum: 2026-11-04. CI-Repository: `TheDaimos/weather-router-dev-pub`, Branch `feature/p7-010-global-concurrency-2026-10-16`.

## Ausgangslage
Die öffentliche WR-V2-Vertragskopie verlangte bisher zwingend `max_data_age_seconds` und enthielt eine 900-Sekunden-Sperre für explizite OPERA-RATE-Anfragen. Private WR-V2-Entwicklung arbeitet hingegen mit serverseitiger, nutzerkonfigurierter Gültigkeit. **Die öffentliche Quelle ist ein separater Entwicklungsstand; Public-CI-PASS ist kein Nachweis für den privaten HEAD.**

## Umsetzungen
- `3374eaf2a325c2cf2d9de54216b975f9e93250df`: Public-V2-Parser lässt vom Client weggelassene Altersgrenzen zu, akzeptiert boolesche Satellitenpräferenz und sperrt 901/1650 Sekunden nicht mehr.
- `aecfaa9c09df44e19c4cee93b79ff3840b35b54f`: Public-Request-JSON-Schema entsprechend korrigiert.
- `7edaf1552a9261e2c2d4bd6b6f128af10f0beb4d`: bisherige Schema-Regression aktualisiert.
- `8afecbd16f4b83ec903f5679d25919dddfc5c57e`: eigenständige öffentliche Python-Tests zum WR-Authority-Request, boolescher Präferenz, 1650 Sekunden und verbotenen Providerlisten hinzugefügt.
- `0564d2d070644eb0646faae49df1d485d2251025`: Legacy-Test, der OPERA >900 Sekunden erwartungsgemäß ablehnte, angepasst.
- `79960757a5752cac51d8cd54f4851aa020d0197a`: veraltete Loader-166-Versionsassertion an den bestehenden öffentlichen Loader 167 angepasst.

## CI
Die bereits existierende **öffentliche** `.github/workflows/public-ci.yml` startet Python 3.12 + 3.13, unittest-Gesamtprüfungen, P7-010-Verträge und native Rasterbildtests. Der Commit `79960757...` hat den öffentlichen Lauf `41891110092` und weiteren Matrixlauf `41891118897` ausgelöst. Ergebnis zum Erstellungszeitpunkt: noch nicht final; kein vorgetäuschtes PASS. Öffentlicher API-Monitorlauf `41891072806` für vorherigen Code-HEAD war SUCCESS.

## Offene Freigabegrenze
Das öffentliche Repository enthält nicht die vollständige private WR-OPERA-Runtime. Deshalb ersetzt diese CI **nicht** die Python-Gesamtregression des privaten Branches `TheDaimos/weather-router-dev@deploy/dev`. Für deren Abnahme muss eine ausdrücklich freigegebene öffentliche, bereinigte Testsnapshot-Version bereitstehen; private Actions, private Checkout-Tokens und private Artefaktpublikation sind verboten. TEST69 nicht wiederholen. PROD VM101 nicht ändern. Test-/Diagnoseexporte ausschließlich `TheDaimos/Project-Log-And-Export@main`.
