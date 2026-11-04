# WR TEST70-73 – Authentifizierte OPERA-Kacheln: Gültigkeit ausschließlich von WR

**Entwicklung:** ausschließlich `TheDaimos/weather-router-dev-pub@feature/p7-010-global-concurrency-2026-10-16`. Keine Änderungen an privaten Repositories.

## Öffentliche bestätigte Ausgangsbasis
Public Python CI `41911279008` und `41911266249` **SUCCESS**, API-Monitor `41911266492` **SUCCESS** auf Commit `8b66ca6924b8d7528b7ec5483a6a0a4fb8ba3e78`.

## Durchgeführte Änderungen
1. `82707a0f531159b52698df773ca281ba0d8e9faf`: In `opera_tile_access.assert_authorized` die lokale 900-Sekunden-Grenze entfernt. Stattdessen ist `max_age_seconds` verpflichtend, nur als tatsächliche Ganzzahl zwischen 1–3600 zulässig. Grundlage: UTC-Messzeitpunkt des Frames.
2. `45ac28340ac1783f5714ecdd2d097024c7deffb8`: `OperaTileView` benötigt einen WR-Server-Callback `server_validity_seconds`. Dieser wird **bei jedem** Autorisierungspunkt (vor Lookup, nach Worker-Wartezeit, vor HTTP-Antwort) abgefragt. Fehlende Konfiguration wird fail-closed verweigert; keine heimliche clientseitige 900-Sekunden-Frist.
3. `4d95416180837f2f64c7e1dd3a27e6cec99c0e6c`: Pure-Python-Vertragstests aktualisiert und um ungültige Serverwerte, 1650-s-Grenze und anschließenden Widerruf erweitert.
4. `e166786e1ae958e2f4a2b9f5c118e524977d9396`: HTTP-Test-Harness erhält jetzt eine explizite simulierte WR-Laufzeitvorgabe, statt eine implizite Clientfrist vorauszusetzen.

## Laufende CI
Öffentliche CI am Test-Commit: `41913441795` (Python), `41913441667` (API Monitor). **API Monitor SUCCESS**; Python bei Berichtserstellung noch offen. Alle CI-Ergebnisse nur als bestanden deklarieren, wenn GitHub SUCCESS meldet.

## Nicht als erledigt deklarieren
Der HTTP-Handler wird weiterhin nicht für HA registriert. Die Source-Monitor-Downloads sind noch nicht wissenschaftlich/qualitativ promotet, OPERA-Provider-Registry und Capability-Katalog fehlen. Für die Vollinstallation bleiben ein echter geprüfter Frame-Promote-Pfad, Benutzer-/Profilprüfung mit aktuellem WR-Status, aktiver HA-HTTP-Route, vollständige Consumer-V2-Antwort mit `times.valid_until`, Deploy-Artefaktparität und HA DEV VM109 Realtests erforderlich.

**INSTALLATIONSFREIGABE:** NEIN. PROD VM101 nicht ändern. TEST69 nicht wiederholen. **Private GitHub Actions verboten**, nur öffentliche CI. Diagnose-/Realtest-Exporte nur nach `TheDaimos/Project-Log-And-Export@main`.
