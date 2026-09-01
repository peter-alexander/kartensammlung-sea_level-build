#!/usr/bin/env python3

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from grid import WEB_MERCATOR_WORLD
from prefetch_adaptive_mapterhorn import prefetch


def main():
	resolution = WEB_MERCATOR_WORLD / (512 * (2 ** 11))
	parent = {
		"zoom": 11,
		"resolution": resolution,
		"left": -WEB_MERCATOR_WORLD / 2.0,
		"top": WEB_MERCATOR_WORLD / 2.0,
	}
	plan = {
		"base_zoom": 11,
		"domains": [
			{
				"zoom": 16,
				"coarse_x0": 1,
				"coarse_y0": 1,
				"coarse_width": 1,
				"coarse_height": 1,
				"fine_pixels_per_coarse_cell": 512,
				"fine_width": 512,
				"fine_height": 512,
			},
			{
				"zoom": 16,
				"coarse_x0": 1,
				"coarse_y0": 1,
				"coarse_width": 1,
				"coarse_height": 1,
				"fine_pixels_per_coarse_cell": 512,
				"fine_width": 512,
				"fine_height": 512,
			},
			{
				"zoom": 13,
				"coarse_x0": 8,
				"coarse_y0": 8,
				"coarse_width": 4,
				"coarse_height": 4,
				"fine_pixels_per_coarse_cell": 64,
				"fine_width": 256,
				"fine_height": 256,
			},
		],
	}

	report = prefetch(
		plan,
		parent,
		"unused-cache",
		download=False,
	)

	if report["domain_count"] != 3:
		raise AssertionError(report)
	if report["tile_references"] != 3:
		raise AssertionError(report)
	if report["unique_tile_count"] != 2:
		raise AssertionError(report)
	if report["unique_tiles_by_zoom"] != {
		"13": 1,
		"16": 1,
	}:
		raise AssertionError(report)

	print("ok")


if __name__ == "__main__":
	main()
