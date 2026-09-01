#!/usr/bin/env python3

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union
from shapely.prepared import prep

from coverage_planner import plan as build_coverage_plan
from prepare_candidate_work_region import (
	WEB_MERCATOR_RADIUS,
	component_work_geometry,
	find_component,
	read_component_spans,
)


def lonlat_to_mercator(geometry):
	def convert(lon, lat, z=None):
		lon = np.asarray(lon, dtype=np.float64)
		lat = np.asarray(lat, dtype=np.float64)
		x = WEB_MERCATOR_RADIUS * np.radians(lon)
		y = WEB_MERCATOR_RADIUS * np.arcsinh(
			np.tan(np.radians(lat))
		)
		if z is None:
			return x, y
		return x, y, z

	return transform(convert, geometry)


def source_groups(source_features, core_geometry):
	groups = defaultdict(list)
	properties = {}

	for feature in source_features:
		geometry_data = feature.get("geometry")
		if not geometry_data:
			continue

		props = feature.get("properties", {})
		zoom = props.get("source_fidelity_processing_zoom")
		if zoom is None:
			continue

		geometry = lonlat_to_mercator(
			shape(geometry_data)
		).intersection(core_geometry)
		if geometry.is_empty:
			continue

		key = (
			str(props.get("source") or ""),
			int(zoom),
		)
		groups[key].append(geometry)
		properties[key] = {
			"source": props.get("source"),
			"name": props.get("name"),
			"resolution_m": props.get("resolution_m"),
			"source_fidelity_processing_zoom": int(zoom),
		}

	result = []
	for key, geometries in groups.items():
		geometry = unary_union(geometries)
		if not geometry.is_valid:
			geometry = geometry.buffer(0)
		if geometry.is_empty:
			continue

		result.append({
			**properties[key],
			"geometry": geometry,
			"prepared": prep(geometry),
		})

	result.sort(
		key=lambda item: (
			-int(item["source_fidelity_processing_zoom"]),
			float(item["resolution_m"])
				if item["resolution_m"] is not None
				else math.inf,
			str(item["source"] or ""),
		)
	)
	return result


def assign_cells(
	component,
	spans,
	parent_grid,
	source_items,
	*,
	factor,
	base_zoom,
):
	min_col, min_row, max_col, max_row = (
		int(value)
		for value in component["bbox_cells"]
	)
	width = max_col - min_col + 1
	height = max_row - min_row + 1
	assignment = np.zeros(
		(height, width),
		dtype=np.int16,
	)
	source_assignment = np.empty(
		(height, width),
		dtype=object,
	)
	source_assignment[:] = None

	coarse_resolution = (
		float(parent_grid["resolution"])
		* int(factor)
	)
	left = float(parent_grid["left"])
	top = float(parent_grid["top"])
	source_counts = Counter()

	for row, span_left, span_right in spans:
		row = int(row)
		for col in range(
			int(span_left),
			int(span_right) + 1,
		):
			x0 = left + col * coarse_resolution
			x1 = x0 + coarse_resolution
			y1 = top - row * coarse_resolution
			y0 = y1 - coarse_resolution
			cell = box(x0, y0, x1, y1)

			selected = None
			for source in source_items:
				if source["prepared"].intersects(cell):
					selected = source
					break

			if selected is None:
				zoom = int(base_zoom)
				source = "base-fallback"
			else:
				zoom = int(
					selected[
						"source_fidelity_processing_zoom"
					]
				)
				source = str(
					selected.get("source")
					or "unknown"
				)

			local_row = row - min_row
			local_col = col - min_col
			assignment[local_row, local_col] = zoom
			source_assignment[
				local_row,
				local_col,
			] = source
			source_counts[(zoom, source)] += 1

	return {
		"assignment": assignment,
		"source_assignment": source_assignment,
		"bbox_origin_col": min_col,
		"bbox_origin_row": min_row,
		"source_counts": source_counts,
	}


