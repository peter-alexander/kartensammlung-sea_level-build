# Meeresspiegel – Produktionsarchitektur

Status: Entwurf nach erfolgreichem End-to-End-Prototyp Hoek van Holland / Westland

## Ziel

Das Kartenoverlay `Meeresspiegel` soll weltweit oder großregional eine terrainbasierte,
mit dem Meer verbundene Überflutungsdarstellung liefern.

Der Browser führt keine Flood-Berechnung aus. Die aufwendige Topologie wird offline
vorberechnet. Im Client wird nur noch ein vorberechneter Schwellenwert-Datensatz
gegen den Meeresspiegel-Slider verglichen.

## Semantik des Datensatzes

Jede Rasterzelle speichert den niedrigsten Meeresspiegel, bei dem diese Zelle über
einen zusammenhängenden Geländeweg vom offenen Meer erreichbar wird.

Beispiel:

- reale Höhe der Zelle: -4 m
- niedrigster Weg zum Meer führt über eine 5,84-m-Barriere
- exakter Inundation Threshold: 5,84 m
- bei einem Slider mit 1-m-Schritten gespeicherte Klasse: 6 m

Das verhindert das fachlich falsche Bathtub-Verhalten `Geländehöhe <= Meeresspiegel`.

## Festgelegte Grundentscheidungen

### 1. Offline statt Browser

Priority Flood / Minimax-Konnektivität wird vollständig offline berechnet.

Vorteile:

- keine CPU-/RAM-Last im Browser,
- keine viewportabhängigen Flood-Fills,
- keine Tile-Grenzprobleme im Client,
- reproduzierbarer Datensatz,
- sehr leichte Slider-Interaktion.

### 2. 4er-Nachbarschaft

Für die Produktionsberechnung wird zunächst 4er-Nachbarschaft verwendet.

Der Rotterdam/Zeeland-Test zeigte, dass 8er-Nachbarschaft Wasser diagonal durch
Pixelecken gelangen lässt und Barrieren deutlich leichter überwindet.

### 3. Maximaler Modellpegel zunächst +100 m

Der aktuelle Slider reicht von 0 bis 100 m.

Zellen, deren Inundation Threshold über 100 m liegt, müssen für V1 nicht exakt
gespeichert werden. Sie erhalten einen gemeinsamen Sentinelwert.

Dadurch können:

- Berechnung und Ausgabe auf den tatsächlich relevanten Höhenbereich begrenzt werden,
- hochliegende Binnengebiete aus der Ausgabe entfallen,
- die Rasterdaten wesentlich stärker komprimieren.

### 4. Quantisierung auf Slider-Schritte

V1 verwendet 1-m-Schritte.

Der exakte Threshold wird für die Ausgabe auf den ersten sichtbaren Sliderwert
aufgerundet:

`stored_threshold = ceil(exact_threshold)`

Aus 5,84375 m wird also 6 m.

Erforderliche Klassen:

- 0 bis 100
- Sentinel für >100 / außerhalb des Modellbereichs

Die interne Berechnung darf weiterhin mit höherer Genauigkeit arbeiten.

## Eingabedaten

### DEM

#### Produktionsbasis V1

Bevorzugte Basis ist ein konsistenter globaler DEM mit ungefähr 30 m nativer
Auflösung.

Mapterhorn ist für die Kartensammlung besonders attraktiv, weil:

- die Kartensammlung Mapterhorn bereits verwendet,
- ein globaler 30-m-Datensatz verfügbar ist,
- PMTiles-Downloads und Gebietsextrakte unterstützt werden,
- zahlreiche Regionen zusätzlich höher aufgelöste offene DEMs besitzen.

Für die globale V1 sollte dennoch bewusst nur eine klar definierte Basisauflösung
verwendet werden. Hochauflösende regionale Verfeinerungen kommen als eigener
zweiter Schritt.

Wichtig: Mapterhorn kombiniert verschiedene offene Datenquellen. Vor einer
öffentlichen Veröffentlichung des abgeleiteten Threshold-Datensatzes muss die
Lizenz- und Attribution-Kette der tatsächlich verwendeten Quellen geprüft und
dokumentiert werden.

#### Alternative globale DEMs

