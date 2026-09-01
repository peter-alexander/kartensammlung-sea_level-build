#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path

from compare_resolution_benchmark import (
	compare_to_fine,
	flooded_fraction,
	load_run,
	sample_points,
)
from threshold_levels import LEVELS_M


def run_summary(grid_meta, threshold):
	grid = grid_meta["grid"]
	center_lat = (
		grid_meta["config"]["bounds"]["south"]
		+ grid_meta["config"]["bounds"]["north"]
	) / 2.0
	ground_pixel = (
		grid["resolution"]
		* math.cos(math.radians(center_lat))
	)

	return {
		"zoom": int(grid["zoom"]),
		"shape": [
			int(threshold.shape[0]),
			int(threshold.shape[1]),
		],
		"cells": int(threshold.size),
		"ground_pixel_m_approx": round(ground_pixel, 3),
		"sample_points": sample_points(
			grid_meta,
			threshold,
		),
		"flooded_fraction": flooded_fraction(
			threshold,
			list(LEVELS_M),
		),
	}


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--coarse", required=True)
	parser.add_argument("--fine", required=True)
	parser.add_argument("--output", required=True)
	args = parser.parse_args()

	coarse_meta, coarse = load_run(args.coarse)
	fine_meta, fine = load_run(args.fine)

	coarse_zoom = int(coarse_meta["grid"]["zoom"])
	fine_zoom = int(fine_meta["grid"]["zoom"])
	if fine_zoom <= coarse_zoom:
		raise ValueError("Fine-Zoom muss größer als Coarse-Zoom sein.")

	factor = 2 ** (fine_zoom - coarse_zoom)

	report = {
		"coarse": run_summary(coarse_meta, coarse),
		"fine": run_summary(fine_meta, fine),
		"factor": factor,
		"comparison": compare_to_fine(
			coarse,
			fine,
			factor,
			list(LEVELS_M),
		),
	}

	Path(args.output).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
