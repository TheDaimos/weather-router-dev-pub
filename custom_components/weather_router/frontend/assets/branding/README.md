# WeatherRouter Runtime Branding

Dieser Ordner enthält ausschließlich aus den kanonischen Grafikassets erzeugte Runtime-Kopien für die Home-Assistant-Integration.

Dateien:

```text
weather-router-brandmark.png
weather-router-emblem.png
```

Verwendung:

```text
weather-router-brandmark.png
→ WeatherRouter Lab
→ HTML-Hilfe
→ transparente UI-Darstellung

weather-router-emblem.png
→ größere Präsentationsflächen mit vollständigem Emblem
```

Regeln:

- Runtime-Kopien nicht von Hand bearbeiten.
- Änderungen immer aus dem akzeptierten kanonischen Asset neu erzeugen.
- Kanonische Binärdateien unter `assets/graphics/` versionieren und mit SHA256 dokumentieren.
- Die Home-Assistant-Integrationskachel verwendet seit Home Assistant 2026.3 lokale Brand-Dateien unter `custom_components/weather_router/brand/`.
- Für die Integrationskachel sind `brand/icon.png` (256 × 256) und `brand/icon@2x.png` (512 × 512) vorgesehen.
