#!/usr/bin/env python3

import argparse
import concurrent.futures
import json
import math
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import mapbox_vector_tile
import numpy as np
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union


WEB_MERCATOR_WORLD = 40075016.68557849
DEFAULT_ATTRIBUTION_URL = "https://download.mapterhorn.com/attribution.json"
DEFAULT_DOWNLOAD_URLS_URL = "https://download.mapterhorn.com/download_urls.json"
DEFAULT_COVERAGE_TILE_URL = (
	"https://single-archive-tiles.mapterhorn.com/coverage/{z}/{x}/{y}.mvt"
)
USER_AGENT = "Kartensammlung-SeaLevel-CoveragePlanner/1.0"


def parse_bbox(value):
	parts = [float(part.strip()) for part in value.split(",")]
	if len(parts) != 4:
		raise argparse.ArgumentTypeError(
			"BBox muss west,south,east,north enthalten."
		)

	west, south, east, north = parts
	if not (-180.0 <= west < east <= 180.0):
		raise argparse.ArgumentTypeError("Ungültige West/Ost-Grenzen.")
	if not (-85.05112878 <= south < north <= 85.05112878):
		raise argparse.ArgumentTypeError("Ungültige Süd/Nord-Grenzen.")

	return (west, south, east, north)


def lon_to_tile_x(lon, zoom):
	return (lon + 180.0) / 360.0 * (2 ** zoom)


def lat_to_tile_y(lat, zoom):
	lat_rad = math.radians(lat)
	return (
		1.0
		- math.asinh(math.tan(lat_rad)) / math.pi
	) / 2.0 * (2 ** zoom)


def inclusive_min_tile(value):
	nearest = round(value)
	if math.isclose(value, nearest, rel_tol=0.0, abs_tol=1e-10):
		return int(nearest)

	return math.floor(value)


def exclusive_max_tile(value):
	nearest = round(value)
	if math.isclose(value, nearest, rel_tol=0.0, abs_tol=1e-10):
		return int(nearest) - 1

	return math.floor(value)


def tiles_for_bbox(bounds, zoom):
	west, south, east, north = bounds

	x_min = inclusive_min_tile(lon_to_tile_x(west, zoom))
	x_max = exclusive_max_tile(lon_to_tile_x(east, zoom))
	y_min = inclusive_min_tile(lat_to_tile_y(north, zoom))
	y_max = exclusive_max_tile(lat_to_tile_y(south, zoom))

	return [
		(x, y)
		for y in range(y_min, y_max + 1)
		for x in range(x_min, x_max + 1)
	]


def tile_bounds_lonlat(x, y, zoom):
	n = 2 ** zoom

	west = x / n * 360.0 - 180.0
	east = (x + 1) / n * 360.0 - 180.0

	def tile_y_to_lat(tile_y):
		return math.degrees(
			math.atan(
				math.sinh(
					math.pi * (1.0 - 2.0 * tile_y / n)
				)
			)
		)

	north = tile_y_to_lat(y)
	south = tile_y_to_lat(y + 1)
	return (west, south, east, north)


def tile_geometry_to_lonlat(geometry, x, y, zoom, extent):
	n = 2 ** zoom

	def convert(tile_x, tile_y, z=None):
		tile_x = np.asarray(tile_x, dtype=np.float64)
		tile_y = np.asarray(tile_y, dtype=np.float64)

		lon = (
			(x + tile_x / extent) / n * 360.0
			- 180.0
		)
		global_y = y + (1.0 - tile_y / extent)
		lat = np.degrees(
			np.arctan(
				np.sinh(
					math.pi * (1.0 - 2.0 * global_y / n)
				)
			)
		)

		if z is None:
			return lon, lat

		return lon, lat, z

	return transform(convert, geometry)


def fetch_bytes(url, *, timeout=60):
	request = urllib.request.Request(
		url,
		headers={"User-Agent": USER_AGENT},
	)
	with urllib.request.urlopen(request, timeout=timeout) as response:
		return response.read()


def fetch_json(url):
	return json.loads(fetch_bytes(url).decode("utf-8"))


