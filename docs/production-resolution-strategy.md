# Produktionsauflösung und DEM-Strategie

Stand: 31. August 2026

## Entscheidung in Kurzform

Für die Meeresspiegel-Simulation wird **nicht automatisch die höchste verfügbare
DEM-Auflösung verarbeitet**.

Stattdessen wird eine abgestufte Strategie verwendet:

1. globale Basis nahe der nativen globalen DEM-Auflösung,
2. regionale Küsten-Verfeinerung auf ungefähr 10–15 m Ziel-Bodenpixel, sofern
   eine ausreichend gute DTM-Quelle vorhanden ist,
3. noch feinere 5–6-m-Verarbeitung nur dort, wo ein eigener QA-Test einen
   relevanten fachlichen Gewinn zeigt.

Der Hoek-van-Holland/Rotterdam-Benchmark zeigt, dass bei einem nativen 5-m-DTM
eine Verarbeitung mit ungefähr 11,8 m Bodenpixel bereits fast identische
Connectivity-Ergebnisse wie ungefähr 5,9 m liefert.

## Datenquellen

### Mapterhorn

Mapterhorn bleibt die bevorzugte Aggregationsquelle.

Vorteile:

- globale Basis ungefähr 30 m,
- zahlreiche regionale hochauflösende DTM-Quellen,
- einheitliches Terrarium-Ausgabeformat,
- offene Source-Pipeline,
- Quellen und Lizenzen über den Source Catalog nachvollziehbar.

Für die Niederlande enthält Mapterhorn aktuell:

- Source: `nlahn5lowresfilled`
- Actueel Hoogtebestand Nederland, AHN5
- DTM 5 m
- Lizenz: CC BY 4.0
- Zugriff/Buildstand: 2025

Die Mapterhorn-Website weist die Niederlande derzeit als teilweise mit 5-m-Daten
abgedeckt aus.

Wichtig: Die derzeit noch offene Mapterhorn-Arbeit an niederländischen AHN-Daten
zeigt, dass sich die High-Resolution-Abdeckung weiterentwickeln kann. Ein
Produktionsbuild muss deshalb immer Source-/Versionsmetadaten speichern und darf
nicht stillschweigend auf ein veränderliches `latest` vertrauen.

### AHN direkt

AHN selbst bietet unter anderem:

- DTM 0,5 m,
- DTM 5 m,
- DSM 0,5 m,
- DSM 5 m.

Die Höhen beziehen sich auf NAP; das kombinierte CRS wird als
Amersfoort / RD New + NAP height (EPSG:7415) beschrieben.

AHN ist Open Data.

Für unsere aktuelle Pipeline ist eine direkte AHN-Integration zunächst nicht nötig,
weil Mapterhorn bereits das 5-m-DTM integriert. Eine direkte Quelle bleibt aber
wertvoll für spätere Referenz- und Qualitätsprüfungen.

## Auflösungsbenchmark

### Gebiet

Hoek van Holland / Rotterdam / Westland / Delft / südliches Den Haag.

Die Benchmarkfläche wurde so gewählt, dass Z11, Z12 und Z13 exakt hierarchisch
vergleichbar sind.

### Verarbeitung

Gleiche:

- Mapterhorn-Quelle,
- OSM-Ocean-Maske,
- 4er-Nachbarschaft,
- 1-m-Thresholdquantisierung,
- Bounding Box.

Nur der Processing-Zoom wurde geändert.

| Stufe | ungefähre Bodenauflösung | Zellen |
| ---: | ---: | ---: |
| Z11 | 23,53 m | 3.145.728 |
| Z12 | 11,77 m | 12.582.912 |
| Z13 | 5,88 m | 50.331.648 |

Z13 liegt damit in der Größenordnung der nativen 5-m-AHN-Quelle.

### Punktwerte

| Ort | Z11 | Z12 | Z13 |
| --- | ---: | ---: | ---: |
| Hoek van Holland | 4 m | 4 m | 4 m |
| Maassluis | 3 m | 4 m | 4 m |
| Rotterdam Zentrum | 3 m | 4 m | 4 m |
| Westland-Polder | 3 m | 4 m | 4 m |
| Delft | 3 m | 4 m | 4 m |
| Den Haag Süd | 3 m | 4 m | 4 m |

Z11 lässt damit in diesem Bereich eine relevante Barriere um ungefähr eine
Sliderstufe zu früh durch.

### Überflutete Fläche gegenüber Z13

Besonders auffällig:

#### Z11

- +2 m: +7,0865 Prozentpunkte gegenüber Z13
- +3 m: **+40,9179 Prozentpunkte**
- +4 m: +0,1410 Prozentpunkte

Der große Fehler bei +3 m verschwindet bei +4 m wieder. Das ist typisch für einen
durch die gröbere Rasterung zu niedrig gewordenen kritischen Sattel/Deich:
eine große zusammenhängende Fläche wird genau eine Stufe zu früh erreichbar.

Für die ungefähr 1.742 km² große Benchmarkfläche entsprechen die +40,9
Prozentpunkte grob **713 km²**, die bei +3 m zu früh als meerverbunden erscheinen.

Z11 ist für diese Art von Küsten-/Poldergebiet daher fachlich zu grob.

#### Z12

- +2 m: -0,0146 Prozentpunkte
- +3 m: +0,0283 Prozentpunkte
- +4 m: -0,0186 Prozentpunkte
- +5 m: +0,3915 Prozentpunkte
- +6 m: praktisch 0

Bei +3 m entspricht die Differenz nur ungefähr 0,5 km².
Die größte beobachtete Differenz bei +5 m entspricht ungefähr 6,8 km².

