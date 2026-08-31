#!/usr/bin/env python3

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from priority_flood import compute_inundation_threshold


def quantize_exact(values, max_level=100, step=1.0):
	array = np.asarray(values, dtype=np.float64)
	out = np.ceil(np.maximum(array, 0.0) / step).astype(np.int64)
	out[out > max_level] = max_level + 1
	return out.astype(np.uint8)


def main():
	elevation = np.asarray([
		[0, 2, 8, 4, 4, 4],
		[0, 2, 8, -4, -4, 4],
		[0, 2, 8, -4, -4, 12],
		[0, -2, 8, 4, 4, 4],
	], dtype=np.float32)

	sea = np.asarray([
		[1, 0, 0, 0, 0, 0],
		[1, 0, 0, 0, 0, 0],
		[1, 0, 0, 0, 0, 0],
		[1, 0, 0, 0, 0, 0],
	], dtype=np.uint8)

	exact = compute_inundation_threshold(
		elevation.tolist(),
		sea.astype(bool).tolist(),
		connectivity=4,
	)
	expected = quantize_exact(exact)

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		elevation_path = tmp / "elevation.f32"
		sea_path = tmp / "sea.u8"
		output_path = tmp / "threshold.u8"

		elevation.tofile(elevation_path)
		sea.tofile(sea_path)

		subprocess.run([
			str(ROOT / "build" / "priority_flood_quantized"),
			"--elevation", str(elevation_path),
			"--sea-mask", str(sea_path),
			"--output", str(output_path),
			"--width", str(elevation.shape[1]),
			"--height", str(elevation.shape[0]),
			"--max-level", "100",
			"--step", "1",
			"--connectivity", "4",
		], check=True)

		actual = np.fromfile(output_path, dtype=np.uint8).reshape(elevation.shape)

	if not np.array_equal(actual, expected):
		raise AssertionError(
			"Quantized Priority Flood stimmt nicht mit Referenz überein.\n"
			f"expected={expected.tolist()}\n"
			f"actual={actual.tolist()}"
		)

	print(json.dumps({
		"status": "ok",
		"expected": expected.tolist(),
		"actual": actual.tolist(),
	}, indent=2))


if __name__ == "__main__":
	main()
