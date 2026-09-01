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

## Source-Fidelity-Pilot

Der vollständige Low-Memory-Pfad wurde anschließend auf einer realen
Mapterhorn-Work-Region innerhalb der slowenischen Source `si` geprüft.

Die Coverage-Metadaten melden:

- Source: `si` / DMR - digitalni model reliefa,
- native Auflösung: **1,0 m**,
- Source-Fidelity-Processing-Zoom: **Z16**,
- Ground Resolution im Pilot: **0,836 m**.

Pilot-Raster:

- 1.536 x 1.536 Zellen,
- 2.359.296 Zellen insgesamt,
- 9 echte Z16-Mapterhorn-Tiles,
- 0 fehlende DEM-Tiles.

Exakter Z16-Candidate:

- Sea-Zellen: 850.151,
- Landzellen: 1.509.145,
- Candidate-Landzellen: 1.497.379,
- Candidate-Landanteil: 99,2204 %.

Die kleine Pilotregion liegt fast vollständig in einer niedrig gelegenen,
zusammenhängenden Küstenzone. Deshalb ist der Candidate-Anteil hier bewusst
kein Maß für die globale Prefilter-Wirkung.

Die exakte Highres-Zerlegung ergab:

- 1 Candidate-Land-Komponente,
- 1.497.379 Landzellen,
- Component-Fenster: 1.536 x 1.385 = 2.128.896 Zellen.

Mit einem Direktlimit von 1.000.000 Fensterzellen wurde automatisch der
Domain-Fallback verwendet:

- 4 Domains,
- 8 Solver-Läufe insgesamt,
- maximal 2 Läufe pro Domain,
- 3.788 verbesserte Randthresholds.

Vergleich mit einem globalen Z16-Priority-Flood auf derselben Region:

- **0 abweichende Candidate-Landzellen**,
- **0 nicht-Sentinel-Zellen außerhalb Candidate-Land**,
- damit bytegleich auf allen fachlich relevanten Zellen.

Gemessene Peak-RSS-/Laufzeitwerte:

| Schritt | Peak-RSS | Laufzeit |
| --- | ---: | ---: |
| globaler Z16-Referenz-Flood | 18.252 KiB | 0,04 s |
| exakter Candidate | 9.128 KiB | 0,02 s |
| Komponentenbildung | 5.104 KiB | 0,02 s |
| serielle Component-/Domain-Pipeline | 40.336 KiB | 0,52 s |

Damit ist der Pfad

`grobe Work Region -> Source-Fidelity-DEM -> exakter Candidate -> exakte Components -> automatischer Domain-Fallback`

erstmals vollständig mit echter 1-m-Quelldatenauflösung validiert.

### Wichtige Coverage-Erkenntnis

Die `coverage_bounds` einer Mapterhorn-Source reichen nicht aus, um zu
entscheiden, ob eine Work Region vollständig durch diese Source abgedeckt ist.

Eine MultiPolygon-Coverage kann dieselbe Bounding Box aufspannen und innerhalb
dieser Box trotzdem Lücken enthalten. Das trat beim ersten Pilotversuch mit
`si` tatsächlich auf.

Für die Produktionspipeline muss deshalb die **echte Coverage-Geometrie**
geschnitten bzw. auf vollständige Abdeckung geprüft werden. Bounding Boxes
dürfen nur zur schnellen Vorauswahl verwendet werden.

## Work-Region-Planer und gemischte Source-Fidelity

Der Pilot wurde inzwischen zu wiederverwendbaren Bausteinen verallgemeinert.

`scripts/plan_work_region.py` schneidet eine Work Region mit den **echten**
Mapterhorn-Coverage-Geometrien. Für Diagnose und Auflösungsentscheidung wird
daraus eine überschneidungsfreie Best-Source-Partition erzeugt.

Wichtig ist dabei:

> Source-Grenzen sind **keine Solver-Grenzen**.

