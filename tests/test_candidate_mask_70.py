#!/usr/bin/env python3

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def unpack_mask(path, cells):
	data = np.fromfile(path, dtype=np.uint8)
	bits = np.unpackbits(
		data,
		bitorder="little",
	)
	return bits[:cells].astype(bool)


def main():
	elevation = np.asarray([
		[0, 10, 80, 20, 20, 20],
		[0, 10, 80, 20, 90, 20],
		[0, 10, 80, 20, 20, 20],
		[0, 10, 10, 10, 80, 20],
	], dtype=np.float32)
	sea = np.asarray([
		[1, 0, 0, 0, 0, 0],
		[1, 0, 0, 0, 0, 0],
		[1, 0, 0, 0, 0, 0],
		[1, 0, 0, 0, 0, 0],
	], dtype=np.uint8)

	expected = np.asarray([
		[1, 1, 0, 0, 0, 0],
		[1, 1, 0, 0, 0, 0],
		[1, 1, 0, 0, 0, 0],
		[1, 1, 1, 1, 0, 0],
	], dtype=bool)

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		elevation_path = tmp / "elevation.f32"
		sea_path = tmp / "sea.u8"
		mask_path = tmp / "candidate.bit"
		report_path = tmp / "report.json"

		elevation.tofile(elevation_path)
		sea.tofile(sea_path)

		subprocess.run([
			str(ROOT / "build" / "candidate_mask_70"),
			"--elevation", str(elevation_path),
			"--sea-mask", str(sea_path),
			"--output", str(mask_path),
			"--report", str(report_path),
			"--width", str(elevation.shape[1]),
			"--height", str(elevation.shape[0]),
			"--max-level", "70",
		], check=True)

		actual = unpack_mask(
			mask_path,
			elevation.size,
		).reshape(elevation.shape)

		if not np.array_equal(actual, expected):
			raise AssertionError(
				f"expected={expected.tolist()} actual={actual.tolist()}"
			)

		report = json.loads(report_path.read_text())
		if report["candidate_cells"] != int(np.count_nonzero(expected)):
			raise AssertionError(report)
		if report["packed_mask_bytes"] != 3:
			raise AssertionError(report)

	print("ok")


if __name__ == "__main__":
	main()
