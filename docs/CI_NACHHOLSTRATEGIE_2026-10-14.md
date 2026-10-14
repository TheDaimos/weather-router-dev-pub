# WeatherRouter DEV-PUB – öffentliche CI-Prüfungen und Nachholverfahren

**Stand: 14. Oktober 2026** · **Entwicklungszweig:** `feature/p7-010-raster-contract-2026-10-14`

## Grundregel

WeatherRouter verwendet die öffentliche Entwicklungs- und Prüfkopie
`TheDaimos/weather-router-dev-pub`, damit GitHub-hosted Actions für
**öffentlich freigabefähigen Quellcode** ohne das private Actions-Freiminuten-
kontingent ausgeführt werden können. Im privaten Projekt sind die freien
Laufminuten momentan erschöpft. **Private GitHub-Actions nicht erneut
anstoßen oder durch private Commits ohne Not weitere Blockaden erzeugen.**

Ein vollständiges Register der ausgefallenen privaten Actions (mit
Laufnummern, Commit und Nachholstatus) wird **ausschließlich im privaten
Repository** gepflegt, nicht in dieser öffentlichen Kopie.

## Was darf in DEV-PUB geprüft werden?

- Veröffentlichungsfähige Python-Module und öffentliche V1-/V2-Verträge.
- Synthetische Provider-, Coverage-, Kartenfokus-, Datumsgrenzen-,
  Zeitstempel-, Raster- und Ressourcenbegrenzungstests.
- Die Prüfung der öffentlichen Dateiverteilung und der Struktur.
- Statische Frontend- und JavaScript-Tests ohne vertrauliche Konfiguration.

**Niemals veröffentlichen:** private Erweiterungen, Zugangsdaten, Tokens,
Provider-Geheimnisse, persönliche Exporte, Diagnoseprotokolle aus realen
Systemen, nicht freigegebene Historien, vertrauliche Umgebungswerte oder
Code, dessen Veröffentlichungsfreigabe fehlt.

## Nachholäquivalente – mit klarer Abgrenzung

| Nicht ausführbare private Prüfung | Zulässiger öffentlicher Ersatz | Einschränkung |
|---|---|---|
| `Validate M2 structure` | `python scripts/verify_m2_structure.py` im öffentlichen Gesamt-Workflow | Prüft **nur den öffentlichen Quellbestand**, nicht private Dateien oder die private Runtime |
| `P7-010 Raster-Mosaik Vertragspruefung` | `python -m unittest discover -s tests -p 'test_p7_010_raster_mosaic_*.py' -v` | Prüft reine Vertrags-, Coverage- und Zeitfunktionen, keine Live-Provider |
| Weitere Python-/JS-Abnahmen | Öffentlicher Gesamt-Workflow für freigegebene Dateien | Keine implizite Freigabe privater Erweiterungen |
| Echte HA-/DRA-Realabnahme | **Kein** automatischer Ersatz | Bleibt bis Realnachweis offen |

**Erfolgreiche öffentliche Prüfungen** schließen die dokumentierten
privaten Original-Laufnummern nicht automatisch. Das Nachholregister
unterscheidet `öffentlich äquivalent geprüft`,
`weiterhin privat nachzuholen` und `produktiv real abgenommen`.

## Aktive P7-010-Grenzen

Die öffentlich prüfbaren V2-Verträge, Adapter, datumsgrenzenfähige
Coverage-Auswahl und Mehrbild-Zeitauswahl sind **isolierte Testbausteine**.
Der produktive Mehrquellen-Endpunkt, die Echtzeit-Integration des
Gewitterradars, Kachelbegrenzung und HA-/DRA-Realtests bleiben **offen**.
V1-Kompatibilität bleibt verbindlich; keine privaten P6-Abnahmen wiederholen.

## Prüfergebnisse

- Öffentliche Python-3.12-/3.13-Prüfung der isolierten V2-Bausteine:
  [Lauf 38608695548](https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/38608695548) – **SUCCESS** am damaligen Stand.
- Für alle nach diesem Dokument geänderten Dateien gilt **ausschließlich
  der neue GitHub-Actions-Lauf am jeweils neuesten Commit**.
- Neue private, nicht ausführbare Runs werden im **privaten
  Nachholregister** ergänzt; keine öffentlichen privaten Commit-Listen.
