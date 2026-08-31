# Produktionsauflösung und DEM-Strategie

Stand: 31. August 2026

## Entscheidung in Kurzform

Für die Meeresspiegel-Simulation wird **nicht automatisch die höchste verfügbare
DEM-Auflösung verarbeitet**. Der Processing-Zoom folgt aber der tatsächlichen
Mapterhorn-Source-Auflösung.

Aktuelles Modell:

1. globale/regionale Basis ungefähr in nativer globaler DEM-Auflösung,
2. automatische Küsten-Refinements mit
   `target = max(native_source_resolution, 6 m)`,
3. zusätzliche QA-Stufe für Sources <=2 m mit
   `target = max(native_source_resolution, 3 m)`.

Für AHN5 5 m bedeutet das bei ungefähr 52° N automatisch **Z13 / ~5,9 m**.

## Warum die frühere Z12-Regel verworfen wurde

Der historische V1-Benchmark verwendete 1-m-Thresholdklassen und ließ Z12
gegenüber Z13 beinahe identisch erscheinen.

Mit V2 werden zwischen 2 und 5 m jedoch 0,25-m-Stufen gespeichert. Dadurch wird
ein zuvor verdeckter topologischer Unterschied sichtbar:

- Z11 öffnet die kritische Verbindung bei 3,5 m,
- Z12 bei 3,75 m,
- Z13 bei 4,0 m.

Bei 3,75 m weichen **44,300326 %** der Z12-Zellen gegenüber Z13 im sichtbaren
Überflutungszustand ab. Ursache ist ein Schwelleneffekt an einer hydraulisch
entscheidenden Barriere: Eine geringe Thresholdverschiebung schaltet eine große
zusammenhängende Polderfläche um.

Damit wäre es widersprüchlich, 0,25-m-Sliderstufen anzubieten, eine native
5-m-Quelle aber vorher auf ~11,8-m-Bodenpixel zu vergröbern.

## Datenquellen

### Mapterhorn

Mapterhorn bleibt die bevorzugte Aggregationsquelle:

- globale Basis ungefähr 30 m,
- zahlreiche regionale hochauflösende DTM-Quellen,
- einheitliches Terrarium-Format,
- Source-Coverage und Attribution maschinenlesbar.

Für die westlichen Niederlande meldet der reale Planner aktuell:

- Source: `nlahn5lowresfilled`,
- Actueel Hoogtebestand Nederland, AHN5 5m,
- native Auflösung: 5 m,
- CC BY 4.0,
- automatisches Ziel: 6 m,
- Processing-Zoom: Z13,
- resultierende Bodenauflösung: 5,973 m.

### Direkte nationale Quellen

Direkte nationale DTMs bleiben für Referenz- und Qualitätsvergleiche relevant.
Sie sind aber nicht erforderlich, solange Mapterhorn die benötigte Source in
geeigneter Auflösung aggregiert bereitstellt.

## V2-Auflösungsbenchmark

### Gebiet

Hoek van Holland / Rotterdam / Westland / Delft / südliches Den Haag.

Die Bounding Box ist für Z11, Z12 und Z13 exakt hierarchisch ausgerichtet.

### Rastergrößen

| Stufe | Bodenauflösung ungefähr | Zellen |
| ---: | ---: | ---: |
| Z11 | 23,531 m | 3.145.728 |
| Z12 | 11,765 m | 12.582.912 |
| Z13 | 5,883 m | 50.331.648 |

Z13 liegt damit ungefähr in der Größenordnung der nativen AHN5-5-m-Quelle.

### Punktwerte

Alle sechs Stichpunkte liefern:

| Processing | Threshold |
| ---: | ---: |
| Z11 | 3,5 m |
| Z12 | 3,75 m |
| Z13 | 4,0 m |

### Sliderzustand gegenüber Z13

Die wichtigste Metrik prüft für jede der 58 V2-Stufen direkt:

`(coarse_threshold <= slider) != (z13_threshold <= slider)`

Maxima:

- Z11 vs. Z13: **48,466078 % bei 3,5 m**,
- Z12 vs. Z13: **44,300326 % bei 3,75 m**.

Ausgewählte Z12-Werte:

| Pegel | unterschiedliche Zellen |
| ---: | ---: |
| 0 m | 0,031813 % |
| 0,5 m | 0,028348 % |
| 1 m | 0,025662 % |
| 1,7 m | 0,332133 % |
| 2 m | 0,047437 % |
| 2,5 m | 0,052174 % |
| 3 m | 0,075889 % |
| 3,25 m | 4,398163 % |
| 3,5 m | 4,414606 % |
| **3,75 m** | **44,300326 %** |
| 4 m | 0,222421 % |
| 5 m | 0,613157 % |
| 10 m | 0,093357 % |
| 20 m | 0,013733 % |
| 70 m | 0 % |

