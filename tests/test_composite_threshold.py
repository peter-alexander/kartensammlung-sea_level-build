#!/usr/bin/env python3

import json
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
from shapely.geometry import box, mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_composite_threshold import (
	WEB_MERCATOR_RADIUS,
	build_composite,
)
from threshold_levels import class_for_meters


def mercator_to_lonlat(x, y):
	return (
		math.degrees(x / WEB_MERCATOR_RADIUS),
		math.degrees(
			math.atan(
				math.sinh(y / WEB_MERCATOR_RADIUS)
			)
		),
	)


def main():
	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		base_grid_path = tmp / "base-grid.json"
		fine_grid_path = tmp / "fine-grid.json"
		base_threshold_path = tmp / "base.u8"
		fine_threshold_path = tmp / "fine.u8"
		core_path = tmp / "core.geojson"
		output_dir = tmp / "composite"

		base_grid_path.write_text(
			json.dumps({
				"config": {
					"bounds": {
						"west": 0,
						"south": 0,
						"east": 1,
						"north": 1,
					},
				},
				"grid": {
					"zoom": 0,
					"tile_size": 512,
					"x_min": 0,
					"x_max": 0,
					"y_min": 0,
					"y_max": 0,
					"width": 2,
					"height": 2,
					"cells": 4,
					"resolution": 2.0,
					"left": 0.0,
					"bottom": 0.0,
					"right": 4.0,
					"top": 4.0,
				},
			}),
			encoding="utf-8",
		)

		fine_grid_path.write_text(
			json.dumps({
				"grid": {
					"zoom": 1,
					"tile_size": 512,
					"x_min": 0,
					"x_max": 1,
					"y_min": 0,
					"y_max": 1,
					"width": 4,
					"height": 4,
					"cells": 16,
					"resolution": 1.0,
					"left": 0.0,
					"bottom": 0.0,
					"right": 4.0,
					"top": 4.0,
				},
			}),
			encoding="utf-8",
		)

		base = np.asarray([
			[class_for_meters(1), class_for_meters(2)],
			[class_for_meters(3), class_for_meters(4)],
		], dtype=np.uint8)
		base.tofile(base_threshold_path)

		fine = np.full((4, 4), class_for_meters(9), dtype=np.uint8)
		fine.tofile(fine_threshold_path)

		west, south = mercator_to_lonlat(1.0, 1.0)
		east, north = mercator_to_lonlat(3.0, 3.0)
		core_path.write_text(
			json.dumps({
				"type": "Feature",
				"properties": {"source": "synthetic"},
				"geometry": mapping(
					box(west, south, east, north)
				),
			}),
			encoding="utf-8",
		)

		report = build_composite(
			base_grid_path,
			base_threshold_path,
			fine_grid_path,
			fine_threshold_path,
			core_path,
			output_dir,
			chunk_rows=2,
		)

		actual = np.fromfile(
			output_dir / "threshold.u8",
			dtype=np.uint8,
		).reshape((4, 4))

		expected = np.asarray([
			[class_for_meters(1), class_for_meters(1), class_for_meters(2), class_for_meters(2)],
			[class_for_meters(1), class_for_meters(9), class_for_meters(9), class_for_meters(2)],
			[class_for_meters(3), class_for_meters(9), class_for_meters(9), class_for_meters(4)],
			[class_for_meters(3), class_for_meters(3), class_for_meters(4), class_for_meters(4)],
		], dtype=np.uint8)

		if not np.array_equal(actual, expected):
			raise AssertionError(
				f"expected={expected.tolist()} actual={actual.tolist()}"
			)

		if report["fine_pixels_written"] != 4:
			raise AssertionError(report)
		if report["core_vs_upsampled_base"]["max_abs_diff_m"] != 8.0:
			raise AssertionError(report)
		if report["source_coverage_seam_vs_upsampled_base"]["count"] != 4:
			raise AssertionError(report)
		if report["parent_clip_boundary_vs_upsampled_base"]["count"] != 0:
			raise AssertionError(report)

		slider = report[
			"source_coverage_seam_slider_disagreement_vs_upsampled_base"
		]
		if slider["count"] != 4:
			raise AssertionError(slider)
		if slider["by_level"]["2"]["different_cells"] != 2:
			raise AssertionError(slider)
		if slider["maximum"]["different_cells"] != 4:
			raise AssertionError(slider)
		if slider["maximum"]["at_level_m"] != 4.0:
			raise AssertionError(slider)

		fine_grid_z13_path = tmp / "fine-grid-z13.json"
		fine_threshold_z13_path = tmp / "fine-z13.u8"
		core_z13_path = tmp / "core-z13.geojson"
		output_z13_dir = tmp / "composite-z13"

		fine_grid_z13_path.write_text(
			json.dumps({
				"grid": {
					"zoom": 2,
					"tile_size": 512,
					"x_min": 0,
					"x_max": 3,
					"y_min": 0,
					"y_max": 3,
					"width": 8,
					"height": 8,
					"cells": 64,
					"resolution": 0.5,
					"left": 0.0,
					"bottom": 0.0,
					"right": 4.0,
					"top": 4.0,
				},
			}),
			encoding="utf-8",
		)

		fine_z13 = np.full(
			(8, 8),
			class_for_meters(9),
			dtype=np.uint8,
		)
		fine_z13.tofile(fine_threshold_z13_path)

		west_z13, south_z13 = mercator_to_lonlat(1.0, 1.0)
		east_z13, north_z13 = mercator_to_lonlat(3.0, 3.0)
		core_z13_path.write_text(
			json.dumps({
				"type": "Feature",
				"properties": {"source": "synthetic-z13"},
				"geometry": mapping(
					box(
						west_z13,
						south_z13,
						east_z13,
						north_z13,
					)
				),
			}),
			encoding="utf-8",
		)

		report_z13 = build_composite(
			base_grid_path,
			base_threshold_path,
			fine_grid_z13_path,
			fine_threshold_z13_path,
			core_z13_path,
			output_z13_dir,
			chunk_rows=2,
		)

		actual_z13 = np.fromfile(
			output_z13_dir / "threshold.u8",
			dtype=np.uint8,
		).reshape((8, 8))
		expected_z13 = np.repeat(
			np.repeat(base, 4, axis=0),
			4,
			axis=1,
		)
		expected_z13[2:6, 2:6] = class_for_meters(9)

		if not np.array_equal(actual_z13, expected_z13):
			raise AssertionError(
				f"expected_z13={expected_z13.tolist()} "
				f"actual_z13={actual_z13.tolist()}"
			)
		if report_z13["factor"] != 4:
			raise AssertionError(report_z13)
		if report_z13["fine_pixels_written"] != 16:
			raise AssertionError(report_z13)

	print("ok")


if __name__ == "__main__":
	main()
