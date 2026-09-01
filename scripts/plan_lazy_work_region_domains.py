#!/usr/bin/env python3

import argparse
import json
import math
import struct
from pathlib import Path

from grid import grid_from_config, load_config


SPAN_RECORD_BYTES = 12


def find_component(report, component_id):
	for component in report["components"]:
		if int(component["id"]) == int(component_id):
			return component
	raise ValueError(
		f"Component-ID {component_id} wurde nicht gefunden."
	)


def read_component_spans(path, component):
	offset_records = int(component["span_offset_records"])
	span_count = int(component["span_count"])
	result = []

	with Path(path).open("rb") as source:
		source.seek(offset_records * SPAN_RECORD_BYTES)
		for _ in range(span_count):
			raw = source.read(SPAN_RECORD_BYTES)
			if len(raw) != SPAN_RECORD_BYTES:
				raise RuntimeError(
					"Span-Datei endet innerhalb der Component."
				)
			result.append(struct.unpack("<III", raw))

	return result


def require_integer_scale(parent_grid, fine_grid, coarse_factor):
	coarse_resolution = (
		float(parent_grid["resolution"])
		* int(coarse_factor)
	)
	scale = coarse_resolution / float(fine_grid["resolution"])
	rounded = int(round(scale))

	if rounded <= 0 or not math.isclose(
		scale,
		rounded,
		rel_tol=0.0,
		abs_tol=1e-8,
	):
		raise ValueError(
			"Coarse- und Fine-Raster sind nicht hierarchisch "
			"ganzzahlig ausgerichtet."
		)

	return rounded


def coarse_span_to_fine_rect(
	row,
	left,
	right,
	parent_grid,
	fine_grid,
	*,
	coarse_factor,
):
	parent_resolution = float(parent_grid["resolution"])
	coarse_resolution = (
		parent_resolution * int(coarse_factor)
	)
	fine_resolution = float(fine_grid["resolution"])

	world_left = (
		float(parent_grid["left"])
		+ int(left) * coarse_resolution
	)
	world_right = (
		float(parent_grid["left"])
		+ (int(right) + 1) * coarse_resolution
	)
	world_top = (
		float(parent_grid["top"])
		- int(row) * coarse_resolution
	)
	world_bottom = (
		float(parent_grid["top"])
		- (int(row) + 1) * coarse_resolution
	)

	x0 = int(round(
		(world_left - float(fine_grid["left"]))
		/ fine_resolution
	))
	x1 = int(round(
		(world_right - float(fine_grid["left"]))
		/ fine_resolution
	))
	y0 = int(round(
		(float(fine_grid["top"]) - world_top)
		/ fine_resolution
	))
	y1 = int(round(
		(float(fine_grid["top"]) - world_bottom)
		/ fine_resolution
	))

	x0 = max(0, x0)
	y0 = max(0, y0)
	x1 = min(int(fine_grid["width"]), x1)
	y1 = min(int(fine_grid["height"]), y1)

	if x1 <= x0 or y1 <= y0:
		return None

	return x0, y0, x1, y1


