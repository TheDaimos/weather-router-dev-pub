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

## Gesamt-Nachholprüfung und Paketabnahme am 14.10.2026

- GitHub Actions [38624414768](https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/38624414768) am Commit `e7557aa9960927632c142abc4a17b1493b629a5e`: **SUCCESS** für Python 3.12 und 3.13, je 1.217 öffentliche Python-Tests sowie getrennte 55 V2-Rastertests, die bereits Teil der 1.217 Gesamtzahl sind.
- Ab diesem Stand wurden die bislang fehlenden **öffentlich ausführbaren Schritte des privaten M2-Workflows** zusätzlich ausgeführt: Dateiverteilungsschutz, Integrationsstruktur, JavaScript-Syntax, Git-Export, Erstellung der öffentlichen Integrations-ZIP, vollständige Prüfung der 117 Paketdateien, SHA256-Kontrolle, ZIP-Integritätsprüfung und öffentlicher Artefakt-Upload (7 Tage Aufbewahrung).
- Katalogtest für reale `weather.precipitation.layer`-Zuordnungen: Bei zwei Raster-Capabilities fehlt eine garantierte numerische Einheit. Der optionale V2-Vertrag führt diese korrekt als `null` weiter, statt Werte zu erfinden oder die Datenquelle pauschal auszuschließen.
- Neuerer öffentlicher Prüflauf [38625014603](https://github.com/TheDaimos/weather-router-dev-pub/actions/runs/38625014603), Commit `84549031311ee7d42e9d2ccc6b18920fa04196ef`: Python 3.12 und 3.13 **SUCCESS**, **1.219 öffentliche Python-Tests je Version** (davon 57 V2-Rastertests, bereits in den 1.219 enthalten) und 117 vollständig überprüfte ZIP-Paketdateien.

### Differenz zum privaten Entwicklungsstand bleibt getrennt

Der historische Vergleich zeigte 325 gemeinsame Dateien, 40 voneinander abweichende Dateifassungen, 365 nur private und 23 nur öffentliche Dateien. Diese Zahlen gelten für die im privaten Nachholregister genannten Vergleichscommits, nicht unveränderlich für zukünftige HEADs.

Vor allem verlangt der private Strukturprüfer zusätzliche, im eigenen Frontend nicht vorhandene Git-Export-Marker `_wrPendingGitExport` und `pendingGitExport`; der gemeinsame tatsächliche Frontendcode verwendet stattdessen `_wrGitPendingExport`. Der private Prüfer muss **fachlich korrigiert oder durch echte Implementierung erfüllt** werden, bevor ein bitidentischer privater M2-PASS behauptet wird. Öffentliche Erfolge belegen nur den öffentlichen, reproduzierbar geprüften Quellstand.

Keine 230 Wiederholungen desselben Workflows erforderlich; die 230 historischen Einträge sind Commit-Ausführungen, keine zusätzlichen individuellen Testfälle. Reale Home-Assistant-, DRA- und Geräteabnahmen bleiben offen.
