#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path

import numpy as np
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

from coverage_planner import (
	WEB_MERCATOR_WORLD,
	ground_resolution,
	parse_bbox,
	plan as build_coverage_plan,
	tiles_for_bbox,
)
from threshold_levels import threshold_config


def load_work_geometry(*, bounds=None, geojson_path=None):
	if (bounds is None) == (geojson_path is None):
		raise ValueError(
			"Genau eine Work-Region-Quelle muss angegeben werden."
		)

	if bounds is not None:
		return box(*bounds)

	data = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
	if data.get("type") == "Feature":
		geometry = shape(data["geometry"])
	elif data.get("type") == "FeatureCollection":
		geometries = [
			shape(feature["geometry"])
			for feature in data.get("features", [])
			if feature.get("geometry")
		]
		geometry = unary_union(geometries)
	else:
		geometry = shape(data)

	if not geometry.is_valid:
		geometry = geometry.buffer(0)
	if geometry.is_empty:
		raise ValueError("Work-Region-Geometrie ist leer.")

	return geometry


def projected_area_m2(geometry):
	radius = WEB_MERCATOR_WORLD / (2.0 * math.pi)

	def project(lon, lat, z=None):
		lon = np.asarray(lon, dtype=np.float64)
		lat = np.asarray(lat, dtype=np.float64)
		x = radius * np.radians(lon)
		y = radius * np.arcsinh(np.tan(np.radians(lat)))
		if z is None:
			return x, y
		return x, y, z

	return float(transform(project, geometry).area)


def source_priority(feature):
	properties = feature.get("properties", {})
	zoom = properties.get("source_fidelity_processing_zoom")
	resolution = properties.get("resolution_m")
	source = str(properties.get("source") or "")

	return (
		-(int(zoom) if zoom is not None else -1),
		float(resolution) if resolution is not None else math.inf,
		source,
	)


def build_source_partition(work_geometry, source_features):
	work_area = projected_area_m2(work_geometry)
	if work_area <= 0.0:
		raise ValueError("Work-Region hat keine positive Fläche.")

	raw = []
	intersections = []

	for feature in source_features:
		geometry_data = feature.get("geometry")
		if not geometry_data:
			continue

		geometry = shape(geometry_data).intersection(work_geometry)
		if geometry.is_empty:
			continue
		if not geometry.is_valid:
			geometry = geometry.buffer(0)
		if geometry.is_empty:
			continue

		properties = dict(feature.get("properties", {}))
		area_m2 = projected_area_m2(geometry)
		record = {
			"source": properties.get("source"),
			"name": properties.get("name"),
			"resolution_m": properties.get("resolution_m"),
			"source_fidelity_processing_zoom": properties.get(
				"source_fidelity_processing_zoom"
			),
			"source_fidelity_ground_resolution_m": properties.get(
				"source_fidelity_ground_resolution_m"
			),
			"area_m2": area_m2,
			"area_fraction": area_m2 / work_area,
			"bounds": list(geometry.bounds),
		}
		raw.append(record)
		intersections.append({
			"type": "Feature",
			"properties": properties,
			"geometry": mapping(geometry),
		})

	remaining = work_geometry
	effective = []
	effective_features = []

	for feature in sorted(intersections, key=source_priority):
		geometry = shape(feature["geometry"]).intersection(remaining)
		if geometry.is_empty:
			continue
		if not geometry.is_valid:
			geometry = geometry.buffer(0)
		if geometry.is_empty:
			continue

		properties = dict(feature.get("properties", {}))
		area_m2 = projected_area_m2(geometry)
		record = {
			"source": properties.get("source"),
			"name": properties.get("name"),
			"resolution_m": properties.get("resolution_m"),
			"source_fidelity_processing_zoom": properties.get(
				"source_fidelity_processing_zoom"
			),
			"source_fidelity_ground_resolution_m": properties.get(
				"source_fidelity_ground_resolution_m"
			),
			"area_m2": area_m2,
			"area_fraction": area_m2 / work_area,
			"bounds": list(geometry.bounds),
		}
		effective.append(record)
		effective_features.append({
			"type": "Feature",
			"properties": {
				**properties,
				"effective_area_m2": area_m2,
				"effective_area_fraction": area_m2 / work_area,
			},
			"geometry": mapping(geometry),
		})

		remaining = remaining.difference(geometry)
		if remaining.is_empty:
			break

	if not remaining.is_valid:
		remaining = remaining.buffer(0)

	uncovered_area = (
		0.0
		if remaining.is_empty
		else projected_area_m2(remaining)
	)

	return {
		"work_area_m2": work_area,
		"raw_sources": raw,
		"effective_sources": effective,
		"effective_features": effective_features,
		"uncovered_geometry": remaining,
		"uncovered_area_m2": uncovered_area,
		"uncovered_area_fraction": uncovered_area / work_area,
	}


def choose_uniform_zoom(partition, base_zoom):
	zooms = [
		int(item["source_fidelity_processing_zoom"])
		for item in partition["effective_sources"]
		if item.get("source_fidelity_processing_zoom") is not None
	]
	if not zooms:
		return int(base_zoom)
	return max(int(base_zoom), max(zooms))


