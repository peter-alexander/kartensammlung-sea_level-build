#!/usr/bin/env python3

import argparse
import json
import math
import struct
from pathlib import Path

import numpy as np
from shapely.geometry import box, mapping
from shapely.ops import transform, unary_union


SPAN_RECORD_BYTES = 12
WEB_MERCATOR_RADIUS = 6378137.0


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
	path = Path(path)

	expected_min_bytes = (
		offset_records + span_count
	) * SPAN_RECORD_BYTES
	if path.stat().st_size < expected_min_bytes:
		raise ValueError(
			"Span-Datei ist kürzer als die angegebene Component."
		)

	spans = []
	with path.open("rb") as source:
		source.seek(offset_records * SPAN_RECORD_BYTES)
		for _ in range(span_count):
			raw = source.read(SPAN_RECORD_BYTES)
			if len(raw) != SPAN_RECORD_BYTES:
				raise RuntimeError(
					"Span-Datei endet innerhalb der Component."
				)
			spans.append(struct.unpack("<III", raw))

	return spans


def mercator_to_lonlat(geometry):
	def convert(x, y, z=None):
		x = np.asarray(x, dtype=np.float64)
		y = np.asarray(y, dtype=np.float64)
		lon = np.degrees(x / WEB_MERCATOR_RADIUS)
		lat = np.degrees(
			np.arctan(
				np.sinh(y / WEB_MERCATOR_RADIUS)
			)
		)
		if z is None:
			return lon, lat
		return lon, lat, z

	return transform(convert, geometry)


def component_work_geometry(
	component,
	spans,
	grid,
	*,
	coarse_width,
	coarse_height,
	factor,
	halo_coarse_cells=1,
):
	factor = int(factor)
	halo = int(halo_coarse_cells)
	if factor <= 0:
		raise ValueError("factor muss > 0 sein.")
	if halo < 0:
		raise ValueError("halo_coarse_cells muss >= 0 sein.")

	width = int(grid["width"])
	height = int(grid["height"])
	if width % factor != 0 or height % factor != 0:
		raise ValueError(
			"Grid-Dimensionen müssen durch factor teilbar sein."
		)
	if width // factor != int(coarse_width):
		raise ValueError(
			"Coarse-Breite stimmt nicht mit Grid/factor überein."
		)
	if height // factor != int(coarse_height):
		raise ValueError(
			"Coarse-Höhe stimmt nicht mit Grid/factor überein."
		)

	resolution = float(grid["resolution"])
	left = float(grid["left"])
	top = float(grid["top"])
	rectangles = []

	for row, span_left, span_right in spans:
		row = int(row)
		span_left = int(span_left)
		span_right = int(span_right)

		x0_coarse = max(0, span_left - halo)
		x1_coarse = min(
			int(coarse_width),
			span_right + 1 + halo,
		)
		y0_coarse = max(0, row - halo)
		y1_coarse = min(
			int(coarse_height),
			row + 1 + halo,
		)

		x0 = left + x0_coarse * factor * resolution
		x1 = left + x1_coarse * factor * resolution
		y1 = top - y0_coarse * factor * resolution
		y0 = top - y1_coarse * factor * resolution
		rectangles.append(box(x0, y0, x1, y1))

	if not rectangles:
		raise ValueError("Component enthält keine Span-Geometrie.")

	geometry_mercator = unary_union(rectangles)
	if not geometry_mercator.is_valid:
		geometry_mercator = geometry_mercator.buffer(0)
	if geometry_mercator.is_empty:
		raise RuntimeError(
			"Work-Region-Geometrie ist nach Union leer."
		)

	geometry_lonlat = mercator_to_lonlat(geometry_mercator)
	if not geometry_lonlat.is_valid:
		geometry_lonlat = geometry_lonlat.buffer(0)

	return geometry_mercator, geometry_lonlat


