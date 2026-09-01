#!/usr/bin/env python3

import json
import shutil
import subprocess
from collections import deque
from pathlib import Path

import numpy as np


def initialize_output(path, cells, sentinel, chunk_cells=1 << 20):
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)

	chunk = np.full(
		min(int(chunk_cells), int(cells)),
		sentinel,
		dtype=np.uint8,
	)

	with path.open("wb") as output:
		remaining = int(cells)
		while remaining:
			count = min(remaining, chunk.size)
			output.write(chunk[:count].tobytes())
			remaining -= count


def improve(target, values):
	better = values < target
	count = int(np.count_nonzero(better))
	if count:
		target[better] = values[better]
	return count


def build_boundary(domain, sentinel):
	boundary = np.full(
		(domain["height"], domain["width"]),
		sentinel,
		dtype=np.uint8,
	)
	boundary[0, :] = np.minimum(
		boundary[0, :],
		domain["incoming"]["top"],
	)
	boundary[-1, :] = np.minimum(
		boundary[-1, :],
		domain["incoming"]["bottom"],
	)
	boundary[:, 0] = np.minimum(
		boundary[:, 0],
		domain["incoming"]["left"],
	)
	boundary[:, -1] = np.minimum(
		boundary[:, -1],
		domain["incoming"]["right"],
	)
	return boundary


def apply_external_sea_seeds(
	domain,
	land,
	external_sea,
	sentinel,
):
	if not external_sea:
		return 0

	improvements = 0
	for side in ("top", "bottom", "left", "right"):
		outside = external_sea.get(side)
		if outside is None:
			continue

		outside = np.asarray(
			outside,
			dtype=bool,
		)
		if side == "top":
			edge_land = land[0, :]
		elif side == "bottom":
			edge_land = land[-1, :]
		elif side == "left":
			edge_land = land[:, 0]
		else:
			edge_land = land[:, -1]

		if outside.shape != edge_land.shape:
			raise ValueError(
				f"External-Sea-Länge passt nicht für {side}: "
				f"{outside.shape} != {edge_land.shape}"
			)

		seed = np.full(
			edge_land.shape,
			sentinel,
			dtype=np.uint8,
		)
		seed[edge_land & outside] = 0
		improvements += improve(
			domain["incoming"][side],
			seed,
		)

	return improvements


def scatter_domain(
	output_path,
	result,
	land,
	domain,
	sentinel,
	global_width,
):
	with Path(output_path).open("r+b") as output:
		for local_row in range(domain["height"]):
			values = np.full(
				domain["width"],
				sentinel,
				dtype=np.uint8,
			)
			row_land = land[local_row]
			values[row_land] = result[
				local_row,
				row_land,
			]

			global_row = domain["y0"] + local_row
			offset = (
				global_row * int(global_width)
				+ domain["x0"]
			)
			output.seek(offset)
			output.write(values.tobytes())


def regular_domains(width, height, domain_width, domain_height):
	width = int(width)
	height = int(height)
	domain_width = int(domain_width)
	domain_height = int(domain_height)

	if min(width, height, domain_width, domain_height) <= 0:
		raise ValueError("Raster- und Domain-Dimensionen müssen > 0 sein.")

	result = []
	for grid_row, y0 in enumerate(
		range(0, height, domain_height)
	):
		for grid_col, x0 in enumerate(
			range(0, width, domain_width)
		):
			result.append({
				"grid_row": grid_row,
				"grid_col": grid_col,
				"x0": x0,
				"y0": y0,
				"width": min(domain_width, width - x0),
				"height": min(domain_height, height - y0),
			})
	return result


