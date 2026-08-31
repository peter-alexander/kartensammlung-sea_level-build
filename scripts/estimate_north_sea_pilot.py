#!/usr/bin/env python3

import json
import math
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "north_sea_pilot.json"
EARTH_RADIUS = 6378137.0
WORLD_METERS = 2.0 * math.pi * EARTH_RADIUS


def lon_to_tile_x(lon, zoom):
	return (lon + 180.0) / 360.0 * (2 ** zoom)


def lat_to_tile_y(lat, zoom):
	lat_rad = math.radians(lat)
	return (
		1.0
		- math.asinh(math.tan(lat_rad)) / math.pi
	) / 2.0 * (2 ** zoom)


def main():
	config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
	bounds = config["bounds"]
	dem = config["dem"]
	zoom = int(dem["processing_zoom"])
	tile_size = int(dem["tile_size"])

	x0 = math.floor(lon_to_tile_x(bounds["west"], zoom))
	x1 = math.floor(lon_to_tile_x(bounds["east"], zoom))
	y0 = math.floor(lat_to_tile_y(bounds["north"], zoom))
	y1 = math.floor(lat_to_tile_y(bounds["south"], zoom))

	tiles_x = x1 - x0 + 1
	tiles_y = y1 - y0 + 1
	pixels_x = tiles_x * tile_size
	pixels_y = tiles_y * tile_size
	cells = pixels_x * pixels_y

	center_lat = (bounds["south"] + bounds["north"]) / 2.0
	web_pixel_m = WORLD_METERS / ((2 ** zoom) * tile_size)
	ground_pixel_m = web_pixel_m * math.cos(math.radians(center_lat))

	# Produktionsziel: kompakte Arrays, nicht Python-Objekte.
	# elevation float32 + threshold uint8 + state uint8 + sea/passable bool.
	bytes_core = cells * (4 + 1 + 1 + 1)
	bytes_with_work = cells * (4 + 1 + 1 + 1 + 4)

	report = {
		"zoom": zoom,
		"tile_range": {
			"x": [x0, x1],
			"y": [y0, y1],
		},
		"tiles": {
			"x": tiles_x,
			"y": tiles_y,
			"count": tiles_x * tiles_y,
		},
		"raster": {
			"width": pixels_x,
			"height": pixels_y,
			"cells": cells,
		},
		"resolution": {
			"web_mercator_m_per_pixel": round(web_pixel_m, 3),
			"ground_m_per_pixel_at_center": round(ground_pixel_m, 3),
			"center_latitude": center_lat,
		},
		"memory_estimate_gib": {
			"compact_core": round(bytes_core / (1024 ** 3), 2),
			"with_int32_work_array": round(bytes_with_work / (1024 ** 3), 2),
		},
		"mapterhorn_extract_command": (
			"pmtiles extract "
			f"--bbox={bounds['west']},{bounds['south']},{bounds['east']},{bounds['north']} "
			f"--maxzoom={zoom} --overfetch=0 "
			f"{dem['pmtiles']} north-sea-dem.pmtiles"
		),
		"mapterhorn_dry_run_command": (
			"pmtiles extract "
			f"--bbox={bounds['west']},{bounds['south']},{bounds['east']},{bounds['north']} "
			f"--maxzoom={zoom} --overfetch=0 --dry-run "
			f"{dem['pmtiles']} north-sea-dem.pmtiles"
		),
	}

	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
