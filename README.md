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
automatisch erkannten AHN5-Z12-Refinement. Ein 128-Pixel-Transition-Collar
reduziert die maximale gemessene Fine/Base-Seam-Abweichung von 14 m auf 4 m;
kein getesteter Seam-Pixel unterscheidet sich noch um mehr als 5 m.

Das resultierende Z6–Z12-PMTiles ist rund 10,8 MB groß und wurde erfolgreich
verifiziert. Dieses veröffentlichte Phase-1C-Artefakt verwendet noch das
historische V1-Schema mit 1-m-Schritten bis 100 m.

Für V2 ist der Modellbereich auf 0–70 m begrenzt und nichtlinear quantisiert:

- 0–2 m: 0,1-m-Schritte,
- >2–5 m: 0,25-m-Schritte,
- >5–20 m: 1-m-Schritte,
- >20–70 m: 5-m-Schritte.

Das ergibt 58 reguläre Klassen plus Sentinel. Die numerische Klassenauflösung ist
nicht mit der regional tatsächlich verfügbaren DEM-Genauigkeit gleichzusetzen;
diese hängt von der jeweiligen Quelle ab.

Nächster Schritt ist ein erneuter Phase-1C-Build mit V2 und danach der visuelle
Test in der Kartensammlung. Vor einer endgültigen Produktionsauflösung wird auch
der Z11/Z12/Z13-Auflösungsbenchmark mit V2 wiederholt.

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
