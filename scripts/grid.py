import json
import math
from pathlib import Path

WEB_MERCATOR_RADIUS = 6378137.0
WEB_MERCATOR_WORLD = 2.0 * math.pi * WEB_MERCATOR_RADIUS


def lon_to_tile_x(lon, zoom):
	return (lon + 180.0) / 360.0 * (2 ** zoom)


def lat_to_tile_y(lat, zoom):
	lat_rad = math.radians(lat)
	return (
		1.0
		- math.asinh(math.tan(lat_rad)) / math.pi
	) / 2.0 * (2 ** zoom)


def _exclusive_max_tile(value):
	nearest = round(value)
	if math.isclose(value, nearest, rel_tol=0.0, abs_tol=1e-10):
		return int(nearest) - 1

	return math.floor(value)


def grid_from_config(config):
	bounds = config["bounds"]
	dem = config["dem"]
	zoom = int(dem["processing_zoom"])
	tile_size = int(dem["tile_size"])

	x_min = math.floor(lon_to_tile_x(bounds["west"], zoom))
	x_max = _exclusive_max_tile(lon_to_tile_x(bounds["east"], zoom))
	y_min = math.floor(lat_to_tile_y(bounds["north"], zoom))
	y_max = _exclusive_max_tile(lat_to_tile_y(bounds["south"], zoom))

	if x_max < x_min or y_max < y_min:
		raise ValueError("Die Bounds ergeben kein nicht-leeres Tile-Raster.")

	resolution = WEB_MERCATOR_WORLD / ((2 ** zoom) * tile_size)
	left = -WEB_MERCATOR_WORLD / 2.0 + x_min * tile_size * resolution
	top = WEB_MERCATOR_WORLD / 2.0 - y_min * tile_size * resolution
	width = (x_max - x_min + 1) * tile_size
	height = (y_max - y_min + 1) * tile_size
	right = left + width * resolution
	bottom = top - height * resolution

	return {
		"zoom": zoom,
		"tile_size": tile_size,
		"x_min": x_min,
		"x_max": x_max,
		"y_min": y_min,
		"y_max": y_max,
		"width": width,
		"height": height,
		"cells": width * height,
		"resolution": resolution,
		"left": left,
		"bottom": bottom,
		"right": right,
		"top": top,
	}


def load_config(path):
	return json.loads(Path(path).read_text(encoding="utf-8"))
