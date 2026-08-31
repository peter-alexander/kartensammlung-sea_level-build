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

Nächster Schritt ist der visuelle Test des V2-Composites in der Kartensammlung.
Danach wird der Z11/Z12/Z13-Auflösungsbenchmark mit V2 wiederholt, bevor die
automatische Coverage→Processing-Zoom-Regel endgültig festgelegt wird.

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
