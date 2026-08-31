#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path

import numpy as np
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

from coverage_planner import (
	WEB_MERCATOR_WORLD,
	exclusive_max_tile,
	inclusive_min_tile,
	lat_to_tile_y,
	lon_to_tile_x,
	tile_bounds_lonlat,
)


def load_source_geometry(path, source):
	data = json.loads(Path(path).read_text(encoding="utf-8"))

	for feature in data.get("features", []):
		if feature.get("properties", {}).get("source") != source:
			continue

		geometry = shape(feature["geometry"])
		if geometry.is_empty:
			break
		return geometry, feature.get("properties", {})

	raise ValueError(f"Source {source!r} wurde in {path} nicht gefunden.")


def buffer_geometry_web_mercator(geometry, distance_m):
	if distance_m <= 0:
		return geometry

	radius = WEB_MERCATOR_WORLD / (2.0 * math.pi)

	def forward(lon, lat, z=None):
		lon = np.asarray(lon, dtype=np.float64)
		lat = np.asarray(lat, dtype=np.float64)

		x = radius * np.radians(lon)
		y = radius * np.arcsinh(
			np.tan(np.radians(lat))
		)

		if z is None:
			return x, y

		return x, y, z

	def backward(x, y, z=None):
		x = np.asarray(x, dtype=np.float64)
		y = np.asarray(y, dtype=np.float64)

		lon = np.degrees(x / radius)
		lat = np.degrees(
			np.arctan(
				np.sinh(y / radius)
			)
		)

		if z is None:
			return lon, lat

		return lon, lat, z

	projected = transform(forward, geometry)
	buffered = projected.buffer(distance_m)
	return transform(backward, buffered)


def parent_target_bounds(metadata):
	bounds = metadata.get("config", {}).get("bounds")
	if bounds:
		return (
			float(bounds["west"]),
			float(bounds["south"]),
			float(bounds["east"]),
			float(bounds["north"]),
		)

	grid = metadata["grid"]
	zoom = int(grid["zoom"])
	west, _south, _east, north = tile_bounds_lonlat(
		grid["x_min"],
		grid["y_min"],
		zoom,
	)
	_west, south, east, _north = tile_bounds_lonlat(
		grid["x_max"],
		grid["y_max"],
		zoom,
	)
	return (west, south, east, north)


