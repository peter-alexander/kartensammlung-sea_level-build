#!/usr/bin/env python3

from collections import OrderedDict
from pathlib import Path

import fiona
import numpy as np
from affine import Affine
from rasterio.features import rasterize

from grid import WEB_MERCATOR_WORLD
from prepare_phase1a_dem import (
	decode_terrarium,
	download_task_set,
	overzoom_parent_tile,
	resolve_http_fallbacks,
	tile_path,
	tile_url,
)


def adaptive_domain_grid(
	parent_grid,
	domain,
):
	parent_grid = dict(parent_grid)
	zoom = int(domain["zoom"])
	scale = int(
		domain["fine_pixels_per_coarse_cell"]
	)
	parent_zoom = int(parent_grid["zoom"])
	zoom_factor = 2 ** (zoom - parent_zoom)
	if zoom_factor <= 0 or scale % zoom_factor != 0:
		raise ValueError(
			"Ungültige adaptive Zoom-/Scale-Kombination."
		)

	coarse_factor = scale // zoom_factor
	if coarse_factor <= 0:
		raise ValueError(
			"Ungültiger adaptiver Coarse-Faktor."
		)

	parent_resolution = float(
		parent_grid["resolution"]
	)
	coarse_resolution = (
		parent_resolution * coarse_factor
	)
	resolution = coarse_resolution / scale

	coarse_x0 = int(domain["coarse_x0"])
	coarse_y0 = int(domain["coarse_y0"])
	width = int(domain["fine_width"])
	height = int(domain["fine_height"])

	left = (
		float(parent_grid["left"])
		+ coarse_x0 * coarse_resolution
	)
	top = (
		float(parent_grid["top"])
		- coarse_y0 * coarse_resolution
	)
	right = left + width * resolution
	bottom = top - height * resolution

	half = WEB_MERCATOR_WORLD / 2.0
	global_pixel_x0 = int(round(
		(left + half) / resolution
	))
	global_pixel_y0 = int(round(
		(half - top) / resolution
	))

	expected_left = (
		-half + global_pixel_x0 * resolution
	)
	expected_top = (
		half - global_pixel_y0 * resolution
	)
	if (
		abs(expected_left - left) > 1e-5
		or abs(expected_top - top) > 1e-5
	):
		raise ValueError(
			"Adaptive Domain ist nicht auf Target-Pixel "
			"ausgerichtet."
		)

	return {
		"zoom": zoom,
		"resolution": resolution,
		"left": left,
		"top": top,
		"right": right,
		"bottom": bottom,
		"width": width,
		"height": height,
		"cells": width * height,
		"global_pixel_x0": global_pixel_x0,
		"global_pixel_y0": global_pixel_y0,
	}


def target_tiles_for_grid(
	grid,
	tile_size=512,
):
	tile_size = int(tile_size)
	x0 = int(grid["global_pixel_x0"])
	y0 = int(grid["global_pixel_y0"])
	x1 = x0 + int(grid["width"])
	y1 = y0 + int(grid["height"])

	tile_x0 = x0 // tile_size
	tile_y0 = y0 // tile_size
	tile_x1 = (x1 - 1) // tile_size
	tile_y1 = (y1 - 1) // tile_size

	return [
		(x, y)
		for y in range(tile_y0, tile_y1 + 1)
		for x in range(tile_x0, tile_x1 + 1)
	]


