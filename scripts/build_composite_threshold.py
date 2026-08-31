#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path

import numpy as np
from shapely.geometry import shape
from shapely import contains_xy


WEB_MERCATOR_RADIUS = 6378137.0


def lon_to_mercator_x(lon):
	return WEB_MERCATOR_RADIUS * math.radians(lon)


def lat_to_mercator_y(lat):
	return WEB_MERCATOR_RADIUS * math.asinh(
		math.tan(math.radians(lat))
	)


def mercator_x_to_lon(x):
	return math.degrees(x / WEB_MERCATOR_RADIUS)


def mercator_y_to_lat(y):
	return math.degrees(
		math.atan(
			math.sinh(y / WEB_MERCATOR_RADIUS)
		)
	)


def load_grid(path):
	return json.loads(Path(path).read_text(encoding="utf-8"))


def load_core_feature(path):
	data = json.loads(Path(path).read_text(encoding="utf-8"))
	if data.get("type") == "Feature":
		return (
			shape(data["geometry"]),
			data.get("properties", {}),
		)

	return shape(data), {}


def core_mask_chunk(geometry, grid, row_start, row_end):
	cols = np.arange(grid["width"], dtype=np.float64)
	rows = np.arange(row_start, row_end, dtype=np.float64)

	x = grid["left"] + (cols + 0.5) * grid["resolution"]
	y = grid["top"] - (rows + 0.5) * grid["resolution"]

	lon = np.degrees(x / WEB_MERCATOR_RADIUS)
	lat = np.degrees(
		np.arctan(
			np.sinh(y / WEB_MERCATOR_RADIUS)
		)
	)

	return contains_xy(
		geometry,
		lon[None, :],
		lat[:, None],
	)


def build_output_grid(base_meta, fine_zoom):
	base = base_meta["grid"]
	base_zoom = int(base["zoom"])

	if fine_zoom < base_zoom:
		raise ValueError("Fine-Zoom darf nicht kleiner als Base-Zoom sein.")

	factor = 2 ** (fine_zoom - base_zoom)
	resolution = float(base["resolution"]) / factor
	width = int(base["width"]) * factor
	height = int(base["height"]) * factor

	return {
		"zoom": fine_zoom,
		"tile_size": int(base["tile_size"]),
		"x_min": int(base["x_min"]) * factor,
		"x_max": (int(base["x_max"]) + 1) * factor - 1,
		"y_min": int(base["y_min"]) * factor,
		"y_max": (int(base["y_max"]) + 1) * factor - 1,
		"width": width,
		"height": height,
		"cells": width * height,
		"resolution": resolution,
		"left": float(base["left"]),
		"bottom": float(base["bottom"]),
		"right": float(base["right"]),
		"top": float(base["top"]),
	}


def metric_state():
	return {
		"count": 0,
		"equal": 0,
		"abs_sum": 0,
		"max_abs": 0,
		"gt1": 0,
		"gt2": 0,
		"gt5": 0,
	}


def add_metrics(state, fine_values, base_values, mask):
	if not np.any(mask):
		return

	diff = (
		fine_values[mask].astype(np.int16)
		- base_values[mask].astype(np.int16)
	)
	abs_diff = np.abs(diff)

	state["count"] += int(abs_diff.size)
	state["equal"] += int(np.count_nonzero(abs_diff == 0))
	state["abs_sum"] += int(abs_diff.sum())
	state["max_abs"] = max(
		state["max_abs"],
		int(abs_diff.max(initial=0)),
	)
	state["gt1"] += int(np.count_nonzero(abs_diff > 1))
	state["gt2"] += int(np.count_nonzero(abs_diff > 2))
	state["gt5"] += int(np.count_nonzero(abs_diff > 5))


