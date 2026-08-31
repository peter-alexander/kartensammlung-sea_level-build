#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import numpy as np


NO_SEED = 255


def load_grid(path):
	return json.loads(Path(path).read_text(encoding="utf-8"))["grid"]


def sample_coarse_threshold(coarse, coarse_grid, fine_grid, rows, cols):
	rows = np.asarray(rows, dtype=np.int64)
	cols = np.asarray(cols, dtype=np.int64)

	x = fine_grid["left"] + (cols.astype(np.float64) + 0.5) * fine_grid["resolution"]
	y = fine_grid["top"] - (rows.astype(np.float64) + 0.5) * fine_grid["resolution"]

	coarse_cols = np.floor(
		(x - coarse_grid["left"]) / coarse_grid["resolution"]
	).astype(np.int64)
	coarse_rows = np.floor(
		(coarse_grid["top"] - y) / coarse_grid["resolution"]
	).astype(np.int64)

	valid = (
		(coarse_rows >= 0)
		& (coarse_rows < coarse_grid["height"])
		& (coarse_cols >= 0)
		& (coarse_cols < coarse_grid["width"])
	)

	values = np.full(rows.shape, NO_SEED, dtype=np.uint8)
	values[valid] = coarse[
		coarse_rows[valid],
		coarse_cols[valid],
	]

	return values


def build_boundary(
	coarse_grid_path,
	coarse_threshold_path,
	fine_grid_path,
	output_path,
	*,
	max_level=100,
):
	coarse_grid = load_grid(coarse_grid_path)
	fine_grid = load_grid(fine_grid_path)

	coarse = np.memmap(
		coarse_threshold_path,
		dtype=np.uint8,
		mode="r",
		shape=(coarse_grid["height"], coarse_grid["width"]),
	)

	output_path = Path(output_path)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	boundary = np.memmap(
		output_path,
		dtype=np.uint8,
		mode="w+",
		shape=(fine_grid["height"], fine_grid["width"]),
	)
	boundary[:] = NO_SEED

	width = fine_grid["width"]
	height = fine_grid["height"]

	top_cols = np.arange(width, dtype=np.int64)
	top_rows = np.zeros(width, dtype=np.int64)
	boundary[0, :] = sample_coarse_threshold(
		coarse,
		coarse_grid,
		fine_grid,
		top_rows,
		top_cols,
	)

	if height > 1:
		bottom_rows = np.full(width, height - 1, dtype=np.int64)
		boundary[-1, :] = sample_coarse_threshold(
			coarse,
			coarse_grid,
			fine_grid,
			bottom_rows,
			top_cols,
		)

	if height > 2:
		side_rows = np.arange(1, height - 1, dtype=np.int64)

		left_cols = np.zeros(side_rows.size, dtype=np.int64)
		boundary[1:-1, 0] = sample_coarse_threshold(
			coarse,
			coarse_grid,
			fine_grid,
			side_rows,
			left_cols,
		)

		if width > 1:
			right_cols = np.full(side_rows.size, width - 1, dtype=np.int64)
			boundary[1:-1, -1] = sample_coarse_threshold(
				coarse,
				coarse_grid,
				fine_grid,
				side_rows,
				right_cols,
			)

	boundary.flush()

	edge = np.concatenate([
		np.asarray(boundary[0, :]),
		np.asarray(boundary[-1, :]) if height > 1 else np.empty(0, dtype=np.uint8),
		np.asarray(boundary[1:-1, 0]) if height > 2 else np.empty(0, dtype=np.uint8),
		(
			np.asarray(boundary[1:-1, -1])
			if height > 2 and width > 1
			else np.empty(0, dtype=np.uint8)
		),
	])

	sentinel = max_level + 1
	active = edge <= max_level
	report = {
		"coarse_grid": str(coarse_grid_path),
		"fine_grid": str(fine_grid_path),
		"output": str(output_path),
		"fine_shape": [height, width],
		"edge_cells": int(edge.size),
		"active_boundary_seeds": int(np.count_nonzero(active)),
		"sentinel_boundary_cells": int(np.count_nonzero(edge == sentinel)),
		"unmapped_boundary_cells": int(np.count_nonzero(edge == NO_SEED)),
		"active_min": int(edge[active].min()) if np.any(active) else None,
		"active_max": int(edge[active].max()) if np.any(active) else None,
	}

	report_path = output_path.with_suffix(".report.json")
	report_path.write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)

	return report


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Projiziert einen groben Inundation-Threshold auf den äußeren Rand "
			"eines feineren Refinement-Rasters."
		)
	)
	parser.add_argument("--coarse-grid", required=True)
	parser.add_argument("--coarse-threshold", required=True)
	parser.add_argument("--fine-grid", required=True)
	parser.add_argument("--output", required=True)
	parser.add_argument("--max-level", type=int, default=100)
	args = parser.parse_args()

	report = build_boundary(
		args.coarse_grid,
		args.coarse_threshold,
		args.fine_grid,
		args.output,
		max_level=args.max_level,
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
