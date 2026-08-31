#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path

import numpy as np


RADIUS = 6378137.0


def mercator(lon, lat):
	return (
		RADIUS * math.radians(lon),
		RADIUS * math.asinh(math.tan(math.radians(lat))),
	)


def load_threshold(directory):
	directory = Path(directory)
	meta = json.loads((directory / "grid.json").read_text(encoding="utf-8"))
	grid = meta["grid"]
	threshold = np.memmap(
		directory / "threshold.u8",
		dtype=np.uint8,
		mode="r",
		shape=(grid["height"], grid["width"]),
	)
	return meta, threshold


def crop_bounds(meta, array, bounds):
	grid = meta["grid"]
	west, south = mercator(bounds["west"], bounds["south"])
	east, north = mercator(bounds["east"], bounds["north"])

	col0 = int(round((west - grid["left"]) / grid["resolution"]))
	col1 = int(round((east - grid["left"]) / grid["resolution"]))
	row0 = int(round((grid["top"] - north) / grid["resolution"]))
	row1 = int(round((grid["top"] - south) / grid["resolution"]))

	if not (0 <= row0 < row1 <= grid["height"]):
		raise ValueError(f"Ungültiger Zeilenausschnitt {row0}:{row1}")
	if not (0 <= col0 < col1 <= grid["width"]):
		raise ValueError(f"Ungültiger Spaltenausschnitt {col0}:{col1}")

	return np.asarray(array[row0:row1, col0:col1])


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--reference", required=True)
	parser.add_argument("--refinement", required=True)
	parser.add_argument("--config", required=True)
	parser.add_argument("--boundary-report", required=True)
	parser.add_argument("--sea-report", required=True)
	parser.add_argument("--output", required=True)
	args = parser.parse_args()

	config = json.loads(Path(args.config).read_text(encoding="utf-8"))
	core_bounds = config["refinement"]["core_bounds"]

	reference_meta, reference = load_threshold(args.reference)
	refinement_meta, refinement = load_threshold(args.refinement)

	reference_core = crop_bounds(reference_meta, reference, core_bounds)
	refinement_core = crop_bounds(refinement_meta, refinement, core_bounds)

	if reference_core.shape != refinement_core.shape:
		raise ValueError(
			f"Core-Raster stimmen nicht überein: "
			f"{reference_core.shape} vs {refinement_core.shape}"
		)

	diff = refinement_core.astype(np.int16) - reference_core.astype(np.int16)
	abs_diff = np.abs(diff)
	levels = [0,1,2,3,4,5,6,7,8,10,20,50,100]

	level_report = {}
	for level in levels:
		ref_fraction = float(np.mean(reference_core <= level))
		fine_fraction = float(np.mean(refinement_core <= level))
		level_report[str(level)] = {
			"reference_fraction": ref_fraction,
			"refinement_fraction": fine_fraction,
			"difference": fine_fraction - ref_fraction,
		}

	boundary_report = json.loads(
		Path(args.boundary_report).read_text(encoding="utf-8")
	)
	sea_report = json.loads(
		Path(args.sea_report).read_text(encoding="utf-8")
	)

	report = {
		"core_bounds": core_bounds,
		"core_shape": list(reference_core.shape),
		"core_cells": int(reference_core.size),
		"sea_seed_cells_in_refinement_work_area": sea_report["sea_seed_cells"],
		"boundary": boundary_report,
		"comparison": {
			"exact_equal_pct": round(float(np.mean(diff == 0) * 100), 6),
			"mean_abs_diff_m": round(float(np.mean(abs_diff)), 6),
			"median_abs_diff_m": round(float(np.median(abs_diff)), 6),
			"max_abs_diff_m": int(np.max(abs_diff)),
			"pct_diff_gt_1m": round(float(np.mean(abs_diff > 1) * 100), 6),
			"pct_diff_gt_2m": round(float(np.mean(abs_diff > 2) * 100), 6),
			"pct_diff_gt_5m": round(float(np.mean(abs_diff > 5) * 100), 6),
		},
		"levels": level_report,
	}

	Path(args.output).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
