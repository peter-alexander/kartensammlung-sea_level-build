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
		with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as target:
			target.write(response.read())
	except urllib.error.HTTPError as error:
		if error.code == 404:
			return "missing"
		raise

	return "downloaded"


def decode_terrarium(path):
	with Image.open(path) as image:
		rgb = np.asarray(image.convert("RGB"), dtype=np.float32)

	return (
		rgb[:, :, 0] * 256.0
		+ rgb[:, :, 1]
		+ rgb[:, :, 2] / 256.0
		- 32768.0
	)


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
			url = MAPTERHORN_TEMPLATE.format(z=grid["zoom"], x=x, y=y)
			path = cache_dir / "mapterhorn" / str(grid["zoom"]) / str(x) / f"{y}.webp"
			tasks.append((x, y, url, path))

	status = {}
	with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
		futures = {
			executor.submit(download_tile, url, path): (x, y, path)
			for x, y, url, path in tasks
		}

		for future in concurrent.futures.as_completed(futures):
			x, y, path = futures[future]
			result = future.result()
			status[(x, y)] = result
			print(f"{result}: {grid['zoom']}/{x}/{y}", file=sys.stderr)

	elevation_path = work_dir / "elevation.f32"
	elevation = np.memmap(
		elevation_path,
		dtype=np.float32,
		mode="w+",
		shape=(grid["height"], grid["width"]),
	)
	elevation[:] = np.nan

	missing_tiles = []
	for x, y, _url, path in tasks:
		if status[(x, y)] == "missing":
			missing_tiles.append([x, y])
			continue

		tile = decode_terrarium(path)
		if tile.shape != (grid["tile_size"], grid["tile_size"]):
			raise RuntimeError(
				f"Unerwartete Tile-Größe {tile.shape} für {grid['zoom']}/{x}/{y}"
			)

		row = (y - grid["y_min"]) * grid["tile_size"]
		col = (x - grid["x_min"]) * grid["tile_size"]
		elevation[
			row:row + grid["tile_size"],
			col:col + grid["tile_size"],
		] = tile

	elevation.flush()

	metadata = {
		"config": config,
		"grid": grid,
		"dem": {
			"tile_url": MAPTERHORN_TEMPLATE,
			"tile_count": len(tasks),
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
		"missing_tile_count": len(missing_tiles),
		"elevation_bytes": elevation_path.stat().st_size,
	}, indent=2))


if __name__ == "__main__":
	main()
