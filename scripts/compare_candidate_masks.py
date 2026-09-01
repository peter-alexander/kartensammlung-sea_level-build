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


def unpack_bit_range(packed, start_bit, count):
	if count <= 0:
		return np.empty(0, dtype=bool)

	byte0 = start_bit // 8
	bit_offset = start_bit % 8
	byte1 = (start_bit + count + 7) // 8
	raw = np.asarray(packed[byte0:byte1], dtype=np.uint8)
	bits = np.unpackbits(raw, bitorder="little")

	return bits[
		bit_offset:bit_offset + count
	].astype(bool, copy=False)


def compare_candidate_masks(
	fine_mask_path,
	coarse_mask_path,
	sea_mask_path,
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

	fine_cells = width * height
	coarse_width = width // factor
	coarse_height = height // factor
	coarse_cells = coarse_width * coarse_height

	require_file_size(
		fine_mask_path,
		(fine_cells + 7) // 8,
	)
	require_file_size(
		coarse_mask_path,
		(coarse_cells + 7) // 8,
	)
	require_file_size(
		sea_mask_path,
		fine_cells,
	)

	fine_packed = np.memmap(
		fine_mask_path,
		dtype=np.uint8,
		mode="r",
	)
	coarse_packed = np.memmap(
		coarse_mask_path,
		dtype=np.uint8,
		mode="r",
	)
	sea_mask = np.memmap(
		sea_mask_path,
		dtype=np.uint8,
		mode="r",
		shape=(height, width),
	)

	metrics = {
		"fine_candidate_cells": 0,
		"conservative_candidate_cells": 0,
		"false_negative_cells": 0,
		"false_positive_cells": 0,
		"land_cells": 0,
		"fine_candidate_land_cells": 0,
		"conservative_candidate_land_cells": 0,
		"false_negative_land_cells": 0,
		"false_positive_land_cells": 0,
	}

	for coarse_row0 in range(0, coarse_height, chunk_coarse_rows):
		coarse_row1 = min(
			coarse_height,
			coarse_row0 + chunk_coarse_rows,
		)
		coarse_rows = coarse_row1 - coarse_row0
		fine_row0 = coarse_row0 * factor
		fine_rows = coarse_rows * factor

		coarse_start = coarse_row0 * coarse_width
		coarse_count = coarse_rows * coarse_width
		coarse_candidate = unpack_bit_range(
			coarse_packed,
			coarse_start,
			coarse_count,
		).reshape(coarse_rows, coarse_width)

		conservative = np.repeat(
			np.repeat(
				coarse_candidate,
				factor,
				axis=0,
			),
			factor,
			axis=1,
		)

		fine_start = fine_row0 * width
		fine_count = fine_rows * width
		fine_candidate = unpack_bit_range(
			fine_packed,
			fine_start,
			fine_count,
		).reshape(fine_rows, width)

		sea = np.asarray(
			sea_mask[
				fine_row0:fine_row0 + fine_rows,
				:
			],
			dtype=np.uint8,
		)
		land = sea == 0

		false_negative = fine_candidate & ~conservative
		false_positive = conservative & ~fine_candidate

		metrics["fine_candidate_cells"] += int(
			np.count_nonzero(fine_candidate)
		)
		metrics["conservative_candidate_cells"] += int(
			np.count_nonzero(conservative)
		)
		metrics["false_negative_cells"] += int(
			np.count_nonzero(false_negative)
		)
		metrics["false_positive_cells"] += int(
			np.count_nonzero(false_positive)
		)
		metrics["land_cells"] += int(
			np.count_nonzero(land)
		)
		metrics["fine_candidate_land_cells"] += int(
			np.count_nonzero(fine_candidate & land)
		)
		metrics["conservative_candidate_land_cells"] += int(
			np.count_nonzero(conservative & land)
		)
		metrics["false_negative_land_cells"] += int(
			np.count_nonzero(false_negative & land)
		)
		metrics["false_positive_land_cells"] += int(
			np.count_nonzero(false_positive & land)
		)

	fine_candidate_cells = metrics["fine_candidate_cells"]
	conservative_cells = metrics["conservative_candidate_cells"]
	land_cells = metrics["land_cells"]
	fine_candidate_land = metrics["fine_candidate_land_cells"]
	conservative_land = metrics[
		"conservative_candidate_land_cells"
	]

	def pct(value, denominator):
		if denominator == 0:
			return 0.0
		return round(
			float(value) * 100.0 / float(denominator),
			6,
		)

	report = {
		"fine_width": width,
		"fine_height": height,
		"fine_cells": fine_cells,
		"factor": factor,
		"coarse_width": coarse_width,
		"coarse_height": coarse_height,
		"coarse_cells": coarse_cells,
		**metrics,
		"fine_candidate_pct": pct(
			fine_candidate_cells,
			fine_cells,
		),
		"conservative_candidate_pct": pct(
			conservative_cells,
			fine_cells,
		),
		"conservative_total_excluded_pct": round(
			100.0 - pct(conservative_cells, fine_cells),
			6,
		),
		"false_negative_pct_of_fine_candidates": pct(
			metrics["false_negative_cells"],
			fine_candidate_cells,
		),
		"candidate_inflation_factor": (
			round(
				conservative_cells / fine_candidate_cells,
				6,
			)
			if fine_candidate_cells
			else None
		),
		"fine_candidate_land_pct": pct(
			fine_candidate_land,
			land_cells,
		),
		"conservative_candidate_land_pct": pct(
			conservative_land,
			land_cells,
		),
		"conservative_land_excluded_pct": round(
			100.0 - pct(conservative_land, land_cells),
			6,
		),
		"false_negative_land_pct_of_fine_candidates": pct(
			metrics["false_negative_land_cells"],
			fine_candidate_land,
		),
		"land_candidate_inflation_factor": (
			round(
				conservative_land / fine_candidate_land,
				6,
			)
			if fine_candidate_land
			else None
		),
	}

	return report


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--fine-mask", required=True)
	parser.add_argument("--coarse-mask", required=True)
	parser.add_argument("--sea-mask", required=True)
	parser.add_argument("--output", required=True)
	parser.add_argument("--width", type=int, required=True)
	parser.add_argument("--height", type=int, required=True)
	parser.add_argument("--factor", type=int, required=True)
	parser.add_argument("--chunk-coarse-rows", type=int, default=32)
	args = parser.parse_args()

	report = compare_candidate_masks(
		args.fine_mask,
		args.coarse_mask,
		args.sea_mask,
		width=args.width,
		height=args.height,
		factor=args.factor,
		chunk_coarse_rows=args.chunk_coarse_rows,
	)

	Path(args.output).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
