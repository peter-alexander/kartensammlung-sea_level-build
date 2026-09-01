#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from materialize_mapterhorn_work_region_domain import (
	MapterhornWorkRegionDomainMaterializer,
)
from plan_lazy_work_region_domains import plan_domains
from process_lazy_domains import (
	process_lazy_domains,
	write_report,
)


def process_work_region(
	*,
	components_report,
	spans,
	component_id,
	parent_grid,
	fine_config,
	coarse_factor,
	sea_vector,
	cache_dir,
	work_dir,
	output_dir,
	solver,
	levels,
	domain_width=2048,
	domain_height=2048,
	workers=8,
	max_solver_runs=100000,
):
	plan = plan_domains(
		components_report,
		spans,
		component_id,
		parent_grid,
		fine_config,
		coarse_factor=coarse_factor,
		domain_width=domain_width,
		domain_height=domain_height,
	)
	if not plan["domains"]:
		raise RuntimeError(
			"Work Region enthält keine aktive Highres-Domain."
		)

	materializer = MapterhornWorkRegionDomainMaterializer(
		fine_config_path=fine_config,
		components_report_path=components_report,
		spans_path=spans,
		component_id=component_id,
		parent_grid_path=parent_grid,
		coarse_factor=coarse_factor,
		sea_vector_path=sea_vector,
		cache_dir=cache_dir,
		workers=workers,
	)

	output_dir = Path(output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)
	threshold_dir = output_dir / "threshold-domains"

	solver_report = process_lazy_domains(
		plan["domains"],
		materializer,
		None,
		work_dir,
		solver,
		levels,
		global_width=plan["fine_grid"]["width"],
		global_height=plan["fine_grid"]["height"],
		max_solver_runs=max_solver_runs,
		domain_output_dir=threshold_dir,
	)

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
			"safe coarse RLE work region -> sparse active "
			"highres domains -> lazy Mapterhorn materialization "
			"-> monotone boundary convergence"
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
			"domainweise in Source-Fidelity-Auflösung, ohne ein "
			"vollständiges Highres-Raster zu materialisieren."
		)
	)
	parser.add_argument("--components-report", required=True)
	parser.add_argument("--spans", required=True)
	parser.add_argument("--component-id", type=int, required=True)
	parser.add_argument("--parent-grid", required=True)
	parser.add_argument("--fine-config", required=True)
	parser.add_argument("--coarse-factor", type=int, required=True)
	parser.add_argument("--sea-vector", required=True)
	parser.add_argument("--cache-dir", default="cache")
	parser.add_argument("--work-dir", required=True)
	parser.add_argument("--output-dir", required=True)
	parser.add_argument("--solver", required=True)
	parser.add_argument("--levels", required=True)
	parser.add_argument("--domain-width", type=int, default=2048)
	parser.add_argument("--domain-height", type=int, default=2048)
	parser.add_argument("--workers", type=int, default=8)
	parser.add_argument(
		"--max-solver-runs",
		type=int,
		default=100000,
	)
	args = parser.parse_args()

	result = process_work_region(
		components_report=args.components_report,
		spans=args.spans,
		component_id=args.component_id,
		parent_grid=args.parent_grid,
		fine_config=args.fine_config,
		coarse_factor=args.coarse_factor,
		sea_vector=args.sea_vector,
		cache_dir=args.cache_dir,
		work_dir=args.work_dir,
		output_dir=args.output_dir,
		solver=args.solver,
		levels=args.levels,
		domain_width=args.domain_width,
		domain_height=args.domain_height,
		workers=args.workers,
		max_solver_runs=args.max_solver_runs,
	)

	print(json.dumps(result, indent=2))


if __name__ == "__main__":
	main()