def parent_clip_edge_mask(
	edge,
	fine_grid,
	row_start,
	core_properties,
):
	clipped_sides = core_properties.get("clipped_sides") or {}
	target_bounds = core_properties.get("parent_target_bounds")

	if not target_bounds or not any(clipped_sides.values()):
		return np.zeros_like(edge)

	west, south, east, north = [
		float(value)
		for value in target_bounds
	]
	tolerance = float(fine_grid["resolution"]) * 1.5

	cols = np.arange(fine_grid["width"], dtype=np.float64)
	rows = np.arange(
		row_start,
		row_start + edge.shape[0],
		dtype=np.float64,
	)

	x = (
		float(fine_grid["left"])
		+ (cols + 0.5) * float(fine_grid["resolution"])
	)
	y = (
		float(fine_grid["top"])
		- (rows + 0.5) * float(fine_grid["resolution"])
	)

	clip = np.zeros_like(edge)

	if clipped_sides.get("west"):
		clip |= (
			np.abs(x[None, :] - lon_to_mercator_x(west))
			<= tolerance
		)
	if clipped_sides.get("east"):
		clip |= (
			np.abs(x[None, :] - lon_to_mercator_x(east))
			<= tolerance
		)
	if clipped_sides.get("south"):
		clip |= (
			np.abs(y[:, None] - lat_to_mercator_y(south))
			<= tolerance
		)
	if clipped_sides.get("north"):
		clip |= (
			np.abs(y[:, None] - lat_to_mercator_y(north))
			<= tolerance
		)

	return edge & clip


def collect_edge_outliers(
	outliers,
	fine_values,
	base_values,
	edge,
	fine_grid,
	row_start,
	*,
	edge_kind,
	limit=50,
):
	if not np.any(edge):
		return

	diff = (
		fine_values.astype(np.int16)
		- base_values.astype(np.int16)
	)
	abs_diff = np.abs(diff)
	candidate_mask = edge & (abs_diff > 1)

	if not np.any(candidate_mask):
		return

	rows, cols = np.nonzero(candidate_mask)
	values = abs_diff[rows, cols]

	if values.size > limit:
		selected = np.argpartition(values, -limit)[-limit:]
		rows = rows[selected]
		cols = cols[selected]
		values = values[selected]

	for local_row, col, absolute_difference in zip(
		rows.tolist(),
		cols.tolist(),
		values.tolist(),
	):
		row = row_start + local_row
		x = (
			fine_grid["left"]
			+ (col + 0.5) * fine_grid["resolution"]
		)
		y = (
			fine_grid["top"]
			- (row + 0.5) * fine_grid["resolution"]
		)
		lon = mercator_x_to_lon(x)
		lat = mercator_y_to_lat(y)
		fine_value = int(fine_values[local_row, col])
		base_value = int(base_values[local_row, col])

		outliers.append({
			"edge_kind": edge_kind,
			"abs_diff_m": int(absolute_difference),
			"signed_diff_m": fine_value - base_value,
			"fine_threshold_m": fine_value,
			"base_threshold_m": base_value,
			"lon": round(lon, 8),
			"lat": round(lat, 8),
			"fine_row": int(row),
			"fine_col": int(col),
		})

	outliers.sort(
		key=lambda item: (
			-item["abs_diff_m"],
			-item["signed_diff_m"],
			item["lat"],
			item["lon"],
		)
	)
	del outliers[limit:]


def finish_metrics(state):
	count = state["count"]
	if count == 0:
		return {
			"count": 0,
			"exact_equal_pct": None,
			"mean_abs_diff_m": None,
			"max_abs_diff_m": None,
			"pct_diff_gt_1m": None,
			"pct_diff_gt_2m": None,
			"pct_diff_gt_5m": None,
		}

	return {
		"count": count,
		"exact_equal_pct": round(100.0 * state["equal"] / count, 6),
		"mean_abs_diff_m": round(state["abs_sum"] / count, 6),
		"max_abs_diff_m": state["max_abs"],
		"pct_diff_gt_1m": round(100.0 * state["gt1"] / count, 6),
		"pct_diff_gt_2m": round(100.0 * state["gt2"] / count, 6),
		"pct_diff_gt_5m": round(100.0 * state["gt5"] / count, 6),
	}


