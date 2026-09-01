# Mapterhorn Coverage Planner

Stand: 1. September 2026

## Zweck

Der Coverage Planner übersetzt die aktuelle Mapterhorn-Quellenabdeckung in einen
reproduzierbaren Meeresspiegel-Produktionsplan.

Er beantwortet für ein Zielgebiet:

- welche Mapterhorn-DEM-Quellen vorhanden sind,
- welche native Auflösung diese Quellen haben,
- welche Lizenz und Attribution gelten,
- welche Flächen ein automatisches Tier-2-Refinement rechtfertigen,
- welche Quellen zusätzlich Tier-3-QA-Kandidaten sind,
- welcher Web-Mercator-Processing-Zoom aus Source-Auflösung und Breitenlage
  sinnvoll ist.

Die High-Resolution-Bereiche werden damit nicht über Ländergrenzen oder eine
manuell gepflegte Liste definiert.

Nach dem Uniform-Z13-Benchmark ist die Source-Coverage jedoch nicht mehr
automatisch die Grenze eines separat gelösten Refinement-Thresholdfelds. Sie
liefert primär die Information, **welche DEM-Qualität vorhanden ist und welcher
Processing-Zoom sich für eine größere zusammenhängende Processing-Domain lohnt**.

## Mapterhorn-Datenquellen

### Coverage-Geometrie

Mapterhorn veröffentlicht `coverage.pmtiles`. Der Planner verwendet den
zugehörigen MVT-Endpunkt und lädt nur die Coverage-Kacheln, die das
Planungsgebiet plus kleinen räumlichen Kontext schneiden.

Die Coverage-Features tragen das Attribut `source`.

### Attribution

`attribution.json` enthält pro Quelle unter anderem:

- Source-Name,
- Datensatzname,
- native Auflösung,
- Lizenz,
- Produzent,
- Website,
- Zugriffsjahr.

Damit kann die geometrische Coverage unmittelbar mit der nativen
DEM-Auflösung verbunden werden.

### Terrain-Archive

`download_urls.json` listet:

- `planet.pmtiles` für Zoom 0–12,
- regionale Archive für Zoom 13+,
- Bounds, Min-/Maxzoom und Dateigrößen.

Z13+ ist nicht mehr ausschließlich eine Tier-3-Sonderstufe. Der V2-Benchmark
zeigt, dass auch ein automatisches Tier-2-Refinement einer nativen 5-m-Quelle
Z13 benötigen kann.

Der Planner meldet deshalb die schneidenden High-Resolution-Archive weiterhin
mit. Für großflächige Builds muss später je Region entschieden werden, ob viele
Einzelrequests oder ein passendes regionales Archiv effizienter sind.

## Priorität überlappender Quellen

Mapterhorn priorisiert seine Terrain-Quellen nach der eigenen
Aggregationslogik. Für den Flood-Build verwenden wir das bereits aggregierte
Mapterhorn-Terrain.

Der Coverage Planner muss diese Verschneidung deshalb nicht nachbauen. Er nutzt
die Source-Coverages für die Entscheidung, **wo** eine höhere DEM-Qualität
vorhanden ist und **wie fein** eine Processing-Domain sinnvoll gerechnet werden
kann.

Die eigentliche Flood-Berechnung soll innerhalb einer Domain möglichst auf einem
gemeinsamen Graphen erfolgen. Fehlende High-Resolution-Tiles dürfen dabei aus der
globalen Mapterhorn-Basis überzoomt werden; die reale DEM-Genauigkeit bleibt
selbstverständlich die der gröberen Quelle.

## Planungsregeln

### Tier 1 – Base

Die globale/regionale Basis bleibt ungefähr in der Größenordnung der globalen
~30-m-Quelle.

Ziel:

`~30 m ground resolution`

Der konkrete Web-Mercator-Zoom wird aus der geographischen Breite berechnet.

### Tier 2 – automatisch

Eine Source wird Tier 2, wenn:

`native_resolution <= 10 m`

Die Zielauflösung ist source-abhängig:

`target_ground_resolution = max(native_resolution, 6 m)`

Anschließend wird der nächstliegende Web-Mercator-Zoom aus Zielauflösung und
Breitenlage bestimmt.

Beispiele bei ungefähr 52° N:

| native Source | automatisches Ziel | Zoom | Bodenpixel |
| ---: | ---: | ---: | ---: |
| 10 m | 10 m | Z12 | ~11,8 m |
| 5 m | 6 m | Z13 | ~5,9 m |
| 1 m | 6 m | Z13 | ~5,9 m |
| 0,5 m | 6 m | Z13 | ~5,9 m |

Damit wird eine 5-m-Quelle nicht unnötig auf ~12 m vergröbert. Gleichzeitig
führt eine 0,5- oder 1-m-Quelle nicht automatisch zu einem 1-m-Arbeitsraster.

### Warum AHN5 jetzt Z13 erhält

Der historische V1-Benchmark verwendete 1-m-Thresholdklassen. Darin erschien
Z12 gegenüber Z13 sehr ähnlich.

Der neue V2-Benchmark verwendet die tatsächlichen 58 Sliderklassen. Dabei
zeigen alle sechs Stichpunkte im Hoek-/Rotterdam-Gebiet denselben kritischen
Connectivity-Threshold:

| Processing | Threshold |
| ---: | ---: |
| Z11 | 3,5 m |
| Z12 | 3,75 m |
| Z13 | 4,0 m |

