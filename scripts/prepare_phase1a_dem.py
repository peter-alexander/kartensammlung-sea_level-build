#!/usr/bin/env python3

import argparse
import concurrent.futures
import gzip
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

from grid import grid_from_config, load_config


MAPTERHORN_TEMPLATE = "https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"


def tile_path(cache_dir, zoom, x, y):
	return (
		Path(cache_dir)
		/ "mapterhorn"
		/ str(zoom)
		/ str(x)
		/ f"{y}.webp"
	)


def tile_url(zoom, x, y):
	return MAPTERHORN_TEMPLATE.format(z=zoom, x=x, y=y)


def download_tile(url, path):
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)

	if path.exists() and path.stat().st_size > 0:
		return "cached"

	request = urllib.request.Request(
		url,
		headers={"User-Agent": "Kartensammlung-SeaLevel-Build/1.0"},
	)

	try:
		with urllib.request.urlopen(
			request,
			timeout=60,
		) as response, path.open("wb") as target:
			target.write(response.read())
	except urllib.error.HTTPError as error:
		if error.code == 404:
			return "missing"
		raise

	return "downloaded"


def download_task_set(tasks, workers, *, label_zoom=None):
	status = {}

	with concurrent.futures.ThreadPoolExecutor(
		max_workers=workers
	) as executor:
		futures = {
			executor.submit(
				download_tile,
				url,
				path,
			): (x, y)
			for x, y, url, path in tasks
		}

		for future in concurrent.futures.as_completed(futures):
			x, y = futures[future]
			result = future.result()
			status[(x, y)] = result
			if label_zoom is not None:
				print(
					f"{result}: {label_zoom}/{x}/{y}",
					file=sys.stderr,
				)

	return status


def decode_terrarium_bytes(data):
	with Image.open(io.BytesIO(data)) as image:
		rgb = np.asarray(image.convert("RGB"), dtype=np.float32)

	return (
		rgb[:, :, 0] * 256.0
		+ rgb[:, :, 1]
		+ rgb[:, :, 2] / 256.0
		- 32768.0
	)


def decode_terrarium(path):
	return decode_terrarium_bytes(Path(path).read_bytes())


def overzoom_parent_tile(
	parent_tile,
	target_x,
	target_y,
	target_zoom,
	parent_zoom,
):
	if parent_zoom >= target_zoom:
		raise ValueError(
			"parent_zoom muss kleiner als target_zoom sein."
	)
	if parent_tile.ndim != 2:
		raise ValueError("Parent-Tile muss zweidimensional sein.")

	tile_height, tile_width = parent_tile.shape
	if tile_height != tile_width:
		raise ValueError("Parent-Tile muss quadratisch sein.")

	zoom_delta = target_zoom - parent_zoom
	factor = 2 ** zoom_delta
	if tile_width % factor != 0:
		raise ValueError(
			"Tile-Größe ist nicht durch den Overzoom-Faktor teilbar."
		)

	local_x = target_x % factor
	local_y = target_y % factor
	crop_size = tile_width // factor
	x0 = local_x * crop_size
	y0 = local_y * crop_size
	crop = parent_tile[
		y0:y0 + crop_size,
		x0:x0 + crop_size,
	]

	return np.repeat(
		np.repeat(crop, factor, axis=0),
		factor,
		axis=1,
	)


def resolve_pmtiles_fallbacks(
	missing_targets,
	target_zoom,
	fallback_min_zoom,
	reader,
):
	if fallback_min_zoom is None:
		return {}, list(missing_targets)

	fallback_min_zoom = int(fallback_min_zoom)
	if fallback_min_zoom < 0:
		raise ValueError(
			"overzoom_fallback_minzoom muss >= 0 sein."
		)
	if fallback_min_zoom >= target_zoom:
		raise ValueError(
			"overzoom_fallback_minzoom muss kleiner als Processing-Zoom sein."
		)

	unresolved = set(missing_targets)
	resolved = {}

	for parent_zoom in range(
		target_zoom - 1,
		fallback_min_zoom - 1,
		-1,
	):
		if not unresolved:
			break

		factor = 2 ** (target_zoom - parent_zoom)
		parent_coords = sorted({
			(
				target_x // factor,
				target_y // factor,
			)
			for target_x, target_y in unresolved
		})
		available = {
			(parent_x, parent_y)
			for parent_x, parent_y in parent_coords
			if reader.get(
				parent_zoom,
				parent_x,
				parent_y,
			) is not None
		}

		for target_x, target_y in list(unresolved):
			parent_x = target_x // factor
			parent_y = target_y // factor
			if (parent_x, parent_y) not in available:
				continue

			resolved[(target_x, target_y)] = {
				"parent_zoom": parent_zoom,
				"parent_x": parent_x,
				"parent_y": parent_y,
			}
			unresolved.remove((target_x, target_y))

	return resolved, sorted(unresolved)