Die gesamte Work Region bleibt eine uniforme Processing-Domain. Der höchste
benötigte Source-Fidelity-Zoom innerhalb der tatsächlichen Work-Region-
Geometrie bestimmt das gemeinsame Raster. Wo Mapterhorn auf diesem Zoom keine
Tile liefert, kann `scripts/prepare_phase1a_dem.py` automatisch auf die
nächstfeinere verfügbare Parent-Tile zurückfallen und sie auf das gemeinsame
Raster overzoomen.

Der HTTP-Fallback wird über

`overzoom_fallback_mode = "http"`

und `overzoom_fallback_minzoom` gesteuert.

### Gemischter Realtest `si` + `tinitaly`

Eine kleine reale Work Region an der Coverage-Grenze enthielt effektiv:

- **48,108602 %** `si`,
  native Auflösung 1 m, Source-Fidelity Z16,
- **51,891398 %** `tinitaly`,
  native Auflösung 10 m, Source-Fidelity Z13.

Der Planer wählte für die gemeinsame Work Region korrekt **Z16**.

Pilot-Raster:

- 1.024 x 512 Zellen,
- 524.288 Zellen,
- ungefähr 0,834 m Ground Resolution,
- 2 Z16-Tiles.

Beide Z16-Tiles wurden vom aktuellen Mapterhorn-ZXY-Endpunkt direkt geliefert,
obwohl ein Teil der Coverage nur `tinitaly` als beste Source ausweist. Das
zeigt, dass Coverage-Source-Fidelity und technisch verfügbare ZXY-Maxzoom-Tiles
nicht identisch behandelt werden dürfen: vorhandene feinere Tiles können
verwendet werden; die Coverage-Metadaten bleiben die fachliche Aussage über die
native Datenauflösung.

### Echter HTTP-Fallback

Der Fallback wurde zusätzlich an der bereits bekannten Niederlande-Z15-Probe
geprüft:

- angefordert: 1 Z15-Tile,
- direkter Z15-Request: 404,
- gefundener Parent: Z14,
- aufgelöste Fallback-Tiles: 1,
- verbleibende fehlende Tiles: **0**.

Damit ist auch der reale Pfad

`fehlende High-Zoom-Tile -> nächster verfügbarer Parent -> Overzoom auf gemeinsames Raster`

validiert.

## Grobe Component direkt als Work Region

`scripts/prepare_candidate_work_region.py` rekonstruiert aus dem
RLE-Span-Export einer groben Candidate-Land-Komponente ihre tatsächliche
geografische Geometrie.

Dabei wird bewusst **nicht nur die Component-Bounding-Box** verwendet. Eine
hochaufgelöste Source, die lediglich in einer leeren Ecke der Bounding Box
liegt, darf sonst nicht die komplette Work Region unnötig auf einen höheren
Processing-Zoom ziehen.

Für die Source-Fidelity-Entscheidung wird die **Core-Geometrie ohne Halo**
verwendet. Ein Halo ist nur Rechen- bzw. Sea-Kontext und darf den
Processing-Zoom des Cores nicht erhöhen.

## Zwei verschiedene grobe Sea-Masken

Der reale RLE-End-to-End-Versuch zeigte eine wichtige Trennung:

- für den konservativen 70-m-Candidate ist
  **Sea-Any = OR aller feinen Kinder** richtig,
- für die Zerlegung in sichere grobe Work Regions muss dagegen
  **Pure-Sea = AND aller feinen Kinder** verwendet werden.

Mit Sea-Any kann eine gemischte Küstenzelle bereits als Meer gelten, obwohl sie
noch echtes Land enthält. Würde diese Zelle aus dem groben Landgraphen
entfernt, könnte eine reale Highres-Landverbindung künstlich getrennt werden.

Pure-Sea entfernt deshalb nur Grobzellen, die garantiert vollständig aus Meer
bestehen. Das macht Work Regions konservativ größer, kann aber keine
Highres-Landbrücke an einer gemischten Küstenzelle abschneiden.

