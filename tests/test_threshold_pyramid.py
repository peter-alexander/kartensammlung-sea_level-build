#!/usr/bin/env python3

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_threshold_pyramid import downsample_bayer


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

	print("ok")


if __name__ == "__main__":
	main()
