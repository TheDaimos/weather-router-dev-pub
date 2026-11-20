# WeatherRouter 1.0.0 FINAL – öffentlicher Prüfstatus

Datum: 20.11.2026 · Status: **Distributions-CI bestanden; DEV-Gesamtabnahme offen**

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

## Öffentliche CI-Nachweise vom 20.11.2026

- [FINAL-Distributions-CI](https://github.com/TheDaimos/weather-router-pub/actions/runs/44699917696): **success**, Commit `3ed4bf411f0ad85056220c94677cd035718d556b`; das geprüfte ZIP mit SHA-256-Liste wird als Workflow-Artefakt bereitgestellt.
- [FINAL-Projektseite (GitHub Pages)](https://github.com/TheDaimos/weather-router-pub/actions/runs/44699915299): **success**, derselbe Commit.
- [DEV-Public-CI](https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/44699863057): **failure**, Commit `ff4e4c3c78a859096193a1ed488b2c4e9ddfff67`, Python 3.12 und 3.13. Distribution-Guard und JavaScript-Syntax bestanden; Python-Unittests, Strukturprüfung und Git-Export-Frontendtest fehlgeschlagen. Die einzelnen Prüfprotokolle wurden als CI-Artefakte archiviert.

Ein grüner FINAL-Distributionscheck bestätigt Paketaufbau und ausgewählte statische Kriterien, **nicht** den vollständigen Funktionsumfang oder die bestandene DEV-Testmatrix.

Die öffentlichen Tests enthalten ältere Annahmen und Vertragsstände. Ob jeder Fehlschlag ausschließlich darauf beruht, ist noch **nicht** für jeden Einzeltest geklärt. Tests dürfen nicht stillschweigend entfernt oder übersprungen werden, um ein grünes Ergebnis zu erzeugen.

## Release-Gates

1. Test- und Vertragsabweichungen einzeln klassifizieren, beabsichtigte neue Sollwerte dokumentieren und Regressionen beheben.
2. Öffentliche CI vollständig ausführen und die Ergebnisse dem exakten Release-Commit zuordnen.
3. HACS-Neuinstallation, Sidebar, Original-Branding, Provider-Defaults inklusive OPERA und Zusammenspiel mit GewitterRadar auf DEV testen.
4. Offizielles `v1.0.0`-Tag und GitHub-Release im stabilen öffentlichen Repository erstellen.
5. Falls ein bewusst unter Testvorbehalt veröffentlichtes FINAL gewünscht ist, den Testvorbehalt im Release sichtbar ausweisen.

## Datenschutz und Nachweisführung

Nur bereinigte Prüfergebnisse ins öffentliche Repository übernehmen. Rohdaten, Export2Git, echte Standortdaten und Betriebsdiagnosen bleiben ausschließlich in `TheDaimos/Project-Log-And-Export`. Eine erfolgreiche Musterprüfung ersetzt keine manuelle Datenschutzfreigabe.
