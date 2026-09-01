# Produktionsauflösung und DEM-Strategie

Stand: 1. September 2026

## Grundentscheidung

Fachliche Auflösung und technische Skalierung werden getrennt behandelt.

Eine DEM-Source soll mindestens auf einer Processing-Auflösung gerechnet werden,
deren Bodenpixel nicht gröber als die native Source-Auflösung sind. RAM- oder
Disk-Grenzen sollen nicht dadurch gelöst werden, gute Quellen künstlich gröber
zu rechnen.

Der Coverage Planner unterscheidet deshalb ab Schema V4:

- die derzeit ausführbare Empfehlung,
- den Source-Fidelity-Zoom.

Der Source-Fidelity-Zoom ist die erste Web-Mercator-Stufe, deren Bodenpixel
kleiner oder gleich der nativen Source-Auflösung sind.

Für AHN5 5 m bei ungefähr 52 Grad Nord gilt:

- Z13: etwa 5,883 m Bodenpixel, knapp zu grob,
- Z14: etwa 2,941 m Bodenpixel, Source-Fidelity.

Der veröffentlichte uniforme Z13-Pilot bleibt als Architektur- und QA-Nachweis
erhalten, ist aber nicht mehr die finale Auflösungsentscheidung.

## Z12 gegen Z13

Der frühere V2-Benchmark zeigte bei 3,75 m eine maximale
Sliderzustandsabweichung von 44,300326 %. Damit wurde Z12 für AHN5 verworfen.

## Z13 gegen Z14

Gleiche Hoek-/Rotterdam-Bounding-Box, gleiches V2-Schema, gleiche Ocean-Maske
und 4er-Nachbarschaft:

| Stufe | Raster | Zellen | Bodenpixel |
| ---: | ---: | ---: | ---: |
| Z13 | 6.144 x 8.192 | 50.331.648 | ~5,883 m |
| Z14 | 12.288 x 16.384 | 201.326.592 | ~2,941 m |

Sample-Thresholds:

| Ort | Z13 | Z14 |
| --- | ---: | ---: |
| Hoek van Holland | 4,0 m | 3,75 m |
| Maassluis | 4,0 m | 4,0 m |
| Rotterdam Zentrum | 4,0 m | 3,75 m |
| Westland-Polder | 4,0 m | 3,75 m |
| Delft | 4,0 m | 3,75 m |
| Den Haag Süd | 4,0 m | 3,75 m |

Vergleich:

- mittlere absolute Thresholddifferenz: 0,1242 m,
- Median: 0 m,
- >1 m Unterschied: 0,0316 %,
- >2 m: 0,0114 %,
- >5 m: 0,0001 %,
- maximale Sliderzustandsabweichung:
  **44,268125 % bei 3,75 m**.

Der große Flächeneffekt entsteht trotz kleiner mittlerer Differenz durch eine
kritische topologische Verbindung.

Bei 3,75 m sind überflutet:

- Z13: 46,0778574 %,
- Z14: 90,1996230 %.

Z13 ist damit für AHN5 nicht als konvergiert nachgewiesen.

## Z15-Kontrollversuch

Für dieselbe Bounding Box wurden 3.072 Z15-Tiles angefordert. Der getestete
Mapterhorn-ZXY-Endpunkt lieferte für alle 3.072 Tiles 404. Der Versuch wurde vor
dem Flood abgebrochen, weil fehlendes DEM auch auf Land lag.

Z14 war im vorherigen Lauf vollständig vorhanden.

Der Befund gilt nur für diesen Endpoint, dieses Testgebiet und diesen Zeitpunkt.
Er beweist keinen allgemeinen Maxzoom für alle Mapterhorn- oder
Niederlande-Sources.

Für die aktuell getestete AHN5-Pipeline ist Z14 jedoch sowohl die
Source-Fidelity-Stufe als auch die feinste erfolgreich getestete direkt
verfügbare Stufe.

## Rechenkosten Z13 gegen Z14

| Stufe | DEM Peak-RSS | Candidate Peak-RSS | Flood Peak-RSS | Flood-Zeit |
| ---: | ---: | ---: | ---: | ---: |
| Z13 | ~269 MB | ~21 MB | ~282 MB | ~1,01 s |
| Z14 | ~859 MB | ~58 MB | ~1.118 MB | ~4,24 s |

