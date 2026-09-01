#!/usr/bin/env python3

import argparse
import json
import math
import struct
from collections import defaultdict
from pathlib import Path

import numpy as np


SPAN_RECORD_BYTES = 12
POPCOUNT = np.asarray(
	[bin(value).count("1") for value in range(256)],
	dtype=np.uint8,
)


def find_component(report, component_id):
	for component in report["components"]:
		if int(component["id"]) == int(component_id):
			return component
	raise ValueError(
		f"Component-ID {component_id} wurde nicht gefunden."
	)


def read_spans_by_row(path, component):
	offset_records = int(component["span_offset_records"])
	span_count = int(component["span_count"])
	result = defaultdict(list)

	with Path(path).open("rb") as source:
		source.seek(offset_records * SPAN_RECORD_BYTES)
		for _ in range(span_count):
			raw = source.read(SPAN_RECORD_BYTES)
			if len(raw) != SPAN_RECORD_BYTES:
				raise RuntimeError(
					"Span-Datei endet innerhalb der Component."
				)
			row, left, right = struct.unpack("<III", raw)
			result[int(row)].append(
				(int(left), int(right))
			)

	for intervals in result.values():
		intervals.sort()

	return result


def require_candidate_size(path, width, height):
	cells = int(width) * int(height)
	expected = (cells + 7) // 8
	actual = Path(path).stat().st_size
	if actual != expected:
		raise ValueError(
			f"Unerwartete Candidate-Dateigröße: "
			f"erwartet={expected}, tatsächlich={actual}"
		)
	if int(width) % 8 != 0:
		raise ValueError(
			"Fine-Grid-Breite muss für Streaming durch 8 teilbar sein."
		)


def map_intervals_to_fine(
	spans_by_row,
	parent_grid,
	fine_grid,
	*,
	coarse_factor,
):
	parent_resolution = float(parent_grid["resolution"])
	fine_resolution = float(fine_grid["resolution"])
	coarse_resolution = (
		parent_resolution * int(coarse_factor)
	)
	scale = coarse_resolution / fine_resolution
	scale_rounded = int(round(scale))

	if not math.isclose(
		scale,
		scale_rounded,
		rel_tol=0.0,
		abs_tol=1e-8,
	):
		raise ValueError(
			"Coarse- und Fine-Raster sind nicht hierarchisch ausgerichtet."
		)

	mapped = {}
	for coarse_row, intervals in spans_by_row.items():
		fine_intervals = []
		for left, right in intervals:
			x0 = (
				float(parent_grid["left"])
				+ left * coarse_resolution
			)
			x1 = (
				float(parent_grid["left"])
				+ (right + 1) * coarse_resolution
			)
			col0 = int(round(
				(x0 - float(fine_grid["left"]))
				/ fine_resolution
			))
			col1 = int(round(
				(x1 - float(fine_grid["left"]))
				/ fine_resolution
			))
			col0 = max(0, col0)
			col1 = min(int(fine_grid["width"]), col1)
			if col1 <= col0:
				continue
			if col0 % 8 != 0 or col1 % 8 != 0:
				raise ValueError(
					"Component-Grenzen sind nicht byte-aligned "
					"im Fine-Raster."
				)
			fine_intervals.append((col0, col1))

		if fine_intervals:
			mapped[int(coarse_row)] = fine_intervals

	return mapped, scale_rounded


def fine_row_to_coarse_row(
	fine_row,
	parent_grid,
	fine_grid,
	*,
	coarse_factor,
):
	fine_resolution = float(fine_grid["resolution"])
	y = (
		float(fine_grid["top"])
		- (int(fine_row) + 0.5) * fine_resolution
	)
	parent_row = math.floor(
		(float(parent_grid["top"]) - y)
		/ float(parent_grid["resolution"])
	)
	return int(parent_row) // int(coarse_factor)


