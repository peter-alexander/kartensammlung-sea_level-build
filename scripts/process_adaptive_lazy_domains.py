#!/usr/bin/env python3

import hashlib
import json
import os
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


CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINT_SIDES = ("top", "bottom", "left", "right")


def checkpoint_signature(domain_specs, levels_csv):
	payload = {
		"levels": str(levels_csv),
		"domains": [
			{
				key: int(domain[key])
				for key in (
					"id",
					"zoom",
					"coarse_x0",
					"coarse_y0",
					"coarse_width",
					"coarse_height",
					"fine_pixels_per_coarse_cell",
					"fine_width",
					"fine_height",
				)
			}
			for domain in domain_specs
		],
	}
	encoded = json.dumps(
		payload,
		sort_keys=True,
		separators=(",", ":"),
	).encode("utf-8")
	return hashlib.sha256(encoded).hexdigest()


def save_checkpoint(
	path,
	domains,
	queue,
	*,
	signature,
	counters,
	completed=False,
):
	if path is None:
		return

	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)

	ordered = sorted(
		domains.values(),
		key=lambda item: int(item["id"]),
	)
	incoming = np.concatenate([
		domain["incoming"][side]
		for domain in ordered
		for side in CHECKPOINT_SIDES
	]).astype(np.uint8, copy=False)
	runs = np.asarray(
		[int(domain["runs"]) for domain in ordered],
		dtype=np.int64,
	)
	land_cells = np.asarray(
		[
			-1
			if domain["land_cells"] is None
			else int(domain["land_cells"])
			for domain in ordered
		],
		dtype=np.int64,
	)
	queue_ids = np.asarray(
		[int(key) for key in queue],
		dtype=np.int64,
	)
	metadata = {
		"schema_version": CHECKPOINT_SCHEMA_VERSION,
		"signature": signature,
		"completed": bool(completed),
		"counters": {
			key: int(value)
			for key, value in counters.items()
		},
	}

	tmp = path.with_name(path.name + ".tmp")
	with tmp.open("wb") as target:
		np.savez_compressed(
			target,
			metadata=np.asarray(
				json.dumps(metadata),
				dtype=np.str_,
			),
			incoming=incoming,
			runs=runs,
			land_cells=land_cells,
			queue=queue_ids,
		)
	os.replace(tmp, path)


def load_checkpoint(
	path,
	domains,
	*,
	expected_signature,
):
	path = Path(path)
	with np.load(path, allow_pickle=False) as data:
		metadata = json.loads(str(data["metadata"]))
		if int(metadata.get("schema_version", -1)) != (
			CHECKPOINT_SCHEMA_VERSION
		):
			raise ValueError(
				"Unbekannte adaptive Checkpoint-Version."
			)
		if metadata.get("signature") != expected_signature:
			raise ValueError(
				"Adaptive Checkpoint passt nicht zu Domainplan "
				"oder Threshold-Klassen."
			)

		ordered = sorted(
			domains.values(),
			key=lambda item: int(item["id"]),
		)
		runs = np.asarray(data["runs"], dtype=np.int64)
		land_cells = np.asarray(
			data["land_cells"],
			dtype=np.int64,
		)
		incoming = np.asarray(
			data["incoming"],
			dtype=np.uint8,
		)
		queue_ids = np.asarray(
			data["queue"],
			dtype=np.int64,
		)

	if runs.size != len(ordered) or land_cells.size != len(ordered):
		raise ValueError(
			"Adaptive Checkpoint hat falsche Domainanzahl."
		)

	offset = 0
	for index, domain in enumerate(ordered):
		for side in CHECKPOINT_SIDES:
			target = domain["incoming"][side]
			end = offset + target.size
			if end > incoming.size:
				raise ValueError(
					"Adaptive Checkpoint endet innerhalb der "
					"Boundary-Daten."
				)
			target[:] = incoming[offset:end]
			offset = end

		domain["runs"] = int(runs[index])
		value = int(land_cells[index])
		domain["land_cells"] = (
			None if value < 0 else value
		)

	if offset != incoming.size:
		raise ValueError(
			"Adaptive Checkpoint enthält überschüssige "
			"Boundary-Daten."
		)

	queue = deque(int(value) for value in queue_ids)
	for key in queue:
		if key not in domains:
			raise ValueError(
				f"Checkpoint-Queue enthält unbekannte Domain {key}."
			)

	return {
		"queue": queue,
		"completed": bool(metadata.get("completed", False)),
		"counters": {
			key: int(value)
			for key, value in metadata.get(
				"counters",
				{},
			).items()
		},
	}


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