### Zellweiser Vergleich gegen Z13

Z11:

- mittlere absolute Thresholdabweichung: 0,515 m
- Median: 1 m
- >1 m Unterschied: 0,418 %
- >2 m Unterschied: 0,144 %

Z12:

- mittlere absolute Thresholdabweichung: **0,022 m**
- Median: 0 m
- >1 m Unterschied: 0,107 %
- >2 m Unterschied: **0,009 %**

Damit ist Z12 dem Z13-Ergebnis sehr nahe.

## Produktionsentscheidung für High-Resolution-Küsten

### Standardziel

**10–15 m Bodenpixel.**

Für die Niederlande bei etwa 52° N entspricht das ungefähr Z12.

Begründung:

- topologisch fast identisch zu Z13,
- nur ein Viertel der Z13-Zellen,
- wesentlich weniger RAM, I/O und spätere PNG/PMTiles-Arbeit,
- 1-m-Sliderquantisierung macht einen Teil der zusätzlichen DEM-Feinheit ohnehin
  unsichtbar,
- vermeidet unnötige Verarbeitung von 0,5–5-m-Quelldaten, wenn sie im
  Endprodukt keinen messbaren Unterschied erzeugen.

### Nicht automatisch native Auflösung verwenden

Mapterhorn enthält regional unter anderem 0,4-m-, 0,5-m- und 1-m-DTMs.

Für die Meeresspiegel-Connectivity wäre es ineffizient, diese Daten pauschal mit
1-m-Pixeln durch Priority Flood zu schicken.

Eine 1-m-Quelle bedeutet nicht, dass unser Modell zwingend ein 1-m-Arbeitsraster
benötigt.

### Ausnahme: schmale hydraulisch relevante Barrieren

Deiche, Dämme oder Straßendämme können schmaler als 10 m sein.

Deshalb bleibt eine feinere Stufe von ungefähr 5–6 m vorgesehen, wenn:

- ein regionaler Benchmark bei 10–15 m eine relevante Barriere verliert,
- der feinere Lauf den Threshold sichtbar korrigiert,
- die Quelle tatsächlich genügend native Auflösung besitzt.

Z13 wird damit **QA-/Sonderstufe**, nicht Standard für jedes High-Resolution-Gebiet.

## Globale Basis

Die globale Mapterhorn-Basis liegt ungefähr bei 30 m.

Für diese Basis sollte das Arbeitsraster in derselben Größenordnung bleiben,
statt die 30-m-Daten künstlich auf 5–10 m hochzusampeln.

Zielbereich:

**ungefähr 25–40 m Bodenpixel.**

Ein einzelner Web-Mercator-Zoom entspricht weltweit nicht einer konstanten
Bodenauflösung. Die Bodenpixel werden mit zunehmender geographischer Breite kleiner.

Daher darf die endgültige globale Pipeline nicht einfach sagen:

`global = immer Z11`

sondern muss die reale Bodenauflösung bzw. die Quelldatenauflösung berücksichtigen.

## Empfohlenes hierarchisches Modell

### Tier 1 – Global Base

- globale ~30-m-Quelle,
- Threshold 0–100 m,
- vollständige weltweite/continentale Connectivity,
- Zielraster ungefähr in nativer Auflösung.

### Tier 2 – Coastal Refinement

Für Gebiete mit guten offenen DTMs:

- Ziel: 10–15 m,
- Priorität auf flache Küsten, Polder, Deltas und große Ästuare,
- regionale Berechnung mit konsistenten Randbedingungen aus Tier 1.

Beispiele:

- Niederlande,
- Belgien,
- Deutschland Küstenländer,
- Dänemark,
- Großbritannien,
- weitere Regionen mit guten nationalen DTMs.

### Tier 3 – Critical Refinement

Nur bei nachgewiesenem Nutzen:

- etwa 5–6 m,
- schmale Deich-/Damm-Systeme,
- besonders kritische Küstenabschnitte.

## Randbedingungen regionaler Verfeinerungen

Ein regionales High-Resolution-Raster darf nicht unabhängig als abgeschlossene
Insel gerechnet werden.

Für Küstenregionen mit genügend offenem Meer im Ausschnitt können Ocean-Seeds
direkt verwendet werden.

Für Binnen- oder abgeschnittene Refinements muss die grobe globale Berechnung
Rand-Thresholds liefern:

`fine_boundary_threshold = coarse_global_threshold`

Diese Randwerte werden zusammen mit echten Ocean-Seeds als initiale Bedingungen
in den feineren Priority Flood eingespeist.

Damit bleibt ein regionales Refinement topologisch mit der globalen Welt verbunden.

## Auswirkungen auf Europa

Phase 1B mit ungefähr 45 m war bewusst nur ein Skalierungstest.

Für einen echten europäischen Produktionsdatensatz wird diese Auflösung nicht
einfach übernommen.

Vorgeschlagen:

1. globale/europäische Basis in ungefähr 25–40-m-Klasse,
2. Nordseeküste als erster 10–15-m-Refinement-Layer,
3. danach weitere High-Resolution-Küstenregionen.

## Nächster technischer Schritt

Bevor Europa gebaut wird, wird die Pipeline für **hierarchische Refinements**
erweitert:

1. grober Threshold als Randbedingung einlesen,
2. High-Resolution-Region auf 10–15 m rechnen,
3. Fine-Threshold über den groben Datensatz legen,
4. Übergang am Refinement-Rand prüfen,
5. gemeinsame PMTiles-Ausgabe erzeugen.

Danach kann Phase 1A in den Niederlanden als erstes echtes Refinement des größeren
Nordsee-/Europa-Basisrasters neu aufgebaut werden.
