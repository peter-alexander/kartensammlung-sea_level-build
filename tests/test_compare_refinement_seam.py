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

from compare_refinement_seam import compare_refinement_seam
from build_composite_threshold import WEB_MERCATOR_RADIUS
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

		base_grid_path.write_text(
			json.dumps({
				"grid": {
					"zoom": 0,
					"width": 2,
					"height": 2,
					"resolution": 2.0,
					"left": 0.0,
					"top": 4.0,
				},
			}),
			encoding="utf-8",
		)
		fine_grid_path.write_text(
			json.dumps({
				"grid": {
					"zoom": 2,
					"width": 8,
					"height": 8,
					"resolution": 0.5,
					"left": 0.0,
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

		fine = np.repeat(
			np.repeat(base, 4, axis=0),
			4,
			axis=1,
		)
		fine[2:6, 2:6] = class_for_meters(9)
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

		report = compare_refinement_seam(
			base_grid_path,
			base_threshold_path,
			fine_grid_path,
			fine_threshold_path,
			core_path,
			chunk_rows=2,
		)

		seam = report["refinement_seam_vs_upsampled_base"]
		if seam["count"] != 12:
			raise AssertionError(report)
		if seam["exact_equal_pct"] != 0.0:
			raise AssertionError(report)

		slider = report[
			"refinement_seam_slider_disagreement_vs_upsampled_base"
		]
		if slider["maximum"]["different_cells"] != 12:
			raise AssertionError(slider)
		if slider["maximum"]["at_level_m"] != 4.0:
			raise AssertionError(slider)

	print("ok")


if __name__ == "__main__":
	main()
