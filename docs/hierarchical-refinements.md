# Hierarchische Refinements

Stand: 31. August 2026

## Ziel

Eine globale oder europäische Basis soll in ungefähr nativer globaler
DEM-Auflösung gerechnet werden. Küstenregionen mit besseren DTMs sollen danach
feiner gerechnet werden können, ohne dass jedes Refinement bis zum offenen Meer
reichen muss.

Dazu übernimmt das feinere Raster die bereits bekannte Meer-Konnektivität des
gröberen Rasters an seinem äußeren Rand.

## Prinzip

Für ein Refinement werden verwendet:

1. feines lokales DEM,
2. echte Ocean-Seeds innerhalb des Refinement-Ausschnitts, falls vorhanden,
3. grobe Inundation-Thresholds am äußeren Refinement-Rand.

Für jede feine Randzelle wird der Parent-Threshold über den Zellmittelpunkt
abgetastet.

Der initiale Randwert lautet:

`fine_seed = max(parent_threshold, fine_elevation)`

Damit kann eine grobe Parent-Zelle keine im feinen DEM höhere lokale Randbarriere
unterschlagen.

Parent-Sentinel `101` bedeutet innerhalb des 0–100-m-Modells keinen nutzbaren
Randweg. `255` bedeutet kein Boundary-Seed.

## Priority-Flood-Kern

`src/priority_flood_quantized.cpp` unterstützt nun optional:

`--boundary-threshold <boundary.u8>`

Die Boundary-Datei hat dieselbe Rastergröße wie das feine DEM:

- 0–100 = aktiver Randseed,
- 101 = Parent-Sentinel,
- 255 = kein Seed.

Aktive Boundary-Seeds sind nur auf dem äußersten Rasterrand zulässig. Ein
versehentlicher Interior-Seed führt zum Fehler, damit keine künstlichen
Abkürzungen unbemerkt in einen Build gelangen.

### Wichtige Änderung: echte Relaxation

Mit unterschiedlich hohen Randseeds reicht die frühere Regel
`first enqueue wins` nicht mehr.

Beispiel:

- rechter Rand wird vom groben Parent mit 8 m initialisiert,
- im Refinement existiert aber ein besserer interner Weg vom Meer mit 4 m.

Der 8-m-Wert muss auf 4 m verbessert werden können.

Der C++-Kern verwendet deshalb nun eine Dial-/Bucket-Relaxation:

- ein kleinerer gefundener Threshold ersetzt einen höheren vorläufigen Wert,
- veraltete Bucket-Einträge werden beim Abarbeiten übersprungen,
- die Speicherstruktur bleibt weiterhin sehr kompakt.

Die alte Ocean-only-Berechnung bleibt dadurch unverändert korrekt.

## Boundary-Erzeugung

Neues Tool:

`scripts/build_refinement_boundary.py`

Eingaben:

- Parent-`grid.json`,
- Parent-`threshold.u8`,
- Fine-`grid.json`.

Ausgabe:

- `boundary.u8`,
- `boundary.report.json`.

Nur der äußere Fine-Rand wird befüllt. Das Rasterinnere bleibt `255`.

## Refinements ohne eigenes Meer

`scripts/write_ocean_mask_raw.py` unterstützt:

`--allow-empty-sea`

Damit kann ein Binnen-Refinement eine komplett leere Ocean-Maske besitzen. In
diesem Fall muss der Flood vollständig über Boundary-Seeds initialisiert werden.

Der C++-Kern akzeptiert einen Build, wenn mindestens eine der beiden Quellen
nutzbare Seeds liefert:

- Ocean-Seeds oder
- Boundary-Seeds.

## Halo und veröffentlichter Core

Ein Refinement soll nicht bis unmittelbar an seinem Boundary-Rand veröffentlicht
werden.

Empfohlen:

```text
Parent/Base
┌───────────────────────────────┐
│                               │
│   Fine work area              │
│   ┌───────────────────────┐   │
│   │ Halo                  │   │
│   │   ┌───────────────┐   │   │
│   │   │ publish core  │   │   │
│   │   └───────────────┘   │   │
│   │                       │   │
│   └───────────────────────┘   │
│                               │
└───────────────────────────────┘
```

Die groben Randbedingungen wirken am äußeren Work-Rand. Veröffentlicht wird nur
der innere Core. Dadurch liegen mögliche Parent-/Fine-Diskretisierungsfehler am
Rand außerhalb des sichtbaren Refinements.

Die notwendige Halo-Breite wird regional getestet; im ersten realen Benchmark
wurde eine Z12-Tilebreite bzw. 512 Pixel verwendet.

## Realer Benchmark Z11 → Z12

Gebiet:

Rotterdam / Delft / Westland.

