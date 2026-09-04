#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path

from process_adaptive_mapterhorn_work_region import (
	process_adaptive_work_region,
)
from validate_adaptive_threshold_output import (
	validate_adaptive_threshold_output,
)


def validate_final_output(
	plan,
	report,
	output_dir,
	checkpoint_path,
	*,
	levels_csv,
	components_report_path,
	spans_path,
	parent_grid_path,
):
	solver = report["solver"]
	output_dir = Path(output_dir)
	threshold_dir = output_dir / "threshold-domains"

	normalized_domains = [
		{
			**domain,
			"id": int(domain.get("id", index)),
		}
		for index, domain in enumerate(
			plan["domains"],
			start=1,
		)
	]
	expected = {
		f"r{int(domain['id'])}-c{int(domain['zoom'])}.u8": int(
			domain["fine_cells"]
		)
		for domain in normalized_domains
	}
	actual = {
		path.name: path.stat().st_size
		for path in threshold_dir.glob("*.u8")
	}

	missing = sorted(set(expected) - set(actual))
	unexpected = sorted(set(actual) - set(expected))
	wrong_sizes = sorted(
		name
		for name in set(expected) & set(actual)
		if expected[name] != actual[name]
	)

	summary = {
		"completed": bool(solver["completed"]),
		"domain_count": int(solver["domain_count"]),
		"initial_domain_count": int(
			solver["initial_domain_count"]
		),
		"solver_runs": int(solver["solver_runs"]),
		"materializations": int(
			solver["materializations"]
		),
		"finalization_materializations": int(
			solver["finalization_materializations"]
		),
		"boundary_improvements": int(
			solver["boundary_improvements"]
		),
		"external_sea_improvements": int(
			solver["external_sea_improvements"]
		),
		"never_converged_domain_count": int(
			solver["never_converged_domain_count"]
		),
		"peak_materialized_cells": int(
			solver["peak_materialized_cells"]
		),
		"threshold_file_count": len(actual),
		"threshold_bytes": sum(actual.values()),
		"missing_file_count": len(missing),
		"unexpected_file_count": len(unexpected),
		"wrong_size_file_count": len(wrong_sizes),
		"checkpoint_bytes": (
			Path(checkpoint_path).stat().st_size
			if Path(checkpoint_path).exists()
			else 0
		),
	}

	expected_cells = sum(
		int(domain["fine_cells"])
		for domain in normalized_domains
	)

	if not summary["completed"]:
		raise AssertionError(summary)
	if summary["domain_count"] != len(plan["domains"]):
		raise AssertionError(summary)
	if summary["finalization_materializations"] != len(
		plan["domains"]
	):
		raise AssertionError(summary)
	if summary["threshold_file_count"] != len(plan["domains"]):
		raise AssertionError(summary)
	if summary["threshold_bytes"] != expected_cells:
		raise AssertionError(summary)
	if missing or unexpected or wrong_sizes:
		raise AssertionError({
			"missing": missing[:20],
			"unexpected": unexpected[:20],
			"wrong_sizes": wrong_sizes[:20],
		})
	if not solver["all_domain_work_deleted"]:
		raise AssertionError(summary)

	manifest_path = output_dir / "reconstruction-manifest.json"
	deep_qa = validate_adaptive_threshold_output(
		plan=plan,
		threshold_dir=threshold_dir,
		checkpoint_path=checkpoint_path,
		levels_csv=levels_csv,
		components_report_path=components_report_path,
		spans_path=spans_path,
		parent_grid_path=parent_grid_path,
		manifest_output=manifest_path,
	)
	(output_dir / "adaptive-validation.json").write_text(
		json.dumps(deep_qa, indent=2) + "\n",
		encoding="utf-8",
	)

	summary.update({
		"checkpoint_signature": deep_qa["checkpoint_signature"],
		"sentinel_class": int(deep_qa["sentinel_class"]),
		"sentinel_cells": int(
			deep_qa["thresholds"]["sentinel_cells"]
		),
		"non_sentinel_cells": int(
			deep_qa["thresholds"]["non_sentinel_cells"]
		),
		"zero_run_non_sentinel_cells": int(
			deep_qa["thresholds"][
				"zero_run_non_sentinel_cells"
			]
		),
		"fixed_point_adjacency_count": int(
			deep_qa["fixed_point"]["adjacency_count"]
		),
		"fixed_point_directed_edge_checks": int(
			deep_qa["fixed_point"]["directed_edge_checks"]
		),
		"fixed_point_improvable_pixels": int(
			deep_qa["fixed_point"]["improvable_pixels"]
		),
		"component_partition_missing_cells": int(
			deep_qa["component_partition"]["missing_cells"]
		),
		"component_partition_overlap_cells": int(
			deep_qa["component_partition"]["overlap_cells"]
		),
		"component_partition_extra_cells": int(
			deep_qa["component_partition"]["extra_cells"]
		),
		"reconstruction_spatial_mapping_valid": bool(
			deep_qa["reconstruction"]["spatial_mapping_valid"]
		),
		"reconstruction_manifest": str(manifest_path),
		"validation_report": str(
			output_dir / "adaptive-validation.json"
		),
	})

	return summary


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Rechnet einen begrenzten Checkpoint-Chunk einer "
			"adaptiven Work Region und validiert bei Konvergenz "
			"die vollständige sparse Threshold-Ausgabe."
		)
	)
	parser.add_argument("--components-report", required=True)
	parser.add_argument("--spans", required=True)
	parser.add_argument("--parent-grid", required=True)
	parser.add_argument("--adaptive-plan", required=True)
	parser.add_argument("--seed-plan", required=True)
	parser.add_argument("--component-id", type=int, required=True)
	parser.add_argument("--coarse-factor", type=int, required=True)
	parser.add_argument("--sea-vector", required=True)
	parser.add_argument("--cache-dir", required=True)
	parser.add_argument("--work-dir", required=True)
	parser.add_argument("--output-dir", required=True)
	parser.add_argument("--solver", required=True)
	parser.add_argument("--levels", required=True)
	parser.add_argument("--checkpoint", required=True)
	parser.add_argument("--status-output", required=True)
	parser.add_argument("--final-summary")
	parser.add_argument("--workers", type=int, default=8)
	parser.add_argument(
		"--checkpoint-every-runs",
		type=int,
		default=500,
	)
	parser.add_argument(
		"--max-runs-this-invocation",
		type=int,
		default=7500,
	)
	parser.add_argument(
		"--max-solver-runs",
		type=int,
		default=100000,
	)
	parser.add_argument("--github-env")
	args = parser.parse_args()

	plan = json.loads(
		Path(args.adaptive_plan).read_text(
			encoding="utf-8"
		)
	)
	resume = Path(args.checkpoint).exists()

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
		workers=args.workers,
		max_solver_runs=args.max_solver_runs,
		adaptive_plan_path=args.adaptive_plan,
		checkpoint_path=args.checkpoint,
		checkpoint_every_runs=args.checkpoint_every_runs,
		resume=resume,
		max_runs_this_invocation=(
			args.max_runs_this_invocation
		),
		write_outputs_during_convergence=False,
		seed_plan_path=args.seed_plan,
	)

	solver = result["solver"]
	status = {
		"completed": bool(solver["completed"]),
		"resumed": bool(resume),
		"solver_runs": int(solver["solver_runs"]),
		"queue_remaining": int(solver["queue_remaining"]),
		"materializations": int(
			solver["materializations"]
		),
		"boundary_improvements": int(
			solver["boundary_improvements"]
		),
		"external_sea_improvements": int(
			solver["external_sea_improvements"]
		),
		"peak_materialized_cells": int(
			solver["peak_materialized_cells"]
		),
		"checkpoint_bytes": (
			Path(args.checkpoint).stat().st_size
			if Path(args.checkpoint).exists()
			else 0
		),
	}

	if status["completed"]:
		final_summary = validate_final_output(
			plan,
			result,
			args.output_dir,
			args.checkpoint,
			levels_csv=args.levels,
			components_report_path=args.components_report,
			spans_path=args.spans,
			parent_grid_path=args.parent_grid,
		)
		status["final"] = final_summary
		if args.final_summary:
			Path(args.final_summary).write_text(
				json.dumps(
					final_summary,
					indent=2,
				) + "\n",
				encoding="utf-8",
			)

	Path(args.status_output).write_text(
		json.dumps(status, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(status, indent=2))

	github_env = args.github_env or os.environ.get(
		"GITHUB_ENV"
	)
	if github_env:
		with open(
			github_env,
			"a",
			encoding="utf-8",
		) as target:
			target.write(
				"DONE="
				+ (
					"true"
					if status["completed"]
					else "false"
				)
				+ "\n"
			)


if __name__ == "__main__":
	main()
