#!/usr/bin/env python3

import json
import shutil
import subprocess
from collections import defaultdict, deque
from pathlib import Path

import numpy as np

from process_lazy_domains import (
	apply_external_sea_seeds,
	build_boundary,
	improve,
	write_sparse_domain,
)


def domain_key(domain):
	if "id" in domain:
		return int(domain["id"])
	return (
		int(domain["coarse_y0"]),
		int(domain["coarse_x0"]),
		int(domain["zoom"]),
	)


def validate_domain(domain):
	required = (
		"coarse_x0",
		"coarse_y0",
		"coarse_width",
		"coarse_height",
		"zoom",
		"fine_pixels_per_coarse_cell",
		"fine_width",
		"fine_height",
	)
	for key in required:
		if key not in domain:
			raise ValueError(
				f"Adaptive Domain ohne {key}."
			)

	if min(
		int(domain["coarse_width"]),
		int(domain["coarse_height"]),
		int(domain["fine_pixels_per_coarse_cell"]),
		int(domain["fine_width"]),
		int(domain["fine_height"]),
	) <= 0:
		raise ValueError("Adaptive Domain darf nicht leer sein.")

	if int(domain["fine_width"]) != (
		int(domain["coarse_width"])
		* int(domain["fine_pixels_per_coarse_cell"])
	):
		raise ValueError("Adaptive Domain hat inkonsistente Fine-Breite.")
	if int(domain["fine_height"]) != (
		int(domain["coarse_height"])
		* int(domain["fine_pixels_per_coarse_cell"])
	):
		raise ValueError("Adaptive Domain hat inkonsistente Fine-Höhe.")


def build_adjacencies(domains):
	left_edges = defaultdict(list)
	right_edges = defaultdict(list)
	top_edges = defaultdict(list)
	bottom_edges = defaultdict(list)

	for key, domain in domains.items():
		x0 = int(domain["coarse_x0"])
		y0 = int(domain["coarse_y0"])
		x1 = x0 + int(domain["coarse_width"])
		y1 = y0 + int(domain["coarse_height"])

		left_edges[x0].append((y0, y1, key))
		right_edges[x1].append((y0, y1, key))
		top_edges[y0].append((x0, x1, key))
		bottom_edges[y1].append((x0, x1, key))

	def match(first, second, side_first, side_second):
		result = []
		for coordinate in set(first) & set(second):
			a = sorted(first[coordinate])
			b = sorted(second[coordinate])
			i = 0
			j = 0

			while i < len(a) and j < len(b):
				a0, a1, akey = a[i]
				b0, b1, bkey = b[j]
				overlap0 = max(a0, b0)
				overlap1 = min(a1, b1)

				if overlap1 > overlap0 and akey != bkey:
					result.append({
						"a": akey,
						"a_side": side_first,
						"b": bkey,
						"b_side": side_second,
						"coarse_start": overlap0,
						"coarse_end": overlap1,
					})

				if a1 <= b1:
					i += 1
				if b1 <= a1:
					j += 1

		return result

	adjacencies = []
	adjacencies.extend(
		match(
			right_edges,
			left_edges,
			"right",
			"left",
		)
	)
	adjacencies.extend(
		match(
			bottom_edges,
			top_edges,
			"bottom",
			"top",
		)
	)

	by_domain = defaultdict(list)
	for adjacency in adjacencies:
		by_domain[adjacency["a"]].append(adjacency)
		by_domain[adjacency["b"]].append(adjacency)

	return adjacencies, by_domain


def side_offset(domain, side, coarse_value):
	if side in ("top", "bottom"):
		origin = int(domain["coarse_x0"])
	else:
		origin = int(domain["coarse_y0"])

	return (
		int(coarse_value) - origin
	) * int(domain["fine_pixels_per_coarse_cell"])


def side_values(result, land, side):
	if side == "top":
		return result[0, :], land[0, :]
	if side == "bottom":
		return result[-1, :], land[-1, :]
	if side == "left":
		return result[:, 0], land[:, 0]
	if side == "right":
		return result[:, -1], land[:, -1]
	raise ValueError(f"Unbekannte Domain-Seite: {side}")


