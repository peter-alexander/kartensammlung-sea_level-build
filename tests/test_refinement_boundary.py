#!/usr/bin/env python3

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_refinement_boundary import build_boundary


def write_grid(path, *, width, height, resolution, left, top):
	data = {
		"grid": {
			"width": width,
			"height": height,
			"resolution": resolution,
			"left": left,
			"top": top,
		}
	}
	Path(path).write_text(json.dumps(data), encoding="utf-8")


def main():
	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		coarse_grid = tmp / "coarse-grid.json"
		fine_grid = tmp / "fine-grid.json"
		coarse_threshold = tmp / "coarse.u8"
		output = tmp / "boundary.u8"

		write_grid(
			coarse_grid,
			width=2,
			height=2,
			resolution=2.0,
			left=0.0,
			top=4.0,
		)
		write_grid(
			fine_grid,
			width=4,
			height=4,
			resolution=1.0,
			left=0.0,
			top=4.0,
		)

		np.asarray([
			[1, 2],
			[3, 4],
		], dtype=np.uint8).tofile(coarse_threshold)

		report = build_boundary(
			coarse_grid,
			coarse_threshold,
			fine_grid,
			output,
		)

		actual = np.fromfile(output, dtype=np.uint8).reshape((4, 4))
		expected = np.asarray([
			[1, 1, 2, 2],
			[1, 255, 255, 2],
			[3, 255, 255, 4],
			[3, 3, 4, 4],
		], dtype=np.uint8)

		if not np.array_equal(actual, expected):
			raise AssertionError(
				f"expected={expected.tolist()} actual={actual.tolist()}"
			)

		if report["active_boundary_seeds"] != 12:
			raise AssertionError(report)

		fine_grid_z13 = tmp / "fine-grid-z13.json"
		output_z13 = tmp / "boundary-z13.u8"
		write_grid(
			fine_grid_z13,
			width=8,
			height=8,
			resolution=0.5,
			left=0.0,
			top=4.0,
		)

		report_z13 = build_boundary(
			coarse_grid,
			coarse_threshold,
			fine_grid_z13,
			output_z13,
		)
		actual_z13 = np.fromfile(
			output_z13,
			dtype=np.uint8,
		).reshape((8, 8))

		if not np.all(actual_z13[0, :4] == 1):
			raise AssertionError(actual_z13.tolist())
		if not np.all(actual_z13[0, 4:] == 2):
			raise AssertionError(actual_z13.tolist())
		if not np.all(actual_z13[-1, :4] == 3):
			raise AssertionError(actual_z13.tolist())
		if not np.all(actual_z13[-1, 4:] == 4):
			raise AssertionError(actual_z13.tolist())
		if not np.all(actual_z13[1:4, 0] == 1):
			raise AssertionError(actual_z13.tolist())
		if not np.all(actual_z13[4:-1, 0] == 3):
			raise AssertionError(actual_z13.tolist())
		if not np.all(actual_z13[1:4, -1] == 2):
			raise AssertionError(actual_z13.tolist())
		if not np.all(actual_z13[4:-1, -1] == 4):
			raise AssertionError(actual_z13.tolist())
		if not np.all(actual_z13[1:-1, 1:-1] == 255):
			raise AssertionError(actual_z13.tolist())
		if report_z13["active_boundary_seeds"] != 28:
			raise AssertionError(report_z13)

	print("ok")


if __name__ == "__main__":
	main()
