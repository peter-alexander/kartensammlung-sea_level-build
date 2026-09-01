#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import numpy as np


SPAN_RECORD_BYTES = 12


def require_file_size(path, expected):
	path = Path(path)
	actual = path.stat().st_size
	if actual != expected:
		raise ValueError(
			f"Unerwartete Dateigröße für {path}: "
			f"erwartet={expected}, tatsächlich={actual}"
		)


def find_component(report, component_id):
	for component in report["components"]:
		if int(component["id"]) == int(component_id):
			return component
	raise ValueError(
		f"Component-ID {component_id} wurde nicht gefunden."
	)


def copy_window(
	source_path,
	target_path,
	*,
	dtype,
	global_width,
	global_height,
	x0,
	y0,
	width,
	height,
):
	itemsize = np.dtype(dtype).itemsize
	require_file_size(
		source_path,
		global_width * global_height * itemsize,
	)

	with (
		open(source_path, "rb") as source,
		open(target_path, "wb") as target,
	):
		for row in range(y0, y0 + height):
			offset = (
				(row * global_width + x0)
				* itemsize
			)
			source.seek(offset)
			data = source.read(width * itemsize)
			if len(data) != width * itemsize:
				raise RuntimeError(
					"Quellfenster konnte nicht vollständig "
					"gelesen werden."
				)
			target.write(data)


def set_packed_range(packed, start, end):
	if end < start:
		return

	first_byte = start >> 3
	last_byte = end >> 3
	first_bit = start & 7
	last_bit = end & 7

	if first_byte == last_byte:
		mask = (
			((1 << (last_bit - first_bit + 1)) - 1)
			<< first_bit
		)
		packed[first_byte] |= np.uint8(mask)
		return

	packed[first_byte] |= np.uint8(
		(0xFF << first_bit) & 0xFF
	)
	if last_byte > first_byte + 1:
		packed[first_byte + 1:last_byte] = 0xFF
	packed[last_byte] |= np.uint8(
		(1 << (last_bit + 1)) - 1
	)


def build_local_land_mask(
	spans_path,
	component,
	output_path,
	*,
	x0,
	y0,
	width,
	height,
):
	cell_count = width * height
	packed = np.zeros(
		(cell_count + 7) // 8,
		dtype=np.uint8,
	)

	offset_records = int(
		component["span_offset_records"]
	)
	span_count = int(component["span_count"])

	require_file_size(
		spans_path,
		int(component.get(
			"_expected_spans_file_bytes",
			Path(spans_path).stat().st_size,
		)),
	)

	with open(spans_path, "rb") as source:
		source.seek(offset_records * SPAN_RECORD_BYTES)
		remaining = span_count

		while remaining:
			count = min(remaining, 1 << 16)
			raw = source.read(count * SPAN_RECORD_BYTES)
			if len(raw) != count * SPAN_RECORD_BYTES:
				raise RuntimeError(
					"Span-Datei endet innerhalb der Komponente."
				)

			spans = np.frombuffer(
				raw,
				dtype="<u4",
			).reshape((-1, 3))

			for row, left, right in spans:
				local_row = int(row) - y0
				local_left = int(left) - x0
				local_right = int(right) - x0

				if (
					local_row < 0
					or local_row >= height
					or local_left < 0
					or local_right >= width
				):
					raise RuntimeError(
						"Component-Span liegt außerhalb "
						"des lokalen Fensters."
					)

				start = (
					local_row * width
					+ local_left
				)
				end = (
					local_row * width
					+ local_right
				)
				set_packed_range(
					packed,
					start,
					end,
				)

			remaining -= count

	packed.tofile(output_path)

	return {
		"mask_bytes": int(packed.nbytes),
		"mask_cells": int(
			np.unpackbits(
				packed,
				bitorder="little",
			)[:cell_count].sum()
		),
	}


def materialize(
	components_report_path,
	spans_path,
	component_id,
	elevation_path,
	sea_mask_path,
	output_dir,
	*,
	global_width,
	global_height,
	halo=1,
):
	if global_width <= 0 or global_height <= 0:
		raise ValueError(
			"global_width und global_height müssen > 0 sein."
		)
	if halo < 0:
		raise ValueError("halo muss >= 0 sein.")

	report = json.loads(
		Path(components_report_path).read_text()
	)
	component = find_component(
		report,
		component_id,
	)

	min_col, min_row, max_col, max_row = (
		int(value)
		for value in component["bbox_cells"]
	)

	x0 = max(0, min_col - halo)
	y0 = max(0, min_row - halo)
	x1 = min(global_width - 1, max_col + halo)
	y1 = min(global_height - 1, max_row + halo)
	width = x1 - x0 + 1
	height = y1 - y0 + 1

	output_dir = Path(output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	local_elevation = output_dir / "elevation.f32"
	local_sea = output_dir / "sea_mask.u8"
	local_land = output_dir / "land_mask.bit"

	copy_window(
		elevation_path,
		local_elevation,
		dtype=np.float32,
		global_width=global_width,
		global_height=global_height,
		x0=x0,
		y0=y0,
		width=width,
		height=height,
	)
	copy_window(
		sea_mask_path,
		local_sea,
		dtype=np.uint8,
		global_width=global_width,
		global_height=global_height,
		x0=x0,
		y0=y0,
		width=width,
		height=height,
	)

	mask_report = build_local_land_mask(
		spans_path,
		component,
		local_land,
		x0=x0,
		y0=y0,
		width=width,
		height=height,
	)

	if mask_report["mask_cells"] != int(
		component["cells"]
	):
		raise RuntimeError(
			"Materialisierte Landmaske enthält nicht "
			"genau die Component-Zellen."
		)

	result = {
		"component_id": int(component["id"]),
		"component_rank": int(component["rank"]),
		"component_cells": int(component["cells"]),
		"component_coastal_cells": int(
			component["coastal_cells"]
		),
		"global_width": int(global_width),
		"global_height": int(global_height),
		"halo": int(halo),
		"window": {
			"x0": x0,
			"y0": y0,
			"x1": x1,
			"y1": y1,
			"width": width,
			"height": height,
			"cells": width * height,
		},
		"component_fill_pct": (
			float(component["cells"])
			* 100.0
			/ float(width * height)
		),
		"elevation_path": str(local_elevation),
		"sea_mask_path": str(local_sea),
		"land_mask_path": str(local_land),
		**mask_report,
	}

	(output_dir / "component.json").write_text(
		json.dumps(result, indent=2) + "\n",
		encoding="utf-8",
	)

	return result


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--components-report", required=True)
	parser.add_argument("--spans", required=True)
	parser.add_argument("--component-id", type=int, required=True)
	parser.add_argument("--elevation", required=True)
	parser.add_argument("--sea-mask", required=True)
	parser.add_argument("--output-dir", required=True)
	parser.add_argument("--global-width", type=int, required=True)
	parser.add_argument("--global-height", type=int, required=True)
	parser.add_argument("--halo", type=int, default=1)
	args = parser.parse_args()

	report = materialize(
		args.components_report,
		args.spans,
		args.component_id,
		args.elevation,
		args.sea_mask,
		args.output_dir,
		global_width=args.global_width,
		global_height=args.global_height,
		halo=args.halo,
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