def resample_thresholds(
	values,
	source_scale,
	target_scale,
	sentinel,
):
	values = np.asarray(values, dtype=np.uint8)
	source_scale = int(source_scale)
	target_scale = int(target_scale)

	if source_scale == target_scale:
		return np.array(values, copy=True)

	if source_scale > target_scale:
		if source_scale % target_scale != 0:
			raise ValueError(
				"Fine->Coarse-Ratio ist nicht ganzzahlig."
			)
		ratio = source_scale // target_scale
		if values.size % ratio != 0:
			raise ValueError(
				"Fine->Coarse-Kantenlänge ist nicht teilbar."
			)
		return values.reshape(
			(-1, ratio)
		).min(axis=1)

	if target_scale % source_scale != 0:
		raise ValueError(
			"Coarse->Fine-Ratio ist nicht ganzzahlig."
		)
	ratio = target_scale // source_scale
	return np.repeat(values, ratio)


def propagate_adjacency(
	source_key,
	source_domain,
	result,
	land,
	adjacency,
	domains,
	sentinel,
):
	if adjacency["a"] == source_key:
		source_side = adjacency["a_side"]
		target_key = adjacency["b"]
		target_side = adjacency["b_side"]
	else:
		source_side = adjacency["b_side"]
		target_key = adjacency["a"]
		target_side = adjacency["a_side"]

	target = domains[target_key]
	edge_values, edge_land = side_values(
		result,
		land,
		source_side,
	)

	source_start = side_offset(
		source_domain,
		source_side,
		adjacency["coarse_start"],
	)
	source_end = side_offset(
		source_domain,
		source_side,
		adjacency["coarse_end"],
	)
	target_start = side_offset(
		target,
		target_side,
		adjacency["coarse_start"],
	)
	target_end = side_offset(
		target,
		target_side,
		adjacency["coarse_end"],
	)

	values = np.full(
		source_end - source_start,
		sentinel,
		dtype=np.uint8,
	)
	source_values = edge_values[
		source_start:source_end
	]
	source_land = edge_land[
		source_start:source_end
	]
	valid = source_land & (source_values < sentinel)
	values[valid] = source_values[valid]

	resampled = resample_thresholds(
		values,
		source_domain["fine_pixels_per_coarse_cell"],
		target["fine_pixels_per_coarse_cell"],
		sentinel,
	)
	if resampled.size != target_end - target_start:
		raise RuntimeError(
			"Resampelte Domain-Kante hat falsche Länge."
		)

	target_values = target["incoming"][
		target_side
	][target_start:target_end]
	return (
		target_key,
		improve(target_values, resampled),
	)


