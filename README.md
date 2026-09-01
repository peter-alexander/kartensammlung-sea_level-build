# Kartensammlung Sea Level Build

Offline-Buildpipeline für das Overlay **Meeresspiegel** der Kartensammlung.

Ziel ist ein vorberechneter `inundation_threshold`-Datensatz: Jede Rasterzelle
speichert den niedrigsten Meeresspiegel, bei dem sie über Gelände mit dem offenen
Meer verbunden wird. Die aufwendige Priority-Flood-Berechnung erfolgt offline;
MapLibre vergleicht im Browser nur noch den vorberechneten Schwellenwert mit dem
Sliderwert.

## Aktueller Stand

Der bevorzugte regionale High-Resolution-Pfad ist als **uniforme
Processing-Domain** validiert: innerhalb einer Domain wird das bestverfügbare
DEM auf einem gemeinsamen Processing-Raster zusammengesetzt und anschließend
ein einziger Priority Flood gerechnet. Die Source-Coverage ist damit keine
harte Threshold-Merge-Grenze mehr.

Der veröffentlichte westliche Niederlande-Z13-Stand bleibt unter
**output/phase1c-uniform-z13/** als Architektur- und QA-Nachweis erhalten:

- 1.394.606.080 Zellen,
- ein gemeinsamer Z13-Priority-Flood,
- 28,51 s Flood-Zeit,
- 8.284.340 KiB Peak-RSS,
- verifiziertes Z6-Z13-PMTiles mit 39.630.942 Bytes.

### Neue Auflösungsentscheidung

Z13 ist **nicht mehr die fachliche Endauflösung für AHN5**.

Der direkte V2-Benchmark Z13 gegen Z14 auf derselben Hoek-/Rotterdam-Fläche
ergab:

- Z13: ungefähr 5,883 m Bodenpixel,
- Z14: ungefähr 2,941 m Bodenpixel,
- maximale Sliderzustandsabweichung:
  **44,268125 % bei 3,75 m**.

AHN5 hat 5 m native Auflösung. Z13 unterabtastet die Source damit knapp; Z14 ist
bei ungefähr 52 Grad Nord die erste Web-Mercator-Stufe, deren Bodenpixel nicht
gröber als die native Source sind.

Ein zusätzlicher Z15-Kontrollversuch konnte nicht durchgeführt werden: Für die
identische Benchmarkfläche lieferte der getestete Mapterhorn-ZXY-Endpunkt auf
Z15 für alle 3.072 angeforderten Tiles 404. Z14 war dagegen vollständig
verfügbar.

Der Coverage Planner meldet deshalb ab Schema V4 zusätzlich den
**Source-Fidelity-Zoom**. Die bisherige ausführbare Empfehlung bleibt vorerst
separat erhalten, bis Z14-Domains technisch sicher skaliert werden können.

### 70-m-Candidate-Pass

Ein exakter, bitgepackter Vorpass ist implementiert. Er markiert nur Zellen, die
bei höchstens 70 m tatsächlich über Terrain mit dem Meer verbunden sein können.

Im niederländischen Lowland-Worst-Case sind erwartungsgemäß 100 % der Zellen
Kandidaten. Der Pass selbst ist jedoch sehr billig und soll in reliefreichen
Küstenregionen Gebirge und abgeschlossene Hochlandbereiche vor dem teuren
58-Klassen-Solver entfernen.

Die V2-Thresholdklassierung bleibt unverändert:

- 0-2 m: 0,1-m-Schritte,
- >2-5 m: 0,25-m-Schritte,
- >5-20 m: 1-m-Schritte,
- >20-70 m: 5-m-Schritte,
- 58 reguläre Klassen plus Sentinel.

Siehe **docs/phase-1c-uniform-z13-result.md** für den Architekturtest und
**docs/source-resolution-benchmark-v2.md** für die aktuelle
Auflösungsentscheidung.

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
