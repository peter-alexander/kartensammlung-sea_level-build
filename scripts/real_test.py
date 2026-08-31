#!/usr/bin/env python3

import argparse
import json
import math
import sys
import urllib.request
import zipfile
from pathlib import Path

try:
	import geopandas as gpd
	import numpy as np
	from PIL import Image
	import rasterio
	from rasterio.features import rasterize
	from rasterio.transform import Affine
except ImportError as error:
	raise SystemExit(
		"Benötigt: numpy, pillow, rasterio, geopandas (pip install numpy pillow rasterio geopandas)"
	) from error

from sea_level_priority_flood import compute_inundation_threshold

WEB_MERCATOR_RADIUS = 6378137.0
WEB_MERCATOR_WORLD = 2.0 * math.pi * WEB_MERCATOR_RADIUS
MAPTERHORN_TEMPLATE = "https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"
NATURAL_EARTH_OCEAN_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_ocean.zip"


def download(url, path):
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)

	if path.exists() and path.stat().st_size > 0:
		return path

	print(f"Download: {url}", file=sys.stderr)
	request = urllib.request.Request(
		url,
		headers={"User-Agent": "Kartensammlung-SeaLevel-Test/1.0"},
	)

	with urllib.request.urlopen(request, timeout=60) as response, path.open("wb") as target:
		target.write(response.read())

	return path


def decode_terrarium(path):
	with Image.open(path) as image:
		rgb = np.asarray(image.convert("RGB"), dtype=np.float32)

	return rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0


def tile_mosaic(z, x_min, x_max, y_min, y_max, cache_dir):
	rows = []

	for y in range(y_min, y_max + 1):
		row = []

		for x in range(x_min, x_max + 1):
			url = MAPTERHORN_TEMPLATE.format(z=z, x=x, y=y)
			path = download(
				url,
				Path(cache_dir) / "mapterhorn" / str(z) / str(x) / f"{y}.webp",
			)
			row.append(decode_terrarium(path))

		rows.append(np.concatenate(row, axis=1))

	return np.concatenate(rows, axis=0)


def mosaic_transform(z, x_min, y_min, tile_size=512, downsample=1):
	resolution = WEB_MERCATOR_WORLD / (2 ** z * tile_size)
	left = -WEB_MERCATOR_WORLD / 2.0 + x_min * tile_size * resolution
	top = WEB_MERCATOR_WORLD / 2.0 - y_min * tile_size * resolution
	pixel_size = resolution * downsample

	return Affine(pixel_size, 0.0, left, 0.0, -pixel_size, top)


def ocean_mask(shape, transform, cache_dir):
	zip_path = download(
		NATURAL_EARTH_OCEAN_URL,
		Path(cache_dir) / "naturalearth" / "ne_10m_ocean.zip",
	)

	with zipfile.ZipFile(zip_path) as archive:
		if "ne_10m_ocean.shp" not in archive.namelist():
			raise RuntimeError("Natural-Earth-Archiv enthält ne_10m_ocean.shp nicht.")

	ocean = gpd.read_file(f"zip://{zip_path}!ne_10m_ocean.shp").to_crs("EPSG:3857")
	left = transform.c
	top = transform.f
	right = left + shape[1] * transform.a
	bottom = top + shape[0] * transform.e
	ocean = ocean.cx[left:right, bottom:top]

	mask = rasterize(
		(
			(geometry, 1)
			for geometry in ocean.geometry
			if geometry is not None and not geometry.is_empty
		),
		out_shape=shape,
		transform=transform,
		fill=0,
		default_value=1,
		dtype="uint8",
		all_touched=False,
	)

	return mask.astype(bool)


def west_boundary_seed_mask(dem, max_elevation=1.0):
	mask = np.zeros(dem.shape, dtype=bool)
	mask[:, 0] = dem[:, 0] <= float(max_elevation)

	if not mask.any():
		raise RuntimeError(
			"Westliche Rasterkante enthält keine geeignete offene Meereszelle."
		)

	return mask


def write_geotiff(path, array, transform, dtype, nodata=None):
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)

	with rasterio.open(
		path,
		"w",
		driver="GTiff",
		height=array.shape[0],
		width=array.shape[1],
		count=1,
		dtype=dtype,
		crs="EPSG:3857",
		transform=transform,
		compress="deflate",
		predictor=2 if np.issubdtype(np.dtype(dtype), np.floating) else 1,
		nodata=nodata,
	) as dataset:
		dataset.write(array.astype(dtype), 1)


def center_latitude(transform, height):
	y = transform.f + (height / 2.0) * transform.e
	return math.degrees(math.atan(math.sinh(y / WEB_MERCATOR_RADIUS)))


