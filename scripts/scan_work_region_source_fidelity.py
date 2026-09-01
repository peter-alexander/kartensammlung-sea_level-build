#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from coverage_planner import plan as build_coverage_plan
from grid import grid_from_config
from plan_lazy_work_region_domains import plan_domains_from_grids
from plan_work_region import build_work_region_plan
from prepare_candidate_work_region import (
	component_work_geometry,
	read_component_spans,
)


def scan_work_regions(
	components_report_path,
	spans_path,
	parent_grid_path,
	*,
	factor,
	cache_dir,
	coverage_zoom=8,
	coverage_context_tiles=1,
	workers=12,
	domain_width=512,
	domain_height=512,
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

	rows = []
	for component in report["components"]:
		spans = read_component_spans(
			spans_path,
			component,
		)
		_geometry_mercator, geometry = (
			component_work_geometry(
				component,
				spans,
				parent_grid,
				coarse_width=int(report["width"]),
				coarse_height=int(report["height"]),
				factor=factor,
				halo_coarse_cells=0,
			)
		)
		bounds = tuple(
			float(value)
			for value in geometry.bounds
		)

		coverage = build_coverage_plan(
			bounds,
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
		work_plan = build_work_region_plan(
			geometry,
			coverage["source_features"],
			base_zoom=base_zoom,
			tile_size=512,
		)

		zoom = int(
			work_plan["uniform_processing_zoom"]
		)
		fine_config = {
			"bounds": {
				"west": bounds[0],
				"south": bounds[1],
				"east": bounds[2],
				"north": bounds[3],
			},
			"dem": {
				"processing_zoom": zoom,
				"tile_size": 512,
			},
		}
		fine_grid = grid_from_config(fine_config)
		domain_plan = plan_domains_from_grids(
			component,
			spans,
			parent_grid,
			fine_grid,
			coarse_factor=factor,
			domain_width=domain_width,
			domain_height=domain_height,
		)

		scale = int(
			domain_plan[
				"fine_pixels_per_coarse_cell"
			]
		)
		core_fine_cells = (
			int(component["cells"])
			* scale
			* scale
		)

		sources = [
			{
				"source": item.get("source"),
				"name": item.get("name"),
				"resolution_m": item.get(
					"resolution_m"
				),
				"source_fidelity_processing_zoom": (
					item.get(
						"source_fidelity_processing_zoom"
					)
				),
				"area_fraction": item.get(
					"area_fraction"
				),
			}
			for item in work_plan[
				"coverage"
			]["effective_sources"]
		]

		rows.append({
			"component_id": int(component["id"]),
			"component_rank": int(component["rank"]),
			"coarse_cells": int(component["cells"]),
			"span_count": int(component["span_count"]),
			"coastal_cells": int(
				component["coastal_cells"]
			),
			"bounds": list(bounds),
			"source_fidelity_zoom": zoom,
			"fine_pixels_per_coarse_cell": scale,
			"core_fine_cells": core_fine_cells,
			"fine_bbox_cells": int(fine_grid["cells"]),
			"fine_width": int(fine_grid["width"]),
			"fine_height": int(fine_grid["height"]),
			"active_domain_count": int(
				domain_plan["active_domain_count"]
			),
			"full_bbox_domain_count": int(
				domain_plan[
					"full_bbox_domain_count"
				]
			),
			"sources": sources,
			"uncovered_area_fraction": float(
				work_plan["coverage"][
					"uncovered_area_fraction"
				]
			),
		})

	rows.sort(
		key=lambda item: (
			-int(item["source_fidelity_zoom"]),
			int(item["core_fine_cells"]),
			-int(item["active_domain_count"]),
			int(item["component_rank"]),
		)
	)

	highres = [
		item
		for item in rows
		if int(item["source_fidelity_zoom"])
			> int(parent_grid["zoom"])
	]
	multidomain_highres = [
		item
		for item in highres
		if int(item["active_domain_count"]) > 1
	]

	return {
		"schema_version": 1,
		"component_count": len(rows),
		"parent_zoom": int(parent_grid["zoom"]),
		"coarse_factor": int(factor),
		"domain_width": int(domain_width),
		"domain_height": int(domain_height),
		"highres_component_count": len(highres),
		"multidomain_highres_component_count": len(
			multidomain_highres
		),
		"best_multidomain_qa_candidates": (
			multidomain_highres[:20]
		),
		"work_regions": rows,
	}


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Scannt sichere RLE-Work-Regions gegen echte "
			"Mapterhorn-Coverage und rangiert Highres-QA-Kandidaten."
		)
	)
	parser.add_argument("--components-report", required=True)
	parser.add_argument("--spans", required=True)
	parser.add_argument("--parent-grid", required=True)
	parser.add_argument("--factor", type=int, required=True)
	parser.add_argument("--cache-dir", default="cache")
	parser.add_argument("--coverage-zoom", type=int, default=8)
	parser.add_argument(
		"--coverage-context-tiles",
		type=int,
		default=1,
	)
	parser.add_argument("--workers", type=int, default=12)
	parser.add_argument("--domain-width", type=int, default=512)
	parser.add_argument("--domain-height", type=int, default=512)
	parser.add_argument("--output", required=True)
	args = parser.parse_args()

	result = scan_work_regions(
		args.components_report,
		args.spans,
		args.parent_grid,
		factor=args.factor,
		cache_dir=args.cache_dir,
		coverage_zoom=args.coverage_zoom,
		coverage_context_tiles=(
			args.coverage_context_tiles
		),
		workers=args.workers,
		domain_width=args.domain_width,
		domain_height=args.domain_height,
	)

	Path(args.output).write_text(
		json.dumps(result, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps({
		"component_count": result["component_count"],
		"highres_component_count": (
			result["highres_component_count"]
		),
		"multidomain_highres_component_count": (
			result[
				"multidomain_highres_component_count"
			]
		),
		"best_multidomain_qa_candidates": (
			result["best_multidomain_qa_candidates"]
		),
	}, indent=2))


if __name__ == "__main__":
	main()
