#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--grid", default="tmp/phase1a/grid.json")
	parser.add_argument("--elevation", default="tmp/phase1a/elevation.f32")
	parser.add_argument("--sea-mask", default="tmp/phase1a/sea_mask.u8")
	parser.add_argument("--threshold", default="tmp/phase1a/threshold.u8")
	parser.add_argument("--output-dir", default="tmp/phase1a/qa")
	parser.add_argument("--max-level", type=int, default=100)
	args = parser.parse_args()

	metadata = json.loads(Path(args.grid).read_text(encoding="utf-8"))
	grid = metadata["grid"]
	shape = (grid["height"], grid["width"])
	count = grid["cells"]
	output_dir = Path(args.output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	elevation = np.memmap(args.elevation, dtype=np.float32, mode="r", shape=shape)
	sea = np.memmap(args.sea_mask, dtype=np.uint8, mode="r", shape=shape)
	threshold = np.memmap(args.threshold, dtype=np.uint8, mode="r", shape=shape)

	if threshold.size != count:
		raise RuntimeError("Threshold-Größe stimmt nicht.")

	hist = np.bincount(
		np.asarray(threshold).reshape(-1),
		minlength=max(args.max_level + 2, 256),
	)
	threshold_counts = {
		str(level): int(hist[level])
		for level in range(args.max_level + 2)
		if hist[level] > 0
	}

	center_y = (grid["top"] + grid["bottom"]) / 2.0
	center_lat = math.degrees(
		math.atan(math.sinh(center_y / 6378137.0))
	)
	ground_pixel = grid["resolution"] * math.cos(math.radians(center_lat))
	cell_area = ground_pixel * ground_pixel

	levels = []
	for level in (0, 1, 2, 5, 10, 20, 50, 100):
		bathtub = np.isfinite(elevation) & (elevation <= level)
		connected = threshold <= level
		protected = bathtub & ~connected
		levels.append({
			"level_m": level,
			"bathtub_cells": int(np.count_nonzero(bathtub)),
			"connected_cells": int(np.count_nonzero(connected)),
			"protected_low_land_cells": int(np.count_nonzero(protected)),
			"protected_low_land_km2_approx": round(
				np.count_nonzero(protected) * cell_area / 1_000_000.0,
				2,
			),
		})

	transform = Affine(
		grid["resolution"],
		0.0,
		grid["left"],
		0.0,
		-grid["resolution"],
		grid["top"],
	)

	with rasterio.open(
		output_dir / "threshold.tif",
		"w",
		driver="GTiff",
		width=grid["width"],
		height=grid["height"],
		count=1,
		dtype="uint8",
		crs="EPSG:3857",
		transform=transform,
		compress="deflate",
		predictor=1,
		tiled=True,
		blockxsize=512,
		blockysize=512,
	) as dataset:
		for row in range(0, grid["height"], 512):
			height = min(512, grid["height"] - row)
			window = rasterio.windows.Window(0, row, grid["width"], height)
			dataset.write(np.asarray(threshold[row:row + height, :]), 1, window=window)

	report = {
		"grid": grid,
		"center_latitude": round(center_lat, 6),
		"ground_pixel_m_approx": round(ground_pixel, 3),
		"sea_seed_cells": int(np.count_nonzero(sea)),
		"threshold_counts": threshold_counts,
		"sentinel_cells": int(hist[args.max_level + 1]),
		"levels": levels,
	}
	(output_dir / "report.json").write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