def pack_zoom_rectangles(
	assignment,
	zoom,
	*,
	origin_col,
	origin_row,
	scale,
	domain_pixels,
):
	target = assignment == int(zoom)
	visited = np.zeros(
		target.shape,
		dtype=bool,
	)
	max_coarse_side = max(
		1,
		int(domain_pixels) // int(scale),
	)
	domains = []

	height, width = target.shape
	for row in range(height):
		col = 0
		while col < width:
			if not target[row, col] or visited[row, col]:
				col += 1
				continue

			rect_width = 1
			while (
				rect_width < max_coarse_side
				and col + rect_width < width
				and target[row, col + rect_width]
				and not visited[row, col + rect_width]
			):
				rect_width += 1

			rect_height = 1
			while (
				rect_height < max_coarse_side
				and row + rect_height < height
			):
				slice_target = target[
					row + rect_height,
					col:col + rect_width,
				]
				slice_visited = visited[
					row + rect_height,
					col:col + rect_width,
				]
				if not (
					np.all(slice_target)
					and not np.any(slice_visited)
				):
					break
				rect_height += 1

			visited[
				row:row + rect_height,
				col:col + rect_width,
			] = True

			domains.append({
				"zoom": int(zoom),
				"coarse_x0": int(
					origin_col + col
				),
				"coarse_y0": int(
					origin_row + row
				),
				"coarse_width": int(rect_width),
				"coarse_height": int(rect_height),
				"coarse_cells": int(
					rect_width * rect_height
				),
				"fine_pixels_per_coarse_cell": int(scale),
				"fine_width": int(
					rect_width * scale
				),
				"fine_height": int(
					rect_height * scale
				),
				"fine_cells": int(
					rect_width
					* rect_height
					* scale
					* scale
				),
			})

			col += rect_width

	return domains