def resolve_http_fallbacks(
	missing_targets,
	target_zoom,
	fallback_min_zoom,
	cache_dir,
	workers,
):
	if fallback_min_zoom is None:
		return {}, list(missing_targets), []

	fallback_min_zoom = int(fallback_min_zoom)
	if fallback_min_zoom < 0:
		raise ValueError(
			"overzoom_fallback_minzoom muss >= 0 sein."
		)
	if fallback_min_zoom >= target_zoom:
		raise ValueError(
			"overzoom_fallback_minzoom muss kleiner als Processing-Zoom sein."
		)

	unresolved = set(missing_targets)
	resolved = {}
	parent_tiles = []

	for parent_zoom in range(
		target_zoom - 1,
		fallback_min_zoom - 1,
		-1,
	):
		if not unresolved:
			break

		factor = 2 ** (target_zoom - parent_zoom)
		parent_coords = sorted({
			(
				target_x // factor,
				target_y // factor,
			)
			for target_x, target_y in unresolved
		})
		tasks = [
			(
				parent_x,
				parent_y,
				tile_url(parent_zoom, parent_x, parent_y),
				tile_path(
					cache_dir,
					parent_zoom,
					parent_x,
					parent_y,
				),
			)
			for parent_x, parent_y in parent_coords
		]
		status = download_task_set(
			tasks,
			workers,
			label_zoom=parent_zoom,
		)
		available = {
			(parent_x, parent_y)
			for parent_x, parent_y in parent_coords
			if status[(parent_x, parent_y)] != "missing"
		}

		for parent_x, parent_y in sorted(available):
			parent_tiles.append({
				"zoom": parent_zoom,
				"x": parent_x,
				"y": parent_y,
				"status": status[(parent_x, parent_y)],
			})

		for target_x, target_y in list(unresolved):
			parent_x = target_x // factor
			parent_y = target_y // factor
			if (parent_x, parent_y) not in available:
				continue

			resolved[(target_x, target_y)] = {
				"parent_zoom": parent_zoom,
				"parent_x": parent_x,
				"parent_y": parent_y,
			}
			unresolved.remove((target_x, target_y))

	return resolved, sorted(unresolved), parent_tiles


def pmtiles_tile_bytes(reader, compression, zoom, x, y):
	data = reader.get(zoom, x, y)
	if data is None:
		raise RuntimeError(
			f"PMTiles-Fallback enthält {zoom}/{x}/{y} nicht."
		)

	name = getattr(compression, "name", str(compression))
	if name == "NONE":
		return data
	if name == "GZIP":
		return gzip.decompress(data)

	raise RuntimeError(
		"Nicht unterstützte PMTiles-Tile-Kompression "
		f"{name!r}."
	)


