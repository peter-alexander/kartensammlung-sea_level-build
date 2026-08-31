#!/usr/bin/env python3

import argparse
import io
import json
import math
import sqlite3
from pathlib import Path

import numpy as np
from PIL import Image

from grid import load_config
from threshold_levels import (
	LEVELS_M,
	SENTINEL_CLASS,
	SENTINEL_M,
	class_for_meters,
	format_level,
	threshold_config,
)


TERRARIUM_OFFSET = 32768.0
TERRARIUM_SCALE = 256.0


def encode_terrarium(values):
	array = np.asarray(values, dtype=np.float64)
	raw = np.rint((array + TERRARIUM_OFFSET) * TERRARIUM_SCALE).astype(np.int64)

	red = ((raw >> 16) & 255).astype(np.uint8)
	green = ((raw >> 8) & 255).astype(np.uint8)
	blue = (raw & 255).astype(np.uint8)

	return np.stack((red, green, blue), axis=-1)


def classes_to_meters(values):
	array = np.asarray(values, dtype=np.uint8)
	if np.any(array > SENTINEL_CLASS):
		raise ValueError("Threshold-Raster enthält ungültige Klassen.")

	lookup = np.asarray((*LEVELS_M, SENTINEL_M), dtype=np.float64)
	return lookup[array]


def png_bytes(values):
	rgb = encode_terrarium(classes_to_meters(values))
	buffer = io.BytesIO()
	Image.fromarray(rgb, "RGB").save(buffer, format="PNG", optimize=True)
	return buffer.getvalue()


def downsample_bayer(array):
	"""
	Stratifiziertes Nearest-Neighbour für 2x2-Blöcke.

	Die gewählte Subpixelposition wechselt in einem 2x2-Muster über die
	Ausgabepixel. Dadurch bleibt die Threshold-Verteilung wesentlich besser
	erhalten als bei einer festen Ecke, ohne künstliche Zwischenwerte zu erzeugen.
	"""

	height, width = array.shape
	if height % 2 != 0 or width % 2 != 0:
		raise ValueError(
			f"Rastergröße {width}x{height} ist für 2x-Downsampling nicht gerade."
		)

	a00 = array[0::2, 0::2]
	a01 = array[0::2, 1::2]
	a10 = array[1::2, 0::2]
	a11 = array[1::2, 1::2]

	out_height, out_width = a00.shape
	output = np.empty((out_height, out_width), dtype=np.uint8)

	output[0::2, 0::2] = a00[0::2, 0::2]
	output[0::2, 1::2] = a01[0::2, 1::2]
	output[1::2, 0::2] = a10[1::2, 0::2]
	output[1::2, 1::2] = a11[1::2, 1::2]

	return output


def init_mbtiles(path, metadata):
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)

	if path.exists():
		path.unlink()

	db = sqlite3.connect(path)
	db.execute("PRAGMA journal_mode=OFF")
	db.execute("PRAGMA synchronous=OFF")
	db.execute(
		"""
		CREATE TABLE metadata (
			name TEXT,
			value TEXT
		)
		"""
	)
	db.execute(
		"""
		CREATE TABLE tiles (
			zoom_level INTEGER,
			tile_column INTEGER,
			tile_row INTEGER,
			tile_data BLOB
		)
		"""
	)
	db.execute(
		"""
		CREATE UNIQUE INDEX tile_index
		ON tiles (zoom_level, tile_column, tile_row)
		"""
	)

	db.executemany(
		"INSERT INTO metadata (name, value) VALUES (?, ?)",
		[(str(key), str(value)) for key, value in metadata.items()],
	)
	db.commit()
	return db


def write_zoom(
	db,
	array,
	*,
	zoom,
	global_x0,
	global_y0,
	tile_size,
	sentinel,
):
	height, width = array.shape
	global_x1 = global_x0 + width
	global_y1 = global_y0 + height

	tile_x_min = global_x0 // tile_size
	tile_x_max = (global_x1 - 1) // tile_size
	tile_y_min = global_y0 // tile_size
	tile_y_max = (global_y1 - 1) // tile_size

	written = 0
	bytes_total = 0

	for tile_y in range(tile_y_min, tile_y_max + 1):
		for tile_x in range(tile_x_min, tile_x_max + 1):
			tile_global_x0 = tile_x * tile_size
			tile_global_y0 = tile_y * tile_size
			tile_global_x1 = tile_global_x0 + tile_size
			tile_global_y1 = tile_global_y0 + tile_size

			overlap_x0 = max(global_x0, tile_global_x0)
			overlap_y0 = max(global_y0, tile_global_y0)
			overlap_x1 = min(global_x1, tile_global_x1)
			overlap_y1 = min(global_y1, tile_global_y1)

			if overlap_x0 >= overlap_x1 or overlap_y0 >= overlap_y1:
				continue

			tile = np.full(
				(tile_size, tile_size),
				sentinel,
				dtype=np.uint8,
			)

			src_x0 = overlap_x0 - global_x0
			src_y0 = overlap_y0 - global_y0
			src_x1 = overlap_x1 - global_x0
			src_y1 = overlap_y1 - global_y0

			dst_x0 = overlap_x0 - tile_global_x0
			dst_y0 = overlap_y0 - tile_global_y0
			dst_x1 = overlap_x1 - tile_global_x0
			dst_y1 = overlap_y1 - tile_global_y0

			tile[dst_y0:dst_y1, dst_x0:dst_x1] = array[
				src_y0:src_y1,
				src_x0:src_x1,
			]

			if np.all(tile == sentinel):
				continue

			data = png_bytes(tile)
			tms_y = (1 << zoom) - 1 - tile_y
			db.execute(
				"""
				INSERT INTO tiles (
					zoom_level,
					tile_column,
					tile_row,
					tile_data
				) VALUES (?, ?, ?, ?)
				""",
				(zoom, tile_x, tms_y, sqlite3.Binary(data)),
			)
			written += 1
			bytes_total += len(data)

	db.commit()

	return {
		"zoom": zoom,
		"tiles": written,
		"png_bytes": bytes_total,
		"tile_x": [tile_x_min, tile_x_max],
		"tile_y": [tile_y_min, tile_y_max],
		"global_pixel_origin": [global_x0, global_y0],
		"raster_shape": [height, width],
	}


