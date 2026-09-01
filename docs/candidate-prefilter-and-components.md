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

- passt die exakte Komponente in das RAM-Budget: direkt seriell rechnen,
- passt sie nicht: **nur diese eine Komponente** in numerische Domains teilen
  und mit ausgetauschten Randthresholds bis zur Konvergenz rechnen.

Das Domain-Splitting ist damit kein globaler Standardfall mehr, sondern ein
Fallback für einzelne übergroße Komponenten.

## Aktueller Prüfpunkt

Noch ausstehend ist die Größenverteilung der **exakten** Z11-Land-Komponenten
auf der Nordadria-/Alpen-Domain. Dieser Benchmark entscheidet, ab welcher
Component-Größe der Domain-Fallback praktisch benötigt wird.
