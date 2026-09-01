# Source-Resolution-Benchmark V2

Stand: 1. September 2026

## Fragestellung

Welche Processing-Auflösung nutzt die vorhandene DEM-Source, ohne sie bereits
bei der Rasterfestlegung zu unterabtasten?

Die technische Skalierung wird separat gelöst.

## Testgebiet

Hoek van Holland / Rotterdam / Westland / Delft / südliches Den Haag.

Bounds:

[3.8671875, 51.83577752045249, 4.5703125, 52.16045455774704]

## Z13 gegen Z14

AHN5 hat 5 m native Source-Auflösung.

Bei ungefähr 52 Grad Nord:

- Z13: ~5,883 m Bodenpixel,
- Z14: ~2,941 m Bodenpixel.

Z13 ist damit knapp gröber als die Source; Z14 ist die erste Stufe, deren
Bodenpixel nicht gröber als 5 m sind.

### Ergebnis

| Kennzahl | Z13 | Z14 |
| --- | ---: | ---: |
| Raster | 6.144 x 8.192 | 12.288 x 16.384 |
| Zellen | 50.331.648 | 201.326.592 |
| Bodenpixel | ~5,883 m | ~2,941 m |
| Flood-Zeit | ~1,01 s | ~4,24 s |
| Flood Peak-RSS | ~282 MB | ~1.118 MB |

Sample-Thresholds:

| Ort | Z13 | Z14 |
| --- | ---: | ---: |
| Hoek van Holland | 4,0 m | 3,75 m |
| Maassluis | 4,0 m | 4,0 m |
| Rotterdam Zentrum | 4,0 m | 3,75 m |
| Westland-Polder | 4,0 m | 3,75 m |
| Delft | 4,0 m | 3,75 m |
| Den Haag Süd | 4,0 m | 3,75 m |

Maximum der Sliderzustandsabweichung:

**44,268125 % bei 3,75 m**

Die mittlere absolute Thresholddifferenz beträgt nur 0,1242 m. Der große
Sliderzustandsunterschied entsteht daher durch einen topologischen
Schwelleneffekt.

## Z15-Probe

Auf Z15 wurden für dieselbe Fläche 3.072 Tiles angefordert. Alle 3.072 Requests
lieferten am getesteten ZXY-Endpunkt 404.

Z14 war dagegen vollständig vorhanden.

Der Z14-Z15-Floodvergleich konnte deshalb nicht ausgeführt werden. Der Befund
wird nicht zu einem allgemeinen Mapterhorn-Maxzoom verallgemeinert.

## Source-Fidelity-Regel

Planner-Schema V4 berechnet zusätzlich den Source-Fidelity-Zoom:

kleinster Zoom, dessen lokale Bodenpixelgröße kleiner oder gleich der nativen
Source-Auflösung ist.

Dafür wird auf die feinere Zoomstufe aufgerundet und nicht der nächstliegende
Zoom gewählt.

AHN5 5 m bei ungefähr 52 Grad Nord:

- Z13 ~5,88 m > 5 m: unterabgetastet,
- Z14 ~2,94 m <= 5 m: Source-Fidelity.

## Candidate-Maske

Parallel wurde die exakte 70-m-Candidate-Maske getestet.

Sie markiert alle Zellen, die über Gelände bis höchstens 70 m mit einem
Sea-Seed verbunden sind.

Candidate-Anteil:

- Z13: 100 %,
- Z14: 100 %.

Für die Niederlande ist das der erwartete Worst Case. Für reliefreiche
Küstengebiete ist dagegen ein großer Pruning-Gewinn zu erwarten und als
nächster Benchmark vorgesehen.

## Schlussfolgerung

- Z13 bleibt als Uniform-Domain-Architekturtest wertvoll.
- Z13 ist für AHN5 nicht mehr das fachliche Auflösungsziel.
- Z14 ist die Source-Fidelity-Stufe für die aktuelle 5-m-Source bei ~52 Grad Nord.
- Die Produktionsautomatik wird erst nach Lösung der Z14-Skalierung umgestellt.