def area_report(array, fine_counts, fine_cells, levels_m, scale):
	report = {}

	for level_m in levels_m:
		class_index = class_for_meters(level_m)
		key = format_level(level_m)
		count = int(np.count_nonzero(array <= class_index)) * scale
		error = count - fine_counts[key]
		report[key] = {
			"estimated_fine_cells": count,
			"error_cells": error,
			"error_pct_domain": round(100.0 * error / fine_cells, 6),
		}

	return report


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Erzeugt aus threshold.u8 eine stratifiziert abgetastete "
			"Terrarium-PNG-MBTiles-Pyramide."
		)
	)
	parser.add_argument("--config", default="config/north_sea_pilot.json")
	parser.add_argument("--grid", default="tmp/phase1a/grid.json")
	parser.add_argument("--threshold", default="tmp/phase1a/threshold.u8")
	parser.add_argument("--output", default="tmp/phase1a/sea-level-threshold.mbtiles")
	parser.add_argument("--report", default="tmp/phase1a/pyramid-report.json")
	parser.add_argument("--minzoom", type=int, default=6)
	parser.add_argument("--sentinel", type=int, default=SENTINEL_CLASS)
	parser.add_argument("--levels", default="0,0.5,1,2,5,10,20,50,70")
	args = parser.parse_args()

	config = load_config(args.config)
	grid_meta = json.loads(Path(args.grid).read_text(encoding="utf-8"))
	grid = grid_meta["grid"]
	maxzoom = int(grid["zoom"])
	tile_size = int(grid["tile_size"])

	if args.minzoom > maxzoom:
		raise ValueError("--minzoom darf nicht größer als Processing-Zoom sein.")

	if args.sentinel != SENTINEL_CLASS:
		raise ValueError(
			f"Sentinel muss für {threshold_config()['scheme']} "
			f"{SENTINEL_CLASS} sein."
		)

	levels_m = [
		float(value.strip())
		for value in args.levels.split(",")
		if value.strip()
	]

	threshold = np.memmap(
		args.threshold,
		dtype=np.uint8,
		mode="r",
		shape=(grid["height"], grid["width"]),
	)

	fine_counts = {
		format_level(level_m): int(
			np.count_nonzero(threshold <= class_for_meters(level_m))
		)
		for level_m in levels_m
	}
	fine_cells = int(threshold.size)

	bounds = config["bounds"]
	metadata = {
		"name": config["name"],
		"type": "overlay",
		"version": "1",
		"description": "Terrain-based sea-level inundation threshold",
		"format": "png",
		"bounds": ",".join(str(bounds[key]) for key in ("west", "south", "east", "north")),
		"minzoom": args.minzoom,
		"maxzoom": maxzoom,
		"attribution": "DEM: Mapterhorn; coastline/ocean: OpenStreetMap contributors",
	}

	db = init_mbtiles(args.output, metadata)
	report = {
		"method": "stratified-nearest-bayer-2x2",
		"minzoom": args.minzoom,
		"maxzoom": maxzoom,
		"threshold": threshold_config(),
		"sentinel": args.sentinel,
		"levels_m": levels_m,
		"zooms": [],
	}

	current = threshold
	global_x0 = grid["x_min"] * tile_size
	global_y0 = grid["y_min"] * tile_size

	try:
		for zoom in range(maxzoom, args.minzoom - 1, -1):
			scale = 4 ** (maxzoom - zoom)

			zoom_result = write_zoom(
				db,
				current,
				zoom=zoom,
				global_x0=global_x0,
				global_y0=global_y0,
				tile_size=tile_size,
				sentinel=args.sentinel,
			)
			zoom_result["area_error"] = area_report(
				current,
				fine_counts,
				fine_cells,
				levels_m,
				scale,
			)
			report["zooms"].append(zoom_result)

			if zoom == args.minzoom:
				break

			current = downsample_bayer(current)
			global_x0 //= 2
			global_y0 //= 2
	finally:
		db.close()

	Path(args.report).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)

	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
