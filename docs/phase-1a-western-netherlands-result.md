# Phase 1A – Ergebnis des ersten Vollbuilds

Build: 31. August 2026

## Status

Der vollständige Pilot für die westlichen Niederlande wurde erfolgreich gerechnet:

```text
Mapterhorn Z11
	+
OSM Water Polygons
	↓
89.653.248-Zellen-Grid
	↓
quantisierter C++ Priority Flood
	↓
threshold.u8
	↓
QA GeoTIFF + Statistik
```

Der Build wurde bewusst noch nicht als Karten-Produkt deployed.

## Eingaberaster

- Tilebereich: Z11 / X 1038–1055 / Y 665–683
- Raster: 9216 × 9728
- Zellen: 89.653.248
- ungefähre Bodenauflösung am Rastermittelpunkt: 23,417 m

### Mapterhorn

- 342 mögliche XYZ-Tiles im vollständigen Rasterrechteck
- 22 fehlende Tiles
- 5.767.168 fehlende DEM-Pixel
- davon laut OSM-Ocean-Maske im Meer: 5.767.168
- fehlende DEM-Pixel an Land: **0**

Damit können fehlende Mapterhorn-Tiles im Pilotgebiet sauber als offene Meeresfläche
interpretiert werden; es gibt keine erkannte DEM-Lücke auf Land.

### OSM Ocean

Ocean-Seed-Zellen:

**51.094.620**

Die Maske wurde aus den OSM Water Polygons in EPSG:3857 ausgeschnitten und exakt
auf das Mapterhorn-Raster rasterisiert.

## Priority-Flood-Performance

Implementierung:

`src/priority_flood_quantized.cpp`

Parameter:

- 4er-Nachbarschaft
- Threshold 0–100 m
- Schrittweite 1 m
- Sentinel 101

Gemessen auf GitHub `ubuntu-latest`:

- verarbeitete Zellen: 89.653.248
- Wall clock: **1,40 s**
- User CPU: 1,13 s
- System CPU: 0,26 s
- Max RSS: **792.076 kB** (~774 MiB)
- Swaps: 0
- nicht erreichbare Zellen: 0
- Sentinel-Zellen: 0

Der Flood-Kern selbst ist damit für deutlich größere Pilotgebiete nicht der
Flaschenhals. Download, DEM-Aufbereitung und Küstenpolygon-Verarbeitung dominieren
den Gesamtbuild.

## Threshold-Verteilung

Besonders große Klassen:

- 0 m: 51.664.331 Zellen
- 1 m: 218.806
- 2 m: 17.982.201
- 3 m: 3.571.027
- 4 m: 1.503.331
- 5 m: 3.236.986
- 6 m: 1.153.393
- 7 m: 1.187.403
- 8 m: 715.509
- 9 m: 632.077
- 10 m: 548.464

Der höchste im Pilot tatsächlich benötigte Threshold ist 86 m. Keine Zelle benötigt
den >100-m-Sentinel.

Die sehr große 2-m-Klasse ist fachlich plausibel als Folge der 1-m-Quantisierung:
große niedrig liegende Gebiete werden erstmals bei Slider +2 m vom Meer aus
erreichbar.

## Bathtub vs. Connectivity

Gelände unterhalb des jeweiligen Meeresspiegels, das nach der Connectivity-Analyse
noch nicht mit dem Meer verbunden ist:

| Meeresspiegel | geschützte/nicht verbundene Fläche |
| ---: | ---: |
| 0 m | ca. 8.322,84 km² |
| +1 m | ca. 10.765,30 km² |
| +2 m | ca. 2.003,30 km² |
| +5 m | ca. 257,38 km² |
| +10 m | ca. 54,03 km² |
| +20 m | ca. 11,99 km² |
| +50 m | ca. 0,85 km² |
| +100 m | 0 km² |

Der starke Sprung zwischen +1 m und +2 m ist ein wichtiger QA-Punkt für die
Kartendarstellung und sollte visuell geprüft werden.

## Stichproben

Quantisierte Schwellenwerte an ausgewählten Punkten:

- Rotterdam: 2 m
- Den Haag: 2 m
- Amsterdam: 2 m
- Schiphol: 2 m
- Almere: 2 m
- Lelystad: 2 m
- Gouda: 2 m
- Kinderdijk: 2 m
- Middelburg: 5 m
- Hoek van Holland: 7 m

### Vergleich mit dem früheren Z12-Test

Für Hoek van Holland liefert der exakte hochauflösendere Z12-Test am selben Punkt:

**6,1328125 m**

Der neue 1-m-Produktionsdatensatz liefert:

**7 m**

Das ist exakt die vorgesehene Quantisierung auf den ersten sichtbaren Sliderwert.

## Ausgabegrößen

- `threshold.u8`: ca. 86 MiB unkomprimiert
- `ocean_mask.tif`: ca. 168 KiB komprimiert
- `threshold.tif`: ca. **2,3 MiB** komprimiert

Die starke Kompression des Threshold-GeoTIFFs bestätigt die Erwartung, dass die
quantisierten Klassen sich sehr gut komprimieren.

Das ist ein starkes Signal dafür, dass auch ein PMTiles-Ausgabedatensatz wesentlich
kleiner werden dürfte als die unkomprimierten Rasterzahlen vermuten lassen.

## Nächster Schritt

Aus dem erfolgreichen Phase-1A-Threshold wird jetzt eine echte Raster-Pyramide
erzeugt und als PMTiles verpackt.

Dabei werden gezielt getestet:

1. sinnvolle Downsampling-Regel für niedrigere Zooms,
2. PNG-/Terrarium-Kompression,
3. PMTiles-Dateigröße,
4. Darstellung bei Z5–Z12,
5. Verhalten des markanten +1 → +2-m-Sprungs,
6. Vergleich mit dem bestehenden Hoek-van-Holland-Testoverlay.

Erst danach wird über einen größeren Nordsee-/Westeuropa-Build entschieden.
