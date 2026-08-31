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
verifiziert.

Nächster Schritt ist der visuelle Test dieses zusammengesetzten Datensatzes in
der Kartensammlung und danach die Skalierung auf ein größeres Parent-Gebiet.

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
Quantisierung 0…100 m
    ↓
Terrarium-Raster
    ↓
PMTiles
    ↓
MapLibre
```

Siehe `docs/architecture.md` für die vollständige Architektur.
