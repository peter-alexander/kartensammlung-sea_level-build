#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path

import numpy as np


def load_run(path):
	path = Path(path)
	grid_meta = json.loads((path / "grid.json").read_text(encoding="utf-8"))
	grid = grid_meta["grid"]
	threshold = np.memmap(
		path / "threshold.u8",
		dtype=np.uint8,
		mode="r",
		shape=(grid["height"], grid["width"]),
	)
	return grid, threshold


def lonlat_to_pixel(lon, lat, grid):
	radius = 6378137.0
	x = radius * math.radians(lon)
	y = radius * math.asinh(math.tan(math.radians(lat)))
	col = int((x - grid["left"]) / grid["resolution"])
	row = int((grid["top"] - y) / grid["resolution"])
	return row, col


def sample_points(grid, threshold):
	points = {
		"Hoek van Holland": (4.134, 51.978),
		"Maassluis": (4.250, 51.923),
		"Rotterdam center": (4.47917, 51.9225),
		"Westland polder": (4.205, 52.005),
		"Delft": (4.3571, 52.0116),
		"Den Haag south": (4.285, 52.050),
	}
	result = {}
	for name, (lon, lat) in points.items():
		row, col = lonlat_to_pixel(lon, lat, grid)
		if row < 0 or col < 0 or row >= grid["height"] or col >= grid["width"]:
			result[name] = None
		else:
			result[name] = int(threshold[row, col])
	return result


def flooded_fraction(threshold, levels):
	total = threshold.size
	return {
		str(level): float(np.count_nonzero(threshold <= level)) / total
		for level in levels
	}


def compare_to_fine(coarse, fine, factor):
	if fine.shape[0] != coarse.shape[0] * factor:
		raise ValueError("Fine/coarse heights do not align.")
	if fine.shape[1] != coarse.shape[1] * factor:
		raise ValueError("Fine/coarse widths do not align.")

	center_offset = factor // 2
	fine_center = fine[
		center_offset::factor,
		center_offset::factor,
	]
	if fine_center.shape != coarse.shape:
		fine_center = fine[
			(center_offset - 1)::factor,
			(center_offset - 1)::factor,
		][:coarse.shape[0], :coarse.shape[1]]

	valid = (coarse <= 100) & (fine_center <= 100)
	diff = coarse.astype(np.int16) - fine_center.astype(np.int16)
	valid_diff = diff[valid]

	if valid_diff.size == 0:
		return {
			"valid_cells": 0,
		"mean_abs_diff_m": None,
		"median_abs_diff_m": None,
		"pct_diff_gt_1m": None,
		"pct_diff_gt_2m": None,
		"pct_diff_gt_5m": None,
	}

	abs_diff = np.abs(valid_diff)
	return {
		"valid_cells": int(valid_diff.size),
		"mean_abs_diff_m": round(float(np.mean(abs_diff)), 4),
		"median_abs_diff_m": round(float(np.median(abs_diff)), 4),
		"pct_diff_gt_1m": round(float(np.mean(abs_diff > 1) * 100), 4),
		"pct_diff_gt_2m": round(float(np.mean(abs_diff > 2) * 100), 4),
		"pct_diff_gt_5m": round(float(np.mean(abs_diff > 5) * 100), 4),
	}


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--z11", required=True)
	parser.add_argument("--z12", required=True)
	parser.add_argument("--z13", required=True)
	parser.add_argument("--output", required=True)
	args = parser.parse_args()

	runs = {}
	for zoom, path in [(11,args.z11),(12,args.z12),(13,args.z13)]:
		grid, threshold = load_run(path)
		runs[zoom] = (grid, threshold)

	levels = [0,1,2,3,4,5,6,7,8,10,20,50,100]
	report = {
		"levels": levels,
		"runs": {},
		"comparison_to_z13_center_sample": {},
	}

	for zoom, (grid, threshold) in runs.items():
		center_lat = math.degrees(
			math.atan(math.sinh(((grid["top"] + grid["bottom"]) / 2.0) / 6378137.0))
		)
		ground_pixel = grid["resolution"] * math.cos(math.radians(center_lat))
		report["runs"][str(zoom)] = {
			"shape": [grid["height"],grid["width"]],
			"cells": int(threshold.size),
			"ground_pixel_m_approx": round(ground_pixel,3),
			"sample_points": sample_points(grid,threshold),
			"flooded_fraction": flooded_fraction(threshold,levels),
			"sentinel_fraction": round(float(np.mean(threshold == 101)),8),
		}

	z13 = runs[13][1]
	report["comparison_to_z13_center_sample"]["z11"] = compare_to_fine(
		runs[11][1], z13, 4
	)
	report["comparison_to_z13_center_sample"]["z12"] = compare_to_fine(
		runs[12][1], z13, 2
	)

	for zoom in (11,12):
		for level in levels:
			coarse = report["runs"][str(zoom)]["flooded_fraction"][str(level)]
			fine = report["runs"]["13"]["flooded_fraction"][str(level)]
			report["runs"][str(zoom)].setdefault("flooded_fraction_error_vs_z13",{})[
				str(level)
			] = round(coarse - fine,8)

	Path(args.output).write_text(
		json.dumps(report,indent=2)+"\n",
		encoding="utf-8",
	)
	print(json.dumps(report,indent=2))


if __name__ == "__main__":
	main()
