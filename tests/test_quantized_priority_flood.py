#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from priority_flood import compute_inundation_threshold
from threshold_levels import (
	LEVELS_M,
	SENTINEL_CLASS,
	class_for_meters,
	levels_csv,
)


def quantize_exact(values):
	array = np.asarray(values, dtype=np.float64)
	safe = np.maximum(array, 0.0)
	indices = np.searchsorted(
		np.asarray(LEVELS_M, dtype=np.float64),
		safe - 1e-12,
		side="left",
	)
	indices[~np.isfinite(array)] = SENTINEL_CLASS
	indices[indices >= SENTINEL_CLASS] = SENTINEL_CLASS
	return indices.astype(np.uint8)


def boundary_to_cpp(boundary, shape):
	if boundary is None:
		return None

	array = np.full(shape, 255, dtype=np.uint8)
	for row in range(shape[0]):
		for col in range(shape[1]):
			value = boundary[row][col]
			if value is None:
				continue
			array[row, col] = class_for_meters(value)

	return array


def run_cpp(elevation, sea, boundary=None):
	elevation = np.asarray(elevation, dtype=np.float32)
	sea = np.asarray(sea, dtype=np.uint8)
	boundary_cpp = boundary_to_cpp(boundary, elevation.shape)

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		elevation_path = tmp / "elevation.f32"
		sea_path = tmp / "sea.u8"
		output_path = tmp / "threshold.u8"

		elevation.tofile(elevation_path)
		sea.tofile(sea_path)

		command = [
			str(ROOT / "build" / "priority_flood_quantized"),
			"--elevation", str(elevation_path),
			"--sea-mask", str(sea_path),
			"--output", str(output_path),
			"--width", str(elevation.shape[1]),
			"--height", str(elevation.shape[0]),
			"--levels", levels_csv(),
			"--connectivity", "4",
		]

		if boundary_cpp is not None:
			boundary_path = tmp / "boundary.u8"
			boundary_cpp.tofile(boundary_path)
			command.extend([
				"--boundary-threshold",
				str(boundary_path),
			])

		subprocess.run(command, check=True)
		return np.fromfile(output_path, dtype=np.uint8).reshape(elevation.shape)


def assert_matches_reference(name, elevation, sea, boundary=None):
	exact = compute_inundation_threshold(
		elevation,
		np.asarray(sea, dtype=bool).tolist(),
		connectivity=4,
		boundary_threshold=boundary,
	)
	expected = quantize_exact(exact)
	actual = run_cpp(elevation, sea, boundary)

	if not np.array_equal(actual, expected):
		raise AssertionError(
			f"{name}: Quantized Priority Flood stimmt nicht mit Referenz überein.\n"
			f"expected={expected.tolist()}\n"
			f"actual={actual.tolist()}"
		)

	return {
		"name": name,
		"expected": expected.tolist(),
		"actual": actual.tolist(),
	}


def test_ocean_only():
	elevation = [
		[0, 2, 8, 4, 4, 4],
		[0, 2, 8, -4, -4, 4],
		[0, 2, 8, -4, -4, 12],
		[0, -2, 8, 4, 4, 4],
	]
	sea = [
		[1, 0, 0, 0, 0, 0],
		[1, 0, 0, 0, 0, 0],
		[1, 0, 0, 0, 0, 0],
		[1, 0, 0, 0, 0, 0],
	]

	return assert_matches_reference("ocean_only", elevation, sea)


def test_boundary_only():
	elevation = [
		[0, 0, 6, 0, 0],
		[0, 0, 6, 0, 0],
		[0, 0, 6, 0, 0],
	]
	sea = [
		[0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0],
	]
	boundary = [
		[None, None, None, None, 3],
		[None, None, None, None, 3],
		[None, None, None, None, 3],
	]

	return assert_matches_reference(
		"boundary_only",
		elevation,
		sea,
		boundary,
	)


def test_boundary_seed_can_be_improved():
	elevation = [
		[0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0],
	]
	sea = [
		[1, 0, 0, 0, 0],
		[1, 0, 0, 0, 0],
		[1, 0, 0, 0, 0],
	]
	boundary = [
		[None, None, None, None, 8],
		[None, None, None, None, 8],
		[None, None, None, None, 8],
	]

	result = assert_matches_reference(
		"boundary_seed_can_be_improved",
		elevation,
		sea,
		boundary,
	)

	if any(value != 0 for row in result["actual"] for value in row):
		raise AssertionError(
			"Ein grober 8-m-Randseed muss durch den internen 0-m-Meeresweg "
			"auf 0 m verbessert werden können."
		)

	return result


def test_blocked_boundary_has_no_usable_seed():
	elevation = [
		[100, 100, 100],
		[100, 100, 100],
	]
	sea = [
		[0, 0, 0],
		[0, 0, 0],
	]
	boundary = [
		[3, None, None],
		[3, None, None],
	]

	result = assert_matches_reference(
		"blocked_boundary_has_no_usable_seed",
		elevation,
		sea,
		boundary,
	)
	if any(
		value != SENTINEL_CLASS
		for row in result["actual"]
		for value in row
	):
		raise AssertionError(
			"Über 70 m blockierte Boundary-Seeds müssen "
			"eine vollständig unverbundene Domain ergeben."
		)

	return result


def test_piecewise_levels():
	elevation = [[0, 0.03, 1.84, 2.12, 4.88, 5.10, 21.0, 70.01]]
	sea = [[1, 0, 0, 0, 0, 0, 0, 0]]
	return assert_matches_reference("piecewise_levels", elevation, sea)


def main():
	results = [
		test_ocean_only(),
		test_piecewise_levels(),
		test_boundary_only(),
		test_boundary_seed_can_be_improved(),
		test_blocked_boundary_has_no_usable_seed(),
	]

	print(json.dumps({
		"status": "ok",
		"tests": results,
	}, indent=2))


if __name__ == "__main__":
	main()
