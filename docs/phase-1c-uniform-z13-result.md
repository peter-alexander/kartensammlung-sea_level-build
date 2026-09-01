# Phase 1C – Uniforme Z13-Processing-Domain

Stand: 1. September 2026

## Ziel

Der Versuch prüft, ob die im hierarchischen Z13-Composite beobachtete
Fine/Base-Naht vermieden werden kann, indem nicht separat gelöste
Thresholdfelder zusammengeführt werden.

Stattdessen wird der gesamte westliche Niederlande-Pilot auf einem gemeinsamen
Z13-Raster gerechnet. Innerhalb dieses Rasters darf die reale DEM-Qualität
wechseln:

- Mapterhorn Z13, wo verfügbar,
- globales Mapterhorn-`planet.pmtiles` als gröberer Fallback,
- fehlendes DEM ausschließlich über Zellen, die die OSM-Ocean-Maske als Meer
  bestätigt.

Danach läuft **ein einziger Priority Flood** über die vollständige Domain.

## Gebiet und Raster

Bounds:

- West: 2,5° E
- Süd: 51,2° N
- Ost: 5,5° E
- Nord: 53,2° N

Processing:

- Zoom: Z13
- Tile-Größe: 512
- Tile-X: 4152–4221
- Tile-Y: 2660–2735
- Raster: 35.840 × 38.912
- Zellen: **1.394.606.080**
- Web-Mercator-Pixel: 9,5546285 m

## DEM-Fallback

Am Z13-Tile-Endpunkt fehlten innerhalb des Processing-Rasters 800 Tiles.

Für den Fallback wurde aus

`https://download.mapterhorn.com/planet.pmtiles`

nur der benötigte Z11–Z12-Ausschnitt extrahiert.

Extrakt:

- 27 HTTP-Requests,
- 136 MB übertragen,
- 136 MB lokales PMTiles,
- 7,13 s,
- `go-pmtiles verify`: erfolgreich.

Von den 800 fehlenden Z13-Tiles konnten **448** aus Z12-Tiles des Planet-Archivs
ersetzt werden. Der korrekte Z12-Quadrant wird ausgewählt und per
Nearest-Neighbor auf die Z13-Zielzelle überzoomt. Das erzeugt keine zusätzliche
Geländeinformation; es stellt nur einen gemeinsamen Processing-Graphen her.

352 Z13-Tiles blieben ohne DEM.

Die anschließende Ocean-Validierung ergab:

- Missing-DEM-Zellen: **92.274.688**
- davon Ocean-Zellen: **92.274.688**
- davon Land-Zellen: **0**

Damit liegen alle verbleibenden DEM-Lücken ausschließlich im offenen Meer.

## Priority Flood

V2-Klassenschema:

- 0–2 m: 0,1 m
- >2–5 m: 0,25 m
- >5–20 m: 1 m
- >20–70 m: 5 m
- 58 reguläre Klassen + Sentinel
- 4er-Nachbarschaft

Ergebnis:

- verarbeitete Zellen: 1.394.570.938
- Sea-Seeds: 817.514.784
- Boundary-Seeds: 0
- stale entries: 0
- Sentinel/disconnected: 35.142
- Laufzeit: **28,51 s**
- Peak-RSS: **8.284.340 KiB**
- Exit: erfolgreich

Damit wird die gesamte Domain ohne interne Parent-/Fine-Thresholdgrenze gelöst.

## Rasterpyramide und PMTiles

Ausgabe:

- Minzoom: 6
- Maxzoom: 13
- Tile-Type: PNG
- Tile-Kompression: none
- Bounds: [2.5, 51.2, 5.5, 53.2]
- PMTiles-Größe: **39.630.942 Bytes**
- SHA256:
  `ff178fe94f592f92e66d8466184e962eece55532f3bedb1e13d020a50de55225`
- `go-pmtiles verify`: erfolgreich

## Vergleich mit hierarchischem Z13

| Kennzahl | Z11→Z13 hierarchisch | uniform Z13 |
| --- | ---: | ---: |
| Flood-Zeit | 24,07 s | **28,51 s** |
| Flood Peak-RSS | ~6,38 Mio. KiB | **8.284.340 KiB** |
| PMTiles | 37.799.462 B | **39.630.942 B** |
| interne Threshold-Merge-Naht | ja | **nein** |

Die Ressourcenmehrkosten sind für diesen Pilot moderat. Gleichzeitig entfällt
die künstliche Threshold-Merge-Grenze vollständig.

Der direkte Z13→Z11-Composite zeigte bei 5 m bis zu **6,388878 %**
unterschiedliche Sliderzustände an der Refinement-Seam. Ein breiterer Collar
reduzierte diesen Wert, beseitigte das Grundproblem aber nicht. Auch eine
zusätzliche Z12-Thresholdstufe ließ an der inneren Z13/Z12-Naht noch ungefähr
5,88 % Abweichung bei 5 m zurück.

## Architekturentscheidung

Für regionale High-Resolution-Gebiete wird deshalb zunächst bevorzugt:

```text
Coverage / Source-Auflösung
        ↓
Processing-Domain + gemeinsamer Zoom
        ↓
bestverfügbares DEM + gröberer Overzoom-Fallback
        ↓
gemeinsame Ocean-Maske
        ↓
ein Priority Flood
        ↓
Rasterpyramide
        ↓
PMTiles
```

Kurzform:

**Coverage-abhängige DEM-Qualität, Domain-abhängiges Processing-Zoom,
keine Coverage-abhängige Threshold-Merge-Grenze.**

Die bestehende hierarchische Parent-/Boundary-Technik bleibt erhalten. Sie wird
für spätere großräumige Domain-Zerlegung benötigt, wenn eine vollständige
Processing-Domain nicht mehr in einen Lauf passt.

Dieser Pilot beweist ausdrücklich **nicht**, dass Europa oder die Welt pauschal
auf Z13 gerechnet werden sollen. Größe und Grenzen zukünftiger
Processing-Domains müssen anhand von Ressourcen, Connectivity und QA gewählt
werden.