def write_elevation_strips(
	elevation_path,
	grid,
	tile_loader,
):
	tile_size = int(grid["tile_size"])
	width = int(grid["width"])
	x_min = int(grid["x_min"])
	x_max = int(grid["x_max"])
	y_min = int(grid["y_min"])
	y_max = int(grid["y_max"])

	with open(elevation_path, "wb") as output:
		for y in range(y_min, y_max + 1):
			strip = np.full(
				(tile_size, width),
				np.nan,
				dtype=np.float32,
			)

			for x in range(x_min, x_max + 1):
				tile = tile_loader(x, y)
				if tile is None:
					continue

				tile = np.asarray(
					tile,
					dtype=np.float32,
				)
				if tile.shape != (tile_size, tile_size):
					raise RuntimeError(
						f"Unerwartete Tile-Größe {tile.shape} "
						f"für {grid['zoom']}/{x}/{y}"
					)

				col = (x - x_min) * tile_size
				strip[
					:,
					col:col + tile_size,
				] = tile

			strip.tofile(output)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--config", default="config/north_sea_pilot.json")
	parser.add_argument("--cache-dir", default="cache")
	parser.add_argument("--work-dir", default="tmp/phase1a")
	parser.add_argument("--workers", type=int, default=8)
	parser.add_argument("--fallback-pmtiles")
	args = parser.parse_args()

	config = load_config(args.config)
	grid = grid_from_config(config)
	cache_dir = Path(args.cache_dir)
	work_dir = Path(args.work_dir)
	work_dir.mkdir(parents=True, exist_ok=True)

	tasks = []
	for y in range(grid["y_min"], grid["y_max"] + 1):
		for x in range(grid["x_min"], grid["x_max"] + 1):
			tasks.append((
				x,
				y,
				tile_url(grid["zoom"], x, y),
				tile_path(cache_dir, grid["zoom"], x, y),
			))

	status = download_task_set(
		tasks,
		args.workers,
		label_zoom=grid["zoom"],
	)
	requested_missing = sorted(
		(x, y)
		for x, y, _url, _path in tasks
		if status[(x, y)] == "missing"
	)

	fallback_min_zoom = config.get(
		"dem",
		{},
	).get("overzoom_fallback_minzoom")

	fallback_file = None
	fallback_reader = None
	fallback_compression = None
	fallback_path = None
	fallback_parent_tiles = []
	fallback_mode = config.get("dem", {}).get(
		"overzoom_fallback_mode"
	)

	if requested_missing and fallback_min_zoom is not None:
		if fallback_mode is None:
			fallback_mode = (
				"pmtiles"
				if args.fallback_pmtiles
				else "http"
			)

		if fallback_mode == "pmtiles":
			if not args.fallback_pmtiles:
				raise RuntimeError(
					"PMTiles-Fallback ist konfiguriert, aber "
					"--fallback-pmtiles fehlt."
				)

			from pmtiles.reader import MmapSource, Reader

			fallback_path = Path(args.fallback_pmtiles)
			fallback_file = fallback_path.open("rb")
			fallback_reader = Reader(MmapSource(fallback_file))
			fallback_compression = fallback_reader.header()[
				"tile_compression"
			]
			fallbacks, unresolved_missing = (
				resolve_pmtiles_fallbacks(
					requested_missing,
					grid["zoom"],
					fallback_min_zoom,
					fallback_reader,
				)
			)
		elif fallback_mode == "http":
			(
				fallbacks,
				unresolved_missing,
				fallback_parent_tiles,
			) = resolve_http_fallbacks(
				requested_missing,
				grid["zoom"],
				fallback_min_zoom,
				cache_dir,
				args.workers,
			)
		else:
			raise ValueError(
				"Unbekannter overzoom_fallback_mode: "
				f"{fallback_mode!r}"
			)
	else:
		fallbacks = {}
		unresolved_missing = list(requested_missing)

	elevation_path = work_dir / "elevation.f32"
	decoded_fallback_parents = {}
	fallback_tiles = []
	unresolved_set = set(unresolved_missing)
	tile_paths = {
		(x, y): path
		for x, y, _url, path in tasks
	}

	def load_target_tile(x, y):
		if (x, y) in unresolved_set:
			return None

		if status[(x, y)] != "missing":
			return decode_terrarium(tile_paths[(x, y)])

		fallback = fallbacks[(x, y)]
		parent_key = (
			fallback["parent_zoom"],
			fallback["parent_x"],
			fallback["parent_y"],
		)
		if parent_key not in decoded_fallback_parents:
			if fallback_mode == "pmtiles":
				data = pmtiles_tile_bytes(
					fallback_reader,
					fallback_compression,
					*parent_key,
				)
				decoded = decode_terrarium_bytes(data)
			elif fallback_mode == "http":
				decoded = decode_terrarium(
					tile_path(
						cache_dir,
						*parent_key,
					)
				)
			else:
				raise RuntimeError(
					"Fallback-Tile ohne gültigen Fallback-Modus."
				)

			decoded_fallback_parents[parent_key] = decoded

		fallback_tiles.append({
			"x": x,
			"y": y,
			"parent_zoom": fallback["parent_zoom"],
			"parent_x": fallback["parent_x"],
			"parent_y": fallback["parent_y"],
		})

		return overzoom_parent_tile(
			decoded_fallback_parents[parent_key],
			x,
			y,
			grid["zoom"],
			fallback["parent_zoom"],
		)

	try:
		write_elevation_strips(
			elevation_path,
			grid,
			load_target_tile,
		)
	finally:
		if fallback_file is not None:
			fallback_file.close()

	missing_tiles = [
		[x, y]
		for x, y in unresolved_missing
	]
	metadata = {
		"config": config,
		"grid": grid,
		"dem": {
			"tile_url": MAPTERHORN_TEMPLATE,
			"tile_count": len(tasks),
			"requested_missing_tile_count": len(
				requested_missing
			),
			"overzoom_fallback_minzoom": fallback_min_zoom,
			"overzoom_fallback_mode": fallback_mode,
			"fallback_parent_tile_count": len(
				fallback_parent_tiles
			),
			"fallback_parent_tiles": fallback_parent_tiles,
			"fallback_pmtiles": (
				str(fallback_path)
				if fallback_path is not None
				else None
			),
			"fallback_tile_count": len(fallback_tiles),
			"fallback_tiles": fallback_tiles,
			"missing_tile_count": len(missing_tiles),
			"missing_tiles": missing_tiles,
			"raw_path": str(elevation_path),
		},
	}
	(work_dir / "grid.json").write_text(
		json.dumps(metadata, indent=2) + "\n",
		encoding="utf-8",
	)

	print(json.dumps({
		"grid": grid,
		"requested_missing_tile_count": len(requested_missing),
		"fallback_tile_count": len(fallback_tiles),
		"missing_tile_count": len(missing_tiles),
		"elevation_bytes": elevation_path.stat().st_size,
	}, indent=2))


if __name__ == "__main__":
	main()