def process_lazy_domains(
	domain_specs,
	materialize_domain,
	output_path,
	work_dir,
	solver_path,
	levels_csv,
	*,
	global_width,
	global_height,
	max_solver_runs=100000,
):
	global_width = int(global_width)
	global_height = int(global_height)
	max_solver_runs = int(max_solver_runs)

	if global_width <= 0 or global_height <= 0:
		raise ValueError(
			"global_width und global_height müssen > 0 sein."
		)
	if max_solver_runs <= 0:
		raise ValueError("max_solver_runs muss > 0 sein.")

	levels = [
		value
		for value in str(levels_csv).split(",")
		if value
	]
	sentinel = len(levels)
	if sentinel <= 0 or sentinel > 254:
		raise ValueError("Ungültige Threshold-Klassen.")

	work_dir = Path(work_dir)
	shutil.rmtree(work_dir, ignore_errors=True)
	work_dir.mkdir(parents=True, exist_ok=True)

	domains = {}
	for spec in domain_specs:
		key = (
			int(spec["grid_row"]),
			int(spec["grid_col"]),
		)
		if key in domains:
			raise ValueError(f"Doppelte Domain {key}.")

		x0 = int(spec["x0"])
		y0 = int(spec["y0"])
		width = int(spec["width"])
		height = int(spec["height"])
		if width <= 0 or height <= 0:
			raise ValueError(f"Leere Domain {key}.")
		if (
			x0 < 0
			or y0 < 0
			or x0 + width > global_width
			or y0 + height > global_height
		):
			raise ValueError(
				f"Domain {key} liegt außerhalb des Globalrasters."
			)

		domains[key] = {
			**spec,
			"grid_row": key[0],
			"grid_col": key[1],
			"x0": x0,
			"y0": y0,
			"width": width,
			"height": height,
			"incoming": {
				"top": np.full(
					width,
					sentinel,
					dtype=np.uint8,
				),
				"bottom": np.full(
					width,
					sentinel,
					dtype=np.uint8,
				),
				"left": np.full(
					height,
					sentinel,
					dtype=np.uint8,
				),
				"right": np.full(
					height,
					sentinel,
					dtype=np.uint8,
				),
			},
			"runs": 0,
			"land_cells": None,
		}

	initialize_output(
		output_path,
		global_width * global_height,
		sentinel,
	)

	queue = deque(domains.keys())
	queued = set(domains.keys())
	solver_runs = 0
	materializations = 0
	boundary_improvements = 0
	external_sea_improvements = 0
	peak_materialized_cells = 0

	def queue_domain(key):
		if key not in domains or key in queued:
			return
		queue.append(key)
		queued.add(key)

	while queue:
		key = queue.popleft()
		queued.remove(key)
		domain = domains[key]

		solver_runs += 1
		if solver_runs > max_solver_runs:
			raise RuntimeError(
				"Lazy-Domain-Solver hat max_solver_runs überschritten."
			)

		domain_dir = (
			work_dir
			/ f"r{key[0]}-c{key[1]}"
		)
		shutil.rmtree(domain_dir, ignore_errors=True)
		domain_dir.mkdir(parents=True)

		try:
			meta = materialize_domain(
				domain,
				domain_dir,
			)
			materializations += 1
			peak_materialized_cells = max(
				peak_materialized_cells,
				domain["width"] * domain["height"],
			)

			elevation_path = Path(meta["elevation_path"])
			sea_path = Path(meta["sea_mask_path"])
			land_path = Path(meta["land_mask_path"])

			expected_cells = (
				domain["width"] * domain["height"]
			)
			if elevation_path.stat().st_size != expected_cells * 4:
				raise ValueError(
					f"Falsche Elevation-Größe für Domain {key}."
				)
			if sea_path.stat().st_size != expected_cells:
				raise ValueError(
					f"Falsche Sea-Mask-Größe für Domain {key}."
				)
			if land_path.stat().st_size != expected_cells:
				raise ValueError(
					f"Falsche Land-Mask-Größe für Domain {key}."
				)

			land = np.fromfile(
				land_path,
				dtype=np.uint8,
			).reshape(
				(domain["height"], domain["width"])
			) != 0
			land_cells = int(np.count_nonzero(land))
			if domain["land_cells"] is None:
				domain["land_cells"] = land_cells
			elif domain["land_cells"] != land_cells:
				raise RuntimeError(
					f"Domain {key} änderte ihre Landmaske "
					"zwischen Materialisierungen."
				)

			external_sea_improvements += (
				apply_external_sea_seeds(
					domain,
					land,
					meta.get("external_sea"),
					sentinel,
				)
			)

			sea = np.fromfile(
				sea_path,
				dtype=np.uint8,
			).reshape(
				(domain["height"], domain["width"])
			)
			has_sea = bool(np.any(sea != 0))
			has_boundary = any(
				np.any(values < sentinel)
				for values in domain["incoming"].values()
			)

			if land_cells == 0 or not (
				has_sea or has_boundary
			):
				result = np.full(
					(domain["height"], domain["width"]),
					sentinel,
					dtype=np.uint8,
				)
			else:
				boundary_path = (
					domain_dir / "boundary.u8"
				)
				result_path = (
					domain_dir / "threshold.u8"
				)
				build_boundary(
					domain,
					sentinel,
				).tofile(boundary_path)

				subprocess.run([
					str(solver_path),
					"--elevation",
					str(elevation_path),
					"--sea-mask",
					str(sea_path),
					"--boundary-threshold",
					str(boundary_path),
					"--output",
					str(result_path),
					"--width",
					str(domain["width"]),
					"--height",
					str(domain["height"]),
					"--levels",
					str(levels_csv),
					"--connectivity",
					"4",
				], check=True)

				result = np.fromfile(
					result_path,
					dtype=np.uint8,
				).reshape(
					(domain["height"], domain["width"])
				)

			domain["runs"] += 1
			scatter_domain(
				output_path,
				result,
				land,
				domain,
				sentinel,
				global_width,
			)

			grid_row, grid_col = key
			neighbors = [
				(
					(grid_row - 1, grid_col),
					"bottom",
					result[0, :],
					land[0, :],
				),
				(
					(grid_row + 1, grid_col),
					"top",
					result[-1, :],
					land[-1, :],
				),
				(
					(grid_row, grid_col - 1),
					"right",
					result[:, 0],
					land[:, 0],
				),
				(
					(grid_row, grid_col + 1),
					"left",
					result[:, -1],
					land[:, -1],
				),
			]

			for (
				neighbor_key,
				neighbor_side,
				values,
				edge_land,
			) in neighbors:
				neighbor = domains.get(neighbor_key)
				if neighbor is None:
					continue

				target = neighbor["incoming"][neighbor_side]
				if target.shape != values.shape:
					raise ValueError(
						"Benachbarte Domain-Kanten haben "
						f"unterschiedliche Länge: {key} -> "
						f"{neighbor_key}."
					)

				outgoing = np.full(
					values.shape,
					sentinel,
					dtype=np.uint8,
				)
				valid = edge_land & (values < sentinel)
				outgoing[valid] = values[valid]

				changed = improve(target, outgoing)
				if changed:
					boundary_improvements += changed
					queue_domain(neighbor_key)
		finally:
			shutil.rmtree(
				domain_dir,
				ignore_errors=True,
			)

	return {
		"domain_count": len(domains),
		"solver_runs": solver_runs,
		"materializations": materializations,
		"boundary_improvements": boundary_improvements,
		"external_sea_improvements": (
			external_sea_improvements
		),
		"peak_materialized_cells": peak_materialized_cells,
		"sentinel_class": sentinel,
		"all_domain_work_deleted": (
			not any(work_dir.iterdir())
		),
		"domains": [
			{
				"grid_row": key[0],
				"grid_col": key[1],
				"x0": domain["x0"],
				"y0": domain["y0"],
				"width": domain["width"],
				"height": domain["height"],
				"land_cells": (
					0
					if domain["land_cells"] is None
					else domain["land_cells"]
				),
				"runs": domain["runs"],
			}
			for key, domain in sorted(domains.items())
		],
	}


def write_report(path, report):
	Path(path).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
