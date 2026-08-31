#!/usr/bin/env python3

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from write_ocean_mask_raw import convert_ocean_mask


def main():
	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		grid_path = tmp / "grid.json"
		tif_path = tmp / "mask.tif"
		raw_path = tmp / "mask.u8"
		elevation_path = tmp / "elevation.f32"

		elevation = np.asarray([
			[1.0, 2.0, np.nan, 4.0],
			[5.0, 6.0, 7.0, 8.0],
			[9.0, 10.0, 11.0, 12.0],
		], dtype=np.float32)
		elevation.tofile(elevation_path)

		mask = np.asarray([
			[0, 0, 1, 0],
			[1, 1, 0, 0],
			[0, 0, 0, 0],
		], dtype=np.uint8)

		with rasterio.open(
			tif_path,
			"w",
			driver="GTiff",
			width=4,
			height=3,
			count=1,
			dtype="uint8",
			transform=from_origin(0, 3, 1, 1),
		) as dataset:
			dataset.write(mask, 1)

		grid_path.write_text(
			json.dumps({
				"grid": {
					"width": 4,
					"height": 3,
				},
				"dem": {
					"raw_path": str(elevation_path),
				},
			}),
			encoding="utf-8",
		)

		report = convert_ocean_mask(
			grid_path,
			tif_path,
			raw_path,
			chunk_rows=2,
		)

		actual = np.fromfile(raw_path, dtype=np.uint8).reshape((3, 4))
		if not np.array_equal(actual, mask):
			raise AssertionError(
				f"expected={mask.tolist()} actual={actual.tolist()}"
			)

		if report["sea_seed_cells"] != 3:
			raise AssertionError(report)
		if report["missing_dem_cells"] != 1:
			raise AssertionError(report)
		if report["missing_dem_sea_cells"] != 1:
			raise AssertionError(report)
		if report["missing_dem_land_cells"] != 0:
			raise AssertionError(report)
		if report["chunk_rows"] != 2:
			raise AssertionError(report)

	print("ok")


if __name__ == "__main__":
	main()