def build_work_region_plan(
	work_geometry,
	source_features,
	*,
	base_zoom,
	tile_size=512,
	max_uniform_cells=0,
):
	partition = build_source_partition(
		work_geometry,
		source_features,
	)
	uniform_zoom = choose_uniform_zoom(partition, base_zoom)
	bounds = tuple(float(value) for value in work_geometry.bounds)
	tiles = tiles_for_bbox(bounds, uniform_zoom)
	uniform_cells = len(tiles) * int(tile_size) * int(tile_size)
	center_lat = (bounds[1] + bounds[3]) / 2.0

	return {
		"bounds": list(bounds),
		"base_zoom": int(base_zoom),
		"uniform_processing_zoom": uniform_zoom,
		"uniform_ground_resolution_m_at_center": round(
			ground_resolution(
				center_lat,
				uniform_zoom,
				tile_size=int(tile_size),
			),
			3,
		),
		"tile_size": int(tile_size),
		"uniform_tile_count": len(tiles),
		"uniform_cells": uniform_cells,
		"max_uniform_cells": int(max_uniform_cells),
		"requires_work_region_split": (
			int(max_uniform_cells) > 0
			and uniform_cells > int(max_uniform_cells)
		),
		"coverage": {
			"work_area_m2": partition["work_area_m2"],
			"raw_sources": partition["raw_sources"],
			"effective_sources": partition["effective_sources"],
			"uncovered_area_m2": partition["uncovered_area_m2"],
			"uncovered_area_fraction": (
				partition["uncovered_area_fraction"]
			),
		},
		"_effective_features": partition["effective_features"],
		"_uncovered_geometry": partition["uncovered_geometry"],
	}


def write_geojson(path, features):
	Path(path).write_text(
		json.dumps({
			"type": "FeatureCollection",
			"features": features,
		}, indent=2) + "\n",
		encoding="utf-8",
	)


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Plant eine Candidate-Work-Region mit echter "
			"Mapterhorn-Coverage und einheitlichem Source-Fidelity-Raster."
		)
	)
	group = parser.add_mutually_exclusive_group(required=True)
	group.add_argument("--bbox", type=parse_bbox)
	group.add_argument("--work-geojson")
	parser.add_argument("--output-dir", required=True)
	parser.add_argument("--coverage-zoom", type=int, default=8)
	parser.add_argument("--coverage-context-tiles", type=int, default=1)
	parser.add_argument("--cache-dir", default="cache")
	parser.add_argument("--workers", type=int, default=12)
	parser.add_argument("--tile-size", type=int, default=512)
	parser.add_argument("--max-uniform-cells", type=int, default=0)
	args = parser.parse_args()

	work_geometry = load_work_geometry(
		bounds=args.bbox,
		geojson_path=args.work_geojson,
	)
	bounds = tuple(float(value) for value in work_geometry.bounds)

	coverage = build_coverage_plan(
		bounds,
		coverage_zoom=args.coverage_zoom,
		coverage_context_tiles=args.coverage_context_tiles,
		cache_dir=args.cache_dir,
		workers=args.workers,
	)
	base_zoom = int(
		coverage["plan"]["base"][
			"recommended_processing_zoom_at_bbox_center"
		]
	)
	work_plan = build_work_region_plan(
		work_geometry,
		coverage["source_features"],
		base_zoom=base_zoom,
		tile_size=args.tile_size,
		max_uniform_cells=args.max_uniform_cells,
	)

	output_dir = Path(args.output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	effective_features = work_plan.pop("_effective_features")
	uncovered = work_plan.pop("_uncovered_geometry")

	plan = {
		"schema_version": 1,
		"strategy": (
			"uniform processing domain; source coverage only selects "
			"available DEM fidelity, never solver boundaries"
		),
		**work_plan,
	}
	(output_dir / "plan.json").write_text(
		json.dumps(plan, indent=2) + "\n",
		encoding="utf-8",
	)

	write_geojson(
		output_dir / "effective-sources.geojson",
		effective_features,
	)
	write_geojson(
		output_dir / "work-region.geojson",
		[{
			"type": "Feature",
			"properties": {"kind": "work-region"},
			"geometry": mapping(work_geometry),
		}],
	)
	if not uncovered.is_empty:
		write_geojson(
			output_dir / "uncovered.geojson",
			[{
				"type": "Feature",
				"properties": {"kind": "base-fallback"},
				"geometry": mapping(uncovered),
			}],
		)

	uniform_zoom = int(plan["uniform_processing_zoom"])
	dem_config = {
		"name": f"work-region-source-fidelity-z{uniform_zoom}",
		"bounds": {
			"west": bounds[0],
			"south": bounds[1],
			"east": bounds[2],
			"north": bounds[3],
		},
		"dem": {
			"provider": "mapterhorn",
			"tile_endpoint": (
				"https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"
			),
			"processing_zoom": uniform_zoom,
			"tile_size": int(args.tile_size),
			"encoding": "terrarium",
			"overzoom_fallback_minzoom": base_zoom,
			"overzoom_fallback_mode": "http",
		},
		"threshold": threshold_config(connectivity=4),
		"work_region_plan": str(output_dir / "plan.json"),
	}
	(output_dir / "dem-config.json").write_text(
		json.dumps(dem_config, indent=2) + "\n",
		encoding="utf-8",
	)

	print(json.dumps(plan, indent=2))


if __name__ == "__main__":
	main()
