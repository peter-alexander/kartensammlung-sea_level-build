# Kartensammlung Sea Level Build

Offline-Buildpipeline für das Overlay **Meeresspiegel** der Kartensammlung.

Ziel ist ein vorberechneter `inundation_threshold`-Datensatz: Jede Rasterzelle
speichert den niedrigsten Meeresspiegel, bei dem sie über Gelände mit dem offenen
Meer verbunden wird. Die aufwendige Priority-Flood-Berechnung erfolgt offline;
MapLibre vergleicht im Browser nur noch den vorberechneten Schwellenwert mit dem
Sliderwert.

## Aktueller Stand

Der bevorzugte regionale High-Resolution-Pfad ist inzwischen als **uniforme
Processing-Domain** validiert:

- Mapterhorn-Coverage-Planner bestimmt, wo eine höhere Arbeitsauflösung fachlich
  sinnvoll ist,
- eine Processing-Domain erhält einen einheitlichen Processing-Zoom,
- innerhalb dieser Domain wird das bestverfügbare Mapterhorn-Terrain verwendet,
- fehlende High-Resolution-Tiles werden geometrisch korrekt aus
  `planet.pmtiles` überzoomt,
- verbleibende DEM-Lücken sind nur zulässig, wenn sie vollständig in der
  Ocean-Maske liegen,
- auf dem gesamten Domain-Raster läuft **ein einziger** quantisierter
  4er-Priority-Flood,
- die Rasterpyramide wird erst nach der vollständigen Flood-Berechnung erzeugt.

Damit ist die Source-Coverage **keine harte Threshold-Merge-Grenze mehr**.
Unterschiedliche DEM-Qualität darf innerhalb einer Processing-Domain wechseln;
die Meer-Konnektivität wird trotzdem auf einem gemeinsamen Graphen gelöst.

Der westliche Niederlande-Pilot wurde vollständig auf Z13 gerechnet:

- 35.840 × 38.912 Pixel,
- 1.394.606.080 Zellen,
- 800 fehlende Z13-Tiles am High-Resolution-Endpunkt,
- davon 448 über Z12 aus `planet.pmtiles` ersetzt,
- 352 verbleibende Tiles ausschließlich über offenem Meer,
- Priority Flood: 28,51 s,
- Peak-RSS des Floods: 8.284.340 KiB,
- PMTiles Z6–Z13: 39.630.942 Bytes,
- SHA256:
  `ff178fe94f592f92e66d8466184e962eece55532f3bedb1e13d020a50de55225`,
- `go-pmtiles verify`: erfolgreich.

Der frühere hierarchische Z11→Z13-Pilot bleibt als wichtiger Vergleich erhalten.
Er benötigte etwas weniger Ressourcen, erzeugte aber an der harten
Threshold-Merge-Grenze bei 5 m bis zu 6,388878 % unterschiedliche Sliderzustände.
Auch ein zwischengeschaltetes Z12-Thresholdfeld beseitigte diese innere Naht
nicht. Größere Transition Collars reduzierten sie, lösten das Grundproblem aber
nicht.

Die Hierarchie-Infrastruktur wird deshalb **nicht entfernt**. Parent-Thresholds,
Boundary-Seeds, Halo und Composite bleiben als Werkzeuge für eine spätere
Zerlegung sehr großer Produktionsgebiete in Processing-Domains erhalten. Sie
sollen jedoch nicht mehr automatisch exakt an DEM-Source-Coverages als sichtbare
Threshold-Merge-Grenzen eingesetzt werden.

Der validierte V2-Z12-Stand bleibt unter `output/phase1c-v2/` erhalten; der neue
uniforme Z13-Stand wird getrennt als QA-Variante veröffentlicht.

Die verwendete V2-Thresholdklassierung bleibt unverändert:

- 0–2 m: 0,1-m-Schritte,
- >2–5 m: 0,25-m-Schritte,
- >5–20 m: 1-m-Schritte,
- >20–70 m: 5-m-Schritte,
- 58 reguläre Klassen plus Sentinel.

Die numerische Klassenauflösung ist nicht mit der regional tatsächlich
verfügbaren DEM-Genauigkeit gleichzusetzen; diese hängt von der jeweiligen Quelle
ab.

Siehe `docs/phase-1c-uniform-z13-result.md` für den vollständigen
Uniform-Z13-Befund.

## Struktur

- `config/` – Pilot- und spätere Produktionskonfigurationen
- `scripts/` – Berechnung, Tests und Tile-Export
- `docs/` – Architektur und fachliche Entscheidungen
- `.github/workflows/` – reproduzierbare manuelle Pilot-Builds

## Grundprinzip

```text
DEM + Ocean-Maske
    ↓
Priority Flood / Minimax-Konnektivität
    ↓
Inundation Threshold
    ↓
Quantisierung 0…70 m, nichtlinear
    ↓
Terrarium-Raster
    ↓
PMTiles
    ↓
MapLibre
```

Siehe `docs/architecture.md` für die vollständige Architektur.