def fetch_coverage_tile(template, zoom, x, y, cache_dir=None):
	url = template.format(z=zoom, x=x, y=y)

	if cache_dir:
		path = (
			Path(cache_dir)
			/ "coverage"
			/ str(zoom)
			/ str(x)
			/ f"{y}.mvt"
		)
		path.parent.mkdir(parents=True, exist_ok=True)
		if path.exists() and path.stat().st_size > 0:
			return path.read_bytes()

	try:
		data = fetch_bytes(url)
	except urllib.error.HTTPError as error:
		if error.code in (204, 404):
			return b""
		raise

	if cache_dir and data:
		path.write_bytes(data)

	return data


def decode_coverage_tile(data, zoom, x, y):
	if not data:
		return []

	decoded = mapbox_vector_tile.decode(data)
	layer = decoded.get("coverage")
	if not layer:
		return []

	extent = int(layer.get("extent", 4096))
	result = []

	for feature in layer.get("features", []):
		source = feature.get("properties", {}).get("source")
		geometry_data = feature.get("geometry")

		if not source or not geometry_data:
			continue

		geometry = shape(geometry_data)
		if geometry.is_empty:
			continue

		geometry = tile_geometry_to_lonlat(
			geometry,
			x,
			y,
			zoom,
			extent,
		)

		if not geometry.is_valid:
			geometry = geometry.buffer(0)

		if geometry.is_empty:
			continue

		result.append((str(source), geometry))

	return result


def recommended_zoom(latitude, target_ground_resolution_m, tile_size=512):
	latitude = max(-85.0, min(85.0, float(latitude)))
	target = float(target_ground_resolution_m)

	if target <= 0.0:
		raise ValueError("target_ground_resolution_m muss > 0 sein.")

	value = math.log2(
		WEB_MERCATOR_WORLD
		* math.cos(math.radians(latitude))
		/ (tile_size * target)
	)

	return max(0, int(round(value)))


def ground_resolution(latitude, zoom, tile_size=512):
	return (
		WEB_MERCATOR_WORLD
		/ ((2 ** zoom) * tile_size)
		* math.cos(math.radians(latitude))
	)


def source_tier(
	resolution,
	*,
	tier2_max_source_resolution_m=10.0,
	tier3_max_source_resolution_m=2.0,
):
	if resolution is None:
		return {
			"automatic_tier": None,
			"tier3_candidate": False,
		}

	resolution = float(resolution)
	return {
		"automatic_tier": (
			2
			if resolution <= tier2_max_source_resolution_m
			else 1
		),
		"tier3_candidate": (
			resolution <= tier3_max_source_resolution_m
		),
	}


def intersecting_archives(download_data, bounds):
	west, south, east, north = bounds
	result = []

	for item in download_data.get("items", []):
		if item.get("name") == "planet.pmtiles":
			continue

		if (
			float(item["max_lon"]) <= west
			or float(item["min_lon"]) >= east
			or float(item["max_lat"]) <= south
			or float(item["min_lat"]) >= north
		):
			continue

		result.append(item)

	return result


def collect_coverage(
	bounds,
	zoom,
	*,
	tile_url,
	cache_dir=None,
	workers=12,
):
	target = box(*bounds)
	tiles = tiles_for_bbox(bounds, zoom)
	pieces = {}

	def load(tile):
		x, y = tile
		data = fetch_coverage_tile(
			tile_url,
			zoom,
			x,
			y,
			cache_dir=cache_dir,
		)
		return tile, decode_coverage_tile(data, zoom, x, y)

	with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
		futures = [executor.submit(load, tile) for tile in tiles]

		for future in concurrent.futures.as_completed(futures):
			_tile, features = future.result()
			for source, geometry in features:
				clipped = geometry.intersection(target)
				if clipped.is_empty:
					continue
				pieces.setdefault(source, []).append(clipped)

	coverage = {}
	for source, geometries in pieces.items():
		merged = unary_union(geometries)
		if not merged.is_valid:
			merged = merged.buffer(0)
		if merged.is_empty:
			continue
		coverage[source] = merged

	return coverage, tiles


def geometry_feature(source, geometry, metadata, planning):
	properties = {
		"source": source,
		"name": metadata.get("name"),
		"resolution_m": metadata.get("resolution"),
		"license": metadata.get("license"),
		"producer": metadata.get("producer"),
		"access_year": metadata.get("access_year"),
		"automatic_tier": planning.get("automatic_tier"),
		"tier3_candidate": planning.get("tier3_candidate"),
		"recommended_processing_zoom": planning.get(
			"recommended_processing_zoom"
		),
		"recommended_ground_resolution_m": planning.get(
			"recommended_ground_resolution_m"
		),
	}

	return {
		"type": "Feature",
		"properties": properties,
		"geometry": mapping(geometry),
	}


