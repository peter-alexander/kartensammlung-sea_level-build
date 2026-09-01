#!/usr/bin/env python3

import json
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mask_candidate_to_work_region import mask_candidate


def test_streaming_component_filter():
	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)

		components = tmp / "components.json"
		spans = tmp / "components.rle"
		parent_grid = tmp / "parent-grid.json"
		fine_grid = tmp / "fine-grid.json"
		candidate = tmp / "candidate.bit"
		output = tmp / "filtered.bit"

		components.write_text(json.dumps({
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
		}))
		with spans.open("wb") as target:
			target.write(struct.pack("<III", 1, 1, 2))
			target.write(struct.pack("<III", 2, 1, 1))

		parent_grid.write_text(json.dumps({
			"grid": {
				"width": 8,
				"height": 8,
				"left": 0.0,
				"top": 80.0,
				"resolution": 10.0,
			},
		}))
		fine_grid.write_text(json.dumps({
			"grid": {
				"width": 16,
				"height": 16,
				"left": 0.0,
				"top": 80.0,
				"resolution": 5.0,
			},
		}))

		np.full(32, 0xFF, dtype=np.uint8).tofile(candidate)

		report = mask_candidate(
			candidate,
			output,
			components,
			spans,
			7,
			parent_grid,
			fine_grid,
			coarse_factor=2,
		)

		if report["fine_pixels_per_coarse_cell"] != 4:
			raise AssertionError(report)
		if report["output_candidate_cells"] != 48:
			raise AssertionError(report)
		if report["removed_candidate_cells"] != 208:
			raise AssertionError(report)
		if report["rows_with_component_core"] != 8:
			raise AssertionError(report)

		bits = np.unpackbits(
			np.fromfile(output, dtype=np.uint8),
			bitorder="little",
		).reshape((16, 16))

		expected = np.zeros((16, 16), dtype=np.uint8)
		expected[4:8, 4:12] = 1
		expected[8:12, 4:8] = 1

		if not np.array_equal(bits, expected):
			raise AssertionError(
				"Gefilterte Highres-Core-Maske ist falsch."
			)


def main():
	test_streaming_component_filter()
	print("ok")


if __name__ == "__main__":
	main()