def main():
	parser = argparse.ArgumentParser(
		description="Realer Meeresspiegel-Priority-Flood-Test mit Mapterhorn + Natural Earth Ocean."
	)
	parser.add_argument("--zoom", type=int, default=9)
	parser.add_argument("--x-min", type=int, default=261)
	parser.add_argument("--x-max", type=int, default=262)
	parser.add_argument("--y-min", type=int, default=168)
	parser.add_argument("--y-max", type=int, default=169)
	parser.add_argument("--downsample", type=int, default=2)
	parser.add_argument("--connectivity", type=int, choices=(4, 8), default=8)
	parser.add_argument("--levels", default="1,2,5,10")
	parser.add_argument(
		"--seed-mode",
		choices=("natural-earth-ocean", "west-boundary"),
		default="natural-earth-ocean",
	)
	parser.add_argument(
		"--boundary-max-elevation",
		type=float,
		default=1.0,
		help="Maximale DEM-Höhe für Seed-Zellen am offenen Westrand.",
	)
	parser.add_argument("--cache-dir", default="tmp/sea_level_real_test/cache")
	parser.add_argument("--output-dir", default="tmp/sea_level_real_test/output")
	args = parser.parse_args()

	if args.x_max < args.x_min or args.y_max < args.y_min:
		parser.error("Tile-Bereich ist ungültig.")

	if args.downsample < 1:
		parser.error("--downsample muss >= 1 sein.")

	levels = [
		float(value.strip())
		for value in args.levels.split(",")
		if value.strip()
	]

	output_dir = Path(args.output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	dem_full = tile_mosaic(
		args.zoom,
		args.x_min,
		args.x_max,
		args.y_min,
		args.y_max,
		args.cache_dir,
	)
	dem = dem_full[::args.downsample, ::args.downsample].astype(np.float32)
	transform = mosaic_transform(
		args.zoom,
		args.x_min,
		args.y_min,
		downsample=args.downsample,
	)
	if args.seed_mode == "west-boundary":
		sea = west_boundary_seed_mask(
			dem,
			max_elevation=args.boundary_max_elevation,
		)
		seed_source = "Open North Sea west boundary"
	else:
		sea = ocean_mask(dem.shape, transform, args.cache_dir)
		seed_source = "Natural Earth 1:10m Ocean"

	print(f"Raster: {dem.shape[1]} x {dem.shape[0]} ({dem.size:,} Zellen)", file=sys.stderr)
	print(f"Sea seeds: {int(sea.sum()):,}", file=sys.stderr)
	print(
		f"West edge DEM: min={float(np.nanmin(dem[:, 0])):.2f} m, "
		f"max={float(np.nanmax(dem[:, 0])):.2f} m",
		file=sys.stderr,
	)

	threshold = np.asarray(
		compute_inundation_threshold(
			dem.tolist(),
			sea.tolist(),
			connectivity=args.connectivity,
		),
		dtype=np.float32,
	)

	write_geotiff(output_dir / "dem.tif", dem, transform, "float32")
	write_geotiff(
		output_dir / "ocean_mask.tif",
		sea.astype(np.uint8),
		transform,
		"uint8",
		nodata=0,
	)
	write_geotiff(
		output_dir / "inundation_threshold.tif",
		threshold,
		transform,
		"float32",
	)

	lat = center_latitude(transform, dem.shape[0])
	web_pixel = abs(transform.a)
	ground_pixel = web_pixel * math.cos(math.radians(lat))
	cell_area_m2 = ground_pixel * ground_pixel

	summaries = []

	for level in levels:
		bathtub = dem <= level
		connected = threshold <= level
		protected_low_land = bathtub & ~connected
		seed_dem_conflict = sea & ~bathtub

		name = str(level).replace(".", "p")
		write_geotiff(
			output_dir / f"bathtub_{name}m.tif",
			bathtub.astype(np.uint8),
			transform,
			"uint8",
			nodata=0,
		)
		write_geotiff(
			output_dir / f"connected_{name}m.tif",
			connected.astype(np.uint8),
			transform,
			"uint8",
			nodata=0,
		)
		write_geotiff(
			output_dir / f"protected_low_land_{name}m.tif",
			protected_low_land.astype(np.uint8),
			transform,
			"uint8",
			nodata=0,
		)

		summaries.append({
			"level_m": level,
			"bathtub_cells": int(bathtub.sum()),
			"connected_cells": int(connected.sum()),
			"protected_low_land_cells": int(protected_low_land.sum()),
			"protected_low_land_km2_approx": round(
				float(protected_low_land.sum() * cell_area_m2 / 1_000_000.0),
				2,
			),
			"seed_dem_conflict_cells": int(seed_dem_conflict.sum()),
		})

	report = {
		"area": "Custom Web Mercator tile window",
		"source_dem": "Mapterhorn Terrarium",
		"seed_mode": args.seed_mode,
		"seed_source": seed_source,
		"boundary_max_elevation_m": args.boundary_max_elevation if args.seed_mode == "west-boundary" else None,
		"zoom": args.zoom,
		"tile_range": {
			"x": [args.x_min, args.x_max],
			"y": [args.y_min, args.y_max],
		},
		"downsample": args.downsample,
		"connectivity": args.connectivity,
		"shape": [int(dem.shape[0]), int(dem.shape[1])],
		"center_latitude": round(lat, 6),
		"ground_pixel_m_approx": round(ground_pixel, 2),
		"dem_min_m": round(float(np.nanmin(dem)), 2),
		"dem_max_m": round(float(np.nanmax(dem)), 2),
		"sea_seed_cells": int(sea.sum()),
		"west_edge_dem_min_m": round(float(np.nanmin(dem[:, 0])), 2),
		"west_edge_dem_max_m": round(float(np.nanmax(dem[:, 0])), 2),
		"levels": summaries,
	}

	(output_dir / "report.json").write_text(
		json.dumps(report, indent=2, ensure_ascii=False) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
	main()