def plan_domains_from_grids(
	component,
	spans,
	parent_grid,
	fine_grid,
	*,
	coarse_factor,
	domain_width,
	domain_height,
):
	coarse_factor = int(coarse_factor)
	domain_width = int(domain_width)
	domain_height = int(domain_height)

	if coarse_factor <= 0:
		raise ValueError("coarse_factor muss > 0 sein.")
	if domain_width <= 0 or domain_height <= 0:
		raise ValueError(
			"domain_width und domain_height müssen > 0 sein."
		)

	fine_per_coarse = require_integer_scale(
		parent_grid,
		fine_grid,
		coarse_factor,
	)

	active = set()
	fine_rectangles = []

	for row, left, right in spans:
		rect = coarse_span_to_fine_rect(
			row,
			left,
			right,
			parent_grid,
			fine_grid,
			coarse_factor=coarse_factor,
		)
		if rect is None:
			continue

		x0, y0, x1, y1 = rect
		fine_rectangles.append(rect)

		domain_col0 = x0 // domain_width
		domain_col1 = (x1 - 1) // domain_width
		domain_row0 = y0 // domain_height
		domain_row1 = (y1 - 1) // domain_height

		for grid_row in range(
			domain_row0,
			domain_row1 + 1,
		):
			for grid_col in range(
				domain_col0,
				domain_col1 + 1,
			):
				active.add((grid_row, grid_col))

	domains = []
	for grid_row, grid_col in sorted(active):
		x0 = grid_col * domain_width
		y0 = grid_row * domain_height
		width = min(
			domain_width,
			int(fine_grid["width"]) - x0,
		)
		height = min(
			domain_height,
			int(fine_grid["height"]) - y0,
		)
		if width <= 0 or height <= 0:
			continue

		domains.append({
			"grid_row": grid_row,
			"grid_col": grid_col,
			"x0": x0,
			"y0": y0,
			"width": width,
			"height": height,
		})

	full_domain_cols = math.ceil(
		int(fine_grid["width"]) / domain_width
	)
	full_domain_rows = math.ceil(
		int(fine_grid["height"]) / domain_height
	)
	full_domain_count = (
		full_domain_cols * full_domain_rows
	)

	return {
		"component_id": int(component["id"]),
		"component_rank": int(component["rank"]),
		"component_cells_coarse": int(component["cells"]),
		"component_span_count": int(component["span_count"]),
		"coarse_factor": coarse_factor,
		"fine_pixels_per_coarse_cell": fine_per_coarse,
		"fine_grid": fine_grid,
		"domain_width": domain_width,
		"domain_height": domain_height,
		"full_bbox_domain_count": full_domain_count,
		"active_domain_count": len(domains),
		"active_domain_fraction": (
			0.0
			if full_domain_count == 0
			else len(domains) / full_domain_count
		),
		"domains": domains,
	}


def plan_domains(
	components_report_path,
	spans_path,
	component_id,
	parent_grid_path,
	fine_config_path,
	*,
	coarse_factor,
	domain_width,
	domain_height,
):
	report = json.loads(
		Path(components_report_path).read_text(
			encoding="utf-8"
		)
	)
	component = find_component(
		report,
		component_id,
	)
	spans = read_component_spans(
		spans_path,
		component,
	)
	parent_grid = json.loads(
		Path(parent_grid_path).read_text(
			encoding="utf-8"
		)
	)["grid"]
	fine_grid = grid_from_config(
		load_config(fine_config_path)
	)

	return plan_domains_from_grids(
		component,
		spans,
		parent_grid,
		fine_grid,
		coarse_factor=coarse_factor,
		domain_width=domain_width,
		domain_height=domain_height,
	)


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Plant nur jene Highres-Domains, die eine grobe "
			"RLE-Work-Region tatsächlich schneiden."
		)
	)
	parser.add_argument("--components-report", required=True)
	parser.add_argument("--spans", required=True)
	parser.add_argument("--component-id", type=int, required=True)
	parser.add_argument("--parent-grid", required=True)
	parser.add_argument("--fine-config", required=True)
	parser.add_argument("--coarse-factor", type=int, required=True)
	parser.add_argument("--domain-width", type=int, default=2048)
	parser.add_argument("--domain-height", type=int, default=2048)
	parser.add_argument("--output", required=True)
	args = parser.parse_args()

	result = plan_domains(
		args.components_report,
		args.spans,
		args.component_id,
		args.parent_grid,
		args.fine_config,
		coarse_factor=args.coarse_factor,
		domain_width=args.domain_width,
		domain_height=args.domain_height,
	)

	Path(args.output).write_text(
		json.dumps(result, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(result, indent=2))


if __name__ == "__main__":
	main()
