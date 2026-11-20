# WeatherRouter 1.0.0 FINAL – öffentlicher Prüfstatus

Datum: 20.11.2026 · Status: **Prüfung offen / keine grüne Gesamtabnahme**

## Gegenstand

- Öffentliche Entwicklungsquelle: `TheDaimos/weather-router-dev-pub`, Branch `main`.
- Öffentlicher Distributionsstand: `TheDaimos/weather-router-pub`, Branch `main`, initialer Snapshot `658295368b5e5efa5e052efb26947dc7b58bf6f8`.
- Manifestversion: `1.0.0`; DEV-Referenz `0.10.327 / Loader 330` wird nicht überschrieben.
- PROD VM101 wurde für die Vorbereitung nicht verändert.

## Bisherige Prüfungen

| Prüfung | Befund |
| --- | --- |
| Verteilungswächter `tests/wr_public_distribution_guard.py` | Bestanden |
| JavaScript-Syntax der Frontenddateien (`node --check`) | Bestanden |
| ZIP-Integritätsprüfung des vorbereiteten Pakets | Bestanden |
| Musterprüfung der übertragenen Integrations-Texte auf Geheimnisse und private Koordinaten | Keine Treffer; **kein Vollbeweis** |
| Python-Unittests (`unittest discover`) | **Nicht bestanden:** 99 Failures, 8 Errors aus 1102 Tests |
| Struktur-/Vertragsprüfung (`scripts/verify_m2_structure.py`) | **Nicht bestanden:** Runtime-Capability-Map weicht vom Vertragsentwurf ab |
| OPERA-Originalprüfung mit LFS | Hier nicht erneut ausgeführt; eigener CI-Workflow vorhanden |
| HA-/HACS-Installation mit GewitterRadar | Ausstehend: Betreiberprüfung |

Die öffentlichen Tests enthalten ältere Annahmen und Vertragsstände. Ob jeder Fehlschlag ausschließlich darauf beruht, ist noch **nicht** für jeden Einzeltest geklärt. Tests dürfen nicht stillschweigend entfernt oder übersprungen werden, um ein grünes Ergebnis zu erzeugen.

## Release-Gates

1. Test- und Vertragsabweichungen einzeln klassifizieren, beabsichtigte neue Sollwerte dokumentieren und Regressionen beheben.
2. Öffentliche CI vollständig ausführen und die Ergebnisse dem exakten Release-Commit zuordnen.
3. HACS-Neuinstallation, Sidebar, Original-Branding, Provider-Defaults inklusive OPERA und Zusammenspiel mit GewitterRadar auf DEV testen.
4. Offizielles `v1.0.0`-Tag und GitHub-Release im stabilen öffentlichen Repository erstellen.
5. Falls ein bewusst unter Testvorbehalt veröffentlichtes FINAL gewünscht ist, den Testvorbehalt im Release sichtbar ausweisen.

## Datenschutz und Nachweisführung

Nur bereinigte Prüfergebnisse ins öffentliche Repository übernehmen. Rohdaten, Export2Git, echte Standortdaten und Betriebsdiagnosen bleiben ausschließlich in `TheDaimos/Project-Log-And-Export`. Eine erfolgreiche Musterprüfung ersetzt keine manuelle Datenschutzfreigabe.
