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
	chunk_coarse_rows=0,
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
	if chunk_coarse_rows < 0:
		raise ValueError("chunk_coarse_rows muss >= 0 sein.")
	if chunk_coarse_rows == 0:
		chunk_coarse_rows = max(1, 64 // factor)

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

	output_elevation_path = Path(output_elevation_path)
	output_sea_mask_path = Path(output_sea_mask_path)
	output_elevation_path.parent.mkdir(parents=True, exist_ok=True)
	output_sea_mask_path.parent.mkdir(parents=True, exist_ok=True)

	finite_coarse_cells = 0
	sea_coarse_cells = 0

	with (
		open(elevation_path, "rb") as elevation_file,
		open(sea_mask_path, "rb") as sea_file,
		open(output_elevation_path, "wb") as coarse_elevation_file,
		open(output_sea_mask_path, "wb") as coarse_sea_file,
	):
		for coarse_row0 in range(
			0,
			coarse_height,
			chunk_coarse_rows,
		):
			coarse_row1 = min(
				coarse_height,
				coarse_row0 + chunk_coarse_rows,
			)
			coarse_rows = coarse_row1 - coarse_row0
			fine_rows = coarse_rows * factor
			fine_count = fine_rows * width

			elevation_chunk = np.fromfile(
				elevation_file,
				dtype=np.float32,
				count=fine_count,
			)
			if elevation_chunk.size != fine_count:
				raise RuntimeError(
					"Elevation konnte nicht vollständig "
					"sequentiell gelesen werden."
				)

			safe = np.nan_to_num(
				elevation_chunk,
				copy=True,
				nan=np.inf,
				posinf=np.inf,
				neginf=np.inf,
			)
			safe_blocks = safe.reshape(
				coarse_rows,
				factor,
				coarse_width,
				factor,
			)
			minimum = safe_blocks.min(axis=(1, 3))
			has_finite = np.isfinite(minimum)
			minimum[~has_finite] = np.nan

			sea_chunk = np.fromfile(
				sea_file,
				dtype=np.uint8,
				count=fine_count,
			)
			if sea_chunk.size != fine_count:
				raise RuntimeError(
					"Sea-Maske konnte nicht vollständig "
					"sequentiell gelesen werden."
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

			minimum.astype(
				np.float32,
				copy=False,
			).tofile(coarse_elevation_file)
			sea_or.tofile(coarse_sea_file)

			finite_coarse_cells += int(
				np.count_nonzero(has_finite)
			)
			sea_coarse_cells += int(
				np.count_nonzero(sea_or)
			)

	return {
		"fine_width": width,
		"fine_height": height,
		"fine_cells": cell_count,
		"factor": factor,
		"chunk_coarse_rows": chunk_coarse_rows,
		"chunk_fine_rows": chunk_coarse_rows * factor,
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
	parser.add_argument("--chunk-coarse-rows", type=int, default=0)
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