class AdaptiveMapterhornDomainMaterializer:
	def __init__(
		self,
		*,
		parent_grid,
		sea_vector_path,
		cache_dir,
		workers=8,
		fallback_min_zoom=None,
		tile_size=512,
		decoded_tile_cache_size=64,
		sea_halo_cache_size=512,
	):
		self.parent_grid = dict(parent_grid)
		self.sea_vector_path = Path(sea_vector_path)
		self.cache_dir = Path(cache_dir)
		self.workers = int(workers)
		self.tile_size = int(tile_size)
		self.fallback_min_zoom = (
			int(self.parent_grid["zoom"])
			if fallback_min_zoom is None
			else int(fallback_min_zoom)
		)
		self.sea_source = None
		self.decoded_tile_cache_size = int(
			decoded_tile_cache_size
		)
		self.sea_halo_cache_size = int(
			sea_halo_cache_size
		)
		self.decoded_tile_cache = OrderedDict()
		self.sea_halo_cache = OrderedDict()
		self.cache_counters = {
			"decoded_tile_hits": 0,
			"decoded_tile_misses": 0,
			"decoded_tile_peak_entries": 0,
			"sea_halo_hits": 0,
			"sea_halo_misses": 0,
			"sea_halo_peak_entries": 0,
		}

		if self.workers <= 0:
			raise ValueError("workers muss > 0 sein.")
		if self.tile_size <= 0:
			raise ValueError("tile_size muss > 0 sein.")
		if self.decoded_tile_cache_size < 0:
			raise ValueError(
				"decoded_tile_cache_size muss >= 0 sein."
			)
		if self.sea_halo_cache_size < 0:
			raise ValueError(
				"sea_halo_cache_size muss >= 0 sein."
			)
		if not self.sea_vector_path.exists():
			raise FileNotFoundError(self.sea_vector_path)

	def close(self):
		if self.sea_source is not None:
			self.sea_source.close()
			self.sea_source = None

	def __del__(self):
		try:
			self.close()
		except Exception:
			pass

	def cache_stats(self):
		return {
			**self.cache_counters,
			"decoded_tile_entries": len(
				self.decoded_tile_cache
			),
			"sea_halo_entries": len(
				self.sea_halo_cache
			),
			"decoded_tile_cache_size": (
				self.decoded_tile_cache_size
			),
			"sea_halo_cache_size": (
				self.sea_halo_cache_size
			),
		}

	def _cache_get(self, cache, key, hit_counter):
		value = cache.get(key)
		if value is None:
			return None
		cache.move_to_end(key)
		self.cache_counters[hit_counter] += 1
		return value

	def _cache_put(
		self,
		cache,
		key,
		value,
		limit,
		peak_counter,
	):
		if limit <= 0:
			return
		cache[key] = value
		cache.move_to_end(key)
		while len(cache) > limit:
			cache.popitem(last=False)
		self.cache_counters[peak_counter] = max(
			self.cache_counters[peak_counter],
			len(cache),
		)

	def _decoded_exact_tile(self, zoom, x, y):
		key = (int(zoom), int(x), int(y))
		cached = self._cache_get(
			self.decoded_tile_cache,
			key,
			"decoded_tile_hits",
		)
		if cached is not None:
			return cached

		self.cache_counters[
			"decoded_tile_misses"
		] += 1
		tile = decode_terrarium(
			tile_path(
				self.cache_dir,
				*key,
			)
		)
		self._cache_put(
			self.decoded_tile_cache,
			key,
			tile,
			self.decoded_tile_cache_size,
			"decoded_tile_peak_entries",
		)
		return tile

	def _domain_grid(self, domain):
		return adaptive_domain_grid(
			self.parent_grid,
			domain,
		)

	def _target_tiles(self, grid):
		return target_tiles_for_grid(
			grid,
			self.tile_size,
		)

	def _download_tiles(self, grid):
		zoom = int(grid["zoom"])
		coords = self._target_tiles(grid)
		tasks = [
			(
				x,
				y,
				tile_url(zoom, x, y),
				tile_path(
					self.cache_dir,
					zoom,
					x,
					y,
				),
			)
			for x, y in coords
		]
		status = download_task_set(
			tasks,
			self.workers,
			label_zoom=zoom,
		)

		missing = sorted(
			(x, y)
			for x, y in coords
			if status[(x, y)] == "missing"
		)
		if missing:
			(
				fallbacks,
				unresolved,
				parent_tiles,
			) = resolve_http_fallbacks(
				missing,
				zoom,
				self.fallback_min_zoom,
				self.cache_dir,
				self.workers,
			)
		else:
			fallbacks = {}
			unresolved = []
			parent_tiles = []

		if unresolved:
			raise RuntimeError(
				"Adaptive Domain enthält nicht auflösbare "
				f"DEM-Tiles: {unresolved[:20]}"
			)

		return {
			"coords": coords,
			"status": status,
			"fallbacks": fallbacks,
			"parent_tiles": parent_tiles,
			"missing": missing,
		}

	def _load_target_tile(
		self,
		zoom,
		x,
		y,
		tile_info,
		_decoded_parents=None,
	):
		target_key = (int(zoom), int(x), int(y))
		cached = self._cache_get(
			self.decoded_tile_cache,
			target_key,
			"decoded_tile_hits",
		)
		if cached is not None:
			return cached

		if tile_info["status"][(x, y)] != "missing":
			return self._decoded_exact_tile(
				zoom,
				x,
				y,
			)

		fallback = tile_info["fallbacks"][(x, y)]
		parent_key = (
			int(fallback["parent_zoom"]),
			int(fallback["parent_x"]),
			int(fallback["parent_y"]),
		)
		parent = self._decoded_exact_tile(
			*parent_key,
		)
		tile = overzoom_parent_tile(
			parent,
			x,
			y,
			zoom,
			parent_key[0],
		)
		self._cache_put(
			self.decoded_tile_cache,
			target_key,
			tile,
			self.decoded_tile_cache_size,
			"decoded_tile_peak_entries",
		)
		return tile

	def _materialize_elevation(self, grid, output_path):
		tile_info = self._download_tiles(grid)
		output = np.empty(
			(int(grid["height"]), int(grid["width"])),
			dtype=np.float32,
		)
		zoom = int(grid["zoom"])
		window_x0 = int(grid["global_pixel_x0"])
		window_y0 = int(grid["global_pixel_y0"])
		window_x1 = window_x0 + int(grid["width"])
		window_y1 = window_y0 + int(grid["height"])
		decoded_parents = {}

		for tile_x, tile_y in tile_info["coords"]:
			tile = self._load_target_tile(
				zoom,
				tile_x,
				tile_y,
				tile_info,
				decoded_parents,
			)
			tile_x0 = tile_x * self.tile_size
			tile_y0 = tile_y * self.tile_size
			tile_x1 = tile_x0 + self.tile_size
			tile_y1 = tile_y0 + self.tile_size

			copy_x0 = max(window_x0, tile_x0)
			copy_y0 = max(window_y0, tile_y0)
			copy_x1 = min(window_x1, tile_x1)
			copy_y1 = min(window_y1, tile_y1)
			if copy_x1 <= copy_x0 or copy_y1 <= copy_y0:
				continue

			output[
				copy_y0 - window_y0:copy_y1 - window_y0,
				copy_x0 - window_x0:copy_x1 - window_x0,
			] = tile[
				copy_y0 - tile_y0:copy_y1 - tile_y0,
				copy_x0 - tile_x0:copy_x1 - tile_x0,
			]

		output.tofile(output_path)
		return {
			"target_tile_count": len(tile_info["coords"]),
			"requested_missing_tile_count": len(
				tile_info["missing"]
			),
			"fallback_parent_tile_count": len(
				tile_info["parent_tiles"]
			),
		}

	def _ensure_sea_source(self):
		if self.sea_source is None:
			self.sea_source = fiona.open(
				self.sea_vector_path
			)
		return self.sea_source

	def _rasterize_sea_halo(self, grid):
		cache_key = (
			int(grid["zoom"]),
			int(grid["global_pixel_x0"]),
			int(grid["global_pixel_y0"]),
			int(grid["width"]),
			int(grid["height"]),
		)
		cached = self._cache_get(
			self.sea_halo_cache,
			cache_key,
			"sea_halo_hits",
		)
		if cached is not None:
			packed, shape = cached
			return np.unpackbits(
				np.frombuffer(
					packed,
					dtype=np.uint8,
				),
				count=shape[0] * shape[1],
			).reshape(shape)

		self.cache_counters["sea_halo_misses"] += 1
		resolution = float(grid["resolution"])
		width = int(grid["width"]) + 2
		height = int(grid["height"]) + 2
		left = float(grid["left"]) - resolution
		top = float(grid["top"]) + resolution
		right = left + width * resolution
		bottom = top - height * resolution

		source = self._ensure_sea_source()
		geometries = [
			feature["geometry"]
			for feature in source.filter(
				bbox=(left, bottom, right, top)
			)
			if feature["geometry"] is not None
		]

		transform_affine = Affine(
			resolution,
			0.0,
			left,
			0.0,
			-resolution,
			top,
		)
		result = rasterize(
			(
				(geometry, 1)
				for geometry in geometries
			),
			out_shape=(height, width),
			fill=0,
			transform=transform_affine,
			dtype=np.uint8,
		)
		self._cache_put(
			self.sea_halo_cache,
			cache_key,
			(
				np.packbits(
					result.reshape(-1)
				).tobytes(),
				result.shape,
			),
			self.sea_halo_cache_size,
			"sea_halo_peak_entries",
		)
		return result

	def __call__(self, domain, domain_dir):
		domain_dir = Path(domain_dir)
		domain_dir.mkdir(parents=True, exist_ok=True)
		grid = self._domain_grid(domain)

		elevation_path = domain_dir / "elevation.f32"
		dem_report = self._materialize_elevation(
			grid,
			elevation_path,
		)

		land = np.ones(
			(int(grid["height"]), int(grid["width"])),
			dtype=np.uint8,
		)
		land_path = domain_dir / "land.u8"
		land.tofile(land_path)

		sea_halo = self._rasterize_sea_halo(grid)
		sea = sea_halo[1:-1, 1:-1]
		sea_path = domain_dir / "sea.u8"
		sea.tofile(sea_path)

		return {
			"elevation_path": str(elevation_path),
			"sea_mask_path": str(sea_path),
			"land_mask_path": str(land_path),
			"external_sea": {
				"top": sea_halo[0, 1:-1] != 0,
				"bottom": sea_halo[-1, 1:-1] != 0,
				"left": sea_halo[1:-1, 0] != 0,
				"right": sea_halo[1:-1, -1] != 0,
			},
			"grid": grid,
			"dem": dem_report,
			"sea_cells": int(np.count_nonzero(sea)),
		}
