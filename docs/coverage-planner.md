# Mapterhorn Coverage Planner

Stand: 31. August 2026

## Zweck

Der Coverage Planner übersetzt die aktuelle Mapterhorn-Quellenabdeckung in einen
reproduzierbaren Meeresspiegel-Produktionsplan.

Er beantwortet für ein Zielgebiet:

- welche Mapterhorn-DEM-Quellen vorhanden sind,
- welche native Auflösung diese Quellen haben,
- welche Lizenz und Attribution gelten,
- welche Flächen ein automatisches Tier-2-Refinement rechtfertigen,
- welche Quellen zusätzlich Tier-3-QA-Kandidaten sind,
- welcher Web-Mercator-Processing-Zoom an der jeweiligen Breitenlage sinnvoll ist.

Die Refinement-Gebiete werden damit nicht mehr über Ländergrenzen oder eine
manuell gepflegte Liste definiert.

## Mapterhorn-Datenquellen

### Coverage-Geometrie

Mapterhorn veröffentlicht:

`https://download.mapterhorn.com/coverage.pmtiles`

Die Datei ist ein Vector-PMTiles-Archiv. Die Coverage-Map verwendet daraus die
Vector-Layer:

`coverage`

mit dem Attribut:

`source`

Die Coverage ist derzeit bis Zoom 14 verfügbar.

Der Planner lädt nicht das vollständige Coverage-PMTiles-Archiv. Er verwendet den
von Mapterhorn bereitgestellten TileJSON-/MVT-Endpunkt und lädt nur die
Coverage-Kacheln, die das gewünschte Planungsgebiet schneiden.

### Attribution

`https://download.mapterhorn.com/attribution.json`

enthält pro Quelle unter anderem:

- `source`,
- `name`,
- `resolution`,
- `license`,
- `producer`,
- `website`,
- `access_year`.

Damit kann die Source-Coverage direkt mit der nativen Datenauflösung und der
Attribution verbunden werden.

Stand 31. August 2026 enthält die Datei 148 Quellen.

### Terrain-Archive

`https://download.mapterhorn.com/download_urls.json`

listet:

- `planet.pmtiles` für Zoom 0–12,
- regionale Archive für Zoom 13+,
- Bounding Boxes,
- Min-/Maxzoom,
- Dateigröße,
- MD5.

Die regionalen Z13+-Archive werden vom Planner derzeit nur informativ gemeldet.

Für das automatische Tier-2-Ziel von ungefähr 10–15 m reicht bei unseren
europäischen Küstenregionen in der Regel Z12 und damit das normale
Mapterhorn-Terrain bis Z12.

Tier-3-QA auf ungefähr 5–6 m benötigt dagegen typischerweise Z13 und damit die
regionalen High-Resolution-Archive bzw. den entsprechenden Tile-Endpunkt.

## Priorität überlappender Mapterhorn-Quellen

Die Mapterhorn-Aggregationspipeline priorisiert Quellen nach:

1. höherem lokalem Maxzoom,
2. bei gleichem Maxzoom lexikographisch früherem Source-Namen.

Mapterhorn verschneidet die Quellen anschließend und füllt NoData-Bereiche mit
nachrangigen Quellen. An Source-Grenzen wird ein begrenztes Seam-Smoothing
angewendet.

Für unsere aktuelle Planung müssen wir diese Priorisierung nicht vollständig
reimplementieren, weil der eigentliche Flood-Build das bereits aggregierte
Mapterhorn-Terrain verwendet.

Der Planner behält deshalb alle im Gebiet vorkommenden Source-Coverages bei und
entscheidet nur, ob ihre native Auflösung ein Refinement rechtfertigt.

## Aktuelle Planungsregeln

Die Regeln sind CLI-Parameter und damit bewusst veränderbar.

### Tier 1 – Base

Ziel:

ungefähr 30 m Bodenauflösung.

Der konkrete Web-Mercator-Zoom wird aus der geographischen Breite berechnet.

Ein fixer globaler Zoom ist ungeeignet, weil die reale Bodenauflösung eines
Web-Mercator-Pixels mit der Breite variiert.

### Tier 2 – automatisch

Eine Source wird automatisch Tier 2, wenn:

`native_resolution <= 10 m`

Ziel:

`~12 m ground resolution`

Der nächstliegende Web-Mercator-Zoom wird automatisch berechnet.

Beispiel Niederlande:

- Source: `nlahn5lowresfilled`
- AHN5 DTM 5 m
- automatisches Tier 2
- bei ungefähr 52° N: Z12
- reale Bodenauflösung ungefähr 11,7 m.

### Tier 3 – nur QA-Kandidat

Eine Source wird zusätzlich Tier-3-Kandidat, wenn:

`native_resolution <= 2 m`

