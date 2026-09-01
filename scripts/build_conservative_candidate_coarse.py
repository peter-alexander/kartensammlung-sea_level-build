#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import numpy as np


def require_file_size(path, expected_bytes):
	path = Path(path)
	actual = path.stat().st_size
	if actual != expected_bytes:
		raise ValueError(
			f"Unerwartete Dateigröße für {path}: "
			f"erwartet={expected_bytes}, tatsächlich={actual}"
		)


def build_conservative_coarse(
	elevation_path,
	sea_mask_path,
	output_elevation_path,
	output_sea_mask_path,
	*,
	width,
	height,
	factor,
	chunk_coarse_rows=32,
):
	width = int(width)
	height = int(height)
	factor = int(factor)
	chunk_coarse_rows = int(chunk_coarse_rows)

	if width <= 0 or height <= 0:
		raise ValueError("width und height müssen > 0 sein.")
	if factor <= 1:
		raise ValueError("factor muss > 1 sein.")
	if width % factor != 0 or height % factor != 0:
		raise ValueError(
			"width und height müssen durch factor teilbar sein."
		)
	if chunk_coarse_rows <= 0:
		raise ValueError("chunk_coarse_rows muss > 0 sein.")

	cell_count = width * height
	require_file_size(
		elevation_path,
		cell_count * np.dtype(np.float32).itemsize,
	)
	require_file_size(
		sea_mask_path,
		cell_count * np.dtype(np.uint8).itemsize,
	)

	coarse_width = width // factor
	coarse_height = height // factor
	coarse_cells = coarse_width * coarse_height

	elevation = np.memmap(
		elevation_path,
		dtype=np.float32,
		mode="r",
		shape=(height, width),
	)
	sea_mask = np.memmap(
		sea_mask_path,
		dtype=np.uint8,
		mode="r",
		shape=(height, width),
	)

	output_elevation_path = Path(output_elevation_path)
	output_sea_mask_path = Path(output_sea_mask_path)
	output_elevation_path.parent.mkdir(parents=True, exist_ok=True)
	output_sea_mask_path.parent.mkdir(parents=True, exist_ok=True)

	coarse_elevation = np.memmap(
		output_elevation_path,
		dtype=np.float32,
		mode="w+",
		shape=(coarse_height, coarse_width),
	)
	coarse_sea = np.memmap(
		output_sea_mask_path,
		dtype=np.uint8,
		mode="w+",
		shape=(coarse_height, coarse_width),
	)

	finite_coarse_cells = 0
	sea_coarse_cells = 0

	for coarse_row0 in range(0, coarse_height, chunk_coarse_rows):
		coarse_row1 = min(
			coarse_height,
			coarse_row0 + chunk_coarse_rows,
		)
		fine_row0 = coarse_row0 * factor
		fine_row1 = coarse_row1 * factor
		coarse_rows = coarse_row1 - coarse_row0

		elevation_chunk = np.asarray(
			elevation[fine_row0:fine_row1, :],
			dtype=np.float32,
		)
		elevation_blocks = elevation_chunk.reshape(
			coarse_rows,
			factor,
			coarse_width,
			factor,
		)
		finite = np.isfinite(elevation_blocks)
		safe = np.where(
			finite,
			elevation_blocks,
			np.float32(np.inf),
		)
		minimum = safe.min(axis=(1, 3))
		has_finite = finite.any(axis=(1, 3))
		minimum[~has_finite] = np.nan

		sea_chunk = np.asarray(
			sea_mask[fine_row0:fine_row1, :],
			dtype=np.uint8,
		)
		sea_blocks = sea_chunk.reshape(
			coarse_rows,
			factor,
			coarse_width,
			factor,
		)
		sea_or = sea_blocks.max(axis=(1, 3)).astype(
			np.uint8,
			copy=False,
		)

		coarse_elevation[coarse_row0:coarse_row1, :] = minimum
		coarse_sea[coarse_row0:coarse_row1, :] = sea_or

		finite_coarse_cells += int(np.count_nonzero(has_finite))
		sea_coarse_cells += int(np.count_nonzero(sea_or))

	coarse_elevation.flush()
	coarse_sea.flush()

	return {
		"fine_width": width,
		"fine_height": height,
		"fine_cells": cell_count,
		"factor": factor,
		"coarse_width": coarse_width,
		"coarse_height": coarse_height,
		"coarse_cells": coarse_cells,
		"elevation_rule": "minimum-of-finite-children",
		"sea_rule": "logical-or-of-children",
		"finite_coarse_cells": finite_coarse_cells,
		"sea_coarse_cells": sea_coarse_cells,
		"output_elevation_bytes": (
			coarse_cells * np.dtype(np.float32).itemsize
		),
		"output_sea_mask_bytes": (
			coarse_cells * np.dtype(np.uint8).itemsize
		),
	}


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--elevation", required=True)
	parser.add_argument("--sea-mask", required=True)
	parser.add_argument("--output-elevation", required=True)
	parser.add_argument("--output-sea-mask", required=True)
	parser.add_argument("--report", required=True)
	parser.add_argument("--width", type=int, required=True)
	parser.add_argument("--height", type=int, required=True)
	parser.add_argument("--factor", type=int, required=True)
	parser.add_argument("--chunk-coarse-rows", type=int, default=32)
	args = parser.parse_args()

	report = build_conservative_coarse(
		args.elevation,
		args.sea_mask,
		args.output_elevation,
		args.output_sea_mask,
		width=args.width,
		height=args.height,
		factor=args.factor,
		chunk_coarse_rows=args.chunk_coarse_rows,
	)

	Path(args.report).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