def build_external_sea_allow_masks(
	domains,
	adjacency_by_domain,
):
	masks = {}
	excluded = 0

	for key, domain in domains.items():
		width = int(domain["fine_width"])
		height = int(domain["fine_height"])
		allowed = {
			"top": np.ones(width, dtype=bool),
			"bottom": np.ones(width, dtype=bool),
			"left": np.ones(height, dtype=bool),
			"right": np.ones(height, dtype=bool),
		}

		for adjacency in adjacency_by_domain.get(key, ()):
			if adjacency["a"] == key:
				side = adjacency["a_side"]
			else:
				side = adjacency["b_side"]

			start = side_offset(
				domain,
				side,
				adjacency["coarse_start"],
			)
			end = side_offset(
				domain,
				side,
				adjacency["coarse_end"],
			)
			excluded += int(
				np.count_nonzero(
					allowed[side][start:end]
				)
			)
			allowed[side][start:end] = False

		masks[key] = allowed

	return masks, excluded


def filter_external_sea(external_sea, allowed):
	if not external_sea:
		return None

	result = {}
	for side, allow in allowed.items():
		values = external_sea.get(side)
		if values is None:
			continue

		values = np.asarray(values, dtype=bool)
		if values.shape != allow.shape:
			raise ValueError(
				f"External-Sea-Länge passt nicht für {side}: "
				f"{values.shape} != {allow.shape}"
			)
		result[side] = values & allow

	return result


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
	checkpoint_path=None,
	checkpoint_every_runs=0,
	resume=False,
	max_runs_this_invocation=0,
	write_outputs_during_convergence=True,
	initial_domain_ids=None,
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

	checkpoint_every_runs = int(checkpoint_every_runs)
	max_runs_this_invocation = int(max_runs_this_invocation)
	if checkpoint_every_runs < 0:
		raise ValueError("checkpoint_every_runs muss >= 0 sein.")
	if max_runs_this_invocation < 0:
		raise ValueError(
			"max_runs_this_invocation muss >= 0 sein."
		)
	if resume and checkpoint_path is None:
		raise ValueError(
			"resume benötigt einen checkpoint_path."
		)

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

	signature = checkpoint_signature(
		[
			{
				**domain,
				"id": int(domain["id"]),
			}
			for domain in sorted(
				domains.values(),
				key=lambda item: int(item["id"]),
			)
		],
		levels_csv,
	)

	adjacencies, adjacency_by_domain = build_adjacencies(
		domains
	)
	(
		external_sea_allow_masks,
		internal_edge_pixels_excluded_from_external_sea,
	) = build_external_sea_allow_masks(
		domains,
		adjacency_by_domain,
	)

	work_dir = Path(work_dir)
	shutil.rmtree(work_dir, ignore_errors=True)
	work_dir.mkdir(parents=True, exist_ok=True)

	output_dir = Path(output_dir)
	if not resume:
		shutil.rmtree(output_dir, ignore_errors=True)
	output_dir.mkdir(parents=True, exist_ok=True)

	counters = {
		"solver_runs": 0,
		"materializations": 0,
		"boundary_improvements": 0,
		"external_sea_improvements": 0,
		"peak_materialized_cells": 0,
		"max_fine_width": 0,
		"max_fine_height": 0,
		"finalization_materializations": 0,
	}

	if resume:
		checkpoint = load_checkpoint(
			checkpoint_path,
			domains,
			expected_signature=signature,
		)
		queue = checkpoint["queue"]
		for key, value in checkpoint["counters"].items():
			if key in counters:
				counters[key] = int(value)
		checkpoint_completed = checkpoint["completed"]
	else:
		if initial_domain_ids is None:
			queue = deque(domains.keys())
		else:
			initial_keys = []
			seen_initial = set()
			for value in initial_domain_ids:
				key = int(value)
				if key not in domains:
					raise ValueError(
						f"Unbekannte initiale Domain {key}."
					)
				if key in seen_initial:
					continue
				seen_initial.add(key)
				initial_keys.append(key)
			if not initial_keys:
				raise ValueError(
					"initial_domain_ids darf nicht leer sein."
				)
			queue = deque(initial_keys)
		checkpoint_completed = False

	queued = set(queue)
	runs_this_invocation = 0

	def queue_domain(key):
		if key not in domains or key in queued:
			return
		queue.append(key)
		queued.add(key)

	while queue:
		key = queue.popleft()
		queued.remove(key)
		domain = domains[key]

		counters["solver_runs"] += 1
		runs_this_invocation += 1
		if counters["solver_runs"] > max_solver_runs:
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
			counters["materializations"] += 1

			width = int(domain["fine_width"])
			height = int(domain["fine_height"])
			cells = width * height
			counters["peak_materialized_cells"] = max(
				counters["peak_materialized_cells"],
				cells,
			)
			counters["max_fine_width"] = max(counters["max_fine_width"], width)
			counters["max_fine_height"] = max(counters["max_fine_height"], height)

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

			counters["external_sea_improvements"] += (
				apply_external_sea_seeds(
					domain,
					land,
					filter_external_sea(
						meta.get("external_sea"),
						external_sea_allow_masks[key],
					),
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
			if write_outputs_during_convergence:
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
					counters["boundary_improvements"] += changed
					queue_domain(target_key)
		finally:
			shutil.rmtree(
				domain_dir,
				ignore_errors=True,
			)

		should_checkpoint = (
			checkpoint_path is not None
			and checkpoint_every_runs > 0
			and counters["solver_runs"] % checkpoint_every_runs == 0
		)
		should_pause = (
			max_runs_this_invocation > 0
			and runs_this_invocation >= max_runs_this_invocation
			and bool(queue)
		)
		if should_checkpoint or should_pause:
			save_checkpoint(
				checkpoint_path,
				domains,
				queue,
				signature=signature,
				counters=counters,
				completed=False,
			)
		if should_pause:
			return {
				"status": "paused",
				"completed": False,
				"checkpoint_path": str(checkpoint_path),
				"queue_remaining": len(queue),
				"initial_domain_count": (
					len(domains)
					if initial_domain_ids is None
					else len({
						int(value)
						for value in initial_domain_ids
					})
				),
				"domain_count": len(domains),
				"adjacency_count": len(adjacencies),
				**counters,
				"internal_edge_pixels_excluded_from_external_sea": (
					internal_edge_pixels_excluded_from_external_sea
				),
				"sentinel_class": sentinel,
				"all_domain_work_deleted": not any(
					work_dir.iterdir()
				),
			}

	# Bei deaktivierter Zwischenausgabe werden die endgültigen
	# Threshold-Domains erst nach Konvergenz einmal sauber erzeugt.
	if not write_outputs_during_convergence:
		for key in sorted(
			domains,
			key=lambda item: int(domains[item]["id"]),
		):
			domain = domains[key]
			domain_dir = (
				work_dir
				/ f"final-domain-{domain['id']}"
			)
			shutil.rmtree(
				domain_dir,
				ignore_errors=True,
			)
			domain_dir.mkdir(parents=True)
			try:
				meta = materialize_domain(
					domain,
					domain_dir,
				)
				counters["materializations"] += 1
				counters["finalization_materializations"] += 1

				width = int(domain["fine_width"])
				height = int(domain["fine_height"])
				cells = width * height
				counters["peak_materialized_cells"] = max(
					counters["peak_materialized_cells"],
					cells,
				)
				counters["max_fine_width"] = max(
					counters["max_fine_width"],
					width,
				)
				counters["max_fine_height"] = max(
					counters["max_fine_height"],
					height,
				)

				elevation_path = Path(
					meta["elevation_path"]
				)
				sea_path = Path(meta["sea_mask_path"])
				land_path = Path(meta["land_mask_path"])
				land = np.fromfile(
					land_path,
					dtype=np.uint8,
				).reshape((height, width)) != 0
				sea = np.fromfile(
					sea_path,
					dtype=np.uint8,
				).reshape((height, width))

				external = filter_external_sea(
					meta.get("external_sea"),
					external_sea_allow_masks[key],
				)
				apply_external_sea_seeds(
					domain,
					land,
					external,
					sentinel,
				)

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

				has_sea = bool(np.any(sea != 0))
				has_boundary = any(
					np.any(values < sentinel)
					for values in domain[
						"incoming"
					].values()
				)
				if int(np.count_nonzero(land)) == 0 or not (
					has_sea or has_boundary
				):
					result = np.full(
						(height, width),
						sentinel,
						dtype=np.uint8,
					)
				else:
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
			finally:
				shutil.rmtree(
					domain_dir,
					ignore_errors=True,
				)

	if checkpoint_path is not None:
		save_checkpoint(
			checkpoint_path,
			domains,
			queue,
			signature=signature,
			counters=counters,
			completed=True,
		)

	return {
		"status": "complete",
		"completed": True,
		"checkpoint_path": (
			str(checkpoint_path)
			if checkpoint_path is not None
			else None
		),
		"queue_remaining": 0,
		"initial_domain_count": (
			len(domains)
			if initial_domain_ids is None
			else len({
				int(value)
				for value in initial_domain_ids
			})
		),
		"domain_count": len(domains),
		"adjacency_count": len(adjacencies),
		"solver_runs": counters["solver_runs"],
		"materializations": counters["materializations"],
		"finalization_materializations": (
			counters["finalization_materializations"]
		),
		"boundary_improvements": counters["boundary_improvements"],
		"external_sea_improvements": counters["external_sea_improvements"],
		"internal_edge_pixels_excluded_from_external_sea": (
			internal_edge_pixels_excluded_from_external_sea
		),
		"peak_materialized_cells": counters["peak_materialized_cells"],
		"max_fine_width": counters["max_fine_width"],
		"max_fine_height": counters["max_fine_height"],
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
