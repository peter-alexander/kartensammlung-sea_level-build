# Kartensammlung Sea Level Build

Offline-Buildpipeline für das Overlay **Meeresspiegel** der Kartensammlung.

Ziel ist ein vorberechneter `inundation_threshold`-Datensatz: Jede Rasterzelle
speichert den niedrigsten Meeresspiegel, bei dem sie über Gelände mit dem offenen
Meer verbunden wird. Die aufwendige Priority-Flood-Berechnung erfolgt offline;
MapLibre vergleicht im Browser nur noch den vorberechneten Schwellenwert mit dem
Sliderwert.

## Aktueller Stand

Die Pipeline funktioniert inzwischen hierarchisch end-to-end:

- Mapterhorn-Coverage-Planner,
- globale/regionale Base,
- automatische High-Resolution-Refinements,
- Parent-Thresholds als Fine-Randbedingungen,
- Transition Collar + Priority-Flood-Halo,
- quantisierter 4er-Priority-Flood,
- Merge Base + Fine,
- gemeinsame Rasterpyramide,
- PMTiles-Ausgabe.

Phase 1C für die westlichen Niederlande kombiniert eine Z11-Base mit einem
automatisch erkannten AHN5-Z12-Refinement. Der historische V1-Lauf bleibt unter
`output/phase1c/` erhalten.

Der validierte V2-Lauf liegt unter `output/phase1c-v2/` und verwendet:

- 0–2 m: 0,1-m-Schritte,
- >2–5 m: 0,25-m-Schritte,
- >5–20 m: 1-m-Schritte,
- >20–70 m: 5-m-Schritte,
- 58 reguläre Klassen plus Sentinel.

Das V2-PMTiles umfasst Z6–Z12, ist 15.125.875 Bytes groß und wurde erfolgreich
verifiziert. Die neue Slider-Seam-QA vergleicht nicht nur Meterdifferenzen,
sondern direkt, ob Base und Fine bei einer konkreten Sliderstufe unterschiedliche
Überflutungszustände liefern.

An der echten Refinement-Seam liegt die maximale Abweichung bei:

- 0–2 m: 4 von 76.588 Randpixeln (0,005223 %) bei 0,2 m,
- >2–5 m: 538 Pixel (0,702460 %) bei 4,75 m,
- >5–20 m: 69 Pixel (0,090092 %) bei 17 m,
- >20–70 m: 63 Pixel (0,082258 %) bei 30 m.

Gerade im zentralen 0–2-m-Bereich ist die sichtbare Fine/Base-Seam damit
praktisch verschwunden. Der Bereich um 4,75–5 m wird beim visuellen Test gezielt
kontrolliert.

Die numerische Klassenauflösung ist nicht mit der regional tatsächlich
verfügbaren DEM-Genauigkeit gleichzusetzen; diese hängt von der jeweiligen Quelle
ab.

Der visuelle Test des V2-Composites in der Kartensammlung ist bestanden. Der
anschließende Z11/Z12/Z13-V2-Benchmark hat die frühere Z12-Empfehlung für AHN5
revidiert: Im Hoek-/Rotterdam-Test öffnet Z12 eine große Polderfläche bereits bei
3,75 m, Z13 erst bei 4,0 m. Bei 3,75 m unterscheiden sich 44,300326 % der
Benchmarkzellen im sichtbaren Überflutungszustand.

Der Coverage Planner verwendet deshalb jetzt eine source-abhängige Auflösung:

- Tier 2: `target = max(native_source_resolution, 6 m)`,
- Tier 3 QA: `target = max(native_source_resolution, 3 m)` für Sources <=2 m.

Für AHN5 5 m ergibt das bei ungefähr 52° N automatisch Z13 / rund 5,9 m
Bodenpixel. Vor dem nächsten großen Z13-Composite werden Transition Collar und
Priority-Flood-Halo noch von zoomabhängigen Pixel-/Tilewerten auf physisch
vergleichbare Breiten umgestellt.

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
