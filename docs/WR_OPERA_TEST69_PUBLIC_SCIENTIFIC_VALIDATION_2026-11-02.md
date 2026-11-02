# WeatherRouter / OPERA RATE – Wissenschaftlicher Validierungsbericht TEST69 (PUBLIC)

**Datum:** 02.11.2026  
**Geltungsbereich:** OPERA-RATE als ODIM-H5-kartesisches Niederschlagsraster; LAEA-Georeferenzierung; `north_first`-Arrayorientierung; Rendern in WebMercator-/XYZ-Kacheln Z3–Z7.  
**Dokumenttyp:** Veröffentlichung der reproduzierbaren **Methodik und aggregierten Testergebnisse** aus einem privaten, lokal ausgeführten Linux-Prüfstand. Die vertraulichen Originaldateien, deren Prüfsummen, private Dateipfade und Diagnose-Rohprotokolle sind **nicht** Bestandteil dieser Publikation. 
**Freigabestatus:** **Wissenschaftliche Raster-Georeferenzierung in diesem Prüf-Scope positiv nachgewiesen**; keine Aussage über operative Produktivfreigabe, HA-PROD-Bereitschaft, externe Laborzertifizierung oder andere OPERA-Produkte.

## Zusammenfassung

Ein lokal unter Ubuntu/WSL2 durchgeführtes Testprogramm untersuchte neun originale OPERA-RATE-HDF5-Dateien, ihre ODIM-/LAEA-Geometrie, PNG-Pixelwiedergabe, eine frühere Z3-Lesefensterbegrenzung und vollständige Kantenpixel an ausgewählten Kachelübergängen. Ein normativer Abgleich mit der offiziellen EUMETNET-ODIM-Spezifikation begründet die korrekte Speicherzeilenfolge `north_first`.

**Konsolidierter Realtestbefund:**

| Gegenstand | Nachweis | Ergebnis |
|---|---|---|
| ODIM-/LAEA-Geometrie | Neun Originale, vier projizierte Eckpunkte, Auflösung und ausgewählte Pixelzentren | **9/9 bestanden** |
| Projektive Eckresiduen | maximale berechnete Abweichung am Eckenraster | **0,000092704 m** |
| Rastermaßabweichung | Maximaler Unterschied zwischen projizierten Abmessungen und Nennpixelmaß | **0,001077230 m** |
| Rastergrenzen / untersuchte Pixelzentren | getrennt formulierte Referenzberechnung und Rekonstruktor | **0,0 m / 0,0 m** |
| Erste PNG-Stichproben | 324 Kacheln, 2.916 Pixel | **0 Pixelabweichungen; 36 Z3-Renderabbrüche** |
| Z3-Korrektur und Folgetest | 360 Kacheln, 3.240 PNG-Pixel | **0 Pixelabweichungen; 0 Renderfehler** |
| Kachelnahtprüfung | 180 ausgewählte horizontale/vertikale Nähte, komplette zwei Kanten je Naht (2×256 Pixel) | **92.160 Kantenpixel, 0 Abweichungen** |
| Python-Syntax und OPERA-Regression | Aktueller untersuchter Softwarestand | **PASS** |
| Zeilenreihenfolge | ODIM_H5 2.4, §5.2 `Image Data` | **Nord → Süd; West → Ost (north_first)** |

**Begrenzung der Zahlen:** Kantenprüfung aller Pixel **der ausgewählten 180 Nähte**, nicht aller geografisch möglichen Kachelpaare. Die 3.240 Stichprobenpixel stammen aus einem separaten Lauf, können sich mit Kantenpositionen überschneiden und dürfen nicht als vollständig disjunkte Pixelmenge addiert werden.

## 1. Unabhängige wissenschaftliche Grundlage

EUMETNET OPERA, *Data Information Model for HDF5, ODIM_H5 Version 2.4*, 1. Juli 2021. Kapitel 5.2 **Image Data**, gedruckte Seite 33, PDF-Seite 39. Offizielle Quelle:

https://eumetnet.eu/wp-content/uploads/2021/07/ODIM_H5_v2.4.pdf#page=39

Die Spezifikation definiert für kartesische quantitative Bildprodukte: erstes Arrayelement in der oberen linken Ecke; Zeilen laufen **von Norden nach Süden**, Spalten **von Westen nach Osten**. Außerdem verlangt das Modell getrennte Rohwertkennungen für `nodata` und `undetect`. Daraus folgt bei konformer ODIM-H5-IMAGE-/COMP-RATE-Eingabe die Rasterhypothese `north_first`. Die Spezifikationsdefinition ist **unabhängig vom WeatherRouter-Quellcode**.

