# Phase 1A – Westliche Niederlande

Stand: 31. August 2026

## Gebiet

- West: 2.5° E
- Süd: 51.2° N
- Ost: 5.5° E
- Nord: 53.2° N

Der Ausschnitt enthält offene Nordsee, Zeeland/Randstad, Rotterdam, Den Haag,
Amsterdam und große niedrig liegende Flächen im westlichen Teil der Niederlande.

## Processing-Raster

Mapterhorn, Web-Mercator-Zoom 11, 512-Pixel-Tiles.

Gemessene Rastergeometrie:

- Tile-X: 1038–1055
- Tile-Y: 665–683
- 18 × 19 = 342 mögliche Z11-Tiles
- Raster: 9216 × 9728
- Zellen: 89.653.248
- Web-Mercator-Pixel: 38,219 m
- ungefähre Bodenauflösung bei 52,2° N: 23,424 m

Diese Web-Mercator-Auflösung ist teilweise feiner als die ungefähr 30-m-globale
Basisauflösung der DEM-Quelle und darf nicht als zusätzliche reale Geländeinformation
interpretiert werden.

## RAM-Abschätzung

Frühe konservative Python/Array-Abschätzung:

- kompakte Kernarrays: ca. 0,58 GiB
- mit zusätzlichem int32-Arbeitsarray: ca. 0,92 GiB

Der neue quantisierte C++-Kern benötigt kein int32-Threshold-Raster. Wesentliche
dauerhafte Arrays sind:

- Elevation float32: ca. 342 MiB
- Sea-Maske uint8: ca. 86 MiB
- Threshold/Visited uint8: ca. 86 MiB
- Bucket-Indizes: variabel, maximal grob ein uint32 pro aktuell eingereihtem Pixel

Damit ist Phase 1A auf einem normalen GitHub-Runner realistisch.

## Mapterhorn PMTiles Dry Run

Befehl:

```sh
go-pmtiles extract \
	--bbox=2.5,51.2,5.5,53.2 \
	--maxzoom=11 \
	--overfetch=0 \
	--dry-run \
	https://download.mapterhorn.com/planet.pmtiles \
	north-sea-dem.pmtiles
```

Gemessen:

- Region tiles: 478
- result tile entries: 286
- 34 HTTP Requests
- Transfer: ca. 50 MB
- resultierendes Archiv: ca. 50 MB

Damit ist der DEM-Input für Phase 1A sehr klein im Vergleich zum Arbeitsraster.

## OSM Ocean Source

`water-polygons-split-3857.zip`:

- Content-Length: 928.878.835 Bytes
- ungefähr 886 MiB
- unterstützt HTTP Range Requests

Das globale Ocean-Polygonarchiv ist damit wesentlich größer als der DEM-Ausschnitt.
Für wiederholte Builds sollte es gecacht bzw. als Snapshot wiederverwendet werden.

Für spätere Optimierung ist zu prüfen, ob aus dem globalen Snapshot einmalig ein
kleiner, versionierter Pilot-Ausschnitt erzeugt werden soll.

## Quantized Priority Flood

Für die Produktion wurde zusätzlich zur Python-Referenz ein C++-Kern implementiert:

`src/priority_flood_quantized.cpp`

Prinzip:

1. reale Geländehöhe wird auf die erste sichtbare 1-m-Klasse aufgerundet,
2. Werte über +100 m erhalten den Sentinel 101,
3. 101 Buckets repräsentieren Threshold 0…100,
4. Ocean-Seeds starten in Bucket 0,
5. eine Zelle wird beim ersten Erreichen fest zugeordnet,
6. Standard ist 4er-Nachbarschaft.

Damit ist keine allgemeine Float-Priority-Queue mehr nötig.

Der C++-Kern wurde in GitHub Actions gegen die exakte Python-Referenz getestet.
Der Test ist erfolgreich.

## Nächster Build-Schritt

Phase 1A soll nun vollständig bis zum quantisierten Threshold-Raster laufen:

1. Mapterhorn-Ausschnitt laden,
2. Z11 DEM zu einem Raster mosaikieren,
3. OSM Ocean Polygon auf exakt dasselbe Raster rasterisieren,
4. C++ Priority Flood ausführen,
5. `threshold.u8` und georeferenziertes QA-GeoTIFF erzeugen,
6. Statistik pro Thresholdklasse erzeugen,
7. Stichproben in Niederlande/Poldern prüfen,
8. danach erst Terrarium-/PMTiles-Pyramide erzeugen.

Der erste vollständige Pilot soll noch nicht automatisch in die Kartensammlung
deployed werden. Zuerst werden Ergebnis, Laufzeit, RAM und Küstenmaske geprüft.
