# WR TEST70-67 – Public-Repo als einzige Entwicklungslinie: Quellen- und Abnahmelücken

Datum: 2026-11-04. **Einzige WR-Entwicklungslinie ab jetzt:** `TheDaimos/weather-router-dev-pub@feature/p7-010-global-concurrency-2026-10-16`.

## Verifizierte öffentliche Python-CI
Der öffentliche Commit `79960757a5752cac51d8cd54f4851aa020d0197a` bestand die Python-CI-Matrix in Runs `41891110092` und `41891118897` (SUCCESS). Der nachfolgende öffentliche Dokumentations-Commit `e0ecfc7141040f510ef96df12788a5876788c1b6` bestand `41891197066`, `41891188678` (Python Public DEV CI) und `41891188225` (API Monitor). Die CI ist tatsächlich im Public-Repo ausgeführt, ohne Checkout oder Action in einem privaten Repository.

## Architekturstatus, den CI nicht beweist
Eine unmittelbare Quelleninspektion ergibt:
- `custom_components/weather_router/consumer_raster_mosaic_api.py` im öffentlichen Zweig: **19.546 Zeichen**, gegenüber **47.436 Zeichen** im letzten privaten Entwicklungsstand. Die zwei Dateien sind nicht identisch.
- `custom_components/weather_router/raster_mosaic_contract.py` öffentlich: **7.451 Zeichen**, privat: **8.516 Zeichen**; ebenfalls verschieden.
- Öffentlich fehlen `custom_components/weather_router/opera_v2_admission.py` und `custom_components/weather_router/opera_preview_age_policy.py` (bei der Inspektion des öffentlichen Zweigs).
- Die aktuelle öffentliche Consumer-API implementiert folglich **nicht nachweislich** das vollständige serverseitige Anwenden nutzerkonfigurierter OPERA-Gültigkeit, das im privaten Entwicklungsstand bereits angelegt ist.

Diese Angaben dokumentieren den geprüften Stand; sie sind **keine** Autorisierung, private Implementierungen, Zugangsdaten, gerätespezifische Konfigurationen, Originaldaten oder interne Diagnoseexporte pauschal öffentlich zu kopieren.

## Weitere verbindliche Entwicklungsreihenfolge – nur Public
1. Öffentlich vorhandene Runtime gegen die aktuelle WR/GR-V2-Vertragsmatrix inventarisieren (Server-Age-Authority, `times.valid_until`, provider activation, Token-geschützter Kacheltransport, Ringpuffer/Frame-Registry, Atomizität und Fehlergründe). Fehlende Komponenten ohne Secrets und ohne Änderung an V1 portieren.
2. **Vor** einem Claim auf vollständige OPERA-Integration durch öffentliche Python-/Unit-/Integrations-CI beweisen, dass tatsächlich der produktive Resolver und nicht nur der isolierte Request-Parser geprüft wird.
3. Öffentliche CI muss sämtliche benötigten OPERA-Komponenten im **gleichen öffentlichen Commit** prüfen: keine privaten Actions, keine private Repository-Checkouts, keine privaten Tokens für Quellcodezugriff.
4. Danach Package/Manifest/Loader/DRA-Parität, eigenständige HA-DEV-VM109-Installation und dokumentierte Desktop-/Android-/iPad-Realtests.
5. Diagnose- und Realtest-Exporte ausschließlich in `TheDaimos/Project-Log-And-Export@main`; PROD 101 unangetastet.

## Aktuelle Freigabe
**Public Python-CI grün; vollständiger WR OPERA Runtime-Nachweis weiterhin offen.** Keine Installationsfreigabe für gemeinsamen WR/GR-Release. TEST69 ist abgeschlossen und wird nicht wiederholt. **Private GitHub Actions sind und bleiben verboten.**
