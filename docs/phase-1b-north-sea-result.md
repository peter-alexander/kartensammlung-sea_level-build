# Phase 1B – Nordsee-Skalierungstest

Build: 31. August 2026

## Ziel

Phase 1B testet die bereits in Phase 1A bestätigte Architektur auf einem deutlich
größeren, zusammenhängenden Nordsee-Gebiet.

Der Schwerpunkt liegt auf Skalierung und länderübergreifender Connectivity, nicht
auf höherer räumlicher Qualität.

## Gebiet

- West: -2,5° E
- Süd: 49,5° N
- Ost: 13,0° E
- Nord: 58,0° N

Enthalten sind unter anderem:

- südliches und östliches England,
- Ärmelkanal und südliche Nordsee,
- Belgien,
- Niederlande,
- Nordwestdeutschland,
- Dänemark,
- westlicher Ostseezugang.

## Processing-Raster

Phase 1B verwendet bewusst Web-Mercator-Zoom 10 statt Z11.

Grund:

Der gleiche Ausschnitt hätte auf Z11 fast zwei Milliarden Rasterzellen und wäre
für einen normalen GitHub-Runner unnötig groß.

Gemessen:

- Tilebereich: X 504–548, Y 308–349
- 45 × 42 = 1.890 mögliche Z10-Tiles
- Raster: 23.040 × 21.504
- Zellen: **495.452.160**
- Web-Mercator-Pixel: 76,437 m
- ungefähre Bodenauflösung bei 53,75° N: **45,2 m**

Phase 1B ist damit gröber als Phase 1A (~23 m) und soll nicht als
Qualitätssteigerung interpretiert werden.

## Mapterhorn

PMTiles-Dry-Run:

- Region tiles: 2.570
- result tile entries: 1.707
- Transfer: **438 MB**
- 95 HTTP Requests

XYZ-Aufbereitung des Vollbuilds:

- 1.890 mögliche Tiles
- 311 fehlende Tiles
- fehlende DEM-Pixel: 81.526.784
- davon laut OSM-Ocean-Maske im Meer: 81.526.784
- fehlende DEM-Pixel an Land: **0**

DEM-Rohdatei:

**1.981.808.640 Bytes**

DEM-Aufbereitung:

- ca. 30,5 s
- Peak RSS: ca. 1,92 GiB

## OSM Ocean

Ocean-Seed-Zellen:

**254.717.739**

Ocean-Polygon-Ausschnitt:

- ca. 5,1 s
- Peak RSS: ca. 136 MiB

Rasterisierung auf 23.040 × 21.504:

- ca. 16,7 s
- Peak RSS: ca. 1,03 GiB

## Priority Flood

Parameter:

- 4er-Nachbarschaft
- 0–100 m
- 1-m-Quantisierung
- Sentinel 101

Ergebnis:

- Gesamtzellen: 495.452.160
- Ocean-Seeds: 254.717.739
- tatsächlich durch Buckets verarbeitet: 399.058.575
- Sentinel-Zellen: 96.393.585
- davon nach Abschneiden an >100-m-Barrieren nicht mehr besucht: 95.128.462

Der Sentinel bedeutet nicht automatisch einen Fehler oder eine Senke. Er umfasst:

1. Gelände über +100 m,
2. Zellen hinter einer Barriere über +100 m,
3. innerhalb des Modellbereichs nicht vom Meer erreichbare Bereiche.

Performance auf GitHub `ubuntu-latest`:

- Wall clock: **9,69 s**
- Peak RSS: **3.956.780 kB** (~3,77 GiB)
- Swap: 0

Der Runner hatte 15 GiB RAM und 3 GiB Swap.

Damit ist der Flood-Kern auch bei ungefähr einer halben Milliarde Zellen noch
komfortabel runner-tauglich.

## Bathtub vs. Connectivity

Gelände unterhalb des jeweiligen Meeresspiegels, das trotzdem noch nicht
meerverbunden ist:

| Meeresspiegel | nicht verbundene Fläche |
| ---: | ---: |
| 0 m | ca. 14.786 km² |
| +1 m | ca. 8.375 km² |
| +2 m | ca. 5.425 km² |
| +5 m | ca. 1.454 km² |
| +10 m | ca. 1.105 km² |
| +20 m | ca. 988 km² |
| +50 m | ca. 1.239 km² |
| +100 m | ca. 354 km² |