def process_adaptive_lazy_domains(
	domain_specs,
	materialize_domain,
	output_dir,
	work_dir,
	solver_path,
	levels_csv,
	*,
	max_solver_runs=1000000,
):
	levels = [
		value
		for value in str(levels_csv).split(",")
		if value
	]
	sentinel = len(levels)
	if sentinel <= 0 or sentinel > 254:
		raise ValueError("Ungültige Threshold-Klassen.")

	max_solver_runs = int(max_solver_runs)
	if max_solver_runs <= 0:
		raise ValueError("max_solver_runs muss > 0 sein.")

	domains = {}
	for index, spec in enumerate(domain_specs, start=1):
		spec = dict(spec)
		spec.setdefault("id", index)
		validate_domain(spec)
		key = domain_key(spec)
		if key in domains:
			raise ValueError(f"Doppelte adaptive Domain: {key}.")

		width = int(spec["fine_width"])
		height = int(spec["fine_height"])
		domains[key] = {
			**spec,
			"width": int(spec["fine_width"]),
			"height": int(spec["fine_height"]),
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

	adjacencies, adjacency_by_domain = build_adjacencies(
		domains
	)

	work_dir = Path(work_dir)
	shutil.rmtree(work_dir, ignore_errors=True)
	work_dir.mkdir(parents=True, exist_ok=True)

	output_dir = Path(output_dir)
	shutil.rmtree(output_dir, ignore_errors=True)
	output_dir.mkdir(parents=True, exist_ok=True)

	queue = deque(domains.keys())
	queued = set(domains.keys())

	solver_runs = 0
	materializations = 0
	boundary_improvements = 0
	external_sea_improvements = 0
	peak_materialized_cells = 0
	max_fine_width = 0
	max_fine_height = 0

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
				"Adaptive Lazy-Domain-Solver hat "
				"max_solver_runs überschritten."
			)

		domain_dir = work_dir / f"domain-{domain['id']}"
		shutil.rmtree(domain_dir, ignore_errors=True)
		domain_dir.mkdir(parents=True)

		try:
			meta = materialize_domain(
				domain,
				domain_dir,
			)
			materializations += 1

			width = int(domain["fine_width"])
			height = int(domain["fine_height"])
			cells = width * height
			peak_materialized_cells = max(
				peak_materialized_cells,
				cells,
			)
			max_fine_width = max(max_fine_width, width)
			max_fine_height = max(max_fine_height, height)

			elevation_path = Path(meta["elevation_path"])
			sea_path = Path(meta["sea_mask_path"])
			land_path = Path(meta["land_mask_path"])

			if elevation_path.stat().st_size != cells * 4:
				raise ValueError(
					f"Falsche Elevation-Größe für {key}."
				)
			if sea_path.stat().st_size != cells:
				raise ValueError(
					f"Falsche Sea-Mask-Größe für {key}."
				)
			if land_path.stat().st_size != cells:
				raise ValueError(
					f"Falsche Land-Mask-Größe für {key}."
				)

			land = np.fromfile(
				land_path,
				dtype=np.uint8,
			).reshape((height, width)) != 0
			land_cells = int(np.count_nonzero(land))
			if domain["land_cells"] is None:
				domain["land_cells"] = land_cells
			elif domain["land_cells"] != land_cells:
				raise RuntimeError(
					f"Domain {key} änderte ihre Landmaske."
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
			).reshape((height, width))
			has_sea = bool(np.any(sea != 0))
			has_boundary = any(
				np.any(values < sentinel)
				for values in domain["incoming"].values()
			)

			if land_cells == 0 or not (
				has_sea or has_boundary
			):
				result = np.full(
					(height, width),
					sentinel,
					dtype=np.uint8,
				)
			else:
				boundary_path = domain_dir / "boundary.u8"
				result_path = domain_dir / "threshold.u8"
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
					str(width),
					"--height",
					str(height),
					"--levels",
					str(levels_csv),
					"--connectivity",
					"4",
				], check=True)

				result = np.fromfile(
					result_path,
					dtype=np.uint8,
				).reshape((height, width))

			domain["runs"] += 1
			write_sparse_domain(
				output_dir,
				result,
				land,
				{
					"grid_row": domain["id"],
					"grid_col": int(domain["zoom"]),
					"width": width,
					"height": height,
				},
				sentinel,
			)

			for adjacency in adjacency_by_domain.get(
				key,
				(),
			):
				target_key, changed = propagate_adjacency(
					key,
					domain,
					result,
					land,
					adjacency,
					domains,
					sentinel,
				)
				if changed:
					boundary_improvements += changed
					queue_domain(target_key)
		finally:
			shutil.rmtree(
				domain_dir,
				ignore_errors=True,
			)

	return {
		"domain_count": len(domains),
		"adjacency_count": len(adjacencies),
		"solver_runs": solver_runs,
		"materializations": materializations,
		"boundary_improvements": boundary_improvements,
		"external_sea_improvements": external_sea_improvements,
		"peak_materialized_cells": peak_materialized_cells,
		"max_fine_width": max_fine_width,
		"max_fine_height": max_fine_height,
		"sentinel_class": sentinel,
		"all_domain_work_deleted": not any(
			work_dir.iterdir()
		),
		"domains": [
			{
				"id": domain["id"],
				"zoom": int(domain["zoom"]),
				"coarse_x0": int(domain["coarse_x0"]),
				"coarse_y0": int(domain["coarse_y0"]),
				"coarse_width": int(domain["coarse_width"]),
				"coarse_height": int(domain["coarse_height"]),
				"fine_width": int(domain["fine_width"]),
				"fine_height": int(domain["fine_height"]),
				"land_cells": (
					0
					if domain["land_cells"] is None
					else int(domain["land_cells"])
				),
				"runs": int(domain["runs"]),
			}
			for domain in sorted(
				domains.values(),
				key=lambda item: int(item["id"]),
			)
		],
	}


def write_report(path, report):
	Path(path).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
