#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from materialize_adaptive_mapterhorn_domain import (
	AdaptiveMapterhornDomainMaterializer,
)
from plan_adaptive_work_region_domains import adaptive_plan
from process_adaptive_lazy_domains import (
	process_adaptive_lazy_domains,
	write_report,
)


def process_adaptive_work_region(
	*,
	components_report,
	spans,
	parent_grid,
	component_id,
	coarse_factor,
	sea_vector,
	cache_dir,
	work_dir,
	output_dir,
	solver,
	levels,
	coverage_zoom=8,
	coverage_context_tiles=1,
	workers=8,
	domain_pixels=512,
	max_solver_runs=1000000,
	adaptive_plan_path=None,
):
	parent_meta = json.loads(
		Path(parent_grid).read_text(encoding="utf-8")
	)
	parent = parent_meta["grid"]

	if adaptive_plan_path is None:
		plan = adaptive_plan(
			components_report,
			spans,
			parent_grid,
			component_id,
			factor=coarse_factor,
			cache_dir=cache_dir,
			coverage_zoom=coverage_zoom,
			coverage_context_tiles=coverage_context_tiles,
			workers=workers,
			domain_pixels=domain_pixels,
		)
	else:
		plan = json.loads(
			Path(adaptive_plan_path).read_text(
				encoding="utf-8"
			)
		)
		if int(plan["component_id"]) != int(component_id):
			raise ValueError(
				"Adaptive Plan gehört zu einer anderen Component."
			)
	if not plan["domains"]:
		raise RuntimeError(
			"Adaptive Work Region enthält keine Domains."
		)

	output_dir = Path(output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)
	threshold_dir = output_dir / "threshold-domains"

	materializer = AdaptiveMapterhornDomainMaterializer(
		parent_grid=parent,
		sea_vector_path=sea_vector,
		cache_dir=cache_dir,
		workers=workers,
		fallback_min_zoom=plan["base_zoom"],
		tile_size=512,
	)

	try:
		solver_report = process_adaptive_lazy_domains(
			plan["domains"],
			materializer,
			threshold_dir,
			work_dir,
			solver,
			levels,
			max_solver_runs=max_solver_runs,
		)
	finally:
		materializer.close()

	threshold_files = sorted(
		threshold_dir.glob("*.u8")
	)
	threshold_bytes = sum(
		path.stat().st_size
		for path in threshold_files
	)

	result = {
		"schema_version": 1,
		"strategy": (
			"safe coarse RLE work region -> adaptive "
			"source-fidelity domains -> lazy Mapterhorn "
			"materialization -> multi-resolution monotone "
			"boundary convergence -> sparse thresholds"
		),
		"component_id": int(component_id),
		"domain_plan": plan,
		"solver": solver_report,
		"output": {
			"threshold_dir": str(threshold_dir),
			"threshold_file_count": len(
				threshold_files
			),
			"threshold_bytes": threshold_bytes,
		},
	}
	write_report(
		output_dir / "report.json",
		result,
	)
	return result


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Verarbeitet eine sichere grobe Candidate-Work-Region "
			"mit adaptiver Mapterhorn-Source-Fidelity und "
			"Multi-Resolution-Domain-Konvergenz."
		)
	)
	parser.add_argument("--components-report", required=True)
	parser.add_argument("--spans", required=True)
	parser.add_argument("--parent-grid", required=True)
	parser.add_argument("--component-id", type=int, required=True)
	parser.add_argument("--coarse-factor", type=int, required=True)
	parser.add_argument("--sea-vector", required=True)
	parser.add_argument("--cache-dir", default="cache")
	parser.add_argument("--work-dir", required=True)
	parser.add_argument("--output-dir", required=True)
	parser.add_argument("--solver", required=True)
	parser.add_argument("--levels", required=True)
	parser.add_argument("--coverage-zoom", type=int, default=8)
	parser.add_argument(
		"--coverage-context-tiles",
		type=int,
		default=1,
	)
	parser.add_argument("--workers", type=int, default=8)
	parser.add_argument("--domain-pixels", type=int, default=512)
	parser.add_argument("--adaptive-plan")
	parser.add_argument(
		"--max-solver-runs",
		type=int,
		default=1000000,
	)
	args = parser.parse_args()

	result = process_adaptive_work_region(
		components_report=args.components_report,
		spans=args.spans,
		parent_grid=args.parent_grid,
		component_id=args.component_id,
		coarse_factor=args.coarse_factor,
		sea_vector=args.sea_vector,
		cache_dir=args.cache_dir,
		work_dir=args.work_dir,
		output_dir=args.output_dir,
		solver=args.solver,
		levels=args.levels,
		coverage_zoom=args.coverage_zoom,
		coverage_context_tiles=args.coverage_context_tiles,
		workers=args.workers,
		domain_pixels=args.domain_pixels,
		max_solver_runs=args.max_solver_runs,
		adaptive_plan_path=args.adaptive_plan,
	)

	print(json.dumps(result, indent=2))


if __name__ == "__main__":
	main()
