# Phase 1C – Uniform Z13 QA

Validierter QA-Stand der uniformen Z13-Processing-Domain für die
westlichen Niederlande.

Dieser Build verwendet ein gemeinsames Z13-Processing-Raster und
einen einzigen Priority Flood über die gesamte Domain. Mapterhorn-Z13
wird verwendet, wo verfügbar; fehlende Land-Tiles werden aus dem
Z11–Z12-Ausschnitt von `planet.pmtiles` überzoomt. Verbleibende
DEM-Lücken wurden gegen die OSM-Ocean-Maske validiert und liegen
ausschließlich im offenen Meer.

- Bounds: 2.5, 51.2, 5.5, 53.2
- Processing-Zoom: Z13
- Raster: 35.840 × 38.912
- Zellen: 1.394.606.080
- Ausgabe: Z6–Z13
- PMTiles: 39.630.942 Bytes
- SHA256:
  `ff178fe94f592f92e66d8466184e962eece55532f3bedb1e13d020a50de55225`

Vollständiger Befund:
`docs/phase-1c-uniform-z13-result.md`