Ziel für einen späteren Vergleich:

`~6 m ground resolution`

Wichtig:

**Tier 3 wird nicht automatisch gebaut.**

Eine 0,5- oder 1-m-Quelle führt also im normalen Produktionsplan weiterhin nur
zu einem ungefähr 12-m-Tier-2-Refinement.

Die ungefähr 6-m-Stufe wird erst verwendet, wenn ein regionaler Benchmark zeigt,
dass sie gegenüber Tier 2 einen fachlich relevanten Connectivity-Gewinn liefert.

Damit bleibt die Auflösungsentscheidung konsistent mit dem
Hoek-van-Holland-Benchmark.

## Ausgaben

`scripts/coverage_planner.py` erzeugt:

### `plan.json`

Enthält:

- Bounding Box,
- Planner-Regeln,
- Base-Empfehlung,
- alle erkannten Quellen,
- Source-Metadaten,
- automatische Tier-Einstufung,
- empfohlene Processing-Zooms,
- Tier-3-QA-Zooms,
- betroffene High-Resolution-Archive.

### `sources.geojson`

Exakte innerhalb des Planungsgebiets rekonstruierte Mapterhorn-Coverage pro Source
mit den relevanten Metadaten.

### `tier2.geojson`

Vereinigte Coverage aller automatischen Tier-2-Quellen.

### `tier3-candidates.geojson`

Vereinigte Coverage aller Tier-3-QA-Kandidaten.

## Erster realer Nordsee-Plan

Planungsgebiet:

`-2.5,49.5,13.0,58.0`

Coverage-Zoom:

Z8.

Ergebnis:

- 132 benötigte Coverage-MVT-Kacheln,
- 31 erkannte DEM-Quellen,
- 30 Tier-2-fähige Quellen,
- 27 Tier-3-QA-Kandidaten,
- 11 räumlich schneidende Z13+-Mapterhorn-Archive.

Die Summe der vollständigen schneidenden High-Resolution-Archive beträgt rund
1,19 TB. Diese Zahl ist **keine notwendige Downloadmenge für Tier 2**. Sie zeigt
nur, wie groß die vollständigen Z13+-Archive sind, deren Bounding Box das
Planungsgebiet schneidet.

Für den normalen Z12-Tier-2-Build werden diese Archive nicht komplett
heruntergeladen.

## Erkannte Beispiele im Nordsee-Plan

### Niederlande

`nlahn5lowresfilled`

- AHN5 DTM,
- 5 m,
- CC BY 4.0,
- automatisch Tier 2,
- Z12,
- ungefähr 11,74 m Bodenpixel.

### Dänemark

`dk`

- 0,4 m,
- automatisch Tier 2 auf ungefähr 12 m,
- zusätzlich Tier-3-QA-Kandidat auf ungefähr 6 m.

### Deutschland

Mehrere Länder-DTMs mit ungefähr 0,25–1 m werden erkannt.

Sie werden trotz der sehr feinen Quelldaten **nicht automatisch auf ihre native
Auflösung oder Z13 hochgerechnet**.

### England / Schottland

Hochauflösende Quellen werden ebenfalls erkannt und nach derselben Regel
eingestuft.

## Verbindung mit der Buildpipeline

Der nächste Verarbeitungsschritt ist:

`scripts/prepare_refinement_region.py`

Er nimmt eine konkrete Source aus `sources.geojson` und:

1. schneidet deren Coverage mit dem Parent-Gebiet,
2. bestimmt den Fine-Tilebereich,
3. fügt einen konfigurierbaren Halo hinzu,
4. begrenzt die Workarea auf den Parent,
5. erzeugt eine Fine-Build-Konfiguration,
6. speichert die exakte Core-Geometrie für den späteren Merge.

Danach folgen:

`build_refinement_boundary.py`

→ Parent-Threshold auf Fine-Rand

`priority_flood_quantized`

→ Fine-Threshold

`build_composite_threshold.py`

→ Fine-Core überschreibt Base

`build_threshold_pyramid.py`

→ gemeinsame Rasterpyramide

→ PMTiles.

## Reproduzierbarkeit

Ein Produktionsbuild sollte zusammen mit seinem Threshold-Datensatz speichern:

- verwendete Planner-Regeln,
- Coverage-Zoom,
- `attribution.json`-Stand bzw. relevante Source-Metadaten,
- `download_urls.json`-Version,
- Mapterhorn-Source-Namen,
- Source-Coverage-Geometrien,
- Processing-Zooms,
- Halo-Größen,
- Parent-/Fine-Buildmetadaten.

Damit bleibt nachvollziehbar, warum ein Gebiet zu einem bestimmten Zeitpunkt mit
einer bestimmten Auflösung gerechnet wurde.
