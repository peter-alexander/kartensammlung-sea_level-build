#!/usr/bin/env python3

import subprocess
import tempfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def pack_mask(mask, path):
	np.packbits(
		mask.reshape(-1).astype(np.uint8),
		bitorder="little",
	).tofile(path)


def run_land_solver(
	elevation_path,
	sea_path,
	mask,
	output_path,
	levels,
):
	mask_path = output_path.with_suffix(".mask.bit")
	pack_mask(mask, mask_path)

	subprocess.run([
		str(ROOT / "build" / "priority_flood_land_mask"),
		"--elevation", str(elevation_path),
		"--sea-mask", str(sea_path),
		"--land-mask", str(mask_path),
		"--output", str(output_path),
		"--width", str(mask.shape[1]),
		"--height", str(mask.shape[0]),
		"--levels", levels,
	], check=True)


def main():
	# Das Meer trennt links und rechts zwei unabhängige
	# Landkomponenten. Der globale Solver darf beide gleichzeitig
	# rechnen; der neue Kern rechnet sie nacheinander.
	elevation = np.asarray([
		[0.0, 0.2, -5.0, 0.1, 0.0],
		[0.0, 0.4, -5.0, 0.3, 0.0],
		[0.0, 0.6, -5.0, 0.5, 0.0],
		[0.0, 0.8, -5.0, 0.7, 0.0],
		[0.0, 1.0, -5.0, 0.9, 0.0],
	], dtype=np.float32)

	sea = np.zeros(elevation.shape, dtype=np.uint8)
	sea[:, 2] = 1

	levels = subprocess.check_output([
		"python",
		str(ROOT / "scripts" / "threshold_levels.py"),
		"--csv",
	], text=True).strip()

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		elevation_path = tmp / "elevation.f32"
		sea_path = tmp / "sea.u8"
		full_path = tmp / "full.u8"
		left_path = tmp / "left.u8"
		right_path = tmp / "right.u8"

		elevation.tofile(elevation_path)
		sea.tofile(sea_path)

		subprocess.run([
			str(ROOT / "build" / "priority_flood_quantized"),
			"--elevation", str(elevation_path),
			"--sea-mask", str(sea_path),
			"--output", str(full_path),
			"--width", str(elevation.shape[1]),
			"--height", str(elevation.shape[0]),
			"--levels", levels,
			"--connectivity", "4",
		], check=True)

		full = np.fromfile(
			full_path,
			dtype=np.uint8,
		).reshape(elevation.shape)
		sentinel = len(levels.split(","))

		candidate_land = (
			(full != sentinel)
			& (sea == 0)
		)
		left = candidate_land.copy()
		left[:, 3:] = False
		right = candidate_land.copy()
		right[:, :3] = False

		run_land_solver(
			elevation_path,
			sea_path,
			left,
			left_path,
			levels,
		)
		run_land_solver(
			elevation_path,
			sea_path,
			right,
			right_path,
			levels,
		)

		left_result = np.fromfile(
			left_path,
			dtype=np.uint8,
		).reshape(elevation.shape)
		right_result = np.fromfile(
			right_path,
			dtype=np.uint8,
		).reshape(elevation.shape)

		merged = np.full(
			elevation.shape,
			sentinel,
			dtype=np.uint8,
		)
		merged[left] = left_result[left]
		merged[right] = right_result[right]

		if not np.array_equal(
			merged[candidate_land],
			full[candidate_land],
		):
			raise AssertionError(
				"Seriell gerechnete Landkomponenten unterscheiden "
				"sich vom globalen Priority Flood."
			)

		if not np.all(
			merged[~candidate_land] == sentinel
		):
			raise AssertionError(
				"Außerhalb der Landkomponenten muss Sentinel stehen."
			)

	print("ok")


if __name__ == "__main__":
	main()
