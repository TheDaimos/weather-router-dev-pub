# WeatherRouter – verbindliche Repository- und CI-Grenze

**Datum:** 2026-10-29  
**Geltungsbereich:** WeatherRouter-Entwicklung und alle Folgeaufträge  
**Status:** verbindliche Arbeitsregel; kein technischer Freigabenachweis

## 1. Maßgebliche Entwicklungsumgebung

**Alle zukünftigen WeatherRouter-Quellcodeänderungen, Implementierungen, Tests, Fehlerkorrekturen, Workflows und Entwicklungsberichte entstehen im öffentlichen Repository `TheDaimos/weather-router-dev-pub`.** Ausgangsbasis ist der vorhandene Public-DEV-Zweig `feature/p7-010-global-concurrency-2026-10-16`; vorhandene Branch-/Releaseprozesse werden nicht ungeprüft ersetzt.

Das Public-DEV-Repository muss selbständig entwickelbar und testbar sein. Es darf keine stille Laufzeit-, Build-, Test- oder Entwicklungsabhängigkeit vom privaten Repository haben. Keine zusätzlichen VMs, manuellen Nutzertransfers oder neue Infrastruktur als Voraussetzung einführen.

## 2. Begrenzte Verwendung des alten privaten Repositories

`TheDaimos/weather-router-dev` ist **keine** Entwicklungsquelle für neue Arbeit. Der Zugriff ist nur für **lesende, gezielte Vergleiche und die nachweisbare Prüfung bisheriger Tests, Providerfunktionen, Kompatibilität und Gesamtregressionen** gestattet, sofern dafür erforderlich.

Kein Entwickeln, Reparieren, Versionieren, Dokumentieren oder Committen in diesem privaten Repository im Rahmen dieses Auftrags. Keine Übernahme von Quelltexten, Originaldaten, Geheimnissen oder internen Konfigurationen nach Public. Keine Übertragung vollständiger privater Quellstände zu öffentlichen Runnern. Wenn eine technische Übernahme nach Private künftig notwendig sein sollte, ist sie ein **separat autorisierter Bereitstellungsvorgang** und nicht Teil der Public-DEV-Entwicklung.

## 3. Absolutes GitHub-Actions-Verbot in privaten Repositories

**Erlaubt:** GitHub Actions in `TheDaimos/weather-router-dev-pub` (PUBLIC), nach Prüfung von Workflow, Datenschutz, Lizenz und Veröffentlichungseignung.

**Absolut verboten:** Verwendung, Auslösung, Aktivierung, Wiederholung oder indirektes Triggern von GitHub Actions in `TheDaimos/weather-router-dev` und **jedem anderen privaten Repository**. Dies umfasst Push, Pull Request, Dispatch, Workflow-Call, automatische/manuelle/indirekte Ausführungen und Reruns.

Diese Regel muss ausdrücklich **in jedem zukünftigen Entwicklungs- und Folgeprompt** stehen, ganz gleich, ob Actions dort notwendig sind.

## 4. Testführung und Freigabe

Tests der tatsächlichen öffentlichen Implementierung in Public-CI ausführen; isolierte synthetische Referenztests sind kein Ersatz. Öffentliche Run-ID, Commit-SHA, Ergebnis und Testumfang protokollieren. Frühere grüne Tests gelten nur für die jeweils getesteten Stände. Privaten Gesamtregressions- und HA-DEV-Realabnahmestatus gesondert kennzeichnen. Wissenschaftlich ungeprüfte OPERA-Produkte bleiben UNVERIFIED/BLOCKED; keine Warnbetrieb-Freigabe.

## 5. Nächster konkreter Ablauf

1. Public-DEV-HEAD, vorhandene Workflows, Tests und tatsächliche OPERA-Module inventarisieren.
2. Fehlende OPERA-Providerfunktionen ausschließlich im Public-DEV-Code implementieren; keine private Quellcodekopie.
3. Bereits vorhandene öffentliche CI für reale Implementierungs-/Consumer-/HTTP-/Rastertests verwenden, Fehler beheben, erneut prüfen.
4. Ergebnisse mit verifizierten Public-Commits und öffentlichen Run-IDs nachweisen.
5. Private Provider-/Gesamtregressionen nur soweit erforderlich **lesend vergleichen und prüfen**; nicht zur Voraussetzung für die reguläre Public-DEV-Arbeit machen.
6. HA DEV VM 109 erst nach kontrollierter, gesondert freigegebener Bereitstellung real abnehmen. HA PROD VM 101 bleibt unangetastet.

**Unveränderliche Kurzregel: PUBLIC = entwickeln + CI. PRIVATE = nur lesende Bestands-/Gesamtprüfungen. Nie private Actions.**
