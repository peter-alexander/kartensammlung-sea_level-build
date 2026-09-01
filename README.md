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

### Candidate-Prefilter und serielle Komponenten

Der 70-m-Candidate-Pfad ist inzwischen als Low-Memory-Prototyp validiert.
Auf einer Nordadria-/Alpen-Domain können 87,69 % der Landzellen bereits vor
dem vollständigen V2-Solver ausgeschlossen werden. Ein konservativer
~423-m-Vorfilter behält davon 86,97 % Ausschlusswirkung bei **0 False
Negatives**.

Die Verarbeitung wird auf **Candidate-Land-Komponenten** umgestellt: Meer wird
nicht als verbindende Komponente behandelt, sondern nur als Threshold-0-
Randbedingung. Einzelne exakte Land-Komponenten können dadurch seriell
gerechnet und danach aus dem RAM entfernt werden. Übergroße Einzelkomponenten
erhalten als Fallback eine interne Domain-Zerlegung.

Der Source-Fidelity-Pfad ist inzwischen ebenfalls als Work-Region-Pipeline
validiert:

- echte Mapterhorn-Coverage-Geometrien statt bloßer Coverage-Bounding-Boxes,
- Source-Grenzen bleiben **keine Solver-Grenzen**,
- gemischte 1-m-/10-m-Coverage wurde auf einem gemeinsamen Z16-Raster
  materialisiert,
- fehlende High-Zoom-ZXY-Tiles können automatisch aus der nächstfeineren
  verfügbaren HTTP-Parent-Tile overzoomt werden,
- grobe RLE-Candidate-Komponenten können als tatsächliche geografische
  Work-Region-Geometrie rekonstruiert werden.

Für sichere grobe Work Regions werden inzwischen zwei Sea-Masken getrennt:
Sea-Any (OR der Kinder) für den konservativen Candidate-Pass und Pure-Sea
(AND der Kinder) für die Komponentenzerlegung. Auf der Nordadria-/Alpen-Domain
ergibt das 87 sichere Faktor-16-Work-Regions; die größte enthält 96,73 % der
groben Candidate-Landfläche.

Deshalb wird eine große Work Region **nicht mehr vollständig in Highres
materialisiert**. Der neue lazy Pfad plant nur aktive Fine-Domains, lädt jeweils
eine Domain aus Mapterhorn, tauscht monotone Randthresholds mit den Nachbarn aus
und löscht die lokalen DEM-Daten danach wieder.

Ein realer Multi-Domain-Pilot mit 12 aktiven 512-x-512-Domains und 23
Materialisierungen war auf 401.664 Work-Region-Zellen bytegleich mit einem
globalen QA-Priority-Flood.

Für die große zusammenhängende Work Region wird die Auflösung inzwischen
**adaptiv innerhalb desselben Solver-Graphen** gewählt. Der reale
Component-1-Plan enthält:

- 14.248 grobe Z11-Zellen,
- 114.317 grobe Z13-Zellen,
- 15.247 grobe Z14-Zellen,
- 1.386 grobe Z16-Zellen.

Das reduziert die geplante Core-Arbeit von rund **38,06 Milliarden** Zellen
bei uniform Z16 auf **1,085 Milliarden**, also um Faktor **35,08**.

Die Multi-Resolution-Kopplung ist real an einer direkten
**Z11-Z16-Küstenkante (32:1)** gegen einen unabhängig expandierten globalen
Referenzgraphen validiert: 524.288 Vergleichszellen, **0 Unterschiede**.

Ein zusammenhängender 128-Domain-Benchmark mit warmem Mapterhorn-Cache brauchte
37,52 s bei 183.464 KiB Peak-RSS. Der adaptive Tile-Prefetch reduziert dabei
24.502 Domain-Tile-Referenzen des Vollplans auf nur **4.615 eindeutige
Mapterhorn-Tiles**.

Längere adaptive Läufe unterstützen inzwischen Checkpoint/Resume. Der
Konvergenzzustand besteht nur aus Queue, Randthresholds und Countern; die
sparse Threshold-Endausgabe kann erst nach vollständiger Konvergenz erzeugt
werden.

Siehe `docs/candidate-prefilter-and-components.md`.

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