Bei **3,75 m** unterscheiden sich Z12 und Z13 bei **44,300326 %** der
Benchmarkzellen im Zustand `threshold <= slider`.

Das ist kein allgemeiner 44-%-Fehler. Eine einzelne hydraulisch entscheidende
Barriere wird bei Z12 um eine 0,25-m-Stufe zu niedrig abgebildet und öffnet
dadurch eine große zusammenhängende Polderfläche zu früh.

Für AHN5 5 m ist Z13 daher die fachlich passende automatische Stufe.

### Tier 3 – QA-Kandidat

Eine Source wird zusätzlich Tier-3-Kandidat, wenn:

`native_resolution <= 2 m`

QA-Ziel:

`target_ground_resolution = max(native_resolution, 3 m)`

Bei ungefähr 52° N entspricht das für sehr feine Sources typischerweise Z14 /
~2,9 m Bodenpixel.

Tier 3 wird **nicht automatisch produziert**. Es dient nur als regionaler
Vergleich, wenn schmale Deiche, Dämme oder ähnliche Strukturen selbst bei der
automatischen ~6-m-Stufe noch relevant verloren gehen.

## Reale Validierung der neuen Regel

Der Planner wurde gegen die aktuelle westliche Niederlande-Coverage geprüft.

Für `nlahn5lowresfilled` liefert der reale Plan:

- Name: Actueel Hoogtebestand Nederland, AHN5 5m,
- native Auflösung: 5,0 m,
- automatisches Tier: 2,
- Ziel-Bodenauflösung: 6,0 m,
- Processing-Zoom: **Z13**,
- resultierende Bodenauflösung im Source-Gebiet: **5,973 m**,
- `requires_z13_plus = true`.

Damit ist die Source→Zoom-Regel nicht nur synthetisch getestet, sondern mit der
aktuellen Mapterhorn-Coverage bestätigt.

## Ausgaben

`scripts/coverage_planner.py` erzeugt:

- `plan.json`: Regeln, Sources, Metadaten, Zielauflösungen und Zooms,
- `sources.geojson`: Source-Coverages im Zielgebiet,
- `sources-context.geojson`: Coverage mit zusätzlichem Planungskontext,
- `tier2.geojson`: vereinigte automatische Tier-2-Coverage,
- `tier3-candidates.geojson`: vereinigte Tier-3-QA-Coverage.

Planner-Schema V3 speichert zusätzlich:

- `recommended_target_ground_resolution_m`,
- `recommended_processing_zoom`,
- `recommended_ground_resolution_m`,
- `requires_z13_plus`,
- entsprechende Tier-3-QA-Zielwerte.

## Nordsee-Kontext

Der frühere Nordsee-Plan erkannte zahlreiche hochauflösende nationale Quellen
und große Z13+-Archive. Die damals dokumentierte Aussage „automatisches Tier 2
ist grundsätzlich Z12“ ist mit V3 überholt.

Beispiele:

- Niederlande, AHN5 5 m → automatisch ungefähr 6 m / Z13,
- Dänemark 0,4 m → automatisch ungefähr 6 m; zusätzlich ~3-m-QA-Kandidat,
- deutsche 0,25–1-m-Sources → ebenfalls nicht native Auflösung, sondern
  automatisch mindestens ungefähr 6 m.

## Verbindung mit der Buildpipeline

Der bevorzugte regionale Pfad nach dem Planner ist jetzt:

1. Coverage und Source-Auflösung bestimmen den empfohlenen Processing-Zoom.
2. Eine ausreichend große zusammenhängende Processing-Domain wird festgelegt.
3. `prepare_phase1a_dem.py` baut auf diesem Zoom ein gemeinsames DEM-Raster:
   - echte High-Resolution-Tiles, wo vorhanden,
   - `planet.pmtiles` als gröberer Overzoom-Fallback.
4. Die OSM-Ocean-Maske wird auf exakt dasselbe Raster gebracht.
5. `priority_flood_quantized` löst die gesamte Domain in **einem** Lauf.
6. `build_threshold_pyramid.py` erzeugt erst danach die Ausgabezoomstufen.
7. PMTiles wird erzeugt und verifiziert.

Der westliche Niederlande-Pilot hat diesen Pfad auf Z13 mit
1.394.606.080 Zellen vollständig validiert.

Die bisherige Hierarchie aus `prepare_refinement_region.py`,
`build_refinement_boundary.py` und `build_composite_threshold.py` bleibt als
Alternative für spätere **Processing-Domain-Grenzen** erhalten. Sie ist weiterhin
notwendig, wenn ein großes Gebiet nicht in einem gemeinsamen Raster gelöst werden
kann. Solche Grenzen werden künftig aber nicht automatisch an eine
DEM-Source-Coverage gelegt.

## Reproduzierbarkeit

Ein Produktionsbuild speichert mindestens:

- Planner-Regeln und Schema-Version,
- Coverage-Zoom und Source-Geometrien,
- relevante Attribution-/Source-Metadaten,
- native Source-Auflösung,
- Ziel-Bodenauflösung und Processing-Zoom,
- betroffene Z13+-Archive,
- Processing-Domain und Zielzoom,
- High-Resolution-/Fallback-Anteile,
- gegebenenfalls Domain-Randbedingungen,
- bei hierarchischer Zerlegung zusätzlich Collar-/Halo- und Parent-Metadaten.

Damit bleibt nachvollziehbar, warum eine Region zu einem bestimmten Zeitpunkt
mit einer bestimmten Auflösung gerechnet wurde.