def build_composite(
	base_grid_path,
	base_threshold_path,
	fine_grid_path,
	fine_threshold_path,
	core_geojson_path,
	output_dir,
	*,
	chunk_rows=128,
):
	base_meta = load_grid(base_grid_path)
	fine_meta = load_grid(fine_grid_path)
	base_grid = base_meta["grid"]
	fine_grid = fine_meta["grid"]

	base_zoom = int(base_grid["zoom"])
	fine_zoom = int(fine_grid["zoom"])
	if fine_zoom < base_zoom:
		raise ValueError("Fine-Zoom muss >= Base-Zoom sein.")

	factor = 2 ** (fine_zoom - base_zoom)
	expected_resolution = float(base_grid["resolution"]) / factor
	if not math.isclose(
		float(fine_grid["resolution"]),
		expected_resolution,
		rel_tol=0.0,
		abs_tol=1e-7,
	):
		raise ValueError("Fine- und Base-Raster sind nicht hierarchisch ausgerichtet.")

	output_grid = build_output_grid(base_meta, fine_zoom)
	output_dir = Path(output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)

	base = np.memmap(
		base_threshold_path,
		dtype=np.uint8,
		mode="r",
		shape=(base_grid["height"], base_grid["width"]),
	)
	fine = np.memmap(
		fine_threshold_path,
		dtype=np.uint8,
		mode="r",
		shape=(fine_grid["height"], fine_grid["width"]),
	)

	output_path = output_dir / "threshold.u8"
	output = np.memmap(
		output_path,
		dtype=np.uint8,
		mode="w+",
		shape=(output_grid["height"], output_grid["width"]),
	)

	for base_row in range(0, base_grid["height"], chunk_rows):
		base_row_end = min(
			base_grid["height"],
			base_row + chunk_rows,
		)
		block = np.asarray(base[base_row:base_row_end, :])
		upsampled = np.repeat(
			np.repeat(block, factor, axis=0),
			factor,
			axis=1,
		)
		out_row = base_row * factor
		output[
			out_row:out_row + upsampled.shape[0],
			:,
		] = upsampled

	output.flush()

	fine_col0 = int(round(
		(float(fine_grid["left"]) - output_grid["left"])
		/ output_grid["resolution"]
	))
	fine_row0 = int(round(
		(output_grid["top"] - float(fine_grid["top"]))
		/ output_grid["resolution"]
	))
	fine_col1 = fine_col0 + int(fine_grid["width"])
	fine_row1 = fine_row0 + int(fine_grid["height"])

	if (
		fine_col0 < 0
		or fine_row0 < 0
		or fine_col1 > output_grid["width"]
		or fine_row1 > output_grid["height"]
	):
		raise ValueError("Fine-Workarea liegt nicht vollständig im Base-Raster.")

	core, core_properties = load_core_feature(core_geojson_path)
	core_metrics = metric_state()
	edge_metrics = metric_state()
	source_seam_metrics = metric_state()
	parent_clip_metrics = metric_state()
	edge_outliers = []
	source_seam_outliers = []
	parent_clip_outliers = []
	written = 0

	for fine_row in range(0, fine_grid["height"], chunk_rows):
		fine_row_end = min(
			fine_grid["height"],
			fine_row + chunk_rows,
		)
		mask = core_mask_chunk(
			core,
			fine_grid,
			fine_row,
			fine_row_end,
		)

		if not np.any(mask):
			continue

		out_row0 = fine_row0 + fine_row
		out_row1 = fine_row0 + fine_row_end

		base_values = np.asarray(
			output[
				out_row0:out_row1,
				fine_col0:fine_col1,
			]
		)
		fine_values = np.asarray(
			fine[fine_row:fine_row_end, :]
		)

		add_metrics(
			core_metrics,
			fine_values,
			base_values,
			mask,
		)

		# Innerer 4er-Rand der Core-Maske für Seam-QA.
		extended_start = max(0, fine_row - 1)
		extended_end = min(
			fine_grid["height"],
			fine_row_end + 1,
		)
		extended = core_mask_chunk(
			core,
			fine_grid,
			extended_start,
			extended_end,
		)

		local_start = fine_row - extended_start
		local_end = local_start + (fine_row_end - fine_row)
		center = extended[local_start:local_end, :]

		up = np.zeros_like(center)
		down = np.zeros_like(center)
		left = np.zeros_like(center)
		right = np.zeros_like(center)

		if fine_row > 0:
			up[:] = extended[local_start - 1:local_end - 1, :]
		if fine_row_end < fine_grid["height"]:
			down[:] = extended[local_start + 1:local_end + 1, :]

		left[:, 1:] = center[:, :-1]
		right[:, :-1] = center[:, 1:]

		edge = center & ~(up & down & left & right)
		parent_clip_edge = parent_clip_edge_mask(
			edge,
			fine_grid,
			fine_row,
			core_properties,
		)
		source_seam_edge = edge & ~parent_clip_edge

		add_metrics(
			edge_metrics,
			fine_values,
			base_values,
			edge,
		)
		add_metrics(
			source_seam_metrics,
			fine_values,
			base_values,
			source_seam_edge,
		)
		add_metrics(
			parent_clip_metrics,
			fine_values,
			base_values,
			parent_clip_edge,
		)

		collect_edge_outliers(
			edge_outliers,
			fine_values,
			base_values,
			edge,
			fine_grid,
			fine_row,
			edge_kind="all_core_edge",
		)
		collect_edge_outliers(
			source_seam_outliers,
			fine_values,
			base_values,
			source_seam_edge,
			fine_grid,
			fine_row,
			edge_kind="source_coverage_seam",
		)
		collect_edge_outliers(
			parent_clip_outliers,
			fine_values,
			base_values,
			parent_clip_edge,
			fine_grid,
			fine_row,
			edge_kind="parent_clip_boundary",
		)

		target = output[
			out_row0:out_row1,
			fine_col0:fine_col1,
		]
		target[mask] = fine_values[mask]
		written += int(np.count_nonzero(mask))

	output.flush()

	grid_metadata = {
		"config": {
			"name": "hierarchical-composite",
			"bounds": base_meta.get("config", {}).get("bounds"),
			"base_grid": str(base_grid_path),
			"fine_grid": str(fine_grid_path),
			"core_geojson": str(core_geojson_path),
		},
		"grid": output_grid,
		"composite": {
			"base_zoom": base_zoom,
			"fine_zoom": fine_zoom,
			"factor": factor,
			"fine_pixel_offset": [fine_col0, fine_row0],
			"fine_pixels_written": written,
		},
	}

	(output_dir / "grid.json").write_text(
		json.dumps(grid_metadata, indent=2) + "\n",
		encoding="utf-8",
	)

	report = {
		"base_zoom": base_zoom,
		"fine_zoom": fine_zoom,
		"factor": factor,
		"output_shape": [
			output_grid["height"],
			output_grid["width"],
		],
		"output_cells": output_grid["cells"],
		"fine_pixels_written": written,
		"core_vs_upsampled_base": finish_metrics(core_metrics),
		"core_edge_vs_upsampled_base": finish_metrics(edge_metrics),
		"source_coverage_seam_vs_upsampled_base": finish_metrics(
			source_seam_metrics
		),
		"parent_clip_boundary_vs_upsampled_base": finish_metrics(
			parent_clip_metrics
		),
		"core_edge_top_outliers": edge_outliers,
		"source_coverage_seam_top_outliers": source_seam_outliers,
		"parent_clip_boundary_top_outliers": parent_clip_outliers,
	}

	(output_dir / "report.json").write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)

	return report


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--base-grid", required=True)
	parser.add_argument("--base-threshold", required=True)
	parser.add_argument("--fine-grid", required=True)
	parser.add_argument("--fine-threshold", required=True)
	parser.add_argument("--core-geojson", required=True)
	parser.add_argument("--output-dir", required=True)
	parser.add_argument("--chunk-rows", type=int, default=128)
	args = parser.parse_args()

	if args.chunk_rows <= 0:
		parser.error("--chunk-rows muss > 0 sein.")

	report = build_composite(
		args.base_grid,
		args.base_threshold,
		args.fine_grid,
		args.fine_threshold,
		args.core_geojson,
		args.output_dir,
		chunk_rows=args.chunk_rows,
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
