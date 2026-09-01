# Candidate-Prefilter und komponentenweise Verarbeitung

Stand: 1. September 2026

## Ziel

Die Source-Auflösung soll fachlich genutzt werden, ohne dafür eine komplette
hochaufgelöste Region gleichzeitig im RAM halten zu müssen.

Die aktuelle Strategie trennt deshalb:

1. konservative grobe Vorauswahl,
2. exakte Highres-Candidate-Ermittlung,
3. Zerlegung in unabhängige Land-Komponenten,
4. serielle Verarbeitung jeweils einer Komponente,
5. Domain-Splitting nur für einzelne Komponenten, die selbst noch zu groß sind.

## 70-m-Candidate

Eine Rasterzelle kann im V2-Modell nur dann eine reguläre Klasse 0-70 m
erhalten, wenn sie über Terrain bis höchstens 70 m mit einem Sea-Seed verbunden
ist.

Der exakte Candidate-Pass ist bitgepackt implementiert in:

`src/candidate_mask_70.cpp`

## Nordadria-/Alpen-Benchmark

Testdomain:

- Bounds: 10,5 / 44,0 / 16,0 / 48,5,
- Processing Z11,
- Raster: 16.896 x 19.456,
- 328.728.576 Zellen.

Exakter Z11-Candidate:

- Sea-Zellen: 42.053.283,
- Landzellen: 286.675.293,
- Candidate-Landzellen: 35.293.314,
- Candidate-Landanteil: 12,3113 %,
- damit ausgeschlossene Landzellen: **87,6887 %**.

Der Candidate-Pass brauchte im ursprünglichen Benchmark ungefähr 89 MB
Peak-RSS und 1,75 s. Der vollständige V2-Flood auf demselben Raster brauchte
ungefähr 1,61 GB Peak-RSS.

## Konservativer Grobfilter

Für einen sicheren Grobfilter gelten:

- Grobzellenhöhe = Minimum aller feinen Kindzellen,
- grobe Sea-Maske = logisches OR aller feinen Kindzellen.

Dadurch darf der Grobfilter zusätzliche Candidate-Flächen erzeugen, aber keine
echte feine Candidate-Zelle verwerfen.

Gemessen gegen die exakte Z11-Candidate-Maske:

| Faktor | ungefährer Pixel | False Negatives | Candidate-Land | Land ausgeschlossen |
| ---: | ---: | ---: | ---: | ---: |
| 1 | ~26 m | - | 12,3113 % | 87,6887 % |
| 2 | ~53 m | 0 | 12,3555 % | 87,6445 % |
| 4 | ~106 m | 0 | 12,6235 % | 87,3765 % |
| 8 | ~211 m | 0 | 12,7749 % | 87,2251 % |
| 16 | ~423 m | 0 | 13,0330 % | **86,9670 %** |

Selbst Faktor 16 vergrößert die Candidate-Landmenge nur um Faktor 1,0586
gegenüber der exakten Maske.

## RAM nach Streaming-Umbau

Die Vorbereitung wurde anschließend auf sequentielles Streaming umgestellt.

Auf derselben 328,7-Mio.-Zellen-Domain:

| Schritt | Peak-RSS |
| --- | ---: |
| gestreamter Z11-DEM-Aufbau | ~145 MB |
| Faktor-16-Minimumsraster, 64 feine Zeilen/Chunk | ~49 MB |
| grober Faktor-16-Candidate-Pass | ~9 MB |

Damit ist die grobe Vorauswahl kein RAM-Engpass mehr.

## Warum das Meer keine Komponente bilden darf

Wenn Sea-Zellen bei der Komponentenbildung enthalten bleiben, verbindet ein
zusammenhängendes Meer sehr viele voneinander unabhängige Küstengebiete zu
einer einzigen riesigen Komponente.

Für die Threshold-Berechnung ist das unnötig.

Alle Sea-Zellen sind Quellen mit Threshold 0. Deshalb kann man die Sea-Zellen
aus dem Landgraphen entfernen und jede Candidate-Land-Komponente separat
betrachten.

Für eine Landzelle direkt neben dem Meer ist der Startwert:

`max(0, elevation_class_of_land_cell)`

also einfach ihre eigene quantisierte Höhenklasse.

Der Referenztest rechnet zwei durch Meer getrennte Land-Komponenten einzeln,
setzt beide Resultate zusammen und vergleicht sie mit dem globalen
Priority-Flood. Die Threshold-Klassen auf allen Candidate-Landzellen sind
bytegleich.

Der separate Referenzkern ist:

`src/priority_flood_land_mask.cpp`

## Grobe und exakte Komponenten

Die Komponenten der konservativen Grobmaske sind **keine fachlichen
Solver-Komponenten**.

Auf Faktor 16 liefert die Nordadria-/Alpen-Domain:

- 580 Candidate-Land-Komponenten,
- größte Komponente: 131.893 Grobzellen,
- das sind 92,8229 % aller groben Candidate-Landzellen.

Die starke Dominanz der größten Komponente kann teilweise durch konservativ
erfundene Verbindungen des Minimumsrasters entstehen.

Daher werden grobe Komponenten ausschließlich als **Work Regions** benutzt:

> Welche Highres-Daten müssen gemeinsam genauer untersucht werden?

Innerhalb jeder Work Region wird danach die exakte Highres-Candidate-Maske
gebildet und erneut in Land-Komponenten zerlegt.

Erst diese exakten Land-Komponenten sind fachlich unabhängige Solver-Einheiten.

### Exakte Z11-Komponenten

