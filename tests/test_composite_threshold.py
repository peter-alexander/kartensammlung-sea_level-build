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

	print("ok")


if __name__ == "__main__":
	main()