Der nicht monotone Verlauf ist möglich: Mit steigendem Pegel werden zusätzliche
niedrige Zellen Teil des Bathtub-Vergleichs, obwohl sie noch hinter höheren
Barrieren liegen.

Die bei +100 m verbleibenden rund 354 km² entsprechen nur einem sehr kleinen Teil
des gesamten Pilotgebiets. Stichproben an zahlreichen Städten zeigen keine
flächige Randabschneidung.

## Stichproben

Quantisierte Schwellenwerte im Phase-1B-Raster:

- Rotterdam: 1 m
- Amsterdam: 2 m
- London: 7 m
- Antwerpen: 8 m
- Gent: 9 m
- Hamburg: 11 m
- Bremen: 9 m
- Kopenhagen: 7 m
- Aalborg: 3 m
- Hull: 4 m
- Cambridge: 9 m
- Köln: 47 m
- Hannover: 56 m
- Dortmund: 87 m

Höher liegende Städte wie Birmingham oder Luxemburg liegen erwartungsgemäß
außerhalb des 0–100-m-Modellbereichs und erhalten Sentinel 101.

## QA

QA-Schritt:

- ca. 15,5 s
- Peak RSS: ca. **5,15 GiB**

Damit war nicht der C++-Flood, sondern die Python-QA der speicherintensivste
Rechenschritt des Builds.

Für noch größere Builds sollte die QA deshalb vor dem Flood-Kern optimiert bzw.
chunkweise ausgeführt werden.

## Rasterpyramide

Methode:

`stratified-nearest-bayer-2x2`

Pyramide:

- Z10: 1.701 Tiles
- Z9: 446 Tiles
- Z8: 123 Tiles
- Z7: 35 Tiles
- Z6: 12 Tiles
- Z5: 6 Tiles
- gesamt: **2.323 Tiles**

Laufzeit:

- ca. **6 min 9 s**
- Peak RSS: ca. 989 MiB

Damit ist die PNG-Erzeugung deutlich langsamer als Flood und QA zusammen und nun
der größte CPU-/Zeitblock der Pipeline.

### Flächenfehler der Übersichtsstufen

Maximaler absoluter Fehler über die QA-Pegel 0, 1, 2, 5, 10, 20, 50 und 100 m:

- Z9: ca. 0,00058 %
- Z8: ca. 0,00170 %
- Z7: ca. 0,00244 %
- Z6: ca. 0,01331 %
- Z5: ca. **0,02627 %**

Damit funktioniert die stratifizierte Nearest-Neighbour-Pyramide auch im wesentlich
größeren Gebiet sehr gut.

## PMTiles

Verifiziertes PMTiles:

- Dateigröße: **65.012.585 Bytes**
- Tile-Typ: PNG
- Minzoom: 5
- Maxzoom: 10
- Bounds: -2,5 / 49,5 / 13,0 / 58,0
- `pmtiles verify`: erfolgreich

Veröffentlichung:

`output/phase1b/sea-level-threshold.pmtiles`

Publish-Commit:

`a9141b3ae42d41b5e7ad6225efe89a5d3d64731c`

Die Kartensammlung verweist für den visuellen Test auf genau diesen Commit.

## Fazit

Phase 1B bestätigt:

1. Priority Flood skaliert auf ~500 Mio. Zellen sehr gut.
2. RAM ist auf einem normalen GitHub-Runner noch komfortabel.
3. OSM-Ocean und Mapterhorn passen auch über mehrere Länder sauber zusammen.
4. Die Rasterpyramide bleibt statistisch sehr genau.
5. PMTiles bleibt mit ~65 MB überraschend kompakt.
6. Die Pipeline ist grundsätzlich bereit für größere Gebiete.

Der aktuelle Flaschenhals ist nicht mehr Priority Flood, sondern PNG-
Rasterpyramidenerzeugung und in zweiter Linie die Python-QA.

## Nächste Entscheidung nach visueller Prüfung

Wenn die Karte über Nordsee/England/Belgien/Niederlande/Deutschland/Dänemark
plausibel aussieht, sind zwei Richtungen sinnvoll:

1. **räumlich weiter skalieren** Richtung Westeuropa/Europa,
2. vor der weiteren Skalierung zuerst die **Produktionsauflösung und DEM-Basis**
   festlegen.

Phase 1B selbst ist ausdrücklich ein Z10-Skalierungstest und noch kein endgültiger
europäischer Produktionsdatensatz.