Aufbau:

- Parent: vollständige küstenverbundene Z11-Berechnung,
- Referenz: vollständige küstenverbundene Z12-Berechnung,
- Refinement-Workarea: Z12, 2048 × 2048 Pixel,
- Publish-/Prüfcore: 1024 × 1024 Pixel,
- Halo: eine Z12-Tilebreite,
- Parent-Boundary: 8.188 Randzellen.

### Erster Lauf mit echten Ocean-Seeds

Die Workarea enthielt 48.786 OSM-Ocean-Seedpixel.

Ergebnis im Core:

- 100 % pixelgenau identisch zur vollständigen Z12-Referenz,
- maximale Thresholdabweichung: 0 m.

### Strenger Boundary-only-Lauf

Für den Kontrolllauf wurden die vorhandenen 48.786 Ocean-Seeds im Refinement
absichtlich auf null gesetzt.

Verwendet wurden ausschließlich:

**8.188 Z11-Boundary-Seeds**

mit Parent-Thresholds von 0 bis 21 m.

Der C++-Flood verarbeitete alle 4.194.304 Workarea-Zellen:

- Sea-Seeds: 0,
- Boundary-Seeds: 8.188,
- stale Bucket-Einträge: 91,
- Sentinel/Disconnected: 0.

Vergleich des 1.048.576-Pixel-Cores mit der vollständigen Z12-Referenz:

| Kennzahl | Ergebnis |
| --- | ---: |
| exakt gleiche Pixel | **100,000 %** |
| mittlere absolute Abweichung | **0,000 m** |
| Median-Abweichung | **0,000 m** |
| maximale Abweichung | **0 m** |
| Pixel >1 m Unterschied | **0 %** |
| Pixel >2 m Unterschied | **0 %** |
| Pixel >5 m Unterschied | **0 %** |

Auch alle geprüften Flächenanteile für 0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 20, 50
und 100 m stimmen exakt überein.

Damit ist für diesen realen Fall nachgewiesen, dass ein feines Binnen-Refinement
die korrekte Meer-Konnektivität vollständig über den gröberen Parent-Rand erben
kann.

## Grid-Korrektur

Während der Benchmark-Vorbereitung wurde ein Randfall in `scripts/grid.py`
korrigiert.

Wenn East oder South exakt auf einer XYZ-Tilekante lagen, wurde bisher die
nächste außerhalb liegende Tile zusätzlich aufgenommen.

East/South werden nun korrekt als exklusive Bounding-Box-Grenzen behandelt.

Beispiel:

Ein gewünschter Z12-Ausschnitt X 2098–2099 / Y 1353–1354 ergibt jetzt exakt:

- 2 × 2 Tiles,
- 1024 × 1024 Pixel.

Dieser Fall ist durch `tests/test_grid.py` abgesichert.

## Tests

Automatisch getestet werden nun:

- Ocean-only Priority Flood,
- reines Boundary-Refinement ohne Sea-Seeds,
- Verbesserung eines zu hohen vorläufigen Boundary-Seeds durch einen besseren
  internen Weg,
- coarse-to-fine Boundary-Projektion,
- exakte XYZ-Gridgrenzen,
- Rasterpyramiden-Downsampling.

## Produktionsmodell

Damit ist die geplante Hierarchie technisch möglich:

```text
Tier 1
globale / europäische Basis ~25–40 m
        │
        │ Parent-Threshold am Rand
        ▼
Tier 2
Küsten-Refinement ~10–15 m
        │
        │ optional erneut Parent für Tier 3
        ▼
Tier 3
kritische Bereiche ~5–6 m
```

Tier 2 oder Tier 3 müssen nicht selbst bis zum offenen Meer reichen.

Ein Tier kann gleichzeitig:

- echte lokale Ocean-Seeds und
- geerbte Parent-Boundary-Seeds

verwenden. Der jeweils beste Weg setzt sich durch die Relaxation durch.

## Transition Collar zwischen Fine und Base

Der erste zusammengesetzte Phase-1C-Build zeigte, dass ein Wechsel exakt an der
Mapterhorn-Source-Coverage fachlich ungünstig sein kann.

Ohne Übergangspuffer lagen einzelne Source-Grenzen direkt auf schmalen
hydraulischen Strukturen oder Source-Lücken. Im westlichen Niederlande-Pilot
ergab die Seam-QA:

- 137.013 Randpixel,
- 92,04 % exakt gleich,
- mittlere absolute Differenz 0,0818 m,
- maximale Differenz 14 m,
- 0,0029 % der Randpixel >5 m Unterschied.

Die Lösung ist ein **Transition Collar**:

1. die echte High-Resolution-Source-Coverage wird als fachlicher Kern erkannt,
2. dieser Kern wird in Web Mercator nach außen gepuffert,
3. auch der Puffer wird auf Fine-Zoom gerechnet,
4. erst am äußeren Pufferrand wird zurück auf die Base gewechselt,
5. außerhalb des Fine-Puffers liefert Mapterhorn weiterhin sein aggregiertes
   Fallback-Terrain.

Damit liegt der Base/Fine-Wechsel nicht mehr zwingend auf einer Küstenlinie,
einem Damm oder einer Source-Lücke.

### Getestete Anfangsregel

Phase 1C verwendet zunächst:

`transition_buffer_pixels = 128`

Bei Z12 entspricht das ungefähr 2,45 km in EPSG:3857 und in den Niederlanden
grob 1,5 km Bodenentfernung.

Der Priority-Flood-Halo bleibt davon getrennt:

`halo_tiles = 1`

Der Halo liegt außerhalb des veröffentlichten Refinement-Cores und dient weiterhin
nur dazu, Parent-Randbedingungen vom sichtbaren Fine/Base-Übergang fernzuhalten.

### Phase-1C-Ergebnis mit 128-Pixel-Collar

- Fine-Workarea: 1.064 Z12-Tiles,
- 121.261.545 Fine-Pixel im Composite,
- gemeinsames Ausgaberaster: 358.612.992 Z12-Zellen,
- fertiges PMTiles: rund 10,8 MB,
- PMTiles-Verify erfolgreich.

Echte Refinement-Seam gegen hochskalierte Z11-Base:

| Kennzahl | ohne Collar | 128-Pixel-Collar |
| --- | ---: | ---: |
| exakt gleich | 92,04 % | **97,82 %** |
| mittlere absolute Differenz | 0,0818 m | **0,0229 m** |
| maximale Differenz | 14 m | **4 m** |
| >1 m Unterschied | 0,1109 % | **0,0888 %** |
| >2 m Unterschied | 0,0562 % | **0,0209 %** |
| >5 m Unterschied | 0,0029 % | **0 %** |

Der zuvor beobachtete 14-m-Ausreißer verschwindet vollständig aus der
Refinement-Seam.

128 Pixel werden deshalb für Phase 1C als **getestete Anfangsregel** übernommen.
Die Größe ist kein universeller Naturwert und bleibt pro Region
konfigurierbar/QA-pflichtig.

## Coverage-Kontext

Der Coverage Planner lädt nun standardmäßig zusätzlich einen kleinen räumlichen
Kontext um die angeforderte Planungs-BBox.

Ausgaben:

- `sources.geojson`: auf das eigentliche Planungsgebiet zugeschnitten,
- `sources-context.geojson`: Source-Geometrien mit zusätzlichem Kontext für
  Refinement-Planung.

Damit kann `prepare_refinement_region.py` unterscheiden zwischen:

- echter Mapterhorn-Source-Grenze,
- Transition Collar,
- Parent-/Pilot-BBox-Clipping.

Das verhindert, dass ein künstlicher Planungsrand als echte Source-Grenze
fehlinterpretiert wird.

## Zusammensetzen der Ausgabe

Für die gemeinsame PMTiles-Ausgabe gilt nun:

1. Base-Threshold bildet die vollständige Fläche ab.
2. Source-Coverage bestimmt, wo ein Refinement fachlich sinnvoll ist.
3. Ein konfigurierbarer Transition Collar erweitert den veröffentlichten
   Fine-Core.
4. Außerhalb des Cores liegt zusätzlich der Priority-Flood-Halo.
5. Parent-Thresholds initialisieren den äußeren Fine-Work-Rand.
6. Nur Core + Transition Collar überschreiben die Base-Zellen.
7. Bei mehreren Refinement-Stufen gewinnt die feinste freigegebene Stufe.
8. Tile-/Zoom-Pyramiden werden erst nach dem fachlichen Merge erzeugt.

Damit gibt es in MapLibre weiterhin nur einen logischen
`inundation_threshold`-Datensatz. Der Browser muss weder Parent noch
Refinement-Grenzen kennen.

## Aktueller Produktionsstand

Der erste vollständige hierarchische Phase-1C-Pilot funktioniert:

`Mapterhorn Coverage → Z11 Base → AHN Z12 + Collar + Halo → Parent-Boundary → Fine Priority Flood → Composite → Z6–Z12-Pyramide → PMTiles`

Das resultierende PMTiles wurde erfolgreich verifiziert.

Der nächste Schritt ist daher kein weiterer Algorithmus-Prototyp mehr, sondern
der erste visuelle Test dieses zusammengesetzten Datensatzes in der
Kartensammlung und anschließend die Planung eines größeren Parent-Gebiets.