Die vierfache Zellzahl pro Zoomstufe ist deutlich sichtbar. Der eigentliche
Priority-Flood-Kern bleibt auf der Benchmarkfläche sehr schnell.

## Exakter 70-m-Candidate-Pass

Vor dem 58-Klassen-Solver kann eine exakte binäre Connectivity berechnet werden:

Meer -> zusammenhängende Zellen mit Höhe kleiner oder gleich 70 m.

Nur diese Zellen können in unserem V2-Schema jemals eine reguläre Klasse
0-70 m erhalten.

Der neue Candidate-Pass arbeitet bitgepackt und ist als
src/candidate_mask_70.cpp implementiert.

Auf der niederländischen Benchmarkfläche:

- Z13 Candidate-Anteil: 100 %,
- Z14 Candidate-Anteil: 100 %.

Das ist der erwartete Lowland-Worst-Case. Der Pass spart dort keine Solverzellen,
ist aber sehr billig:

- Z13 ungefähr 0,39 s / 21 MB Peak-RSS,
- Z14 ungefähr 1,47 s / 58 MB Peak-RSS.

In reliefreichen Küstenregionen soll derselbe Pass Gebirge und abgeschlossene
Hochlandbereiche entfernen.

## Konservativer grober Vorfilter

Ein normal heruntergerechnetes DEM ist als Ausschlussmaske nicht sicher.
Mittelwert oder Interpolation könnte einen schmalen realen Korridor unter 70 m
nach oben glätten.

Ein sicherer grober Filter muss konservativ sein:

- Grobzellenhöhe = Minimum aller feinen Kindzellen,
- grobe Sea-Maske = logisches OR aller Kindzellen.

Damit sind False Positives erlaubt, aber keine False Negatives gegenüber dem
feinen 70-m-Korridor.

Zielpipeline:

konservative Min-Pyramide -> grobe Candidate-Maske ->
exakte Highres-Candidate-Maske -> V2-Priority-Flood.

## Skalierung bei hohem Candidate-Anteil

Die Niederlande zeigen den zweiten notwendigen Fall: Bei nahezu 100 %
Candidate-Anteil hilft räumliches Pruning nicht.

Ein kompletter westlicher-Niederlande-Z14-Domain hätte ungefähr viermal so viele
Zellen wie der validierte Z13-Lauf und überschreitet die aktuelle monolithische
32-Bit-Zellindexgrenze des Solverkerns.

Dafür soll die Domain-Zerlegung iterativ werden:

1. gemeinsames hochauflösendes Graphmodell in Domains teilen,
2. Randthresholds zwischen Nachbardomains austauschen,
3. verbesserte Randwerte monoton weiterreichen,
4. Domains erneut lösen, solange sich Randthresholds verbessern,
5. erst nach Konvergenz die Ausgabe zusammensetzen.

Anders als beim alten einmaligen Threshold-Merge sollen Domain-Grenzen nach
Konvergenz keine fachliche Naht erzeugen.

## Aktueller Planner-Übergang

Bis die Z14-Skalierung fertig ist, wird der bestehende Produktionspfad nicht
automatisch auf Source-Fidelity umgestellt.

Bei ungefähr 52 Grad Nord:

| native Source | derzeit ausführbar | Source-Fidelity |
| ---: | ---: | ---: |
| 10 m | Z12 | Z13 |
| 5 m | Z13 | Z14 |
| 2 m | Z14 QA | Z15 |
| 1 m | Z13 / Z14 QA | Z16 |
| 0,5 m | Z13 / Z14 QA | Z17 |
| 0,25 m | Z13 / Z14 QA | Z18 |

Die linke Spalte ist ein technischer Übergangszustand, nicht das fachliche Ziel.

## Nächste Schritte

1. Candidate-Pruning in einer reliefreichen Küstenregion messen.
2. konservative Min-Elevation-Pyramide implementieren und gegen die exakte
   Candidate-Maske auf False Negatives testen.
3. kompakten Candidate-Solver für niedrige Candidate-Anteile prototypisieren.
4. iterativen Domain-Solver für Lowland-Worst-Cases prototypisieren.
5. erst danach den kompletten westlichen Niederlande-Pilot auf Z14 bauen.
