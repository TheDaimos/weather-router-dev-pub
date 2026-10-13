# WeatherRouter Diagnostic Contracts

Stand: **2026-10-01**

Diese Schemas beschreiben ausschließlich interne/admin-only WeatherRouter-Diagnosewege.
Sie sind **kein Bestandteil von Consumer API V1** und dürfen von Consumer-Produkten
nicht als stabiler Public-Vertrag vorausgesetzt werden.

## Befehle

```text
weather_router/routing_diagnostics
weather_router/routing_diagnostics_clear
weather_router/routing_diagnostics_subscribe
```

## Dateien

- `routing_diagnostic.v1.schema.json` — vollständiger einzelner Decision Trace;
- `routing_diagnostics.request.schema.json` — Verlauf oder Einzeltrace anfordern;
- `routing_diagnostics.index.v1.schema.json` — Verlaufsliste mit kompakten Summaries;
- `routing_diagnostics_clear.request.schema.json` — flüchtigen 50er-Ring leeren;
- `routing_diagnostics_clear.response.schema.json` — Ergebnis des Clear-Befehls;
- `routing_diagnostics_subscribe.request.schema.json` — Live-Subscription starten;
- `routing_diagnostic.event.v1.schema.json` — fachliche Event-Nutzlast eines neuen
  abgeschlossenen Traces.

Home Assistant ergänzt auf WebSocket-Transportebene eine Message-`id`. Diese
Transport-ID gehört nicht zur WeatherRouter-Fachnutzlast und ist in den Schemas nicht
enthalten.

## Stabilitätsregel

Der Diagnosevertrag darf additiv erweitert werden. Breaking Changes benötigen eine
neue Diagnose-Schema-Version. Das ändert **nicht** die unabhängige Version von
`weather_router.consumer`.
