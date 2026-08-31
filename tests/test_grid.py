#!/usr/bin/env python3

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from grid import grid_from_config


def tile_lon(x, zoom):
	return x / (2 ** zoom) * 360.0 - 180.0


def tile_lat(y, zoom):
	return math.degrees(
		math.atan(
			math.sinh(
				math.pi * (1.0 - 2.0 * y / (2 ** zoom))
			)
		)
	)


def make_config(west, south, east, north, zoom):
	return {
		"bounds": {
			"west": west,
			"south": south,
			"east": east,
			"north": north,
		},
		"dem": {
			"processing_zoom": zoom,
			"tile_size": 512,
		},
	}


def main():
	zoom = 12
	config = make_config(
		tile_lon(2098, zoom),
		tile_lat(1355, zoom),
		tile_lon(2100, zoom),
		tile_lat(1353, zoom),
		zoom,
	)
	grid = grid_from_config(config)

	expected = {
		"x_min": 2098,
		"x_max": 2099,
		"y_min": 1353,
		"y_max": 1354,
		"width": 1024,
		"height": 1024,
	}

	for key, value in expected.items():
		if grid[key] != value:
			raise AssertionError(
				f"{key}: expected={value} actual={grid[key]}"
			)

	print("ok")


if __name__ == "__main__":
	main()
