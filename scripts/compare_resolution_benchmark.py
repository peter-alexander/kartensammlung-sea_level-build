#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path

import numpy as np

from threshold_levels import (
	LEVELS_M,
	SENTINEL_CLASS,
	class_for_meters,
	format_level,
)


def lonlat_to_mercator(lon, lat):
	radius = 6378137.0
	return (
		radius * math.radians(lon),
		radius * math.asinh(math.tan(math.radians(lat))),
	)


def crop_to_config_bounds(grid_meta, threshold):
	grid = grid_meta["grid"]
	bounds = grid_meta["config"]["bounds"]
	west, south = lonlat_to_mercator(bounds["west"], bounds["south"])
	east, north = lonlat_to_mercator(bounds["east"], bounds["north"])

	col0 = int(round((west - grid["left"]) / grid["resolution"]))
	col1 = int(round((east - grid["left"]) / grid["resolution"]))
	row0 = int(round((grid["top"] - north) / grid["resolution"]))
	row1 = int(round((grid["top"] - south) / grid["resolution"]))

	if not (0 <= row0 < row1 <= grid["height"]):
		raise ValueError(f"Ungültiger Benchmark-Zeilenausschnitt: {row0}:{row1}")
	if not (0 <= col0 < col1 <= grid["width"]):
		raise ValueError(f"Ungültiger Benchmark-Spaltenausschnitt: {col0}:{col1}")

	return threshold[row0:row1, col0:col1]


def load_run(path):
	path = Path(path)
	grid_meta = json.loads((path / "grid.json").read_text(encoding="utf-8"))
	grid = grid_meta["grid"]
	threshold_full = np.memmap(
		path / "threshold.u8",
		dtype=np.uint8,
		mode="r",
		shape=(grid["height"], grid["width"]),
	)
	threshold = crop_to_config_bounds(grid_meta, threshold_full)
	return grid_meta, threshold


def lonlat_to_pixel(lon, lat, grid):
	radius = 6378137.0
	x = radius * math.radians(lon)
	y = radius * math.asinh(math.tan(math.radians(lat)))
	col = int((x - grid["left"]) / grid["resolution"])
	row = int((grid["top"] - y) / grid["resolution"])
	return row, col


def sample_points(grid_meta, threshold):
	grid = grid_meta["grid"]
	bounds = grid_meta["config"]["bounds"]
	west, south = lonlat_to_mercator(bounds["west"], bounds["south"])
	east, north = lonlat_to_mercator(bounds["east"], bounds["north"])
	crop_col0 = int(round((west - grid["left"]) / grid["resolution"]))
	crop_row0 = int(round((grid["top"] - north) / grid["resolution"]))
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
		row -= crop_row0
		col -= crop_col0
		if row < 0 or col < 0 or row >= threshold.shape[0] or col >= threshold.shape[1]:
			result[name] = None
		else:
			class_index = int(threshold[row, col])
			result[name] = (
				LEVELS_M[class_index]
				if class_index < SENTINEL_CLASS
				else None
			)
	return result


def flooded_fraction(threshold, levels):
	total = threshold.size
	return {
		format_level(level): (
			float(np.count_nonzero(threshold <= class_for_meters(level))) / total
		)
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

	valid = (coarse < SENTINEL_CLASS) & (fine_center < SENTINEL_CLASS)
	lookup = np.asarray(LEVELS_M, dtype=np.float64)
	valid_diff = lookup[coarse[valid]] - lookup[fine_center[valid]]

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
		grid_meta, threshold = load_run(path)
		runs[zoom] = (grid_meta, threshold)

	levels = [0,0.5,1,2,3,4,5,6,7,8,10,20,50,70]
	report = {
		"levels": levels,
		"runs": {},
		"comparison_to_z13_center_sample": {},
	}

	for zoom, (grid_meta, threshold) in runs.items():
		grid = grid_meta["grid"]
		center_lat = (
			grid_meta["config"]["bounds"]["south"]
			+ grid_meta["config"]["bounds"]["north"]
		) / 2.0
		ground_pixel = grid["resolution"] * math.cos(math.radians(center_lat))
		report["runs"][str(zoom)] = {
			"shape": [int(threshold.shape[0]), int(threshold.shape[1])],
			"full_grid_shape": [grid["height"], grid["width"]],
			"cells": int(threshold.size),
			"ground_pixel_m_approx": round(ground_pixel,3),
			"sample_points": sample_points(grid_meta,threshold),
			"flooded_fraction": flooded_fraction(threshold,levels),
			"sentinel_fraction": round(float(np.mean(threshold == SENTINEL_CLASS)),8),
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
			key = format_level(level)
			coarse = report["runs"][str(zoom)]["flooded_fraction"][key]
			fine = report["runs"]["13"]["flooded_fraction"][key]
			report["runs"][str(zoom)].setdefault("flooded_fraction_error_vs_z13",{})[
				key
			] = round(coarse - fine,8)

	Path(args.output).write_text(
		json.dumps(report,indent=2)+"\n",
		encoding="utf-8",
	)
	print(json.dumps(report,indent=2))


if __name__ == "__main__":
	main()
