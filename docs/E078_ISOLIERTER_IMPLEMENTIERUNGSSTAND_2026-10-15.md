# E-078 – isolierter Implementierungsstand (15.10.2026)

**Status: experimenteller Entwicklungszweig, keine Produktfreigabe.**

## Bedienung und Schutz

Der Home-Assistant-Schalter **„Puffer – Vorbereitung (noch nicht verbunden)”** ist im gesonderten E-078-Zweig vorhanden. Er persistiert die unabhängige Option `buffer_enabled` (Standard **false**). Das Lab enthält den Abschnitt **„E-078 · Daten- und Ausgabepuffer”** mit einer Ein-/Aus-Schaltfläche; der Text zeigt ausdrücklich **„Pufferbetrieb: nicht verbunden”**. Der bestehende Providerbetrieb, die Consumer API V1, P7-010 und die normalen Netzwerkzugriffe bleiben unverändert.

Ein eingeschalteter Vorbereitungsschalter bedeutet **nicht**, dass die Pufferverwaltung bereits im Live-Datenfluss arbeitet. Das ist absichtlich kein verstecktes Umschalten von Anfragen. Keine Bereitstellung via DRA vor einem eigenen Freigabeschritt.

## Isolierte Komponenten

- `buffer_core.py`: rein speicherbasierter, standardmäßig ausgeschalteter Zwischenspeicher mit Ablaufzeiten, sofortiger Löschung beim Ausschalten, strikt begrenzten Einträgen/Bytes und gesonderter Prüfung von Cache-Schreiben, Vorladen und Auslieferung. Kein Diskzugriff, keine Providerkontakte und keine Hintergrundaufträge.
- `buffer_policy.py`: experimentelle unabhängige `weather_router.buffer_policy.v1`-Richtlinienregistrierung ohne Provider-/Capability-Dummy. Richtlinien werden vor Schreiben, Vorladen und Ausliefern tatsächlich aufgerufen. Doppelte oder fehlerhafte Registrierungen liefern keine Freigaben; Entladen und Richtlinienwechsel löschen vorhandene Einträge automatisch.
- `tests/test_e078_buffer_core.py`, `tests/test_e078_buffer_policy.py`: ausschließlich synthetische Prüfungen, ohne reale Quellendaten oder Zugangsdaten.

## Abnahmegrenzen

Die E-078-Architektur aus den verbindlichen Konzeptdokumenten wird damit **noch nicht vollständig erfüllt**. Offen bleiben insbesondere:

1. Versionsverträglicher Anschluss des neuen `buffer_policy`-Typs an `extensions.py` einschließlich HA-Lebenszyklus und Manifestvalidierung. Die vorhandenen Providererweiterungen bleiben bis dahin unverändert.
2. Verknüpfung der persistenten Option und einer effektiven Rechte-/Lizenzbewertung mit einer gemeinsamen laufenden Pufferinstanz; absichtlich noch **nicht** mit Consumer-Routing verbunden.
3. Reale Provider- und Verbraucherrechte, eigene Quoten, Speicher- und Ressourcenmessungen unter HA sowie providerbezogene Bedienung und Diagnose.
4. Ausgabepaketpuffer, Fortsetzungen und optionaler Datenträgerpuffer.
5. Getrennte Tests mit dem laufenden P7-010-Mehrquellenpfad, sobald Gewitterradar integriert und die Realabnahme erfolgt ist.

**Abnahmeregel:** Bis alle Bedingungen erfüllt sind, weder „fertig“ noch „aktivierter Puffer“. Der experimentelle Schalter bleibt eine ausdrücklich gekennzeichnete Vorbereitung und kann jederzeit ausgeschaltet werden.