Die geografischen Originaleckpunkte und LAEA-Projektionsparameter definieren die Außenpositionen des Rasters, aber erst die zusätzliche Norm zur Arrayzeilenfolge schließt die vorher bestehende Nord-/Süd-Mehrdeutigkeit.

DWD-, NASA- und wetter.com-Vergleichsbilder waren ergänzende qualitative Plausibilitätschecks. Die in verschiedenen Datenprodukten/Zeiten gezeigten Niederschlagsmuster stellen **keine** pixelgenaue, voneinander unabhängige quantitative Orientierungsreferenz dar und wurden nicht als primärer Nachweis gewertet.

## 2. Prüfverfahren

### 2.1 ODIM-/LAEA-Geometrie

Originaldateien wurden auf HDF5-Signatur, SHA-256, UTC, Produkt RATE, rasterbezogene Metadaten, `projdef`, `xsize`, `ysize`, `xscale`, `yscale` und vier geografische Außenkanten-Eckpunkte `LL`, `UL`, `LR`, `UR` geprüft. Ein separat formulierter Referenzrechner projizierte die Ecken mit `pyproj` in LAEA, verglich die daraus abgeleitete Rasterausdehnung und Pixelzentren mit dem produktiven Rekonstruktionspfad sowie WGS84-/XYZ-Rückprojektionen.

Vorab definierte Testschwellen: 2,0 m bei Eckpunkten und Pixelzentren, 0,25 m für den Projektions-Roundtrip, 0,51 Kartenpixel für die XYZ-Rückprojektion. Diese Schwellen sind **technische Abnahmegrenzen**, keine externe Bestimmung absoluter Messgenauigkeit.

**Unabhängigkeitsgrenze:** Beide Transformationspfade teilen `pyproj`; der Vergleich belegt konsistente Transformation und Parameternutzung, keine vollständig unabhängige externe geodätische Referenzimplementierung.

### 2.2 PNG-Pixel und NoData/Undetect

Für ausgewählte geografische Positionen und Zoomstufen Z3–Z7 wurden echte PNG-Kacheln mit der WeatherRouter-Vorschauroutine gerendert. Ein separates Pixelorakel bestimmte für die geprüften Ausgabepixel geografische Pixelzentren, LAEA-Quellrasterindices, originalen HDF5-Rohwert, Gain/Offset-Kalibration und resultierende RGBA-Farbe. `nodata`, `undetect`, nicht endliche und negative Werte werden nicht als Niederschlag dargestellt.

Zunächst scheiterten 36 von 360 geplanten Kachelrenderings im Zoom 3 am fest implementierten Limit von 1.048.576 Quellrasterzellen pro HDF5-Fenster. Der Renderer wurde auf adaptive Ausgaberaster-Partitionierung umgestellt. **Die Begrenzung pro tatsächlichem HDF5-Lesevorgang blieb aktiv.** Danach wurden die vollständigen 360 betrachteten Renderings ohne Fehler absolviert und 3.240 Pixel ohne Abweichung verglichen.

### 2.3 Vollständiger Randpixelvergleich an Kachelnähten

Ausgewählt wurden für mehrere feste Referenzgebiete je Z3–Z7 benachbarte Kacheln in X- und Y-Richtung. Der Prüfer rendert beide Seiten und kontrolliert **alle 256 Pixel pro Seite** einer horizontalen oder vertikalen Naht; die Sollwerte stammen aus eigenständiger geografischer Abbildung und originaler HDF5-Rohwertkalibration. Die beiden Kachelrandwerte werden nicht künstlich gleichgesetzt: Sie repräsentieren unterschiedliche benachbarte Pixelzentren und dürfen sich wegen des Niederschlagsfeldes unterscheiden. Stattdessen wird jede Randseite gegen ihre **eigene korrekte Quellkoordinate** geprüft.

Realer Lauf: 180 geprüfte Nähte × 512 Kantenpixel = **92.160 Vergleiche**, **0 Fehlzuordnungen**, **0 gemeldete Sperren**.

### 2.4 Sicherheits- und Regressionstests

