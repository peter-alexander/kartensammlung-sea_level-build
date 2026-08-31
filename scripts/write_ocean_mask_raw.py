#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--grid", default="tmp/phase1a/grid.json")
	parser.add_argument("--input", default="tmp/phase1a/ocean_mask.tif")
	parser.add_argument("--output", default="tmp/phase1a/sea_mask.u8")
	args = parser.parse_args()

	metadata = json.loads(Path(args.grid).read_text(encoding="utf-8"))
	grid = metadata["grid"]

	with rasterio.open(args.input) as dataset:
		if dataset.width != grid["width"] or dataset.height != grid["height"]:
			raise RuntimeError(
				f"Maskengröße {dataset.width}x{dataset.height} passt nicht zu "
				f"{grid['width']}x{grid['height']}."
			)

		mask = dataset.read(1).astype(np.uint8, copy=False)

	if not np.any(mask):
		raise RuntimeError("Ocean-Maske enthält keine Seed-Zellen.")

	Path(args.output).parent.mkdir(parents=True, exist_ok=True)
	mask.tofile(args.output)

	elevation = np.memmap(
		metadata["dem"]["raw_path"],
		dtype=np.float32,
		mode="r",
		shape=(grid["height"], grid["width"]),
	)
	missing = ~np.isfinite(elevation)
	missing_land = missing & (mask == 0)
	missing_sea = missing & (mask != 0)

	report = {
		"sea_seed_cells": int(np.count_nonzero(mask)),
		"missing_dem_cells": int(np.count_nonzero(missing)),
		"missing_dem_sea_cells": int(np.count_nonzero(missing_sea)),
		"missing_dem_land_cells": int(np.count_nonzero(missing_land)),
	}

	(Path(args.output).with_suffix(".report.json")).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(report, indent=2))

	if report["missing_dem_land_cells"] > 0:
		raise RuntimeError(
			"DEM enthält fehlende Pixel außerhalb der Ocean-Maske; Build wird abgebrochen."
		)


if __name__ == "__main__":
	main()