def adaptive_plan(
	components_report_path,
	spans_path,
	parent_grid_path,
	component_id,
	*,
	factor,
	cache_dir,
	coverage_zoom=8,
	coverage_context_tiles=1,
	workers=12,
	domain_pixels=512,
):
	report = json.loads(
		Path(components_report_path).read_text(
			encoding="utf-8"
		)
	)
	parent_grid = json.loads(
		Path(parent_grid_path).read_text(
			encoding="utf-8"
		)
	)["grid"]
	component = find_component(report, component_id)
	spans = read_component_spans(
		spans_path,
		component,
	)
	core_mercator, core_lonlat = component_work_geometry(
		component,
		spans,
		parent_grid,
		coarse_width=int(report["width"]),
		coarse_height=int(report["height"]),
		factor=factor,
		halo_coarse_cells=0,
	)

	coverage = build_coverage_plan(
		tuple(float(v) for v in core_lonlat.bounds),
		coverage_zoom=coverage_zoom,
		coverage_context_tiles=coverage_context_tiles,
		cache_dir=cache_dir,
		workers=workers,
	)
	base_zoom = int(
		coverage["plan"]["base"][
			"recommended_processing_zoom_at_bbox_center"
		]
	)
	sources = source_groups(
		coverage["source_features"],
		core_mercator,
	)

	assigned = assign_cells(
		component,
		spans,
		parent_grid,
		sources,
		factor=factor,
		base_zoom=base_zoom,
	)
	assignment = assigned["assignment"]
	parent_zoom = int(parent_grid["zoom"])

	zoom_counts = Counter(
		int(value)
		for value in assignment.reshape(-1)
		if int(value) > 0
	)
	adaptive_fine_cells = 0
	uniform_max_zoom = max(zoom_counts)
	uniform_scale = (
		int(factor)
		* 2 ** (uniform_max_zoom - parent_zoom)
	)
	uniform_core_fine_cells = (
		int(component["cells"])
		* uniform_scale
		* uniform_scale
	)

	domains = []
	domain_counts = {}
	for zoom in sorted(zoom_counts):
		scale = (
			int(factor)
			* 2 ** (int(zoom) - parent_zoom)
		)
		cell_count = int(zoom_counts[zoom])
		adaptive_fine_cells += (
			cell_count * scale * scale
		)

		zoom_domains = pack_zoom_rectangles(
			assignment,
			zoom,
			origin_col=assigned["bbox_origin_col"],
			origin_row=assigned["bbox_origin_row"],
			scale=scale,
			domain_pixels=domain_pixels,
		)
		domain_counts[str(zoom)] = len(
			zoom_domains
		)
		domains.extend(zoom_domains)

	source_counts = [
		{
			"zoom": int(zoom),
			"source": source,
			"coarse_cells": int(count),
			"pct_of_component": (
				float(count)
				* 100.0
				/ float(component["cells"])
			),
		}
		for (zoom, source), count
		in sorted(
			assigned["source_counts"].items(),
			key=lambda item: (
				-item[0][0],
				item[0][1],
			),
		)
	]

	return {
		"schema_version": 1,
		"strategy": (
			"factor-grid source-fidelity assignment; any source "
			"intersection raises a coarse planning cell to that "
			"source zoom; equal-zoom cells are greedily packed "
			"into rectangular numerical domains"
		),
		"component_id": int(component["id"]),
		"component_rank": int(component["rank"]),
		"component_coarse_cells": int(component["cells"]),
		"parent_zoom": parent_zoom,
		"coarse_factor": int(factor),
		"base_zoom": base_zoom,
		"max_source_fidelity_zoom": int(
			uniform_max_zoom
		),
		"domain_pixels": int(domain_pixels),
		"zoom_coarse_cell_counts": {
			str(zoom): int(count)
			for zoom, count in sorted(
				zoom_counts.items()
			)
		},
		"source_coarse_cell_counts": source_counts,
		"adaptive_core_fine_cells": int(
			adaptive_fine_cells
		),
		"uniform_max_zoom_core_fine_cells": int(
			uniform_core_fine_cells
		),
		"adaptive_vs_uniform_cell_ratio": (
			float(adaptive_fine_cells)
			/ float(uniform_core_fine_cells)
		),
		"estimated_cell_reduction_factor": (
			float(uniform_core_fine_cells)
			/ float(adaptive_fine_cells)
		),
		"domain_count": len(domains),
		"domain_counts_by_zoom": domain_counts,
		"domains": domains,
	}


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Plant adaptive Source-Fidelity-Domains innerhalb "
			"einer sicheren groben RLE-Work-Region."
		)
	)
	parser.add_argument("--components-report", required=True)
	parser.add_argument("--spans", required=True)
	parser.add_argument("--parent-grid", required=True)
	parser.add_argument("--component-id", type=int, required=True)
	parser.add_argument("--factor", type=int, required=True)
	parser.add_argument("--cache-dir", default="cache")
	parser.add_argument("--coverage-zoom", type=int, default=8)
	parser.add_argument(
		"--coverage-context-tiles",
		type=int,
		default=1,
	)
	parser.add_argument("--workers", type=int, default=12)
	parser.add_argument("--domain-pixels", type=int, default=512)
	parser.add_argument("--output", required=True)
	args = parser.parse_args()

	result = adaptive_plan(
		args.components_report,
		args.spans,
		args.parent_grid,
		args.component_id,
		factor=args.factor,
		cache_dir=args.cache_dir,
		coverage_zoom=args.coverage_zoom,
		coverage_context_tiles=(
			args.coverage_context_tiles
		),
		workers=args.workers,
		domain_pixels=args.domain_pixels,
	)

	Path(args.output).write_text(
		json.dumps(result, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps({
		key: result[key]
		for key in (
			"component_id",
			"component_coarse_cells",
			"max_source_fidelity_zoom",
			"zoom_coarse_cell_counts",
			"source_coarse_cell_counts",
			"adaptive_core_fine_cells",
			"uniform_max_zoom_core_fine_cells",
			"estimated_cell_reduction_factor",
			"domain_count",
			"domain_counts_by_zoom",
		)
	}, indent=2))


if __name__ == "__main__":
	main()
