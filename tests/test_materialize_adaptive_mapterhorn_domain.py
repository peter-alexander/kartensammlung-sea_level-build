#!/usr/bin/env python3

import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from grid import WEB_MERCATOR_WORLD
from materialize_adaptive_mapterhorn_domain import (
	AdaptiveMapterhornDomainMaterializer,
)


def main():
	resolution = WEB_MERCATOR_WORLD / (512 * (2 ** 11))
	parent_grid = {
		"zoom": 11,
		"resolution": resolution,
		"left": -WEB_MERCATOR_WORLD / 2.0,
		"top": WEB_MERCATOR_WORLD / 2.0,
	}

	with tempfile.TemporaryDirectory() as tmp:
		sea = Path(tmp) / "sea.shp"
		sea.write_bytes(b"x")

		materializer = AdaptiveMapterhornDomainMaterializer(
			parent_grid=parent_grid,
			sea_vector_path=sea,
			cache_dir=Path(tmp) / "cache",
			workers=1,
		)

		for zoom, scale in (
			(11, 16),
			(13, 64),
			(14, 128),
			(16, 512),
		):
			domain = {
				"zoom": zoom,
				"coarse_x0": 1,
				"coarse_y0": 2,
				"coarse_width": 1,
				"coarse_height": 1,
				"fine_pixels_per_coarse_cell": scale,
				"fine_width": scale,
				"fine_height": scale,
			}
			grid = materializer._domain_grid(domain)

			expected_resolution = (
				resolution / (2 ** (zoom - 11))
			)
			if not math.isclose(
				grid["resolution"],
				expected_resolution,
				rel_tol=0.0,
				abs_tol=1e-12,
			):
				raise AssertionError(grid)

			if grid["width"] != scale:
				raise AssertionError(grid)
			if grid["height"] != scale:
				raise AssertionError(grid)

			expected_pixel_x = scale
			expected_pixel_y = 2 * scale
			if grid["global_pixel_x0"] != expected_pixel_x:
				raise AssertionError(grid)
			if grid["global_pixel_y0"] != expected_pixel_y:
				raise AssertionError(grid)

			tiles = materializer._target_tiles(grid)
			expected_tile_x = expected_pixel_x // 512
			expected_tile_y = expected_pixel_y // 512
			if tiles[0] != (
				expected_tile_x,
				expected_tile_y,
			):
				raise AssertionError(
					f"zoom={zoom} tiles={tiles}"
				)

		materializer.close()

	print("ok")


if __name__ == "__main__":
	main()