### Thresholdwerte zellweise

Z11 gegen Z13:

- mittlere absolute Differenz: 0,348 m,
- Median: 0,5 m,
- >1 m: 4,7317 %,
- >2 m: 0,1774 %.

Z12 gegen Z13:

- mittlere absolute Differenz: 0,1551 m,
- Median: 0,25 m,
- >1 m: 0,1731 %,
- >2 m: 0,0295 %.

Die kleine mittlere Z12-Differenz zeigt, warum eine reine RMSE-/MAE-Betrachtung
hier nicht genügt: Eine einzelne topologisch kritische Barriere kann trotz
kleiner lokaler Höhenabweichung eine sehr große Fläche umschalten.

## Rechenkosten des Benchmarks

| Stufe | DEM Peak-RAM | Flood Peak-RAM | Flood-Zeit |
| ---: | ---: | ---: | ---: |
| Z11 | ~78 MiB | ~36 MiB | 0,13 s |
| Z12 | ~116 MiB | ~130 MiB | 0,45 s |
| Z13 | ~260 MiB | ~452 MiB | 1,66 s |

Der Priority-Flood-Kern selbst bleibt effizient. Für große Regionen sind vor
allem Zellzahl, DEM-Download/I/O und Zwischenraster die Skalierungsfaktoren.

## Produktionsregeln

### Tier 1 – Base

Globale ~30-m-Quelle.

Zielbereich:

**ungefähr 25–40 m Bodenpixel**

Der Zoom wird aus Zielauflösung und Breitenlage berechnet.

### Tier 2 – automatisch

Für Sources mit nativer Auflösung <=10 m:

`target_ground_resolution = max(native_source_resolution, 6 m)`

Beispiele bei 52° N:

- 10-m-Source → Z12 / ~11,8 m,
- 5-m-Source → Z13 / ~5,9 m,
- 1-m-Source → ebenfalls Z13 / ~5,9 m.

Damit nutzt die Pipeline gute Daten, ohne 0,5–1-m-Sources automatisch in
entsprechend extreme Arbeitsraster zu übernehmen.

### Tier 3 – QA

Für Sources <=2 m:

`target_ground_resolution = max(native_source_resolution, 3 m)`

Bei 52° N liegt das typischerweise bei Z14 / ~2,9 m.

Tier 3 bleibt eine QA-/Sonderstufe. Sie wird nur verwendet, wenn ein regionaler
Vergleich nachweist, dass die automatische ~6-m-Stufe schmale hydraulische
Strukturen relevant verliert.

## Hierarchische Refinements

Die Parent-Boundary-Pipeline bleibt unverändert grundsätzlich gültig:

`fine_boundary_threshold = coarse_global_threshold`

Ein Fine-Refinement darf damit auch ohne eigenen direkten Meerzugang seine
Konnektivität aus dem gröberen Parent erben.

Die bestehende Phase-1C-Pipeline hat dieses Prinzip bereits erfolgreich für
Z11→Z12 nachgewiesen.

## Konsequenz für Collar und Halo

Mit source-abhängigen Zooms dürfen Transition Collar und Priority-Flood-Halo
nicht mehr ausschließlich als konstante Fine-Pixel bzw. Fine-Tiles verstanden
werden.

Historisch:

- Transition Collar: 128 Pixel bei Z12,
- Halo: 1 Tile = 512 Pixel bei Z12.

Bei Z13 wären dieselben Zahlen physisch nur halb so breit.

Bevor der westliche Niederlande-Composite auf Z13 neu gerechnet wird, werden
diese Parameter deshalb so umgestellt, dass die getestete physische Breite
erhalten bleibt. Erst danach ist ein Z12-vs.-Z13-Compositevergleich fair.

## Auswirkungen auf größere Regionen

Die endgültige Pipeline soll nicht „Land X = Zoom Y“ verwenden.

Stattdessen:

`Mapterhorn Coverage → Source-Auflösung → Ziel-Bodenauflösung → Processing-Zoom`

Benachbarte Sources ähnlicher Qualitätsklasse können anschließend zu
zusammenhängenden Refinement-Flächen vereinigt werden, um unnötigen
Grenzflickenteppich zu vermeiden.

## Nächste Schritte

1. Collar/Halo zoomunabhängig bzw. physisch definieren.
2. Westliche Niederlande mit Planner-Z13 neu rechnen.
3. V2-Seam-QA und visuellen Vergleich Z12↔Z13 durchführen.
4. Danach die Source-basierte Regel auf eine größere Nordsee-/Europa-Region
   anwenden.