`scripts/build_conservative_candidate_coarse.py` kann dafür beide Masken
schreiben:

- `sea-any.u8`: logisches OR, für den Candidate-Pass,
- `sea-all.u8`: logisches AND, für die Work-Region-Komponenten.

### Faktor-16-Benchmark mit Pure-Sea

Auf der Nordadria-/Alpen-Domain änderte sich die Work-Region-Verteilung
deutlich:

| Kennzahl | Sea-Any als Trenner | Pure-Sea als Trenner |
| --- | ---: | ---: |
| Work Regions | 580 | **87** |
| größte Work Region | 131.893 Zellen | **145.198 Zellen** |
| Anteil der größten Region | 92,82 % | **96,73 %** |

Weitere Pure-Sea-Werte:

- Candidate-Land-Grobzellen: 150.103,
- Work Regions mit höchstens 4 Zellen: 52,
- mit höchstens 16 Zellen: 64,
- mit höchstens 64 Zellen: 74,
- Sea-Any-Zellen: 168.127,
- Pure-Sea-Zellen: 160.115.

Die frühere kleine slowenische Pilotzelle gehört mit der sicheren Regel
korrekt zur großen zusammenhängenden Küsten-Work-Region.

Damit war klar, dass

`ganze Work Region -> vollständiges Highres-DEM -> danach Domains`

nicht der Produktionspfad sein kann. Die größte sichere Work Region wäre in
Source-Fidelity-Auflösung bereits **vor** der späteren Component-Zerlegung zu
groß.

## Lazy Highres-Domains vor vollständiger Materialisierung

Der skalierbare Pfad teilt eine große sichere Work Region deshalb bereits vor
dem vollständigen Highres-DEM in numerische Domains.

`scripts/process_lazy_domains.py` implementiert die monotone
Domain-Konvergenz mit einem Materializer-Callback:

1. eine aktive Domain auswählen,
2. nur ihre lokalen Daten materialisieren,
3. bekannte Randthresholds als Boundary-Seeds einspielen,
4. Domain-Priority-Flood rechnen,
5. verbesserte Randthresholds an Nachbardomains weitergeben,
6. Domain-Dateien sofort wieder löschen,
7. eine Nachbardomain nur dann erneut rechnen, wenn sich ihr Rand verbessert.

Der generische synthetische Referenztest enthält auch einen Sea-Kontakt exakt
über einer Domain-Grenze und ist auf allen Work-Region-Zellen bytegleich mit
einem globalen Priority-Flood.

Die Ausgabe kann ebenfalls sparse erfolgen: statt eines riesigen rechteckigen
Highres-Rohfiles wird pro aktiver Domain eine Threshold-Datei geschrieben.

## Sparse Domainplanung aus RLE

`scripts/plan_lazy_work_region_domains.py` projiziert die groben RLE-Spans in
das Fine-Raster und plant nur numerische Domains, die den Work-Region-Core
tatsächlich schneiden.

Leere Domains innerhalb der Bounding Box werden nicht materialisiert und
erzeugen auch keine Threshold-Ausgabe.

## Lazy Mapterhorn-Materialisierung

`scripts/materialize_mapterhorn_work_region_domain.py` materialisiert eine
einzige numerische Domain:

- nur die benötigten Mapterhorn-ZXY-Tiles,
- HTTP-Parent-Fallback für fehlende High-Zoom-Tiles,
- RLE-Core als Fine-Landmaske,
- Elevation außerhalb des Cores wird `NaN`,
- Sea-Maske aus OSM-Wasserpolygonen,
- zusätzlicher 1-Pixel-Sea-Rand für Küstenkontakte außerhalb der Domain.

`scripts/process_lazy_mapterhorn_work_region.py` verbindet diesen Materializer
mit dem lazy Domain-Solver und schreibt sparse Threshold-Domains.