def write_geojson(path, features):
	Path(path).write_text(
		json.dumps(
			{
				"type": "FeatureCollection",
				"features": features,
			},
			indent=2,
		) + "\n",
		encoding="utf-8",
	)


def plan(
	bounds,
	*,
	coverage_zoom=8,
	tier2_max_source_resolution_m=10.0,
	tier3_max_source_resolution_m=2.0,
	base_target_ground_resolution_m=30.0,
	tier2_target_ground_resolution_m=12.0,
	tier3_target_ground_resolution_m=6.0,
	attribution_url=DEFAULT_ATTRIBUTION_URL,
	download_urls_url=DEFAULT_DOWNLOAD_URLS_URL,
	coverage_tile_url=DEFAULT_COVERAGE_TILE_URL,
	cache_dir=None,
	workers=12,
):
	attribution = fetch_json(attribution_url)
	download_data = fetch_json(download_urls_url)
	metadata_by_source = {
		str(item["source"]): item
		for item in attribution
	}

	coverage, tiles = collect_coverage(
		bounds,
		coverage_zoom,
		tile_url=coverage_tile_url,
		cache_dir=cache_dir,
		workers=workers,
	)

	center_lat = (bounds[1] + bounds[3]) / 2.0
	base_zoom = recommended_zoom(
		center_lat,
		base_target_ground_resolution_m,
	)
	base_ground = ground_resolution(center_lat, base_zoom)

	source_records = []
	source_features = []
	tier2_geometries = []
	tier3_geometries = []

	for source in sorted(coverage):
		geometry = coverage[source]
		metadata = metadata_by_source.get(source, {})
		resolution = metadata.get("resolution")
		tier = source_tier(
			resolution,
			tier2_max_source_resolution_m=tier2_max_source_resolution_m,
			tier3_max_source_resolution_m=tier3_max_source_resolution_m,
		)

		centroid_lat = geometry.representative_point().y
		target_resolution = None
		if tier["tier3_candidate"]:
			target_resolution = tier3_target_ground_resolution_m
		elif tier["automatic_tier"] == 2:
			target_resolution = tier2_target_ground_resolution_m

		recommended_processing_zoom = None
		recommended_ground = None
		if target_resolution is not None:
			recommended_processing_zoom = recommended_zoom(
				centroid_lat,
				target_resolution,
			)
			recommended_ground = ground_resolution(
				centroid_lat,
				recommended_processing_zoom,
			)

		planning = {
			**tier,
			"recommended_processing_zoom": recommended_processing_zoom,
			"recommended_ground_resolution_m": (
				round(recommended_ground, 3)
				if recommended_ground is not None
				else None
			),
		}

		bounds_source = list(geometry.bounds)
		record = {
			"source": source,
			"name": metadata.get("name"),
			"resolution_m": resolution,
			"license": metadata.get("license"),
			"producer": metadata.get("producer"),
			"website": metadata.get("website"),
			"access_year": metadata.get("access_year"),
			"coverage_bounds": bounds_source,
			**planning,
		}
		source_records.append(record)
		source_features.append(
			geometry_feature(
				source,
				geometry,
				metadata,
				planning,
			)
		)

		if tier["automatic_tier"] == 2:
			tier2_geometries.append(geometry)
		if tier["tier3_candidate"]:
			tier3_geometries.append(geometry)

	tier2_union = (
		unary_union(tier2_geometries)
		if tier2_geometries
		else None
	)
	tier3_union = (
		unary_union(tier3_geometries)
		if tier3_geometries
		else None
	)

	archives = intersecting_archives(download_data, bounds)

	result = {
		"schema_version": 1,
		"generated_at": datetime.now(timezone.utc).isoformat(),
		"bounds": list(bounds),
		"coverage": {
			"zoom": coverage_zoom,
			"tile_count": len(tiles),
			"tile_url": coverage_tile_url,
			"source_count": len(source_records),
		},
		"mapterhorn": {
			"attribution_url": attribution_url,
			"download_urls_url": download_urls_url,
			"download_urls_version": download_data.get("version"),
			"priority_rule": (
				"higher local maxzoom first; at equal maxzoom "
				"lexicographically earlier source name first"
			),
		},
		"rules": {
			"base_target_ground_resolution_m": (
				base_target_ground_resolution_m
			),
			"tier2_max_source_resolution_m": (
				tier2_max_source_resolution_m
			),
			"tier2_target_ground_resolution_m": (
				tier2_target_ground_resolution_m
			),
			"tier3_max_source_resolution_m": (
				tier3_max_source_resolution_m
			),
			"tier3_target_ground_resolution_m": (
				tier3_target_ground_resolution_m
			),
			"tier3_policy": "QA candidate only; not automatic build",
		},
		"base": {
			"source": "planet.pmtiles / Mapterhorn aggregated terrain",
			"recommended_processing_zoom_at_bbox_center": base_zoom,
			"ground_resolution_m_at_bbox_center": round(base_ground, 3),
		},
		"sources": source_records,
		"tier2": {
			"source_count": sum(
				1
				for item in source_records
				if item["automatic_tier"] == 2
			),
			"has_coverage": tier2_union is not None,
		},
		"tier3_candidates": {
			"source_count": sum(
				1
				for item in source_records
				if item["tier3_candidate"]
			),
			"has_coverage": tier3_union is not None,
		},
		"high_resolution_archives": {
			"count": len(archives),
			"total_bytes": sum(int(item.get("size", 0)) for item in archives),
			"items": archives,
		},
	}

	return {
		"plan": result,
		"source_features": source_features,
		"tier2_union": tier2_union,
		"tier3_union": tier3_union,
	}


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Erzeugt aus der Mapterhorn Coverage Map einen "
			"Base-/Refinement-Plan."
		)
	)
	parser.add_argument("--bbox", type=parse_bbox, required=True)
	parser.add_argument("--output-dir", required=True)
	parser.add_argument("--coverage-zoom", type=int, default=8)
	parser.add_argument("--cache-dir", default="cache")
	parser.add_argument("--workers", type=int, default=12)
	parser.add_argument(
		"--tier2-max-source-resolution",
		type=float,
		default=10.0,
	)
	parser.add_argument(
		"--tier3-max-source-resolution",
		type=float,
		default=2.0,
	)
	parser.add_argument(
		"--base-target-resolution",
		type=float,
		default=30.0,
	)
	parser.add_argument(
		"--tier2-target-resolution",
		type=float,
		default=12.0,
	)
	parser.add_argument(
		"--tier3-target-resolution",
		type=float,
		default=6.0,
	)
	args = parser.parse_args()

	if args.coverage_zoom < 0 or args.coverage_zoom > 14:
		parser.error("--coverage-zoom muss zwischen 0 und 14 liegen.")

	output_dir = Path(args.output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	result = plan(
		args.bbox,
		coverage_zoom=args.coverage_zoom,
		tier2_max_source_resolution_m=args.tier2_max_source_resolution,
		tier3_max_source_resolution_m=args.tier3_max_source_resolution,
		base_target_ground_resolution_m=args.base_target_resolution,
		tier2_target_ground_resolution_m=args.tier2_target_resolution,
		tier3_target_ground_resolution_m=args.tier3_target_resolution,
		cache_dir=args.cache_dir,
		workers=args.workers,
	)

	(output_dir / "plan.json").write_text(
		json.dumps(result["plan"], indent=2) + "\n",
		encoding="utf-8",
	)

	write_geojson(
		output_dir / "sources.geojson",
		result["source_features"],
	)

	for name, geometry in (
		("tier2.geojson", result["tier2_union"]),
		("tier3-candidates.geojson", result["tier3_union"]),
	):
		features = []
		if geometry is not None and not geometry.is_empty:
			features.append({
				"type": "Feature",
				"properties": {
					"kind": name.removesuffix(".geojson"),
				},
				"geometry": mapping(geometry),
			})
		write_geojson(output_dir / name, features)

	summary = {
		"bounds": result["plan"]["bounds"],
		"coverage": result["plan"]["coverage"],
		"base": result["plan"]["base"],
		"tier2": result["plan"]["tier2"],
		"tier3_candidates": result["plan"]["tier3_candidates"],
		"high_resolution_archives": {
			"count": result["plan"]["high_resolution_archives"]["count"],
			"total_bytes": result["plan"]["high_resolution_archives"]["total_bytes"],
		},
	}
	print(json.dumps(summary, indent=2))


if __name__ == "__main__":
	main()
