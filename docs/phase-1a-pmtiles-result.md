# Phase 1A – PMTiles-Pilot

Build: 31. August 2026

## Ergebnis

Der erfolgreiche Threshold-Build der westlichen Niederlande wurde als
Rasterpyramide Z6–Z11 aufbereitet und in PMTiles konvertiert.

### Archiv

- PMTiles: `output/phase1a/sea-level-threshold.pmtiles`
- Größe: **4.300.629 Bytes**
- Tile-Typ: PNG
- Kompression im PMTiles-Header: none
- Minzoom: 6
- Maxzoom: 11
- Bounds: 2.5, 51.2, 5.5, 53.2
- `pmtiles verify`: erfolgreich

Das Archiv enthält insgesamt 472 Rastertiles:

| Zoom | Tiles | PNG-Nutzdaten |
| ---: | ---: | ---: |
| 11 | 342 | 3.109.795 Bytes |
| 10 | 90 | 1.052.852 Bytes |
| 9 | 25 | 319.328 Bytes |
| 8 | 9 | 98.558 Bytes |
| 7 | 4 | 31.755 Bytes |
| 6 | 2 | 11.513 Bytes |

## Rasterpyramide

Methode:

`stratified-nearest-bayer-2x2`

Es werden nur tatsächlich vorhandene Thresholdwerte übernommen. Es entstehen
keine künstlichen Zwischenwerte.

Maximaler Flächenfehler gegenüber Z11 über die QA-Stufen
0, 1, 2, 5, 10, 20, 50 und 100 m:

- Z10: 0,000533 %
- Z9: 0,004004 %
- Z8: 0,015178 %
- Z7: 0,012754 %
- Z6: 0,093703 %

Damit ist Z6 für den Pilot als niedrigste Darstellungsstufe ausreichend.

## Performance

Rasterpyramide Z6–Z11:

- Laufzeit: ca. 24 s
- Max RSS: ca. 214 MiB

Der Priority-Flood selbst bleibt mit etwa 1,2–1,4 s deutlich schneller als die
Kachelerzeugung.

## HTTP-Test

Das veröffentlichte Pilot-PMTiles im öffentlichen Build-Repo wurde über
`raw.githubusercontent.com` geprüft:

- normaler Request: HTTP 200
- Range Request: HTTP 206
- `Accept-Ranges: bytes`
- `Content-Range: bytes 0-126/4300629`
- `Access-Control-Allow-Origin: *`
- 127-Byte-Test enthält korrekte `PMTiles`-Signatur

Damit ist die Datei für den direkten Browserzugriff per PMTiles-Protokoll geeignet.

## Kartensammlung

Die Kartensammlung verwendet für den Pilot einen auf den Publish-Commit gepinnten
Raw-GitHub-Link:

`2b50553a412507f5e9ef7327b6fbbf7282e331b4`

Dadurch ändert sich der getestete Pilotdatensatz nicht, wenn das Build-Repo später
neue Versionen erzeugt.

## Nächste QA

In der Karte besonders prüfen:

1. Z6–Z8: Übersichtsdarstellung und Küstenform,
2. Z9–Z11: Übergänge zwischen Poldern und Küste,
3. über Z11: Overzoom-Verhalten,
4. Meeresspiegel +1 m versus +2 m,
5. Rotterdam, Den Haag, Amsterdam, Schiphol, Almere und Lelystad,
6. Hoek van Holland bei +6/+7 m.

Erst nach dieser visuellen Prüfung wird entschieden, ob Phase 1B räumlich erweitert
oder zuerst die Auflösung / DEM-Basis verfeinert wird.
