#!/usr/bin/env python3

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_threshold_pyramid import classes_to_meters, downsample_bayer
from threshold_levels import SENTINEL_CLASS


def main():
	source = np.asarray([
		[0, 1, 2, 3],
		[4, 5, 6, 7],
		[8, 9, 10, 11],
		[12, 13, 14, 15],
	], dtype=np.uint8)

	actual = downsample_bayer(source)
	expected = np.asarray([
		[0, 3],
		[12, 15],
	], dtype=np.uint8)

	if not np.array_equal(actual, expected):
		raise AssertionError(
			f"expected={expected.tolist()} actual={actual.tolist()}"
		)

	mapped = classes_to_meters(
		np.asarray(
			[[0, 1, 20, 21, 32, 33, 47, 48, 57, SENTINEL_CLASS]],
			dtype=np.uint8,
		)
	)
	expected_m = np.asarray(
		[[0, 0.1, 2, 2.25, 5, 6, 20, 25, 70, 71]],
		dtype=np.float64,
	)
	if not np.allclose(mapped, expected_m):
		raise AssertionError(
			f"expected_m={expected_m.tolist()} mapped={mapped.tolist()}"
		)

	print("ok")


if __name__ == "__main__":
	main()