def prepare_region(
	sources_geojson,
	source,
	parent_grid_path,
	*,
	fine_zoom,
	halo_tiles,
	transition_buffer_pixels,
	output_config,
	output_core,
):
	parent_meta = json.loads(
		Path(parent_grid_path).read_text(encoding="utf-8")
	)
	parent_grid = parent_meta["grid"]
	parent_zoom = int(parent_grid["zoom"])

	if fine_zoom <= parent_zoom:
		raise ValueError("fine_zoom muss größer als Parent-Zoom sein.")

	source_geometry, source_properties = load_source_geometry(
		sources_geojson,
		source,
	)
	target_bounds = parent_target_bounds(parent_meta)

	tile_size = int(parent_grid["tile_size"])
	fine_resolution = (
		WEB_MERCATOR_WORLD
		/ ((2 ** fine_zoom) * tile_size)
	)
	transition_buffer_m = (
		float(transition_buffer_pixels)
		* fine_resolution
	)
	refinement_geometry = buffer_geometry_web_mercator(
		source_geometry,
		transition_buffer_m,
	)
	core = refinement_geometry.intersection(box(*target_bounds))

	if core.is_empty:
		raise ValueError(
			f"Source {source!r} schneidet den Parent-Ausschnitt nicht."
		)

	min_lon, min_lat, max_lon, max_lat = core.bounds

	x_min = inclusive_min_tile(lon_to_tile_x(min_lon, fine_zoom))
	x_max = exclusive_max_tile(lon_to_tile_x(max_lon, fine_zoom))
	y_min = inclusive_min_tile(lat_to_tile_y(max_lat, fine_zoom))
	y_max = exclusive_max_tile(lat_to_tile_y(min_lat, fine_zoom))

	factor = 2 ** (fine_zoom - parent_zoom)
	parent_child_x_min = int(parent_grid["x_min"]) * factor
	parent_child_x_max = (int(parent_grid["x_max"]) + 1) * factor - 1
	parent_child_y_min = int(parent_grid["y_min"]) * factor
	parent_child_y_max = (int(parent_grid["y_max"]) + 1) * factor - 1

	work_x_min = max(parent_child_x_min, x_min - halo_tiles)
	work_x_max = min(parent_child_x_max, x_max + halo_tiles)
	work_y_min = max(parent_child_y_min, y_min - halo_tiles)
	work_y_max = min(parent_child_y_max, y_max + halo_tiles)

	west, _south, _east, north = tile_bounds_lonlat(
		work_x_min,
		work_y_min,
		fine_zoom,
	)
	_west, south, east, _north = tile_bounds_lonlat(
		work_x_max,
		work_y_max,
		fine_zoom,
	)

	config = {
		"name": f"refinement-{source}-z{fine_zoom}",
		"bounds": {
			"west": west,
			"south": south,
			"east": east,
			"north": north,
		},
		"refinement": {
			"source": source,
			"source_properties": source_properties,
			"parent_zoom": parent_zoom,
			"fine_zoom": fine_zoom,
			"halo_tiles": halo_tiles,
			"transition_buffer_pixels": transition_buffer_pixels,
			"transition_buffer_projected_m": transition_buffer_m,
			"core_bounds": list(core.bounds),
			"core_geojson": str(output_core),
		},
		"dem": {
			"provider": "mapterhorn",
			"tile_endpoint": "https://tiles.mapterhorn.com/{z}/{x}/{y}.webp",
			"processing_zoom": fine_zoom,
			"tile_size": int(parent_grid["tile_size"]),
			"encoding": "terrarium",
		},
		"threshold": {
			"min_m": 0,
			"max_m": 100,
			"step_m": 1,
			"connectivity": 4,
			"sentinel": 101,
		},
	}

	Path(output_config).parent.mkdir(parents=True, exist_ok=True)
	Path(output_config).write_text(
		json.dumps(config, indent=2) + "\n",
		encoding="utf-8",
	)

	source_bounds = source_geometry.bounds
	refinement_bounds = refinement_geometry.bounds
	clipped_sides = {
		"west": refinement_bounds[0] < target_bounds[0],
		"south": refinement_bounds[1] < target_bounds[1],
		"east": refinement_bounds[2] > target_bounds[2],
		"north": refinement_bounds[3] > target_bounds[3],
	}

	core_feature = {
		"type": "Feature",
		"properties": {
			"source": source,
			"kind": "refinement-core",
			"parent_target_bounds": list(target_bounds),
			"source_coverage_bounds": list(source_bounds),
			"refinement_geometry_bounds": list(refinement_bounds),
			"transition_buffer_pixels": transition_buffer_pixels,
			"transition_buffer_projected_m": transition_buffer_m,
			"clipped_sides": clipped_sides,
		},
		"geometry": mapping(core),
	}
	Path(output_core).write_text(
		json.dumps(core_feature, indent=2) + "\n",
		encoding="utf-8",
	)

	report = {
		"source": source,
		"parent_zoom": parent_zoom,
		"fine_zoom": fine_zoom,
		"halo_tiles": halo_tiles,
		"transition_buffer_pixels": transition_buffer_pixels,
		"transition_buffer_projected_m": transition_buffer_m,
		"core_bounds": list(core.bounds),
		"source_coverage_bounds": list(source_bounds),
		"refinement_geometry_bounds": list(refinement_bounds),
		"parent_target_bounds": list(target_bounds),
		"clipped_sides": clipped_sides,
		"core_tile_range": {
			"x": [x_min, x_max],
			"y": [y_min, y_max],
		},
		"work_tile_range": {
			"x": [work_x_min, work_x_max],
			"y": [work_y_min, work_y_max],
		},
		"work_tile_count": (
			(work_x_max - work_x_min + 1)
			* (work_y_max - work_y_min + 1)
		),
		"work_bounds": [west, south, east, north],
	}

	report_path = Path(output_config).with_suffix(".report.json")
	report_path.write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)

	return report


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--sources-geojson", required=True)
	parser.add_argument("--source", required=True)
	parser.add_argument("--parent-grid", required=True)
	parser.add_argument("--fine-zoom", type=int, required=True)
	parser.add_argument("--halo-tiles", type=int, default=1)
	parser.add_argument(
		"--transition-buffer-pixels",
		type=int,
		default=0,
	)
	parser.add_argument("--output-config", required=True)
	parser.add_argument("--output-core", required=True)
	args = parser.parse_args()

	if args.halo_tiles < 0:
		parser.error("--halo-tiles muss >= 0 sein.")
	if args.transition_buffer_pixels < 0:
		parser.error("--transition-buffer-pixels muss >= 0 sein.")

	report = prepare_region(
		args.sources_geojson,
		args.source,
		args.parent_grid,
		fine_zoom=args.fine_zoom,
		halo_tiles=args.halo_tiles,
		transition_buffer_pixels=args.transition_buffer_pixels,
		output_config=args.output_config,
		output_core=args.output_core,
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