Testfälle prüften, dass aus Ergebnissen der reinen Geometrie keine automatische wissenschaftliche oder operative Freigabe folgt. Ein vorheriger Vertragstest prüfte ausschließlich veraltete Quelltextliterale und wurde auf AST-basierte Funktions- und Maskenprüfung korrigiert; ein zweiter Test-Fix berücksichtigte den korrekten Python-Operator `ast.Invert`. Die OPERA-Gesamtregression wurde nach diesen Korrekturen mit `passed` abgeschlossen. Kein privater CI-Workflow war dafür erforderlich oder wurde ausgelöst.

## 3. Belegte zeitliche Abfolge der Realtests

| Datum 02.11.2026 (UTC) | Phase | Belegtes Ergebnis |
|---|---|---|
| 11:18 | Wissenschaftlicher Geometrie-Audit | 9/9 Originale geometrisch PASS, anfängliche formale Gates OFFEN |
| 11:27 | Vertrags- und Regressionsnachtest | 4/4 Vertragstests, OPERA-Gesamtregression PASS |
| 11:36 | Erster realer PNG-Pixelaudit | 324 Kacheln, 2.916 Stichproben, 0 Fehlwerte, 36 erwartbare Schutzabbrüche |
| 12:02 | Adaptiver Z3-Fix real geprüft | 360 Kacheln, 3.240 Stichproben, 0 Fehlwerte, 0 Abbrüche |
| 12:16 | AST-Maskenvertrag und Regression | Preview-Tests 5/5, OPERA-Gesamtregression PASS |
| 12:20 | Normativ abgesicherte Kachelnahtprüfung | 180 Nähte, 92.160 Kantenpixel, 0 Mismatch; OPERA-Gesamtregression PASS |

**Einige zwischenzeitliche fehlgeschlagene Gesamtläufe wurden durch zu spezifische bzw. fehlerhaft formulierte Quelltext-Vertragstests verursacht.** Sie wurden nicht verschwiegen und nach korrigierter Prüfmethodik erfolgreich wiederholt. Die hier dokumentierten Endbefunde stammen aus den danach tatsächlich bestandenen lokalen Prüfungen.

## 4. Reproduzierbarkeit und veröffentlichtes Beweisniveau

Zur Reproduktion werden ein autorisierter lokaler Entwicklungsstand der genannten Module, eine Python-Umgebung mit `h5py`, `numpy`, `pyproj`, `Pillow` und die jeweiligen **rechtmäßig zugänglichen ODIM-RATE-HDF5-Originaldateien** benötigt. Der öffentliche Bericht legt weder zugriffsgeschützten Quellcode noch private Originaldaten offen. Pro Originaldatei dokumentiert die vertrauliche interne Nachweiskette eine SHA-256-Prüfsumme und einzeln gemessene Ergebnisse; die aggregierten Ergebnisse stehen oben.

**Wichtige Einschränkung:** Die Veröffentlichung der Methodik ohne Originaldateien/Prüfprotokolle erlaubt Dritten, das Testdesign zu prüfen, aber **nicht**, genau diese neun Originale ohne Zugriff unabhängig erneut auszuführen. Alle Zahlen bezeichnen beobachtete Ergebnisse und keine extern zertifizierten Messungen.

## 5. Wissenschaftliche Schlussfolgerung und operative Trennung

**Fachliche Schlussfolgerung:** Für die untersuchten ODIM-konformen OPERA-RATE-Originale ist die `north_first`-Speicherorientierung normativ belegt; die ODIM-/LAEA-Geometrie sowie die stichprobenbasierte Rasterwertwiedergabe und sämtliche Kantenpixel der ausgewählten 180 Kachelnähte wurden mit null Abweichungen geprüft. Das begründet eine **positive wissenschaftliche Georeferenzierungsbewertung für den genau beschriebenen RATE-Scope**.

**Nicht daraus abzuleiten:** automatische produktive Freigabe in Home Assistant, sofortige Aktivierung von Warnungen, abgenommene Dauerstabilität/OPERA-Provider-Verfügbarkeit, vollständige Qualitätssicherung aller europäischen Pixel oder pauschale Freigabe von DBZH/ACRR. Die tatsächliche Runtime-Statusänderung und die HA-DEV-Realabnahme erfolgen in getrennten, kontrollierten Schritten.

**Governance:** Ausschließlich öffentliche GitHub Actions im öffentlichen Repository zulässig; **niemals private GitHub Actions**. Die hier veröffentlichte Wissenschaftsdokumentation ist kein Diagnose-Export.
