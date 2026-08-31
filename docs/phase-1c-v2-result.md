# Phase 1C V2 – westliche Niederlande

Stand: 31. August 2026

## Zweck

Dieser Lauf validiert das neue nichtlineare V2-Thresholdschema im vollständigen
hierarchischen Produktionspfad:

`Mapterhorn Coverage → Z11 Base → AHN5 Z12 + Collar + Halo → Parent-Boundary → Fine Priority Flood → Composite → Z6–Z12-Pyramide → PMTiles`

Der historische V1-Lauf bleibt separat unter `output/phase1c/` erhalten.

## Thresholdschema

V2 verwendet dieselben diskreten Stufen im Datensatz und im Slider:

- 0–2 m: 0,1 m,
- >2–5 m: 0,25 m,
- >5–20 m: 1 m,
- >20–70 m: 5 m.

Insgesamt werden 58 reguläre Klassen als `uint8`-Indizes gespeichert.
Klasse 58 ist der Sentinel für Thresholds >70 m bzw. außerhalb des
Modellbereichs. Beim Terrarium-Export werden die Klassen wieder in reale
Meterwerte übersetzt.

Wichtig: Die numerische Klassenauflösung beschreibt nicht die tatsächliche
vertikale Genauigkeit der jeweiligen DEM-Quelle.

## Build

- Source-Run: GitHub Actions `33441239895`
- Source-Commit: `9156444474534d8d559e4b4637d1dd302afac3e2`
- Gebiet: `[2.5, 51.2, 5.5, 53.2]`
- Base: Z11
- Refinement: Z12
- Refinement-Source: `nlahn5lowresfilled` / AHN5 5 m
- Transition Collar: 128 Fine-Pixel
- Priority-Flood-Halo: 1 Tile
- Konnektivität: 4er-Nachbarschaft

## PMTiles

- Datei: `output/phase1c-v2/sea-level-threshold.pmtiles`
- Minzoom: 6
- Maxzoom: 12
- Größe: **15.125.875 Bytes**
- SHA256: `e9c6f7d2cb5b9a75981ea6b5f210532dd237fff89c99a3a85e51411e3e1e6e34`
- `go-pmtiles verify`: erfolgreich

Zum Vergleich: Das historische V1-PMTiles hat 10.799.960 Bytes. Die höhere
V2-Dateigröße ist erwartbar, weil vor allem im niedrigen Pegelbereich deutlich
mehr unterschiedliche Thresholdwerte vorkommen.

## Warum eine neue Seam-QA nötig ist

Bei V1 entsprach eine Klassenstufe überall 1 m. Unter V2 reicht die Stufenweite
von 0,1 m bis 5 m. Eine reine Differenz in Metern kann deshalb die visuelle
Bedeutung einer Base/Fine-Abweichung verzerren.

Die neue Metrik prüft für jede Sliderstufe direkt:

`(fine_threshold <= slider) != (base_threshold <= slider)`

Ein Pixel zählt damit nur dann als abweichend, wenn Base und Fine bei genau
dieser Sliderstellung tatsächlich unterschiedlich dargestellt würden.

## Echte Refinement-Seam

Geprüfte Randpixel: **76.588**

| Bereich | max. unterschiedliche Pixel | Anteil | bei Pegel |
| --- | ---: | ---: | ---: |
| 0–2 m | 4 | **0,005223 %** | 0,2 m |
| >2–5 m | 538 | **0,702460 %** | 4,75 m |
| >5–20 m | 69 | **0,090092 %** | 17 m |
| >20–70 m | 63 | **0,082258 %** | 30 m |

Ausgewählte Sliderstufen:

| Pegel | unterschiedliche Pixel | Anteil |
| ---: | ---: | ---: |
| 0 m | 3 | 0,003917 % |
| 0,1 m | 3 | 0,003917 % |
| 0,5 m | 2 | 0,002611 % |
| 1 m | 3 | 0,003917 % |
| 1,5 m | 3 | 0,003917 % |
| 2 m | 1 | 0,001306 % |
| 2,25 m | 2 | 0,002611 % |
| 3 m | 0 | 0 % |
| 4 m | 10 | 0,013057 % |
| 5 m | 455 | 0,594088 % |
| 10 m | 42 | 0,054839 % |
| 20 m | 20 | 0,026114 % |
| 25 m | 22 | 0,028725 % |
| 50 m | 4 | 0,005223 % |
| 70 m | 0 | 0 % |

Damit ist insbesondere der fachlich wichtigste Bereich bis 2 m an der echten
Source-Seam praktisch nahtlos. Der lokale Peak bei 4,75–5 m wird beim visuellen
Test gezielt kontrolliert.

## Klassische Meterdifferenz als Sekundärmetrik

Die V2-Seam hat:

- 97,848227 % exakt gleiche Thresholdklassen,
- mittlere absolute Thresholddifferenz 0,027970 m,
- maximale Differenz 6 m.

Der 6-m-Ausreißer liegt bei Fine 25 m gegenüber Base 19 m. Wegen der 5-m-Stufen
oberhalb 20 m ist diese Zahl nicht direkt mit dem früheren V1-Maximum von 4 m
vergleichbar. Für die sichtbare Naht ist daher die Slider-Zustandsmetrik
maßgeblich.

## Ergebnis

Das nichtlineare V2-Schema funktioniert end-to-end durch:

- Priority Flood,
- Parent-Boundary-Vererbung,
- AHN5-Refinement,
- Composite,
- Rasterpyramide,
- Terrarium-Encoding,
- PMTiles.

Der nächste fachliche Schritt ist der visuelle Test dieses V2-Datensatzes in der
Kartensammlung. Danach wird der Z11/Z12/Z13-Auflösungsbenchmark unter V2
wiederholt, bevor die Coverage-abhängige Processing-Zoom-Regel finalisiert wird.
