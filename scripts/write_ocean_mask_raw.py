#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window


def convert_ocean_mask(
	grid_path,
	input_path,
	output_path,
	*,
	allow_empty_sea=False,
	chunk_rows=1024,
):
	metadata = json.loads(Path(grid_path).read_text(encoding="utf-8"))
	grid = metadata["grid"]

	if chunk_rows <= 0:
		raise ValueError("chunk_rows muss > 0 sein.")

	output_path = Path(output_path)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	mask_raw = np.memmap(
		output_path,
		dtype=np.uint8,
		mode="w+",
		shape=(grid["height"], grid["width"]),
	)
	elevation = np.memmap(
		metadata["dem"]["raw_path"],
		dtype=np.float32,
		mode="r",
		shape=(grid["height"], grid["width"]),
	)

	sea_seed_cells = 0
	missing_dem_cells = 0
	missing_dem_sea_cells = 0
	missing_dem_land_cells = 0

	with rasterio.open(input_path) as dataset:
		if dataset.width != grid["width"] or dataset.height != grid["height"]:
			raise RuntimeError(
				f"Maskengröße {dataset.width}x{dataset.height} passt nicht zu "
				f"{grid['width']}x{grid['height']}."
			)

		for row_start in range(0, grid["height"], chunk_rows):
			height = min(
				chunk_rows,
				grid["height"] - row_start,
			)
			window = Window(
				0,
				row_start,
				grid["width"],
				height,
			)
			mask = dataset.read(
				1,
				window=window,
				out_dtype=np.uint8,
			)
			mask_raw[
				row_start:row_start + height,
				:,
			] = mask

			elevation_chunk = np.asarray(
				elevation[
					row_start:row_start + height,
					:,
				]
			)
			missing = ~np.isfinite(elevation_chunk)
			sea = mask != 0

			sea_seed_cells += int(np.count_nonzero(sea))
			missing_dem_cells += int(np.count_nonzero(missing))
			missing_dem_sea_cells += int(
				np.count_nonzero(missing & sea)
			)
			missing_dem_land_cells += int(
				np.count_nonzero(missing & ~sea)
			)

	mask_raw.flush()

	if sea_seed_cells == 0 and not allow_empty_sea:
		raise RuntimeError("Ocean-Maske enthält keine Seed-Zellen.")

	report = {
		"sea_seed_cells": sea_seed_cells,
		"missing_dem_cells": missing_dem_cells,
		"missing_dem_sea_cells": missing_dem_sea_cells,
		"missing_dem_land_cells": missing_dem_land_cells,
		"chunk_rows": int(chunk_rows),
	}

	(output_path.with_suffix(".report.json")).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)

	if missing_dem_land_cells > 0:
		raise RuntimeError(
			"DEM enthält fehlende Pixel außerhalb der Ocean-Maske; "
			"Build wird abgebrochen."
		)

	return report


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--grid", default="tmp/phase1a/grid.json")
	parser.add_argument("--input", default="tmp/phase1a/ocean_mask.tif")
	parser.add_argument("--output", default="tmp/phase1a/sea_mask.u8")
	parser.add_argument(
		"--allow-empty-sea",
		action="store_true",
		help="Erlaubt eine leere Ocean-Maske für reine Boundary-Refinements.",
	)
	parser.add_argument("--chunk-rows", type=int, default=1024)
	args = parser.parse_args()

	if args.chunk_rows <= 0:
		parser.error("--chunk-rows muss > 0 sein.")

	report = convert_ocean_mask(
		args.grid,
		args.input,
		args.output,
		allow_empty_sea=args.allow_empty_sea,
		chunk_rows=args.chunk_rows,
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
