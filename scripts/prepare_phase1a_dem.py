#!/usr/bin/env python3

import argparse
import concurrent.futures
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


def decode_terrarium(path):
	with Image.open(path) as image:
		rgb = np.asarray(image.convert("RGB"), dtype=np.float32)

	return (
		rgb[:, :, 0] * 256.0
		+ rgb[:, :, 1]
		+ rgb[:, :, 2] / 256.0
		- 32768.0
	)


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


def resolve_overzoom_fallbacks(
	missing_targets,
	target_zoom,
	fallback_min_zoom,
	cache_dir,
	workers,
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
		tasks = [
			(
				x,
				y,
				tile_url(parent_zoom, x, y),
				tile_path(cache_dir, parent_zoom, x, y),
			)
			for x, y in parent_coords
		]
		parent_status = download_task_set(
			tasks,
			workers,
			label_zoom=parent_zoom,
		)

		for target_x, target_y in list(unresolved):
			parent_x = target_x // factor
			parent_y = target_y // factor
			if parent_status[(parent_x, parent_y)] == "missing":
				continue

			resolved[(target_x, target_y)] = {
				"parent_zoom": parent_zoom,
				"parent_x": parent_x,
				"parent_y": parent_y,
				"parent_path": tile_path(
					cache_dir,
					parent_zoom,
					parent_x,
					parent_y,
				),
			}
			unresolved.remove((target_x, target_y))

	return resolved, sorted(unresolved)


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--config", default="config/north_sea_pilot.json")
	parser.add_argument("--cache-dir", default="cache")
	parser.add_argument("--work-dir", default="tmp/phase1a")
	parser.add_argument("--workers", type=int, default=8)
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
	fallbacks, unresolved_missing = resolve_overzoom_fallbacks(
		requested_missing,
		grid["zoom"],
		fallback_min_zoom,
		cache_dir,
		args.workers,
	)

	elevation_path = work_dir / "elevation.f32"
	elevation = np.memmap(
		elevation_path,
		dtype=np.float32,
		mode="w+",
		shape=(grid["height"], grid["width"]),
	)
	elevation[:] = np.nan

	decoded_fallback_parents = {}
	fallback_tiles = []
	unresolved_set = set(unresolved_missing)

	for x, y, _url, path in tasks:
		if (x, y) in unresolved_set:
			continue

		if status[(x, y)] == "missing":
			fallback = fallbacks[(x, y)]
			parent_path = fallback["parent_path"]
			parent_key = str(parent_path)
			if parent_key not in decoded_fallback_parents:
				decoded_fallback_parents[parent_key] = (
					decode_terrarium(parent_path)
				)

			tile = overzoom_parent_tile(
				decoded_fallback_parents[parent_key],
				x,
				y,
				grid["zoom"],
				fallback["parent_zoom"],
			)
			fallback_tiles.append({
				"x": x,
				"y": y,
				"parent_zoom": fallback["parent_zoom"],
				"parent_x": fallback["parent_x"],
				"parent_y": fallback["parent_y"],
			})
		else:
			tile = decode_terrarium(path)

		if tile.shape != (
			grid["tile_size"],
			grid["tile_size"],
		):
			raise RuntimeError(
				f"Unerwartete Tile-Größe {tile.shape} "
				f"für {grid['zoom']}/{x}/{y}"
			)

		row = (y - grid["y_min"]) * grid["tile_size"]
		col = (x - grid["x_min"]) * grid["tile_size"]
		elevation[
			row:row + grid["tile_size"],
			col:col + grid["tile_size"],
		] = tile

	elevation.flush()

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