def build_work_region(
	components_report_path,
	spans_path,
	grid_path,
	component_id,
	*,
	factor,
	halo_coarse_cells=1,
	output_geojson,
	output_report,
):
	report = json.loads(
		Path(components_report_path).read_text(encoding="utf-8")
	)
	grid_meta = json.loads(
		Path(grid_path).read_text(encoding="utf-8")
	)
	grid = grid_meta["grid"]
	component = find_component(report, component_id)
	spans = read_component_spans(spans_path, component)

	geometry_mercator, geometry_lonlat = component_work_geometry(
		component,
		spans,
		grid,
		coarse_width=int(report["width"]),
		coarse_height=int(report["height"]),
		factor=factor,
		halo_coarse_cells=halo_coarse_cells,
	)

	feature = {
		"type": "Feature",
		"properties": {
			"kind": "coarse-candidate-work-region",
			"component_id": int(component["id"]),
			"component_rank": int(component["rank"]),
			"component_cells": int(component["cells"]),
			"component_bbox_cells": component["bbox_cells"],
			"coarse_factor": int(factor),
			"halo_coarse_cells": int(halo_coarse_cells),
		},
		"geometry": mapping(geometry_lonlat),
	}
	output_geojson = Path(output_geojson)
	output_geojson.parent.mkdir(parents=True, exist_ok=True)
	output_geojson.write_text(
		json.dumps(feature, indent=2) + "\n",
		encoding="utf-8",
	)

	min_col, min_row, max_col, max_row = (
		int(value)
		for value in component["bbox_cells"]
	)
	bbox_x0 = max(0, min_col - int(halo_coarse_cells))
	bbox_y0 = max(0, min_row - int(halo_coarse_cells))
	bbox_x1 = min(
		int(report["width"]),
		max_col + 1 + int(halo_coarse_cells),
	)
	bbox_y1 = min(
		int(report["height"]),
		max_row + 1 + int(halo_coarse_cells),
	)
	bbox_fine_cells = (
		(bbox_x1 - bbox_x0)
		* int(factor)
		* (bbox_y1 - bbox_y0)
		* int(factor)
	)

	result = {
		"component_id": int(component["id"]),
		"component_rank": int(component["rank"]),
		"component_cells": int(component["cells"]),
		"component_span_count": int(component["span_count"]),
		"coarse_factor": int(factor),
		"halo_coarse_cells": int(halo_coarse_cells),
		"component_bbox_cells": component["bbox_cells"],
		"work_bbox_coarse_cells_exclusive": [
			bbox_x0,
			bbox_y0,
			bbox_x1,
			bbox_y1,
		],
		"work_bbox_parent_cells": [
			bbox_x0 * int(factor),
			bbox_y0 * int(factor),
			bbox_x1 * int(factor),
			bbox_y1 * int(factor),
		],
		"work_bbox_parent_cell_count": int(bbox_fine_cells),
		"work_geometry_area_m2": float(geometry_mercator.area),
		"work_geometry_bounds_lonlat": list(
			geometry_lonlat.bounds
		),
		"work_geometry_type": geometry_lonlat.geom_type,
		"output_geojson": str(output_geojson),
	}
	Path(output_report).write_text(
		json.dumps(result, indent=2) + "\n",
		encoding="utf-8",
	)

	return result


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Rekonstruiert aus einer groben Candidate-Component "
			"eine geografische Work-Region."
		)
	)
	parser.add_argument("--components-report", required=True)
	parser.add_argument("--spans", required=True)
	parser.add_argument("--grid", required=True)
	parser.add_argument("--component-id", type=int, required=True)
	parser.add_argument("--factor", type=int, required=True)
	parser.add_argument("--halo-coarse-cells", type=int, default=1)
	parser.add_argument("--output-geojson", required=True)
	parser.add_argument("--output-report", required=True)
	args = parser.parse_args()

	result = build_work_region(
		args.components_report,
		args.spans,
		args.grid,
		args.component_id,
		factor=args.factor,
		halo_coarse_cells=args.halo_coarse_cells,
		output_geojson=args.output_geojson,
		output_report=args.output_report,
	)
	print(json.dumps(result, indent=2))


if __name__ == "__main__":
	main()
