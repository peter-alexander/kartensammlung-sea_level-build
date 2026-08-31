# Rasterpyramide – Aggregationsentscheidung

## Problem

Ein einzelner Pixel einer niedrigeren Zoomstufe repräsentiert mehrere
Threshold-Pixel der höchsten Berechnungsauflösung.

Ein mathematisch eindeutiger Threshold für diese größere Fläche existiert nicht:

- `min` färbt den gesamten Grobpixel, sobald irgendein Teil überflutet wird,
- `max` wartet, bis auch der höchstgeschützte Teil überflutet wird,
- Mittelwert erzeugt einen Schwellenwert, den möglicherweise keine reale Zelle besitzt,
- Median glättet die räumliche Struktur stark.

## Gewählte Methode

**Stratifiziertes Nearest-Neighbour mit Bayer-artiger 2x2-Phase.**

Bei jeder Halbierung wird aus jedem 2x2-Block genau ein existierender
Thresholdwert übernommen. Die ausgewählte Position rotiert über die Ausgabepixel:

```text
oben links     oben rechts
unten links    unten rechts
```

Dadurch:

- werden keine künstlichen Thresholdwerte erzeugt,
- gibt es keine dauerhafte Nordwest-/Südost-Abtastverzerrung,
- bleibt die Klassenverteilung statistisch sehr gut erhalten,
- bleiben scharfe Thresholdgrenzen scharf.

## Messung Phase 1A

Verglichen wurde die überflutete Gesamtfläche für:

0, 1, 2, 5, 10, 20, 50 und 100 m.

Maximaler absoluter Fehler relativ zur gesamten Phase-1A-Fläche:

| Zoom | Bayer/stratifiziert |
| ---: | ---: |
| Z10 | ca. 0,00053 % |
| Z9 | ca. 0,0040 % |
| Z8 | ca. 0,0152 % |
| Z7 | ca. 0,0128 % |
| Z6 | ca. 0,0937 % |
| Z5 | ca. 0,2143 % |
| Z4 | ca. 0,3045 % |
| Z3 | ca. 0,5761 % |

Zum Vergleich lag eine feste Nearest-Ecke auf Z6 bei ungefähr 0,30 %,
`min` bei ungefähr 2,03 % und `max` bei ungefähr 6,68 %.

## Entscheidung für Pilot

Der erste PMTiles-Pilot enthält **Z6 bis Z11**.

Unter Z6 wird zunächst nichts dargestellt. Für einen späteren globalen Datensatz
kann Z3–Z5 erneut bewertet werden; der statistische Fehler ist selbst dort noch
klein, aber die Pixel werden visuell sehr groß und benötigen eine eigene
Kartographieentscheidung.