Copernicus DEM GLO-30:

- global ungefähr 30 m,
- EGM2008 als vertikales Referenzsystem,
- gut dokumentiert,
- allerdings DSM statt reinem DTM: Gebäude und Vegetation können falsche Barrieren
  erzeugen.

FABDEM:

- ungefähr 30 m global,
- Gebäude und Waldhöhen aus Copernicus GLO-30 weitgehend entfernt,
- fachlich für Flood-Connectivity attraktiv,
- Lizenz CC BY-NC-SA 4.0 / nicht-kommerzielle Nutzung; daher vor einer Festlegung
  bewusst gegen die gewünschte Lizenzfreiheit der Kartensammlung abwägen.

### Regionale Verfeinerungen

Später können nationale oder regionale DTM-Daten mit höherer Auflösung eingesetzt
werden.

Anforderungen:

- echte Geländehöhe bevorzugt gegenüber DSM,
- bekannte vertikale Referenz,
- Lizenz erlaubt abgeleitete und veröffentlichte Produkte,
- saubere Transformation auf das gemeinsame vertikale Datum,
- Übergänge zur globalen Basis werden geprüft.

Die regionale Verfeinerung darf nicht einfach einen hochauflösenden Ausschnitt
unabhängig flood-fillen. Die Meer-Konnektivität muss mit dem umgebenden Modell
konsistent bleiben.

## Vertikales Datum

Der Produktionsdatensatz benötigt ein explizit dokumentiertes vertikales Datum.

Ziel für V1: EGM2008 / orthometrische Höhe, sofern die verwendete DEM-Basis dies
durchgehend unterstützt.

Für jede Quelle werden gespeichert:

- horizontales CRS,
- vertikales Datum,
- Einheit,
- notwendige Transformation,
- ursprüngliche Quelle und Version.

Wichtig: Eine OSM-Küstenlinie repräsentiert nicht exakt dieselbe physikalische
Nullfläche wie EGM2008. Deshalb bleibt die Darstellung eine terrainbasierte
Meeresspiegel-Simulation und kein lokales Tiden- oder Küsteningenieurmodell.

## Meer-/Küstenmaske

### Produktionsvorschlag

OSM-Wasserpolygone aus `osmdata.openstreetmap.de`.

Vorteile:

- aus `natural=coastline` erzeugt,
- enthält Ozeane und Meere,
- enthält gerade nicht automatisch Seen und Reservoirs,
- wesentlich detaillierter als Natural Earth,
- bereits mit OSMCoastline topologisch aufbereitet.

Natural Earth bleibt für grobe Tests brauchbar, ist für die Produktionsauflösung
aber zu grob.

### Seed-Regel

Nur echte Ozean-/Meereszellen sind initiale Seeds.

- Seed-Threshold = 0
- Binnenseen sind keine Seeds
- unter dem Meeresspiegel liegende Binnensenken sind keine Seeds
- Flüsse werden nicht pauschal als Meer markiert

Tidenflüsse und Ästuare können über das Gelände/DEM vom Meer aus erreicht werden.

## Berechnung

### Mathematische Definition

Für eine Zelle wird der Weg zum Meer gesucht, dessen höchster Geländepunkt möglichst
niedrig ist.

Für einen Schritt:

`next_threshold = max(current_threshold, neighbor_elevation)`

Von mehreren Wegen wird der kleinste resultierende Schwellenwert verwendet.

### Höhenlimit

Für V1 interessiert nur der Bereich bis +100 m.

Zellen deutlich oberhalb dieses Grenzwerts können als Barrieren behandelt werden.
Ein Weg, der über >100 m führen müsste, kann innerhalb des aktuellen Sliders ohnehin
nie relevant werden.

### Arbeitsraster

Die Berechnung erfolgt in der nativen oder bewusst festgelegten Basisauflösung des
DEM, nicht in einer künstlich höher aufgelösten Web-Mercator-Zoomstufe.

Webkarten-Zoomstufen sind Ausgabeformat, nicht Berechnungsauflösung.

### Skalierung

Der Python-Prototyp ist Referenzimplementierung und Testwerkzeug.