Der exakte Nordadria-/Alpen-Lauf bestätigt, dass die erneute Zerlegung fachlich
notwendig ist, aber große Niederungen trotzdem zusammenhängend bleiben können:

- 1.071 exakte Candidate-Land-Komponenten,
- größte Komponente: 33.636.701 Zellen,
- Anteil der größten Komponente an allen Candidate-Landzellen: **95,31 %**,
- lokales Bounding-Box-Fenster mit 1-Zellen-Halo:
  11.238 x 8.569 = 96.298.422 Zellen,
- Component-Füllgrad im lokalen Fenster: 34,93 %.

Für die RAM-Entscheidung ist deshalb nicht nur die Zahl echter
Component-Zellen relevant, sondern vor allem die Größe des lokalen
Materialisierungsfensters.

## Serielle Component-Pipeline

Geplanter regulärer Pfad:

1. Grobe konservative Min-Elevation-Maske erstellen.
2. Groben 70-m-Candidate berechnen.
3. Sea aus der Candidate-Maske entfernen.
4. Grobe Land-Komponenten als Work Regions bestimmen.
5. Eine Work Region auswählen.
6. Nur dafür die benötigten Highres-DEM-Daten materialisieren.
7. Exakten 70-m-Candidate innerhalb der Work Region berechnen.
8. Exakte Candidate-Land-Komponenten bestimmen.
9. **Eine exakte Land-Komponente materialisieren.**
10. Component-Priority-Flood rechnen.
11. Threshold-Ergebnis in die endgültige Ausgabe schreiben.
12. Alle temporären Daten dieser Komponente freigeben.
13. Nächste Komponente.

## RLE-Repräsentation

`src/candidate_land_components.cpp` kann die Komponenten als
Zeilenspannen exportieren.

Eine Span-Datei enthält pro Record drei Little-Endian-`uint32`:

- row,
- left,
- right.

Recordgröße: 12 Bytes.

Der JSON-Report enthält pro Komponente unter anderem:

- Component-ID,
- Zellzahl,
- Bounding Box,
- Zahl der Küstenzellen,
- Offset in der Span-Datei,
- Zahl der Span-Records.

Dadurch ist kein großes `uint32`-Labelraster notwendig.

## Lokales Component-Fenster

`scripts/materialize_candidate_component.py` erzeugt aus einer Component-ID:

- lokales `elevation.f32`,
- lokale `sea_mask.u8`,
- gepackte lokale `land_mask.bit`,
- Metadaten des lokalen Fensters.

Das Fenster erhält standardmäßig einen **1-Zellen-Halo**. Dadurch bleiben
Sea-Nachbarn von Landzellen erhalten, die direkt am Rand der Component-Bounding
Box liegen.

## Übergroße Komponenten

Komponentenweise Verarbeitung löst nicht automatisch jeden Worst Case.

Große zusammenhängende Niederungen wie:

- Niederlande,
- Poebene,
- große Flussdeltas,

können auch nach der exakten Zerlegung eine einzelne sehr große Land-Komponente
bilden.

Daher gilt:

- passt das lokale Component-Fenster in das RAM-Budget: direkt seriell rechnen,
- passt es nicht: **nur diese eine Komponente** in numerische Domains teilen
  und mit ausgetauschten Randthresholds bis zur Konvergenz rechnen.

Der Domain-Solver ist implementiert in:

`scripts/process_component_domains.py`

Er verwendet monotone Randthresholds. Wird für eine Nachbardomain später ein
niedrigerer Randwert gefunden, wird diese Domain erneut gerechnet. Die
Iteration endet, sobald sich kein Randwert mehr verbessert.

### Realbenchmark des Domain-Fallbacks

Die größte exakte Nordadria-/Alpen-Z11-Komponente wurde einmal direkt und
einmal in 2.048 x 2.048 Domains gerechnet.

Ergebnis:

- Component-Landzellen: 33.636.701,
- lokales Fenster: 96.298.422 Zellen,
- 22 tatsächlich belegte Domains,
- 55 Solver-Läufe insgesamt,
- maximal 5 Läufe für eine einzelne Domain,
- 65.837 verbesserte Randwerte,
- direkter Solver: 249.000 KiB Peak-RSS, 1,32 s,
- Domain-Solver: 81.928 KiB Peak-RSS, 6,68 s,
- **0 abweichende Zellen**,
- maximale Threshold-Klassenabweichung: **0**.

Der Domain-Fallback reduziert den gemessenen Peak-RSS damit um rund **67 %**,
ist in diesem Test aber ungefähr fünfmal langsamer. Das ist akzeptabel, weil er
nur für einzelne übergroße Komponenten verwendet wird.

`scripts/process_candidate_components.py` kann den Fallback automatisch anhand
der lokalen Fenstergröße wählen. `--max-direct-window-cells` setzt die Grenze;
für größere Fenster werden `--domain-solver`, `--domain-width` und
`--domain-height` verwendet.

## Nächster Prüfpunkt

Als Nächstes muss die komplette Hierarchie auf einer echten
**Source-Fidelity-/High-Resolution-Work-Region** geprüft werden:

1. konservative grobe Work Region,
2. nur dafür Highres-DEM materialisieren,
3. exakten Highres-Candidate bilden,
4. exakte Highres-Land-Komponenten bestimmen,
5. kleine Komponenten direkt seriell rechnen,
6. übergroße Komponenten automatisch per Domain-Fallback rechnen.

Damit wird erstmals der vollständige Low-Memory-Pfad bei der tatsächlich
gewünschten Source-Auflösung validiert.