def mask_candidate(
	candidate_path,
	output_path,
	components_report_path,
	spans_path,
	component_id,
	parent_grid_path,
	fine_grid_path,
	*,
	coarse_factor,
):
	components_report = json.loads(
		Path(components_report_path).read_text(encoding="utf-8")
	)
	component = find_component(
		components_report,
		component_id,
	)
	parent_grid = json.loads(
		Path(parent_grid_path).read_text(encoding="utf-8")
	)["grid"]
	fine_grid = json.loads(
		Path(fine_grid_path).read_text(encoding="utf-8")
	)["grid"]

	require_candidate_size(
		candidate_path,
		fine_grid["width"],
		fine_grid["height"],
	)

	if int(parent_grid["width"]) % int(coarse_factor) != 0:
		raise ValueError(
			"Parent-Grid-Breite ist nicht durch coarse_factor teilbar."
		)
	if int(parent_grid["height"]) % int(coarse_factor) != 0:
		raise ValueError(
			"Parent-Grid-Höhe ist nicht durch coarse_factor teilbar."
		)
	if (
		int(parent_grid["width"]) // int(coarse_factor)
		!= int(components_report["width"])
		or int(parent_grid["height"]) // int(coarse_factor)
		!= int(components_report["height"])
	):
		raise ValueError(
			"Component-Report passt nicht zum Parent-Grid/factor."
		)

	spans_by_row = read_spans_by_row(
		spans_path,
		component,
	)
	mapped_intervals, fine_per_coarse = (
		map_intervals_to_fine(
			spans_by_row,
			parent_grid,
			fine_grid,
			coarse_factor=coarse_factor,
		)
	)

	width = int(fine_grid["width"])
	height = int(fine_grid["height"])
	row_bytes = width // 8
	input_candidate_cells = 0
	output_candidate_cells = 0
	rows_with_core = 0

	output_path = Path(output_path)
	output_path.parent.mkdir(parents=True, exist_ok=True)

	with (
		Path(candidate_path).open("rb") as source,
		output_path.open("wb") as target,
	):
		for fine_row in range(height):
			raw = source.read(row_bytes)
			if len(raw) != row_bytes:
				raise RuntimeError(
					"Candidate-Datei endet innerhalb einer Zeile."
				)

			source_row = np.frombuffer(
				raw,
				dtype=np.uint8,
			)
			input_candidate_cells += int(
				POPCOUNT[source_row].sum()
			)

			coarse_row = fine_row_to_coarse_row(
				fine_row,
				parent_grid,
				fine_grid,
				coarse_factor=coarse_factor,
			)
			intervals = mapped_intervals.get(coarse_row)
			if not intervals:
				target.write(bytes(row_bytes))
				continue

			rows_with_core += 1
			output_row = np.zeros(
				row_bytes,
				dtype=np.uint8,
			)
			for col0, col1 in intervals:
				byte0 = col0 // 8
				byte1 = col1 // 8
				output_row[byte0:byte1] = (
					source_row[byte0:byte1]
				)

			output_candidate_cells += int(
				POPCOUNT[output_row].sum()
			)
			target.write(output_row.tobytes())

	result = {
		"component_id": int(component["id"]),
		"component_rank": int(component["rank"]),
		"component_cells_coarse": int(component["cells"]),
		"coarse_factor": int(coarse_factor),
		"fine_pixels_per_coarse_cell": int(
			fine_per_coarse
		),
		"fine_width": width,
		"fine_height": height,
		"fine_cells": width * height,
		"rows_with_component_core": rows_with_core,
		"input_candidate_cells": input_candidate_cells,
		"output_candidate_cells": output_candidate_cells,
		"removed_candidate_cells": (
			input_candidate_cells
			- output_candidate_cells
		),
		"output_bytes": output_path.stat().st_size,
	}

	report_path = output_path.with_suffix(
		output_path.suffix + ".report.json"
	)
	report_path.write_text(
		json.dumps(result, indent=2) + "\n",
		encoding="utf-8",
	)

	return result


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Begrenzt einen exakten Highres-Candidate auf die "
			"RLE-Core-Geometrie einer groben Work Region."
		)
	)
	parser.add_argument("--candidate-mask", required=True)
	parser.add_argument("--output", required=True)
	parser.add_argument("--components-report", required=True)
	parser.add_argument("--spans", required=True)
	parser.add_argument("--component-id", type=int, required=True)
	parser.add_argument("--parent-grid", required=True)
	parser.add_argument("--fine-grid", required=True)
	parser.add_argument("--coarse-factor", type=int, required=True)
	args = parser.parse_args()

	result = mask_candidate(
		args.candidate_mask,
		args.output,
		args.components_report,
		args.spans,
		args.component_id,
		args.parent_grid,
		args.fine_grid,
		coarse_factor=args.coarse_factor,
	)
	print(json.dumps(result, indent=2))


if __name__ == "__main__":
	main()