Für große Produktionsgebiete sollte die Kernberechnung später in einer
speicher- und laufzeiteffizienteren Implementierung erfolgen, sobald reale
Pilotgrößen zeigen, dass Python nicht mehr ausreicht.

Mögliche Wege:

- NumPy + kompakte Arrays,
- Numba,
- C++ oder Rust,
- externer / chunkbasierter Priority-Queue-Ansatz.

Nicht verwenden:

- unabhängiger Flood-Fill pro XYZ-Tile,
- unabhängiger Flood-Fill pro Viewport,
- Regionstiles ohne globale Randbedingungen.

## Zwischenprodukt

Empfohlenes kanonisches Zwischenprodukt:

- Cloud Optimized GeoTIFF oder ein vergleichbar robustes Rasterformat,
- exakter oder ausreichend fein quantisierter Threshold,
- explizites CRS und vertikales Datum,
- Quellen-/Versions-Metadaten.

Dieses Zwischenprodukt dient:

- Qualitätskontrolle,
- erneuter Kachelerzeugung ohne Flood-Neuberechnung,
- Vergleich verschiedener Darstellungsformate,
- Reproduzierbarkeit.

## Web-Ausgabe

### Format

Empfehlung: Raster-Dem als Terrarium-kodierte PNG-Tiles in einem PMTiles-Archiv.

MapLibre unterstützt `raster-dem` aus PMTiles mit Terrarium-Encoding.

Vorteile:

- ein deploybares Archiv statt sehr vieler Einzeldateien,
- HTTP Range Requests,
- bestehende PMTiles-Infrastruktur der Kartensammlung,
- `color-relief` kann den Threshold direkt als `elevation` lesen,
- keine zusätzliche Clientbibliothek oder neue Renderinglogik.

### Tile-Größe

512 × 512 Pixel.

### Maxzoom

Der Maxzoom wird an die reale Quellauflösung angepasst.

Eine globale 30-m-Basis soll nicht künstlich als hochauflösendes DEM gerechnet
werden. Eine höhere Web-Zoomstufe kann als Darstellungs-/Oversamplingstufe dienen,
liefert aber keine zusätzliche Geländeinformation.

Der konkrete globale Maxzoom wird nach einem größeren Pilotbuild festgelegt.

### Leere Tiles

Tiles ohne Zellen mit Threshold <= 100 m werden nach Möglichkeit nicht gespeichert.

Damit konzentriert sich das Archiv auf Küsten- und niedrig liegende,
meerrelevante Gebiete.

### Niedrige Zoomstufen

Für die PMTiles-Pyramide muss eine definierte Downsampling-Regel festgelegt werden.

V1-Vorschlag:

- hohe Zooms: echte Thresholdwerte,
- niedrigere Zooms: konservative Aggregation mit Minimum bzw. einer eigens getesteten
  Flood-Darstellungsregel,
- sehr niedrige Zooms gegebenenfalls ausblenden, wenn die Rasteraggregation zu
  irreführend wird.

Diese Entscheidung wird anhand eines Westeuropa-Piloten visuell geprüft.

## Client

Der Client bleibt sehr einfach:

1. `raster-dem`-PMTiles-Source laden.
2. `color-relief`-Layer verwenden.
3. Sliderwert verändert nur die Paint-Expression.
4. `threshold <= slider` wird blau dargestellt.
5. `threshold > slider` bleibt transparent.

Keine Flood-Berechnung im Browser.

Der aktuelle Hoek-van-Holland-Prototyp ist bereits ein funktionierender
End-to-End-Nachweis dieser Architektur.

## Metadaten des Produktionsartefakts

Neben dem PMTiles-Archiv wird ein Manifest veröffentlicht, z. B. `latest.json`.

Mindestens:

- build_id
- created_at
- threshold_min
- threshold_max
- threshold_step
- sentinel_value
- connectivity
- DEM-Quelle
- DEM-Version/Snapshot
- DEM-Auflösung
- horizontales CRS
- vertikales Datum
- Küstenmasken-Quelle
- Küstenmasken-Snapshot
- Ausgabe-Maxzoom
- PMTiles-URL
- bounds
- Attributionen
- Lizenzhinweise
- Qualitäts-/Modellhinweis

## Versionierung