### Realer Multi-Domain-Pilot

Eine sichere reale Faktor-16-Work-Region wurde vollständig über diesen Pfad
gerechnet und gegen einen globalen QA-Priority-Flood derselben Region
verglichen.

Work Region:

- Component-ID: 5,
- 1.569 grobe Candidate-Zellen,
- 424 RLE-Spans,
- Source: `glo30`,
- native Auflösung: 30 m,
- Source-Fidelity: **Z11**.

Fine-Raster der QA-Bounding-Box:

- 1.024 x 3.584,
- 3.670.016 Zellen,
- 14 mögliche 512-x-512-Domains,
- davon nur **12 aktive sparse Domains**.

Lazy-Lauf:

- 23 Solver-Läufe,
- 23 Domain-Materialisierungen,
- 1.569 verbesserte Domain-Randwerte,
- 416 externe Sea-Randverbesserungen,
- maximal gleichzeitig materialisiert:
  **512 x 512 = 262.144 Zellen**,
- temporäre Domain-Daten nach jedem Lauf vollständig gelöscht,
- sparse Threshold-Ausgabe: 12 Dateien / 3.145.728 Bytes,
- Peak-RSS des gesamten Python-Laufs: **227.344 KiB**,
- Laufzeit: **17,77 s**.

Bytevergleich:

- verglichene Work-Region-Landzellen: **401.664**,
- abweichende Zellen: **0**,
- nicht-Sentinel-Zellen außerhalb des Work-Region-Cores: **0**,
- fehlende Domain-Ausgaben: **0**.

Damit ist die reale Kette

`sichere grobe RLE-Work-Region -> sparse Fine-Domains -> Domain einzeln
materialisieren -> Randthresholds austauschen -> Domain löschen`

fachlich validiert.

Der Pilot liegt allerdings nur auf `glo30` und damit Z11. Er beweist die reale
lazy Mapterhorn-/Sea-/RLE-Kopplung und Domain-Konvergenz, aber **noch nicht die
Skalierung einer großen Z14-/Z16-Work-Region**.

## Aktueller Produktionspfad

Der geplante reguläre Ablauf ist jetzt:

1. gestreamtes grobes Parent-DEM,
2. konservativer Grob-Candidate mit Sea-Any,
3. sichere grobe Work Regions mit Pure-Sea,
4. eine RLE-Work-Region auswählen,
5. Core-Geometrie gegen echte Mapterhorn-Coverage schneiden,
6. Source-Fidelity-Zoom des Cores bestimmen,
7. nur aktive Fine-Domains aus dem RLE-Core planen,
8. **eine Fine-Domain materialisieren**,
9. Priority-Flood mit Sea- und Boundary-Seeds rechnen,
10. verbesserte Randthresholds weitergeben,
11. Domain-Daten freigeben,
12. bei Randverbesserung betroffene Domain erneut rechnen,
13. konvergierte Threshold-Domain sparse schreiben,
14. nächste Work Region.

Damit ist der RAM-Verbrauch nicht mehr von der Gesamtfläche einer
zusammenhängenden Küsten-Work-Region abhängig, sondern primär von der gewählten
numerischen Domain-Größe.

## Nächster Prüfpunkt

Als Nächstes werden die **87 sicheren Faktor-16-Work-Regions** gegen die echten
Mapterhorn-Coverage-Geometrien gescannt.

Gesucht wird gezielt eine reale Work Region mit:

- Source-Fidelity > Z11, idealerweise Z14-Z16,
- mehr als einer aktiven Fine-Domain,
- noch überschaubarer Gesamtgröße für einen globalen QA-Referenzlauf.

An dieser Region wird derselbe lazy Bytevergleich wiederholt. Erst danach wird
die sehr große 96,73-%-Work-Region ohne globale Referenz auf den
Source-Fidelity-Pfad losgelassen.

