#!/usr/bin/env python3

import json
from pathlib import Path

import fiona
import numpy as np
from affine import Affine
from rasterio.features import rasterize

from grid import grid_from_config, load_config
from mask_candidate_to_work_region import (
	find_component,
	fine_row_to_coarse_row,
	map_intervals_to_fine,
	read_spans_by_row,
)
from prepare_phase1a_dem import (
	decode_terrarium,
	download_task_set,
	overzoom_parent_tile,
	resolve_http_fallbacks,
	tile_path,
	tile_url,
	write_elevation_strips,
)


class MapterhornWorkRegionDomainMaterializer:
	def __init__(
		self,
		*,
		fine_config_path,
		components_report_path,
		spans_path,
		component_id,
		parent_grid_path,
		coarse_factor,
		sea_vector_path,
		cache_dir,
		workers=8,
	):
		self.config = load_config(fine_config_path)
		self.fine_grid = grid_from_config(self.config)
		self.cache_dir = Path(cache_dir)
		self.workers = int(workers)
		self.coarse_factor = int(coarse_factor)
		self.sea_vector_path = Path(sea_vector_path)

		if self.workers <= 0:
			raise ValueError("workers muss > 0 sein.")
		if self.coarse_factor <= 0:
			raise ValueError("coarse_factor muss > 0 sein.")
		if not self.sea_vector_path.exists():
			raise FileNotFoundError(self.sea_vector_path)

		report = json.loads(
			Path(components_report_path).read_text(
				encoding="utf-8"
			)
		)
		self.component = find_component(
			report,
			component_id,
		)
		self.parent_grid = json.loads(
			Path(parent_grid_path).read_text(
				encoding="utf-8"
			)
		)["grid"]
		spans_by_row = read_spans_by_row(
			spans_path,
			self.component,
		)
		(
			self.fine_intervals_by_coarse_row,
			self.fine_pixels_per_coarse_cell,
		) = map_intervals_to_fine(
			spans_by_row,
			self.parent_grid,
			self.fine_grid,
			coarse_factor=self.coarse_factor,
		)

		self.tile_size = int(self.fine_grid["tile_size"])
		self.target_zoom = int(self.fine_grid["zoom"])
		self.fallback_min_zoom = self.config.get(
			"dem",
			{},
		).get("overzoom_fallback_minzoom")
		self.fallback_mode = self.config.get(
			"dem",
			{},
		).get("overzoom_fallback_mode", "http")

		if self.fallback_mode != "http":
			raise ValueError(
				"Lazy-Mapterhorn-Materializer unterstützt "
				"derzeit nur HTTP-Fallback."
			)

	def _validate_domain(self, domain):
		for key in ("x0", "y0", "width", "height"):
			if int(domain[key]) < 0:
				raise ValueError(
					f"Domain {key} muss >= 0 sein."
				)

		x0 = int(domain["x0"])
		y0 = int(domain["y0"])
		width = int(domain["width"])
		height = int(domain["height"])

		if width <= 0 or height <= 0:
			raise ValueError("Domain darf nicht leer sein.")
		if (
			x0 + width > int(self.fine_grid["width"])
			or y0 + height > int(self.fine_grid["height"])
		):
			raise ValueError(
				"Domain liegt außerhalb des Fine-Grids."
			)

		for value, name in (
			(x0, "x0"),
			(y0, "y0"),
			(width, "width"),
			(height, "height"),
		):
			if value % self.tile_size != 0:
				raise ValueError(
					f"Domain-{name} muss tile-aligned sein."
				)

	def _local_grid(self, domain):
		self._validate_domain(domain)

		x0 = int(domain["x0"])
		y0 = int(domain["y0"])
		width = int(domain["width"])
		height = int(domain["height"])
		resolution = float(self.fine_grid["resolution"])

		x_min = (
			int(self.fine_grid["x_min"])
			+ x0 // self.tile_size
		)
		y_min = (
			int(self.fine_grid["y_min"])
			+ y0 // self.tile_size
		)
		x_max = (
			x_min + width // self.tile_size - 1
		)
		y_max = (
			y_min + height // self.tile_size - 1
		)
		left = (
			float(self.fine_grid["left"])
			+ x0 * resolution
		)
		top = (
			float(self.fine_grid["top"])
			- y0 * resolution
		)

		return {
			"zoom": self.target_zoom,
			"tile_size": self.tile_size,
			"x_min": x_min,
			"x_max": x_max,
			"y_min": y_min,
			"y_max": y_max,
			"width": width,
			"height": height,
			"cells": width * height,
			"resolution": resolution,
			"left": left,
			"top": top,
			"right": left + width * resolution,
			"bottom": top - height * resolution,
		}

	def _materialize_dem(self, local_grid, output_path):
		tasks = []
		for y in range(
			local_grid["y_min"],
			local_grid["y_max"] + 1,
		):
			for x in range(
				local_grid["x_min"],
				local_grid["x_max"] + 1,
			):
				tasks.append((
					x,
					y,
					tile_url(
						local_grid["zoom"],
						x,
						y,
					),
					tile_path(
						self.cache_dir,
						local_grid["zoom"],
						x,
						y,
					),
				))

		status = download_task_set(
			tasks,
			self.workers,
			label_zoom=local_grid["zoom"],
		)
		requested_missing = sorted(
			(x, y)
			for x, y, _url, _path in tasks
			if status[(x, y)] == "missing"
		)

		fallback_parent_tiles = []
		if requested_missing:
			if self.fallback_min_zoom is None:
				raise RuntimeError(
					"Highres-Domain enthält fehlende DEM-Tiles "
					"und keinen Fallback."
				)

			(
				fallbacks,
				unresolved,
				fallback_parent_tiles,
			) = resolve_http_fallbacks(
				requested_missing,
				local_grid["zoom"],
				self.fallback_min_zoom,
				self.cache_dir,
				self.workers,
			)
		else:
			fallbacks = {}
			unresolved = []

		if unresolved:
			raise RuntimeError(
				"Highres-Domain enthält nicht auflösbare "
				f"DEM-Tiles: {unresolved[:20]}"
			)

		decoded_parents = {}
		fallback_tiles = []
		tile_paths = {
			(x, y): Path(path)
			for x, y, _url, path in tasks
		}

		def load_tile(x, y):
			if status[(x, y)] != "missing":
				return decode_terrarium(
					tile_paths[(x, y)]
				)

			fallback = fallbacks[(x, y)]
			parent_key = (
				int(fallback["parent_zoom"]),
				int(fallback["parent_x"]),
				int(fallback["parent_y"]),
			)
			if parent_key not in decoded_parents:
				decoded_parents[parent_key] = (
					decode_terrarium(
						tile_path(
							self.cache_dir,
							*parent_key,
						)
					)
				)

			fallback_tiles.append({
				"x": x,
				"y": y,
				"parent_zoom": parent_key[0],
				"parent_x": parent_key[1],
				"parent_y": parent_key[2],
			})
			return overzoom_parent_tile(
				decoded_parents[parent_key],
				x,
				y,
				local_grid["zoom"],
				parent_key[0],
			)

		write_elevation_strips(
			output_path,
			local_grid,
			load_tile,
		)

		return {
			"tile_count": len(tasks),
			"requested_missing_tile_count": len(
				requested_missing
			),
			"fallback_tile_count": len(fallback_tiles),
			"fallback_parent_tile_count": len(
				fallback_parent_tiles
			),
		}

	def _land_mask(self, domain):
		width = int(domain["width"])
		height = int(domain["height"])
		x0 = int(domain["x0"])
		y0 = int(domain["y0"])
		x1 = x0 + width
		land = np.zeros(
			(height, width),
			dtype=np.uint8,
		)

		for local_row in range(height):
			global_row = y0 + local_row
			coarse_row = fine_row_to_coarse_row(
				global_row,
				self.parent_grid,
				self.fine_grid,
				coarse_factor=self.coarse_factor,
			)
			intervals = (
				self.fine_intervals_by_coarse_row.get(
					coarse_row
				)
			)
			if not intervals:
				continue

			for global_left, global_right in intervals:
				left = max(x0, int(global_left))
				right = min(x1, int(global_right))
				if right <= left:
					continue
				land[
					local_row,
					left - x0:right - x0,
				] = 1

		return land

	def _rasterize_sea_halo(self, local_grid):
		resolution = float(local_grid["resolution"])
		halo_width = int(local_grid["width"]) + 2
		halo_height = int(local_grid["height"]) + 2
		halo_left = float(local_grid["left"]) - resolution
		halo_top = float(local_grid["top"]) + resolution
		halo_right = (
			halo_left + halo_width * resolution
		)
		halo_bottom = (
			halo_top - halo_height * resolution
		)
		bounds = (
			halo_left,
			halo_bottom,
			halo_right,
			halo_top,
		)

		with fiona.open(self.sea_vector_path) as source:
			geometries = [
				feature["geometry"]
				for feature in source.filter(bbox=bounds)
				if feature["geometry"] is not None
			]

		transform = Affine(
			resolution,
			0.0,
			halo_left,
			0.0,
			-resolution,
			halo_top,
		)
		sea_halo = rasterize(
			(
				(geometry, 1)
				for geometry in geometries
			),
			out_shape=(halo_height, halo_width),
			fill=0,
			transform=transform,
			dtype=np.uint8,
		)

		return sea_halo

	def __call__(self, domain, domain_dir):
		domain_dir = Path(domain_dir)
		domain_dir.mkdir(parents=True, exist_ok=True)
		local_grid = self._local_grid(domain)

		elevation_path = domain_dir / "elevation.f32"
		dem_report = self._materialize_dem(
			local_grid,
			elevation_path,
		)

		land = self._land_mask(domain)
		land_path = domain_dir / "land.u8"
		land.tofile(land_path)

		elevation = np.memmap(
			elevation_path,
			dtype=np.float32,
			mode="r+",
			shape=(
				int(local_grid["height"]),
				int(local_grid["width"]),
			),
		)
		elevation[land == 0] = np.nan
		elevation.flush()
		del elevation

		sea_halo = self._rasterize_sea_halo(
			local_grid
		)
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
			"land_cells": int(
				np.count_nonzero(land)
			),
			"sea_cells": int(
				np.count_nonzero(sea)
			),
			"grid": local_grid,
			"dem": dem_report,
		}