Keine unversionierte Datei überschreiben, ohne die Version nachvollziehbar zu
machen.

Empfehlung:

- `sea-level-threshold-YYYYMMDD.pmtiles`
- `latest.json` zeigt auf die aktuelle Version.

Dadurch kann die Kartensammlung stabil auf `latest.json` oder bewusst auf einen
fixen Build zeigen.

## Build-Repository

Für den Produktionsbuild wird ein eigenes Repository empfohlen, statt die schwere
Datenpipeline dauerhaft in `kartensammlung-maplibre` zu betreiben.

Arbeitstitel:

`kartensammlung-sea_level-build`

Inhalt:

- Source-Konfiguration
- Downloader
- Datum-/CRS-Normalisierung
- Coastline-Rasterisierung
- Priority-Flood
- Quantisierung
- QA
- Terrarium-Export
- PMTiles-Erzeugung
- Manifest
- Deployment-Workflow

Im MapLibre-Repo bleibt nur:

- Overlaydefinition
- Panel
- Clientintegration
- kleine Testdaten bei Bedarf

## Qualitätssicherung

Jeder Build erzeugt automatisch:

- Min/Max der DEM-Werte,
- Min/Max der Thresholds,
- Anteil Seed-Zellen,
- Fläche nach Thresholdklasse,
- Vergleich Bathtub vs. Connectivity,
- Stichproben bekannter Senken/Polder,
- Vorschau-GeoTIFFs oder PNGs,
- Prüfung auf NaN/NoData,
- Prüfung auf Tile-Nähte,
- Terrarium-Roundtrip-Test.

Referenztests:

- Niederlande / Polder
- Kaspische Senke als Nicht-Ozean-Senke
- Death Valley als Nicht-Ozean-Senke
- schmale Inseln und Küsten
- Ästuare
- Gebiete mit hohen Deichen / Dünen
- Inseln mit Binnenmulden

## Modellgrenzen

Auch der fertige Datensatz ist kein hydrodynamisches Hochwassermodell.

Nicht oder nur indirekt berücksichtigt:

- Deichbruch
- Schleusen und Pumpwerke
- Sturmflut
- Wellen
- Tiden
- Grundwasser
- zeitabhängige Fließgeschwindigkeit
- Abflusskapazitäten
- Niederschlag
- zukünftige Küstenschutzmaßnahmen
- Gebäude als hydraulische Einzelobjekte

Die öffentliche Beschreibung soll deshalb Begriffe wie
`terrainbasierte Meeresspiegel-Simulation` verwenden.

## Empfohlene Umsetzungsschritte

### Phase 1 – Produktionspilot Nordsee

Gebiet:

- Niederlande
- Belgien
- Nordwestdeutschland
- Ärmelkanal/Nordsee als Seed-Raum

Ziele:

- OSM-Ocean-Maske statt Natural Earth,
- native DEM-Auflösung,
- vollständiger Threshold 0–100 m,
- Quantisierung auf 1 m,
- PMTiles-Pyramide,
- echte Dateigröße und Laufzeit messen,
- niedrige Zoomstufen beurteilen.

### Phase 2 – Westeuropa

Nach erfolgreichem Nordsee-Pilot:

- größere zusammenhängende Küstenregion,
- Speicher-/Laufzeitstrategie validieren,
- Quellen- und Lizenzmanifest finalisieren.

### Phase 3 – Globaler 30-m-Basisdatensatz

Erst wenn die reale Größe und Performance aus Phase 1 und 2 bekannt sind.

### Phase 4 – Regionale High-Resolution-Verfeinerungen

Nur für Regionen mit geeigneten offenen DTM-Daten und sauberem vertikalem Datum.

## Nächste konkrete Aufgabe

Als nächstes wird ein Nordsee-Produktionspilot gebaut.

Vor dem Build werden festgelegt:

1. konkreter Ausschnitt,
2. DEM-Basis,
3. OSM-Wasserpolygon-Snapshot,
4. Processing-Raster,
5. PMTiles-Maxzoom,
6. Downsampling-Regel für niedrige Zooms.

Danach messen wir reale Buildzeit, Peak-RAM und Archivgröße und entscheiden auf
dieser Grundlage über Westeuropa und global.
