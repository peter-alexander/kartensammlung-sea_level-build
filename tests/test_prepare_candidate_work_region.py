#!/usr/bin/env python3

import json
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_candidate_work_region import build_work_region


def write_spans(path, spans):
	with Path(path).open("wb") as target:
		for row, left, right in spans:
			target.write(
				struct.pack("<III", row, left, right)
			)


def test_component_geometry():
	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		report_path = tmp / "components.json"
		spans_path = tmp / "components.rle"
		grid_path = tmp / "grid.json"
		geojson_path = tmp / "work.geojson"
		output_report = tmp / "work.json"

		report_path.write_text(
			json.dumps({
				"width": 4,
				"height": 4,
				"components": [{
					"id": 7,
					"rank": 1,
					"cells": 3,
					"span_offset_records": 0,
					"span_count": 2,
					"bbox_cells": [1, 1, 2, 2],
				}],
			})
		)
		write_spans(
			spans_path,
			[
				(1, 1, 2),
				(2, 1, 1),
			],
		)
		grid_path.write_text(
			json.dumps({
				"grid": {
					"width": 8,
					"height": 8,
					"left": 0.0,
					"top": 80.0,
					"resolution": 10.0,
				},
			})
		)

		result = build_work_region(
			report_path,
			spans_path,
			grid_path,
			7,
			factor=2,
			halo_coarse_cells=0,
			output_geojson=geojson_path,
			output_report=output_report,
		)

		if abs(result["work_geometry_area_m2"] - 1200.0) > 1e-6:
			raise AssertionError(result)
		if result["work_bbox_parent_cells"] != [2, 2, 6, 6]:
			raise AssertionError(result)
		if result["work_bbox_parent_cell_count"] != 16:
			raise AssertionError(result)

		halo_result = build_work_region(
			report_path,
			spans_path,
			grid_path,
			7,
			factor=2,
			halo_coarse_cells=1,
			output_geojson=geojson_path,
			output_report=output_report,
		)
		if abs(
			halo_result["work_geometry_area_m2"] - 6000.0
		) > 1e-6:
			raise AssertionError(halo_result)
		if halo_result["work_bbox_parent_cells"] != [0, 0, 8, 8]:
			raise AssertionError(halo_result)
		if halo_result["work_bbox_parent_cell_count"] != 64:
			raise AssertionError(halo_result)


def main():
	test_component_geometry()
	print("ok")


if __name__ == "__main__":
	main()
